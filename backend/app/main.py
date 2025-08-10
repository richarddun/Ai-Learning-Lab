from fastapi import FastAPI
from pydantic import BaseModel
from backend.services.openrouter import chat_with_openrouter

app = FastAPI(title="AI Learning Lab")


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    """Proxy a chat request to the OpenRouter API."""
    response_text = await chat_with_openrouter(req.message)
    return {"response": response_text}
