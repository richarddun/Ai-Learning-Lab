from typing import List, Optional
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse, Response
import logging
import random
import os
import base64
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import Session
from dotenv import dotenv_values
from backend.services.secrets import get_secret as get_db_secret, set_secret as set_db_secret, delete_secret as del_db_secret
from backend.services.openrouter import (
    chat_with_openrouter,
    stream_chat_with_openrouter,
)
from backend.services import models
from backend.services.database import SessionLocal, engine


models.Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app = FastAPI(title="AI Learning Lab")
logger = logging.getLogger("uvicorn.error")
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


class ChatRequest(BaseModel):
    """Request body for chat interactions."""

    user_id: int
    message: str
    system_prompt: Optional[str] = None


class Profile(BaseModel):
    """Represents a selectable user profile."""

    id: int
    name: str
    avatar: Optional[str] = None


@app.get("/profiles", response_model=List[Profile])
async def get_profiles() -> List[Profile]:
    """Return available user profiles.

    This is a placeholder implementation. In a real application the
    profiles would be loaded from a database.
    """

    return [
        Profile(id=1, name="Alice", avatar="/avatars/alice.png"),
        Profile(id=2, name="Bob", avatar="/avatars/bob.png"),
    ]


class UserCreate(BaseModel):
    name: str
    preferences: str = ""


class PreferencesUpdate(BaseModel):
    preferences: str


class TTSRequest(BaseModel):
    text: str
    voice_id: Optional[str] = None
    # Optional tunables mirrored to ElevenLabs client; ignored if not provided
    stability: Optional[float] = None
    similarity_boost: Optional[float] = None
    style: Optional[float] = None
    use_speaker_boost: Optional[bool] = None


class CharacterCreate(BaseModel):
    name: str
    system_prompt: str = ""
    voice_id: str = ""
    avatar: str = ""


class CharacterUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    avatar: Optional[str] = None


class AvatarGenerateRequest(BaseModel):
    prompt: Optional[str] = None
    style: Optional[str] = None
    size: Optional[str] = None  # e.g., "512x512"
    seed: Optional[int] = None
    include_system_prompt: Optional[bool] = False


class PersonaSuggestRequest(BaseModel):
    """Inputs for suggesting a character system prompt."""

    genres: List[str] = []
    gender: Optional[str] = None
    archetypes: List[str] = []
    traits: List[str] = []
    style: Optional[str] = None


class ImportMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None


class ImportRequest(BaseModel):
    messages: List[ImportMessage]


class AvatarUpdate(BaseModel):
    avatar: str


class UserMetaUpdate(BaseModel):
    system_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    voice_name: Optional[str] = None
    character_id: Optional[int] = None
    character_name: Optional[str] = None
    avatar: Optional[str] = None


class ApiKeyItem(BaseModel):
    name: str
    value: str


@app.get("/settings/api_keys")
def list_api_keys(db: Session = Depends(get_db)):
    """Return API key names without exposing values.

    For backward compatibility the endpoint still lists existing keys, but
    only returns a flag indicating a value is present. This prevents secrets
    from being revealed to the frontend.
    """
    names = set()
    if os.getenv("ALLOW_ENV_SECRETS", "0") in ("1", "true", "True"):
        if ENV_PATH.exists():
            data = dotenv_values(ENV_PATH)
            for k, v in data.items():
                if v is not None:
                    names.add(k)
    # Include DB-backed secrets as well
    try:
        q = db.query(models.ApiSecret.name).all()
        for (n,) in q:
            names.add(n)
    except Exception:
        pass
    items = [{"name": n, "has_value": True} for n in sorted(names)]
    return {"keys": items}


@app.post("/settings/api_keys")
def set_api_key(item: ApiKeyItem, db: Session = Depends(get_db)):
    """Create or update a key value.

    Response does not echo the secret to avoid accidental exposure.
    """
    # Store in DB (encrypted). Do not write to .env.
    try:
        set_db_secret(db, item.name, item.value)
    except Exception:
        pass
    return {"name": item.name, "updated": True}


@app.delete("/settings/api_keys/{name}")
def delete_api_key(name: str, db: Session = Depends(get_db)):
    # Remove from DB
    try:
        del_db_secret(db, name)
    except Exception:
        pass
    return {"deleted": name}


@app.post("/chat")
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """Proxy a chat request to the OpenRouter API while persisting history."""
    user = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_msg = models.Message(user_id=user.id, role="user", content=req.message)
    db.add(user_msg)
    db.commit()

    # Build structured messages array (system + recent conversation)
    # Limit to the most recent 20 messages to keep token usage reasonable
    messages_q = (
        db.query(models.Message)
        .filter(models.Message.user_id == user.id)
        .order_by(models.Message.timestamp.desc())
        .limit(20)
        .all()
    )
    messages_q.reverse()
    role_map = {"user": "user", "bot": "assistant"}
    messages = []
    if req.system_prompt:
        messages.append({"role": "system", "content": req.system_prompt})
    for m in messages_q:
        messages.append({"role": role_map.get(m.role, m.role), "content": m.content})

    response_text = await chat_with_openrouter(messages=messages)

    bot_msg = models.Message(user_id=user.id, role="bot", content=response_text)
    db.add(bot_msg)
    db.commit()

    return {"response": response_text}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest, db: Session = Depends(get_db)):
    """Stream a chat response from the OpenRouter API."""
    user = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Store the user ID locally since accessing attributes on a SQLAlchemy model
    # after the session is closed can raise `DetachedInstanceError`.
    user_id = user.id

    user_msg = models.Message(user_id=user_id, role="user", content=req.message)
    db.add(user_msg)
    db.commit()

    response_text = ""

    async def event_gen():
        nonlocal response_text
        # Build structured messages array including the just-saved user message
        messages_q = (
            db.query(models.Message)
            .filter(models.Message.user_id == user_id)
            .order_by(models.Message.timestamp.desc())
            .limit(20)
            .all()
        )
        messages_q.reverse()
        role_map = {"user": "user", "bot": "assistant"}
        messages = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        for m in messages_q:
            messages.append({"role": role_map.get(m.role, m.role), "content": m.content})

        async for token in stream_chat_with_openrouter(messages=messages):
            response_text += token
            yield token
        # Use the stored user_id to avoid accessing attributes on a detached instance
        bot_msg = models.Message(user_id=user_id, role="bot", content=response_text)
        db.add(bot_msg)
        db.commit()

    return StreamingResponse(event_gen(), media_type="text/plain")


@app.post("/users")
def create_user(req: UserCreate, db: Session = Depends(get_db)):
    """Create a new user profile or return existing by name."""
    user = db.query(models.User).filter(models.User.name == req.name).first()
    if user:
        return {"id": user.id, "name": user.name, "preferences": user.preferences}
    user = models.User(name=req.name, preferences=req.preferences)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "preferences": user.preferences}


@app.get("/users")
def list_users(db: Session = Depends(get_db)):
    """List all users (conversations)."""
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    return {
        "users": [
            {"id": u.id, "name": u.name, "preferences": u.preferences or ""}
        for u in users
        ]
    }


@app.put("/users/{user_id}/preferences")
def update_preferences(
    user_id: int, req: PreferencesUpdate, db: Session = Depends(get_db)
):
    """Update stored preferences for a user."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.preferences = req.preferences
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "preferences": user.preferences}


@app.put("/users/{user_id}/avatar")
def update_user_avatar(user_id: int, req: AvatarUpdate, db: Session = Depends(get_db)):
    """Set or update the avatar URL for a conversation (stored in preferences JSON)."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    import json
    prefs = {}
    try:
        if user.preferences:
            prefs = json.loads(user.preferences)
    except Exception:
        prefs = {}
    prefs["avatar"] = req.avatar
    try:
        user.preferences = json.dumps(prefs)
    except Exception:
        # Fallback: store as plain string
        user.preferences = str({"avatar": req.avatar})
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "preferences": user.preferences}


@app.put("/users/{user_id}/meta")
def update_user_meta(user_id: int, req: UserMetaUpdate, db: Session = Depends(get_db)):
    """Merge arbitrary conversation metadata into preferences JSON.

    Accepts any subset of: system_prompt, voice_id, voice_name, character_id, character_name, avatar.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    import json
    prefs = {}
    try:
        if user.preferences:
            prefs = json.loads(user.preferences)
    except Exception:
        prefs = {}
    payload = {k: v for k, v in req.dict().items() if v is not None}
    if not payload:
        return {"id": user.id, "name": user.name, "preferences": user.preferences or ""}
    prefs.update(payload)
    try:
        user.preferences = json.dumps(prefs)
    except Exception:
        user.preferences = str(prefs)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "preferences": user.preferences}


@app.delete("/users/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db)):
    """Delete a user (conversation) and all its messages."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    # Delete messages explicitly to avoid FK constraint issues
    db.query(models.Message).filter(models.Message.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"deleted": True}


# --- Conversation naming helpers ---
def _random_slug(seed: int | None = None) -> str:
    rng = random.Random(seed)
    adjectives = [
        "brisk", "lively", "curious", "silent", "witty", "brave", "clever", "gentle",
        "merry", "nimble", "patient", "quick", "quiet", "spry", "stellar", "vivid",
        "sunny", "scarlet", "azure", "verdant", "crimson", "golden", "silver", "bold",
        "candid", "bright", "serene", "restless", "arcane", "cosmic"
    ]
    nouns = [
        "zebra", "falcon", "willow", "river", "canyon", "harbor", "meadow", "forest",
        "reef", "ember", "aurora", "nebula", "citadel", "harvest", "summit", "oasis",
        "echo", "harp", "compass", "lantern", "quartz", "atlas", "comet", "horizon"
    ]
    places = [
        "harbor", "valley", "garden", "grove", "spire", "bay", "crest", "dunes",
        "isle", "heights", "fields", "hollow", "ridge", "shore", "woods"
    ]
    return f"{rng.choice(adjectives)}-{rng.choice(nouns)}-{rng.choice(places)}"


@app.get("/conversations/suggest_name")
def suggest_name(seed: Optional[int] = None):
    """Return a suggested human-friendly slug to name a conversation."""
    slug = _random_slug(seed)
    return {"name": slug}


@app.put("/users/{user_id}/name")
def rename_user(user_id: int, name: str, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.name = name
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name}


@app.post("/users/{user_id}/suggest_name")
async def suggest_name_from_history(user_id: int, db: Session = Depends(get_db)):
    """Suggest a 7-word title using recent conversation via LLM.

    Falls back to a random slug if LLM key/config not available.
    """
    try:
        # Build a compact transcript
        messages = (
            db.query(models.Message)
            .filter(models.Message.user_id == user_id)
            .order_by(models.Message.timestamp.desc())
            .limit(20)
            .all()
        )
        messages.reverse()
        lines = []
        for m in messages:
            role = "User" if m.role == "user" else "Assistant"
            lines.append(f"{role}: {m.content}")
        transcript = "\n".join(lines)

        prompt = (
            "You write short titles. Given a chat transcript, "
            "respond with a concise, 7-word conversation title. "
            "No quotes, no punctuation except spaces.\n\n" + transcript
        )
        # Use OpenRouter helper; if not configured it returns a message string
        title = await chat_with_openrouter(prompt, system_prompt="")
        # Sanitize: keep max 7 words
        words = [w for w in title.strip().split() if w]
        if not words:
            raise RuntimeError("empty title")
        title7 = " ".join(words[:7])
        return {"name": title7}
    except Exception:
        # Fallback to slug
        return {"name": _random_slug()}


@app.post("/characters/{char_id}/avatar/generate")
async def generate_character_avatar(char_id: int, req: AvatarGenerateRequest, db: Session = Depends(get_db)):
    """Generate a kid-friendly avatar image for a character using OpenAI Images.

    Stores the image under frontend/assets/characters/{id}/ and updates the character avatar URL.
    """
    c = db.query(models.Character).filter(models.Character.id == char_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")

    openai_key = os.getenv("OPENAI_API_KEY")
    if not openai_key:
        raise HTTPException(status_code=503, detail="Image provider not configured")

    # Build a safe, kid-friendly prompt
    base_style = (
        req.style
        or "friendly colorful cartoon portrait"
    )
    # Supported sizes for OpenAI Images: 1024x1024, 1024x1792, 1792x1024
    size = req.size or "1024x1024"
    name = c.name or "Character"
    sys_prompt = (c.system_prompt or "").strip()
    extra_prompt = (req.prompt or "").strip()
    composed_prompt = f"{base_style}. Profile picture of {name}."
    # Only include the character system prompt if explicitly requested.
    # This helps avoid safety rejections from aggressive content filters.
    if req.include_system_prompt and sys_prompt:
        composed_prompt += f" Personality: {sys_prompt[:300]}"
    if extra_prompt:
        composed_prompt += f" {extra_prompt}"

    # Call OpenAI Images API directly with httpx
    import httpx

    headers = {
        "Authorization": f"Bearer {openai_key}",
        "Content-Type": "application/json",
    }

    async def fetch_image_bytes(model: str) -> bytes:
        body = {
            "model": model,
            "prompt": composed_prompt,
            "size": size,
            "n": 1,
            "response_format": "b64_json",
        }
        if req.seed is not None:
            # Some models may ignore/deny seed; harmless to include
            body["seed"] = req.seed
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post("https://api.openai.com/v1/images/generations", headers=headers, json=body)
            if r.status_code >= 400:
                # Log server response body for diagnosis
                try:
                    logger.error("/avatar/generate %s error %s: %s", model, r.status_code, r.text)
                except Exception:
                    pass
                r.raise_for_status()
            content = r.json()
        data = content.get("data", [])
        if not data:
            raise RuntimeError("No image data returned")
        b64 = data[0].get("b64_json")
        if b64:
            return base64.b64decode(b64)
        # Fallback: download URL if provided
        url = data[0].get("url")
        if not url:
            raise RuntimeError("No base64 or URL image content returned")
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                logger.error("/avatar/generate download error %s: %s", resp.status_code, resp.text)
                resp.raise_for_status()
            return resp.content

    # Try gpt-image-1, then fallback to dall-e-3 if 4xx indicates unsupported params/model
    try:
        try:
            img_bytes = await fetch_image_bytes(os.getenv("IMAGE_MODEL", "gpt-image-1"))
        except httpx.HTTPStatusError as he:
            if 400 <= he.response.status_code < 500:
                # Fallback model
                img_bytes = await fetch_image_bytes("dall-e-3")
            else:
                raise
    except Exception as e:
        # Surface upstream error text if present
        detail_text = str(e)
        if isinstance(e, httpx.HTTPStatusError):
            try:
                detail_text = e.response.text
            except Exception:
                detail_text = str(e)
        logger.exception("/characters/%s/avatar/generate failed: %s", char_id, detail_text)

        # If it looks like a content policy violation, ask OpenRouter to suggest a softened prompt
        suggestion = None
        try:
            import json as _json
            parsed = None
            try:
                parsed = _json.loads(detail_text)
            except Exception:
                parsed = None
            message_txt = None
            code_txt = None
            if isinstance(parsed, dict):
                # OpenAI error shape: { "error": { "message": ..., "code": ... } }
                err = parsed.get("error") if parsed else None
                if isinstance(err, dict):
                    message_txt = err.get("message")
                    code_txt = err.get("code")
            if (code_txt == "content_policy_violation") or (message_txt and ("safety system" in message_txt or "rejected" in message_txt)):
                # Build a prompt for OpenRouter to rewrite safely
                sys_msg = (
                    "You rewrite image prompts to be kid-safe and G-rated. "
                    "Preserve the creative intent, but remove weapons, violence, gore, and dangerous situations. "
                    "Avoid adult themes. Return only a concise rewritten prompt (1-2 sentences), suitable for image generation providers."
                )
                user_msg = (
                    "Original prompt (was rejected):\n" + composed_prompt + "\n\n"
                    "Rewrite it as a friendly, colorful cartoon, kid-safe, G-rated, no violence, no weapons, simple background."
                )
                try:
                    # Ask OpenRouter for a softened prompt
                    suggestion = await chat_with_openrouter(user_msg, sys_msg)
                except Exception as _e:  # fallback if OpenRouter unavailable
                    suggestion = None
        except Exception:
            suggestion = None

        # Return structured error with suggestion if available
        raise HTTPException(
            status_code=422 if suggestion else 502,
            detail={
                "error": {
                    "code": "content_policy_violation" if suggestion else "image_generation_error",
                    "message": detail_text,
                },
                **({"suggestion": suggestion} if suggestion else {}),
            },
        )

    try:
        if not img_bytes or len(img_bytes) == 0:
            raise RuntimeError("Empty image bytes")
        # Write to frontend assets
        root = Path(__file__).resolve().parent.parent.parent
        out_dir = root / "frontend" / "assets" / "characters" / str(char_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"avatar-{int(__import__('time').time())}.png"
        out_path = out_dir / filename
        with open(out_path, "wb") as f:
            f.write(img_bytes)

        # Public URL path relative to static mount
        rel_url = f"/assets/characters/{char_id}/{filename}"
        c.avatar = rel_url
        db.commit()
        db.refresh(c)
        return {"avatar": rel_url}
    except Exception as e:
        logger.exception("/characters/%s/avatar/generate store failed: %s", char_id, e)
        raise HTTPException(status_code=500, detail="Image store failed")


@app.get("/users/{user_id}/history")
def get_history(user_id: int, db: Session = Depends(get_db)):
    """Return chat history for a user."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    messages = (
        db.query(models.Message)
        .filter(models.Message.user_id == user_id)
        .order_by(models.Message.timestamp)
        .all()
    )
    history: List[dict] = [
        {"role": m.role, "content": m.content, "timestamp": m.timestamp.isoformat()}
        for m in messages
    ]
    return {"history": history}


# --- Characters CRUD ---
@app.get("/characters")
def list_characters(db: Session = Depends(get_db)):
    chars = db.query(models.Character).order_by(models.Character.name).all()
    return {
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "system_prompt": c.system_prompt,
                "voice_id": c.voice_id,
                "avatar": c.avatar,
            }
            for c in chars
        ]
    }


@app.post("/characters")
def create_character(req: CharacterCreate, db: Session = Depends(get_db)):
    existing = (
        db.query(models.Character).filter(models.Character.name == req.name).first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Character with this name exists")
    c = models.Character(
        name=req.name,
        system_prompt=req.system_prompt,
        voice_id=req.voice_id,
        avatar=req.avatar,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "id": c.id,
        "name": c.name,
        "system_prompt": c.system_prompt,
        "voice_id": c.voice_id,
        "avatar": c.avatar,
    }


@app.put("/characters/{char_id}")
def update_character(char_id: int, req: CharacterUpdate, db: Session = Depends(get_db)):
    c = db.query(models.Character).filter(models.Character.id == char_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")
    if req.name is not None:
        c.name = req.name
    if req.system_prompt is not None:
        c.system_prompt = req.system_prompt
    if req.voice_id is not None:
        c.voice_id = req.voice_id
    if req.avatar is not None:
        c.avatar = req.avatar
    db.commit()
    db.refresh(c)
    return {
        "id": c.id,
        "name": c.name,
        "system_prompt": c.system_prompt,
        "voice_id": c.voice_id,
        "avatar": c.avatar,
    }


@app.delete("/characters/{char_id}")
def delete_character(char_id: int, db: Session = Depends(get_db)):
    c = db.query(models.Character).filter(models.Character.id == char_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")
    db.delete(c)
    db.commit()
    return {"deleted": True}


@app.post("/characters/suggest_system_prompt")
async def suggest_system_prompt(req: PersonaSuggestRequest):
    """Use OpenRouter to suggest a concise system prompt for a persona.

    Falls back to 503 if OpenRouter is not configured.
    """
    # Compose explicit instructions for the prompter model
    sys_msg = (
        "You craft concise, high-quality system prompts for AI assistant personas. "
        "Output only the prompt text. Avoid markdown, headings, or quotation. "
        "Keep it 5-10 sentences. G-rated, kid-safe, inclusive, and encouraging. "
        "Describe the assistant's role, tone, and constraints. Encourage asking clarifying questions, "
        "admitting uncertainty, and guiding step-by-step. Avoid sensitive or unsafe topics."
    )
    # Build user content from the selection
    def fmt_list(items: list[str], label: str) -> str:
        return f"{label}: " + (", ".join(i.strip() for i in items if i and str(i).strip()) or "unspecified")

    parts = [
        fmt_list(req.genres or [], "Genres"),
        f"Gender: {(req.gender or 'unspecified')}",
        fmt_list(req.archetypes or [], "Archetypes"),
        fmt_list(req.traits or [], "Traits"),
    ]
    if req.style:
        parts.append(f"Style: {req.style}")
    user_msg = (
        "Create a system prompt for an AI persona with these attributes.\n" +
        "\n".join(parts) +
        "\nFocus on being friendly, age-appropriate, and helpful."
    )

    try:
        text = await chat_with_openrouter(message=user_msg, system_prompt=sys_msg)
        if not text or "OpenRouter API key is not configured" in text:
            # Surface as service unavailable; frontend can fallback
            return Response(status_code=503)
        return {"prompt": text.strip()}
    except Exception as e:
        logger.exception("/characters/suggest_system_prompt failed: %s", e)
        return Response(status_code=502, content=str(e).encode("utf-8"), media_type="text/plain")


# --- TTS (ElevenLabs) endpoint ---
@app.post("/tts")
async def tts(req: TTSRequest):
    """Synthesize speech using ElevenLabs and return MP3 bytes.

    If ElevenLabs is not configured or errors, returns 503/502 so the frontend
    can fall back to browser SpeechSynthesis.
    """
    import os
    from tts.elevenlabs_client import ElevenLabsTTSClient

    api_key = get_db_secret(db, "ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        # Not configured; let frontend fall back
        logger.warning("/tts: ELEVENLABS_API_KEY not configured; returning 503 for fallback")
        return Response(status_code=503, content=b"", media_type="application/octet-stream")

    voice_id = req.voice_id or os.getenv("ELEVENLABS_VOICE_ID")
    if not voice_id:
        # Voice not specified
        logger.warning("/tts: Missing voice_id (no request voice_id and ELEVENLABS_VOICE_ID not set)")
        return Response(status_code=400, content=b"Missing voice_id", media_type="text/plain")

    try:
        client = ElevenLabsTTSClient(api_key=api_key)
        logger.info("/tts: Starting ElevenLabs synthesis (len(text)=%d, voice_id=%s)", len(req.text or ""), voice_id)
        kwargs = {}
        if req.stability is not None:
            kwargs["stability"] = req.stability
        if req.similarity_boost is not None:
            kwargs["similarity_boost"] = req.similarity_boost
        if req.style is not None:
            kwargs["style"] = req.style
        if req.use_speaker_boost is not None:
            kwargs["use_speaker_boost"] = req.use_speaker_boost

        # Collect streamed MP3 chunks into a single buffer
        buf = bytearray()
        chunk_count = 0
        for chunk in client.stream(req.text, voice_id, **kwargs):
            if chunk:
                buf.extend(chunk)
                chunk_count += 1
        logger.info("/tts: ElevenLabs synthesis completed (chunks=%d, bytes=%d)", chunk_count, len(buf))

        return Response(content=bytes(buf), media_type="audio/mpeg")
    except Exception as e:
        # Let frontend fall back to speech synthesis
        logger.exception("/tts: ElevenLabs synthesis failed: %s", e)
        return Response(status_code=502, content=str(e).encode("utf-8"), media_type="text/plain")


@app.get("/tts/stream")
async def tts_stream(
    text: str,
    voice_id: str,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
):
    """Stream ElevenLabs MP3 chunks as they are synthesized.

    Designed for low-latency playback in the browser via <audio src>.
    """
    import os
    from tts.elevenlabs_client import ElevenLabsTTSClient

    api_key = get_db_secret(db, "ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        logger.warning("/tts/stream: ELEVENLABS_API_KEY not configured")
        return Response(status_code=503)

    def chunk_gen():
        try:
            client = ElevenLabsTTSClient(api_key=api_key)
            kwargs = {}
            if stability is not None:
                kwargs["stability"] = stability
            if similarity_boost is not None:
                kwargs["similarity_boost"] = similarity_boost
            if style is not None:
                kwargs["style"] = style
            if use_speaker_boost is not None:
                kwargs["use_speaker_boost"] = use_speaker_boost

            for chunk in client.stream(text, voice_id, **kwargs):
                if chunk:
                    yield chunk
        except Exception as e:
            logger.exception("/tts/stream failed: %s", e)
            # End the stream; client will handle fallback
            return

    return StreamingResponse(chunk_gen(), media_type="audio/mpeg")


@app.get("/tts/voices")
async def list_voices():
    """Return available ElevenLabs voices (id + name).

    If API key not set, return 503 so frontend can hide selector.
    """
    import os
    api_key = get_db_secret(db, "ELEVENLABS_API_KEY") or os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        logger.warning("/tts/voices: ELEVENLABS_API_KEY not configured")
        return Response(status_code=503)

    try:
        from tts.elevenlabs_client import ElevenLabsTTSClient
        client = ElevenLabsTTSClient(api_key=api_key)
        raw_voices = client.list_voices()

        def get(v, key, alt=None):
            # Handles object or dict
            if isinstance(v, dict):
                return v.get(key) or (v.get(alt) if alt else None)
            return getattr(v, key, None) or (getattr(v, alt, None) if alt else None)

        voices = []
        for v in raw_voices or []:
            vid = get(v, "voice_id", "id")
            name = get(v, "name") or vid or "Unnamed"
            category = get(v, "category") or ""
            voices.append({"voice_id": vid, "name": name, "category": category})

        return {"voices": voices}
    except Exception as e:
        logger.exception("/tts/voices: failed to fetch voices: %s", e)
        return Response(status_code=502, content=str(e).encode("utf-8"), media_type="text/plain")


@app.post("/users/{user_id}/history/import")
def import_history(user_id: int, req: ImportRequest, db: Session = Depends(get_db)):
    """Import a list of messages into a user's history (JSON only).

    Accepts roles of 'user', 'bot', or 'assistant' (assistant is mapped to 'bot').
    Ignores 'system' messages.
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    def parse_ts(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
        except Exception:
            return None

    created = 0
    for m in req.messages:
        role = (m.role or "").lower().strip()
        if role == "assistant":
            role = "bot"
        if role not in ("user", "bot"):
            continue  # skip unsupported roles like 'system'
        ts = parse_ts(m.timestamp)
        msg = models.Message(user_id=user.id, role=role, content=m.content)
        if ts is not None:
            msg.timestamp = ts
        db.add(msg)
        created += 1
    db.commit()
    return {"imported": created}


# Serve the frontend directory as static files at the root.
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
