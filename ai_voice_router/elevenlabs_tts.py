from __future__ import annotations
from typing import Generator, Optional

from .secrets import SecretsProvider, EnvSecretsProvider


def stream_elevenlabs_mp3(
    text: str,
    voice_id: str,
    *,
    secrets: Optional[SecretsProvider] = None,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
) -> Generator[bytes, None, None]:
    """Yield MP3 chunks from ElevenLabs.

    Caller is responsible for handling missing config (i.e., when no API key)
    by checking for StopIteration immediately or catching exceptions.
    """
    secrets = secrets or EnvSecretsProvider()
    api_key = secrets.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not configured")

    from tts.elevenlabs_client import ElevenLabsTTSClient

    kwargs = {}
    if stability is not None:
        kwargs["stability"] = stability
    if similarity_boost is not None:
        kwargs["similarity_boost"] = similarity_boost
    if style is not None:
        kwargs["style"] = style
    if use_speaker_boost is not None:
        kwargs["use_speaker_boost"] = use_speaker_boost

    client = ElevenLabsTTSClient(api_key=api_key)
    for chunk in client.stream(text, voice_id, **kwargs):
        if chunk:
            yield chunk


def synthesize_elevenlabs_mp3(
    text: str,
    voice_id: str,
    *,
    secrets: Optional[SecretsProvider] = None,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
) -> bytes:
    """Return the full MP3 as bytes for ElevenLabs TTS."""
    buf = bytearray()
    for chunk in stream_elevenlabs_mp3(
        text,
        voice_id,
        secrets=secrets,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    ):
        buf.extend(chunk)
    return bytes(buf)

