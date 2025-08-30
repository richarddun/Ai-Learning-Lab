from __future__ import annotations
import numpy as np
from typing import Dict, Any

try:
    from pedalboard import (
        Pedalboard,
        Reverb,
        Chorus,
        PitchShift,
        Distortion,
        HighpassFilter,
        LowpassFilter,
        Compressor,
        Delay,
        Gain,
    )
except Exception:
    # Provide minimal stubs so module import doesn't fail when pedalboard isn't installed.
    class _Stub:
        def __init__(self, *args, **kwargs):
            pass

        def __call__(self, x, sr):
            return x

    class Pedalboard(list):
        def __call__(self, x, sr):
            return x

    Reverb = Chorus = PitchShift = Distortion = HighpassFilter = LowpassFilter = Compressor = Delay = Gain = _Stub


def pcm16_to_float32(pcm_bytes: bytes) -> np.ndarray:
    x = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return x.reshape(1, -1)  # (channels=1, samples)


def float32_to_pcm16(audio: np.ndarray) -> bytes:
    if audio.ndim == 2:
        audio = audio[0]
    y = np.clip(audio, -1.0, 1.0)
    return (y * 32767.0).astype(np.int16).tobytes()


def apply_fx_block(board: Pedalboard, block: np.ndarray, sr: int) -> np.ndarray:
    try:
        out = board(block, sr)
    except Exception:
        # If pedalboard not available, pass-through
        out = block
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 1.0:
        out = out / peak * 0.98
    return out


def build_wizard_preset(over: Dict[str, Any] | None = None) -> Pedalboard:
    over = over or {}
    return Pedalboard([
        Gain(gain_db=float(over.get("gain_db", -2.0))),
        PitchShift(semitones=float(over.get("pitch_semitones", -2.0))),
        LowpassFilter(cutoff_frequency_hz=float(over.get("lowpass_hz", 9000.0))),
        Reverb(
            room_size=float(over.get("room_size", 0.90)),
            wet_level=float(over.get("wet", 0.28)),
            dry_level=float(over.get("dry", 0.72)),
            damping=float(over.get("damping", 0.35)),
            width=float(over.get("width", 1.0)),
        ),
        Compressor(
            threshold_db=float(over.get("thr_db", -18.0)),
            ratio=float(over.get("ratio", 3.0)),
            attack_ms=float(over.get("attack_ms", 8.0)),
            release_ms=float(over.get("release_ms", 120.0)),
        ),
    ])


def build_robot_preset(over: Dict[str, Any] | None = None) -> Pedalboard:
    over = over or {}
    return Pedalboard([
        HighpassFilter(cutoff_frequency_hz=float(over.get("hp_hz", 300.0))),
        LowpassFilter(cutoff_frequency_hz=float(over.get("lp_hz", 3200.0))),
        Delay(
            delay_seconds=float(over.get("delay_s", 0.012)),
            feedback=float(over.get("feedback", 0.20)),
            mix=float(over.get("mix", 0.25)),
        ),
        Distortion(drive_db=float(over.get("drive_db", 12.0))),
        Compressor(threshold_db=float(over.get("thr_db", -16.0)), ratio=float(over.get("ratio", 4.0))),
    ])


def build_fairy_preset(over: Dict[str, Any] | None = None) -> Pedalboard:
    over = over or {}
    return Pedalboard([
        Gain(gain_db=float(over.get("gain_db", -1.0))),
        PitchShift(semitones=float(over.get("pitch_semitones", 4.0))),
        Chorus(
            rate_hz=float(over.get("chorus_rate_hz", 1.6)),
            depth=float(over.get("chorus_depth", 0.4)),
            centre_delay_ms=float(over.get("chorus_delay_ms", 7.0)),
            feedback=float(over.get("chorus_fb", 0.15)),
            mix=float(over.get("chorus_mix", 0.35)),
        ),
        HighpassFilter(cutoff_frequency_hz=float(over.get("hp_hz", 160.0))),
        Reverb(
            room_size=float(over.get("room_size", 0.65)),
            wet_level=float(over.get("wet", 0.18)),
            dry_level=float(over.get("dry", 0.82)),
            damping=float(over.get("damping", 0.30)),
            width=float(over.get("width", 1.0)),
        ),
        Compressor(threshold_db=float(over.get("thr_db", -20.0)), ratio=float(over.get("ratio", 2.0))),
    ])


def build_goblin_preset(over: Dict[str, Any] | None = None) -> Pedalboard:
    over = over or {}
    return Pedalboard([
        PitchShift(semitones=float(over.get("pitch_semitones", -4.0))),
        LowpassFilter(cutoff_frequency_hz=float(over.get("lowpass_hz", 6500.0))),
        Distortion(drive_db=float(over.get("drive_db", 18.0))),
        Compressor(threshold_db=float(over.get("thr_db", -22.0)), ratio=float(over.get("ratio", 3.5))),
        Reverb(
            room_size=float(over.get("room_size", 0.4)),
            wet_level=float(over.get("wet", 0.10)),
            dry_level=float(over.get("dry", 0.90)),
        ),
    ])


PRESET_BUILDERS = {
    "wizard": build_wizard_preset,
    "robot": build_robot_preset,
    "fairy": build_fairy_preset,
    "goblin": build_goblin_preset,
}


def build_board(preset: str, overrides: Dict[str, Any] | None = None) -> Pedalboard:
    builder = PRESET_BUILDERS.get(preset)
    if not builder:
        return Pedalboard([])
    return builder(overrides or {})

