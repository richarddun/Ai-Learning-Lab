"""Utility functions for interacting with the OpenRouter API."""

import os
from typing import Any, Dict

import httpx


OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def chat_with_openrouter(message: str) -> str:
    """Send a prompt to OpenRouter and return the response text."""
    if not OPENROUTER_API_KEY:
        return "OpenRouter API key is not configured."

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
    data: Dict[str, Any] = {
        "model": "openrouter/auto",
        "messages": [{"role": "user", "content": message}],
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(OPENROUTER_URL, json=data, headers=headers)
        resp.raise_for_status()
        content = resp.json()
    return content.get("choices", [{}])[0].get("message", {}).get("content", "")
