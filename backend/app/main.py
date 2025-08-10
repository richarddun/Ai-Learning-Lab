from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from backend.services.openrouter import chat_with_openrouter

app = FastAPI(title="AI Learning Lab")


class ChatRequest(BaseModel):
    """Request body for chat interactions."""

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


@app.post("/chat")
async def chat(req: ChatRequest):
    """Proxy a chat request to the OpenRouter API."""

    response_text = await chat_with_openrouter(req.message, req.system_prompt)
    return {"response": response_text}
