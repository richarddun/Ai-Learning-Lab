"""Utility functions for interacting with the OpenRouter API."""

import json
import os
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from dotenv import load_dotenv


load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def chat_with_openrouter(
    message: Optional[str] = None,
    system_prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
) -> str:
    """Send a prompt to OpenRouter and return the response text."""

    if not OPENROUTER_API_KEY:
        return "OpenRouter API key is not configured."

    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}

    msg_list: List[Dict[str, str]] = []
    if messages is not None:
        msg_list = messages
    else:
        if system_prompt:
            msg_list.append({"role": "system", "content": system_prompt})
        if message is not None:
            msg_list.append({"role": "user", "content": message})

    data: Dict[str, Any] = {
        "model": "openrouter/auto",
        "messages": msg_list,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(OPENROUTER_URL, json=data, headers=headers)
        resp.raise_for_status()
        content = resp.json()
    return content.get("choices", [{}])[0].get("message", {}).get("content", "")


async def stream_chat_with_openrouter(
    message: Optional[str] = None,
    system_prompt: Optional[str] = None,
    messages: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[str, None]:
    """Yield tokens from OpenRouter's streaming API."""

    if not OPENROUTER_API_KEY:
        yield "OpenRouter API key is not configured."
        return

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Accept": "text/event-stream",
    }

    msg_list: List[Dict[str, str]] = []
    if messages is not None:
        msg_list = messages
    else:
        if system_prompt:
            msg_list.append({"role": "system", "content": system_prompt})
        if message is not None:
            msg_list.append({"role": "user", "content": message})

    data: Dict[str, Any] = {
        "model": "openrouter/auto",
        "stream": True,
        "messages": msg_list,
    }

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST", OPENROUTER_URL, json=data, headers=headers
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if not payload or payload == "[DONE]":
                    break
                try:
                    content = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = content.get("choices", [{}])[0].get("delta", {}).get("content")
                if delta:
                    yield delta
