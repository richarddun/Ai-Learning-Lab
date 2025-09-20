from __future__ import annotations
from typing import List, Dict, Optional

from .secrets import SecretsProvider, EnvSecretsProvider


def list_piper_local_voices() -> List[str]:
    """Return list of local Piper voice IDs (based on downloaded .onnx files)."""
    from backend.piper_utils.voice_manager import list_local_voice_ids

    return list_local_voice_ids()


def list_voices(secrets: Optional[SecretsProvider] = None) -> Dict[str, list]:
    """List available voices by provider.

    Returns a dict with keys:
      - "piper": list[str] of local voice ids
      - "elevenlabs": list[dict] each with {voice_id, name, category?}
    """
    res: Dict[str, list] = {"piper": [], "elevenlabs": []}
    # Piper
    try:
        res["piper"] = list_piper_local_voices()
    except Exception:
        res["piper"] = []

    # ElevenLabs
    try:
        secrets = secrets or EnvSecretsProvider()
        api_key = secrets.get("ELEVENLABS_API_KEY")
        if api_key:
            from tts.elevenlabs_client import ElevenLabsTTSClient

            client = ElevenLabsTTSClient(api_key=api_key)
            raw = client.list_voices() or []

            def get(v, key, alt=None):
                if isinstance(v, dict):
                    return v.get(key) or (v.get(alt) if alt else None)
                return getattr(v, key, None) or (getattr(v, alt, None) if alt else None)

            out = []
            for v in raw:
                vid = get(v, "voice_id", "id")
                name = get(v, "name") or vid or "Unnamed"
                category = get(v, "category") or ""
                out.append({"voice_id": vid, "name": name, "category": category})
            res["elevenlabs"] = out
    except Exception:
        # Keep elevenlabs empty when not available/misconfigured
        pass

    return res

