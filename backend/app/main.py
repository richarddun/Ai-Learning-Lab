
from typing import List, Optional
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from backend.services.openrouter import chat_with_openrouter
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


@app.post("/chat")

async def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """Proxy a chat request to the OpenRouter API while persisting history."""
    user = db.query(models.User).filter(models.User.id == req.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_msg = models.Message(user_id=user.id, role="user", content=req.message)
    db.add(user_msg)
    db.commit()

    response_text = await chat_with_openrouter(req.message)

    bot_msg = models.Message(user_id=user.id, role="bot", content=response_text)
    db.add(bot_msg)
    db.commit()


    return {"response": response_text}


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


@app.put("/users/{user_id}/preferences")
def update_preferences(user_id: int, req: PreferencesUpdate, db: Session = Depends(get_db)):
    """Update stored preferences for a user."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.preferences = req.preferences
    db.commit()
    db.refresh(user)
    return {"id": user.id, "name": user.name, "preferences": user.preferences}


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
