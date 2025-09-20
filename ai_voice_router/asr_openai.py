from __future__ import annotations
from typing import Optional

import httpx

from .secrets import SecretsProvider, EnvSecretsProvider


async def transcribe_openai_whisper(
    audio_bytes: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "audio/webm",
    model: str = "whisper-1",
    secrets: Optional[SecretsProvider] = None,
) -> str:
    """Transcribe audio using OpenAI Whisper via server-side API key.

    Returns the transcribed text. Raises an exception on API error.
    """
    secrets = secrets or EnvSecretsProvider()
    api_key = secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    files = {
        "file": (filename, audio_bytes, content_type),
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
        raise RuntimeError(f"OpenAI ASR error: {detail}")
    data = resp.json()
    return data.get("text", "")

