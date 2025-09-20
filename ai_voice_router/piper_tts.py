from __future__ import annotations
from typing import Generator, Optional, Dict, Any

import uuid
import json as _json

from .secrets import SecretsProvider  # kept for symmetry; not needed for Piper


def _wav_header(sample_rate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    """Return a stream-friendly WAV header with very large data size."""
    import struct

    byte_rate = sample_rate * channels * sampwidth
    block_align = channels * sampwidth
    data_size = 0xFFFFFFFF
    riff_size = (data_size + 36) & 0xFFFFFFFF
    header = [
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, sampwidth * 8),
        b"data",
        struct.pack("<I", data_size),
    ]
    return b"".join(header)


def _to_bool(v: Optional[str | bool], default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("1", "true", "on", "yes")


def _to_int_or_none(v: Optional[str | int]) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(s)
    except Exception:
        return None


def _to_float(v: Optional[str | float], default: float) -> float:
    if v is None:
        return default
    if isinstance(v, (float, int)):
        return float(v)
    s = str(v).strip()
    if not s:
        return default
    try:
        return float(s)
    except Exception:
        return default


def stream_piper_wav(
    text: str,
    voice_id: str,
    *,
    preset: str = "wizard",
    fx_overrides: Optional[Dict[str, Any]] = None,
    bypass_fx: Optional[bool] = False,
    speaker_id: Optional[int] = None,
    length_scale: Optional[float] = 0.96,
    noise_scale: Optional[float] = 0.60,
    noise_w: Optional[float] = 0.8,
) -> Generator[bytes, None, None]:
    """Yield a valid WAV stream synthesized by Piper with optional FX.

    Notes:
      - Requires piper-tts installed, and model available or downloadable.
      - Voices dir can be overridden via env PIPER_VOICES_DIR (see voice_manager).
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
            list_local_voice_files,
        )
        from piper.config import SynthesisConfig
    except Exception as e:
        raise RuntimeError(f"Piper/FX not available: {e}")

    rid = uuid.uuid4().hex[:8]

    # Load model path and select fallback if needed
    try:
        model_path = ensure_voice_local(voice_id)
    except Exception:
        locals_list = list_local_voice_files()
        if locals_list:
            voice_id = locals_list[0].stem
            model_path = locals_list[0]
        else:
            model_path = ensure_voice_local("en_GB-alba-medium")
            voice_id = "en_GB-alba-medium"

    voice = get_voice(voice_id)
    sr = read_sample_rate_from_sidecar(model_path)

    # Build FX board
    over = fx_overrides or {}
    board = build_board(preset, over)

    # Build synthesis config
    _cfg_values = {
        "speaker_id": speaker_id,
        "length_scale": length_scale,
        "noise_scale": noise_scale,
        "noise_w": noise_w,
    }
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

    # Emit WAV header first
    yield _wav_header(sr)

    def _chunk_to_pcm16_bytes(ch):
        try:
            import numpy as _np
        except Exception:
            _np = None
        if isinstance(ch, (bytes, bytearray, memoryview)):
            return bytes(ch)
        if _np is not None and isinstance(ch, _np.ndarray):
            if ch.dtype == _np.int16:
                return ch.tobytes()
            if ch.dtype == _np.float32:
                i16 = _np.clip(ch, -1.0, 1.0)
                i16 = (i16 * 32767.0).astype(_np.int16)
                return i16.tobytes()
        if isinstance(ch, list) and _np is not None:
            arr = _np.asarray(ch)
            if arr.dtype != _np.int16:
                arr = _np.clip(arr, -1.0, 1.0)
                arr = (arr * 32767.0).astype(_np.int16)
            return arr.tobytes()
        for attr in ("audio", "audio_bytes", "data", "samples", "pcm", "pcm16", "buffer", "bytes", "frames"):
            if hasattr(ch, attr):
                val = getattr(ch, attr)
                if isinstance(val, (bytes, bytearray, memoryview)):
                    return bytes(val)
                if _np is not None and isinstance(val, _np.ndarray):
                    if val.dtype == _np.int16:
                        return val.tobytes()
                    if val.dtype == _np.float32:
                        i16 = _np.clip(val, -1.0, 1.0)
                        i16 = (i16 * 32767.0).astype(_np.int16)
                        return i16.tobytes()
        return b""

    bypass = _to_bool(bypass_fx, False)

    # Synthesize (handle arg order variations across piper-tts versions)
    try:
        iterator = voice.synthesize(text, cfg)
    except TypeError:
        iterator = voice.synthesize(cfg, text)

    for ch in iterator:
        pcm16 = _chunk_to_pcm16_bytes(ch)
        if not pcm16:
            continue
        if not bypass:
            block = pcm16_to_float32(pcm16)
            block = apply_fx_block(board, block, sr)
            pcm16 = float32_to_pcm16(block)
        yield pcm16


def synthesize_piper_wav(
    text: str,
    voice_id: str,
    *,
    preset: str = "wizard",
    fx_overrides: Optional[Dict[str, Any]] = None,
    bypass_fx: Optional[bool] = False,
    speaker_id: Optional[int] = None,
    length_scale: Optional[float] = 0.96,
    noise_scale: Optional[float] = 0.60,
    noise_w: Optional[float] = 0.8,
) -> bytes:
    """Return a full WAV by collecting the stream."""
    buf = bytearray()
    for chunk in stream_piper_wav(
        text,
        voice_id,
        preset=preset,
        fx_overrides=fx_overrides,
        bypass_fx=bypass_fx,
        speaker_id=speaker_id,
        length_scale=length_scale,
        noise_scale=noise_scale,
        noise_w=noise_w,
    ):
        buf.extend(chunk)
    return bytes(buf)

