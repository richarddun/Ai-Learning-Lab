from typing import List, Optional
from datetime import datetime, timezone
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse, Response, HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import logging
import random
import os
import base64
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import Session
import httpx
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
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
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
    # Image provider config (optional UI control)
    provider: Optional[str] = None  # 'openai' (default) or 'openrouter'
    model: Optional[str] = None     # optional override (e.g., OpenRouter model id)


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


@app.post("/speech/transcribe")
async def transcribe_speech(
    file: UploadFile = File(...),
    model: str = Form("whisper-1"),
    db: Session = Depends(get_db),
):
    """Proxy audio transcription to OpenAI using a server-side API key.

    Expects multipart/form-data with fields:
      - file: audio blob
      - model: optional, defaults to "whisper-1"
    Returns JSON: {"text": "..."}
    """
    api_key = get_db_secret(db, "OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key is not configured.")

    try:
        audio_bytes = await file.read()
        files = {
            "file": (file.filename or "audio.webm", audio_bytes, file.content_type or "audio/webm"),
            "model": (None, model),
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers=headers,
                files=files,
            )
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = {"status": resp.status_code, "text": resp.text}
            raise HTTPException(status_code=resp.status_code, detail=detail)
        data = resp.json()
        return {"text": data.get("text", "")}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Transcription failed")
        raise HTTPException(status_code=500, detail=str(e))


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
    """Generate a kid-friendly avatar image for a character using the selected provider.

    Stores the image under frontend/assets/characters/{id}/ and updates the character avatar URL.
    """
    c = db.query(models.Character).filter(models.Character.id == char_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Character not found")

    # Decide provider; default to OpenAI for compatibility
    provider = (req.provider or "openai").strip().lower()
    if provider not in ("openai", "openrouter"):
        provider = "openai"

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

    # Provider-specific httpx usage
    import httpx

    if provider == "openrouter":
        openrouter_key = get_db_secret(db, "OPENROUTER_API_KEY")
        if not openrouter_key:
            raise HTTPException(status_code=503, detail="OpenRouter API key not configured")
        or_headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Learning Lab",
        }

        async def fetch_image_bytes(model: str) -> bytes:
            # Use chat completions with modalities per OpenRouter docs
            chosen_model = (req.model or model or "google/gemini-2.5-flash-image-preview").strip()
            payload = {
                "model": chosen_model,
                "messages": [{"role": "user", "content": composed_prompt}],
                "modalities": ["image", "text"],
            }
            async with httpx.AsyncClient(timeout=120) as client:
                rc = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=or_headers, json=payload)
            if rc.status_code >= 400:
                try:
                    logger.error("/avatar/generate (openrouter %s) error %s: %s", chosen_model, rc.status_code, rc.text)
                except Exception:
                    pass
                rc.raise_for_status()
            try:
                cjson = rc.json()
            except Exception:
                raise RuntimeError("OpenRouter chat returned non-JSON for image generation")
            msg = (cjson.get("choices") or [{}])[0].get("message", {})
            images = msg.get("images") or []
            if isinstance(images, list) and images:
                first = images[0] or {}
                iu = (first.get("image_url") or {}).get("url") or first.get("url")
                if isinstance(iu, str) and iu.startswith("data:image/"):
                    import re
                    m = re.match(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", iu)
                    if m:
                        return base64.b64decode(m.group(1))
            content = msg.get("content")
            if isinstance(content, str):
                import re
                m = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
                if m:
                    return base64.b64decode(m.group(1))
            raise RuntimeError("OpenRouter did not include images in response")
    else:
        openai_key = get_db_secret(db, "OPENAI_API_KEY")
        if not openai_key:
            raise HTTPException(status_code=503, detail="OpenAI API key not configured")
        headers = {
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json",
        }

        async def fetch_image_bytes(model: str) -> bytes:
            body = {
                "model": "dall-e-3",
                "prompt": composed_prompt,
                "size": size,
                "n": 1
            }
            if req.seed is not None:
                body["seed"] = req.seed
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post("https://api.openai.com/v1/images/generations", headers=headers, json=body)
            if r.status_code >= 400:
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
            if provider == "openai" and 400 <= he.response.status_code < 500:
                # Fallback model for OpenAI path
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
async def tts(req: TTSRequest, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
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
async def list_voices(db: Session = Depends(get_db)):
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
# ----------------- Piper TTS + Admin (streaming WAV with FX) -----------------
# We register these at the end to avoid import issues when optional deps are missing.

def _wav_header(sample_rate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    import io, wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(sample_rate)
        w.writeframes(b"")
    return buf.getvalue()


@app.post("/tts/stream")
def piper_tts_stream(
    text: str = Form(...),
    voice_id: str = Form(...),
    preset: str = Form("wizard"),
    # Accept strings so blank values don't cause 422; we'll parse safely.
    speaker_id: Optional[str] = Form(None),
    length_scale: Optional[str] = Form("0.96"),
    noise_scale: Optional[str] = Form("0.60"),
    noise_w: Optional[str] = Form("0.8"),
    fx_overrides: Optional[str] = Form(None),
):
    """Stream WAV audio synthesized by Piper and processed with pedalboard FX.

    This POST route accepts form-data and returns audio/wav suitable for <audio> playback.
    It coexists with the existing GET /tts/stream (ElevenLabs MP3).
    """
    try:
        from backend.piper_utils.character_fx import (
            build_board,
            apply_fx_block,
            pcm16_to_float32,
            float32_to_pcm16,
        )
        from backend.piper_utils.voice_manager import (
            get_voice,
            ensure_voice_local,
            read_sample_rate_from_sidecar,
        )
        # Piper 1 API (import lazily to avoid failing app startup when missing)
        from piper.voice import SynthesisConfig
    except Exception as e:
        # Optional deps missing; surface a 503 so clients can fallback
        raise HTTPException(status_code=503, detail=f"Piper/FX not available: {e}")

    import json as _json
    # Load voice and sample rate
    voice = get_voice(voice_id)
    sr = read_sample_rate_from_sidecar(ensure_voice_local(voice_id))

    # Build FX board for this request
    over = _json.loads(fx_overrides) if fx_overrides else {}
    board = build_board(preset, over)

    # Safe parsing helpers for optional fields
    def _to_int_or_none(v: Optional[str]) -> Optional[int]:
        if v is None:
            return None
        s = str(v).strip()
        if not s:
            return None
        try:
            return int(s)
        except Exception:
            return None

    def _to_float(v: Optional[str], default: float) -> float:
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        try:
            return float(s)
        except Exception:
            return default

    # Build SynthesisConfig with compatibility across piper-tts versions
    _cfg_values = {
        "speaker_id": _to_int_or_none(speaker_id),
        "length_scale": _to_float(length_scale, 0.96),
        "noise_scale": _to_float(noise_scale, 0.60),
        "noise_w": _to_float(noise_w, 0.8),
    }
    # Filter unsupported args and alias where needed
    try:
        from inspect import signature
        _params = set(signature(SynthesisConfig).parameters.keys())
    except Exception:
        _params = {"speaker_id", "length_scale", "noise_scale", "noise_w", "noise_scale_w", "speaker"}

    _cfg_kwargs = {}
    for k, v in _cfg_values.items():
        if v is None:
            continue
        if k in _params:
            _cfg_kwargs[k] = v
        elif k == "noise_w" and "noise_scale_w" in _params:
            _cfg_kwargs["noise_scale_w"] = v
        elif k == "speaker_id" and "speaker" in _params:
            _cfg_kwargs["speaker"] = v

    cfg = SynthesisConfig(**_cfg_kwargs)

    def gen():
        # Header first for streaming WAV
        yield _wav_header(sr)
        last_block = None
        # piper-tts APIs differ on argument order; try text-first, then config-first
        try:
            iterator = voice.synthesize(text, cfg)
        except TypeError:
            iterator = voice.synthesize(cfg, text)
        # Adapter: normalize various chunk shapes to PCM16 bytes
        def _chunk_to_pcm16_bytes(ch):
            try:
                import numpy as _np
            except Exception:
                _np = None

            if isinstance(ch, (bytes, bytearray, memoryview)):
                return bytes(ch)
            # Common attributes across versions
            for attr in ("audio", "audio_bytes", "data", "samples"):
                if hasattr(ch, attr):
                    val = getattr(ch, attr)
                    if isinstance(val, (bytes, bytearray, memoryview)):
                        return bytes(val)
                    if _np is not None and isinstance(val, _np.ndarray):
                        if val.dtype == _np.int16:
                            return val.tobytes()
                        if val.dtype == _np.float32:
                            # Convert float32 [-1,1] to int16
                            i16 = _np.clip(val, -1.0, 1.0)
                            i16 = (i16 * 32767.0).astype(_np.int16)
                            return i16.tobytes()
                    if isinstance(val, list) and _np is not None:
                        arr = _np.asarray(val)
                        if arr.dtype != _np.int16:
                            arr = _np.clip(arr, -1.0, 1.0)
                            arr = (arr * 32767.0).astype(_np.int16)
                        return arr.tobytes()
            # Tuple style: (audio, ...)
            if isinstance(ch, tuple) and ch:
                return _chunk_to_pcm16_bytes(ch[0])
            # Fallback
            try:
                return bytes(ch)
            except Exception:
                raise AttributeError("Unsupported Piper chunk shape; missing audio bytes")

        for chunk in iterator:
            pcm = _chunk_to_pcm16_bytes(chunk)
            f32 = pcm16_to_float32(pcm)
            last_block = f32
            f32_fx = apply_fx_block(board, f32, sr)
            yield float32_to_pcm16(f32_fx)
        # Flush FX tail if any
        if last_block is not None:
            tail = apply_fx_block(board, last_block * 0, sr)
            yield float32_to_pcm16(tail)

    return StreamingResponse(gen(), media_type="audio/wav")

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.post("/admin/download")
def admin_download(voice_id: str = Form(...)):
    try:
        from backend.piper_utils.voice_manager import ensure_voice_local, VOICES_DIR
        onnx_path = ensure_voice_local(voice_id)
        return Response(
            f"Downloaded/verified: {onnx_path}\nSidecar: {onnx_path}.json\nStored in {VOICES_DIR}\n",
            media_type="text/plain",
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Avatar Gallery (browse + download) ---
@app.get("/avatar-gallery", response_class=HTMLResponse)
def avatar_gallery(request: Request):
    """Render a simple gallery page of generated avatars under frontend/assets/characters.

    Provides inline preview and a download link that forces attachment.
    """
    root = Path(__file__).resolve().parent.parent.parent
    assets_root = root / "frontend" / "assets"
    chars_dir = assets_root / "characters"

    items: List[dict] = []
    try:
        if chars_dir.exists():
            for char_dir in sorted(chars_dir.iterdir()):
                if not char_dir.is_dir():
                    continue
                char_id = char_dir.name
                for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
                    for f in char_dir.glob(ext):
                        try:
                            stat = f.stat()
                            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
                        except Exception:
                            mtime = None
                        rel_under_assets = f.relative_to(assets_root).as_posix()
                        items.append(
                            {
                                "char_id": char_id,
                                "rel": rel_under_assets,
                                "url": "/assets/" + rel_under_assets,
                                "name": f.name,
                                "mtime": mtime.isoformat() if mtime else "",
                                "epoch": stat.st_mtime if 'stat' in locals() else 0,
                            }
                        )
        items.sort(key=lambda d: d.get("epoch", 0), reverse=True)
    except Exception as e:
        logger.exception("/avatar-gallery listing failed: %s", e)
        items = []

    return templates.TemplateResponse(
        "avatar_gallery.html", {"request": request, "items": items}
    )


@app.get("/avatar-gallery/download")
def avatar_gallery_download(f: str):
    """Force download of an avatar located under frontend/assets.

    The `f` parameter is a POSIX-style relative path under `assets/` such as
    `characters/12/avatar-1693414312.png`. Path traversal is rejected.
    """
    root = Path(__file__).resolve().parent.parent.parent
    assets_root = (root / "frontend" / "assets").resolve()

    # Basic sanitation: reject absolute paths and parent refs
    rel = Path(f)
    if rel.is_absolute() or any(p == ".." for p in rel.parts):
        raise HTTPException(status_code=400, detail="Invalid path")

    file_path = (assets_root / rel).resolve()
    try:
        file_path.relative_to(assets_root)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path scope")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    import mimetypes
    media_type, _ = mimetypes.guess_type(str(file_path))
    media_type = media_type or "application/octet-stream"
    # Force download via Content-Disposition
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=file_path.name,
    )


# --- Standalone Image Generate (chat-like UI + API) ---
@app.get("/image_generate", response_class=HTMLResponse)
def image_generate_page(request: Request):
    """Simple page with a chat-like panel to generate and display images one by one."""
    return templates.TemplateResponse("image_generate.html", {"request": request})


@app.post("/image_generate")
async def image_generate(req: AvatarGenerateRequest, db: Session = Depends(get_db)):
    """Generate an image using the configured provider and store under
    ``frontend/assets/characters/generated``.

    Mirrors the avatar generator but without associating to a character.
    """
    # Decide provider (default to OpenAI for backwards compatibility)
    provider = (req.provider or "openai").strip().lower()
    if provider not in ("openai", "openrouter"):
        provider = "openai"

    base_style = req.style or "friendly colorful cartoon illustration"
    size = req.size or "1024x1024"
    extra_prompt = (req.prompt or "").strip()
    composed_prompt = base_style
    if extra_prompt:
        composed_prompt += f". {extra_prompt}"

    import httpx
    # Build provider-specific headers and fetcher
    if provider == "openrouter":
        openrouter_key = get_db_secret(db, "OPENROUTER_API_KEY")
        if not openrouter_key:
            raise HTTPException(status_code=503, detail="OpenRouter API key not configured")
        or_headers = {
            "Authorization": f"Bearer {openrouter_key}",
            "Content-Type": "application/json",
            "X-Title": "AI Learning Lab",
        }

        async def fetch_image_bytes(model: str) -> bytes:
            # Use chat completions with modalities per OpenRouter docs
            chosen_model = (req.model or model or "google/gemini-2.5-flash-image-preview").strip()
            payload = {
                "model": chosen_model,
                "messages": [{"role": "user", "content": composed_prompt}],
                "modalities": ["image", "text"],
            }
            async with httpx.AsyncClient(timeout=120) as client:
                rc = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=or_headers, json=payload)
            if rc.status_code >= 400:
                try:
                    logger.error("/image_generate (openrouter %s) error %s: %s", chosen_model, rc.status_code, rc.text)
                except Exception:
                    pass
                rc.raise_for_status()
            try:
                cjson = rc.json()
            except Exception:
                raise RuntimeError("OpenRouter chat returned non-JSON for image generation")
            msg = (cjson.get("choices") or [{}])[0].get("message", {})
            # Primary path: message.images -> [{ type: 'image_url', image_url: { url: 'data:image/...;base64,...' } }]
            images = msg.get("images") or []
            if isinstance(images, list) and images:
                first = images[0] or {}
                iu = (first.get("image_url") or {}).get("url") or first.get("url")
                if isinstance(iu, str) and iu.startswith("data:image/"):
                    import re
                    m = re.match(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", iu)
                    if m:
                        return base64.b64decode(m.group(1))
            # Fallback: try to find data URL in content string
            content = msg.get("content")
            if isinstance(content, str):
                import re
                m = re.search(r"data:image/[^;]+;base64,([A-Za-z0-9+/=]+)", content)
                if m:
                    return base64.b64decode(m.group(1))
            raise RuntimeError("OpenRouter did not include images in response")
    else:
        openai_key = get_db_secret(db, "OPENAI_API_KEY")
        if not openai_key:
            raise HTTPException(status_code=503, detail="OpenAI API key not configured")
        headers = {"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"}

        async def fetch_image_bytes(model: str) -> bytes:
            body = {
                "model": "dall-e-3",
                "prompt": composed_prompt,
                "size": size,
                "n": 1,
            }
            if req.seed is not None:
                body["seed"] = req.seed
            async with httpx.AsyncClient(timeout=90) as client:
                r = await client.post("https://api.openai.com/v1/images/generations", headers=headers, json=body)
                if r.status_code >= 400:
                    try:
                        logger.error("/image_generate %s error %s: %s", model, r.status_code, r.text)
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
            url = data[0].get("url")
            if not url:
                raise RuntimeError("No base64 or URL image content returned")
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    logger.error("/image_generate download error %s: %s", resp.status_code, resp.text)
                    resp.raise_for_status()
                return resp.content

    try:
        try:
            # For OpenRouter, the model default is handled inside fetcher
            img_bytes = await fetch_image_bytes(os.getenv("IMAGE_MODEL", "gpt-image-1"))
        except httpx.HTTPStatusError as he:
            if provider == "openai" and 400 <= he.response.status_code < 500:
                img_bytes = await fetch_image_bytes("dall-e-3")
            else:
                raise
    except Exception as e:
        detail_text = str(e)
        if isinstance(e, httpx.HTTPStatusError):
            try:
                detail_text = e.response.text
            except Exception:
                detail_text = str(e)
        # Try to soften prompt via OpenRouter suggestion similar to avatar endpoint
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
                err = parsed.get("error") if parsed else None
                if isinstance(err, dict):
                    message_txt = err.get("message")
                    code_txt = err.get("code")
            if (code_txt == "content_policy_violation") or (message_txt and ("safety system" in message_txt or "rejected" in message_txt)):
                sys_msg = (
                    "You rewrite image prompts to be kid-safe and G-rated. "
                    "Preserve intent; remove weapons, violence, gore, unsafe content. "
                    "Return only the rewritten prompt."
                )
                user_msg = (
                    "Original prompt (was rejected):\n" + composed_prompt + "\n\nRewrite as a friendly, colorful cartoon, G-rated."
                )
                try:
                    suggestion = await chat_with_openrouter(message=user_msg, system_prompt=sys_msg)
                except Exception:
                    suggestion = None
        except Exception:
            suggestion = None

        raise HTTPException(
            status_code=422 if suggestion else 502,
            detail={
                "error": {"code": "content_policy_violation" if suggestion else "image_generation_error", "message": detail_text},
                **({"suggestion": suggestion} if suggestion else {}),
            },
        )

    # Store
    try:
        if not img_bytes or len(img_bytes) == 0:
            raise RuntimeError("Empty image bytes")
        root = Path(__file__).resolve().parent.parent.parent
        # Re-use the avatars location so the gallery and download endpoints
        # automatically pick up these images as well.
        out_dir = root / "frontend" / "assets" / "characters" / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"img-{int(__import__('time').time())}.png"
        out_path = out_dir / filename
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        rel_url = f"/assets/characters/generated/{filename}"
        return {"url": rel_url}
    except Exception as e:
        logger.exception("/image_generate store failed: %s", e)
        raise HTTPException(status_code=500, detail="Image store failed")

# Mount the frontend static files last to avoid shadowing specific routes like /admin
frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
