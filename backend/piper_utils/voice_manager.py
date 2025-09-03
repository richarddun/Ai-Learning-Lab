from __future__ import annotations
from pathlib import Path
from collections import OrderedDict
import json
from typing import Tuple

# Store voices under repo-local directory to avoid requiring /opt permissions
REPO_ROOT = Path(__file__).resolve().parents[3]
VOICES_DIR = REPO_ROOT / "voices"
VOICES_DIR.mkdir(parents=True, exist_ok=True)

_MAX_LOADED = 2
_loaded: "OrderedDict[str, object]" = OrderedDict()


def _hf_download(repo_id: str, filename: str, repo_type: str = "model", revision: str = "main") -> str:
    try:
        from huggingface_hub import hf_hub_download
    except Exception as e:
        raise RuntimeError("huggingface_hub is not installed") from e
    return hf_hub_download(repo_id=repo_id, filename=filename, repo_type=repo_type, revision=revision)


def voice_files_from_manifest(voice_id: str) -> Tuple[Path, Path]:
    manifest_path = _hf_download("rhasspy/piper-voices", "voices.json", repo_type="model", revision="main")
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if voice_id not in manifest:
        raise ValueError(f"Voice '{voice_id}' not found in voices.json")
    info = manifest[voice_id]
    files = info.get("files", {}) or {}

    # Newer voices.json format uses a map of file-path -> metadata
    # (e.g., {".../en_GB-alba-medium.onnx": {...}, ".../en_GB-alba-medium.onnx.json": {...}})
    # Older assumptions looked for explicit keys like 'onnx' or 'json'. Support both.
    onnx_rel = None
    json_rel = None

    # Try explicit fields first (legacy style)
    if isinstance(files, dict):
        for key in ("onnx", "model", "url"):
            val = files.get(key) or info.get(key)
            if isinstance(val, str) and val:
                onnx_rel = val
                break
        json_val = files.get("json")
        if isinstance(json_val, str) and json_val:
            json_rel = json_val

    # If not found, infer from file-path keys in the map
    if onnx_rel is None and isinstance(files, dict):
        file_keys = [k for k in files.keys() if isinstance(k, str)]
        onnx_candidates = [k for k in file_keys if k.endswith(".onnx")]
        if onnx_candidates:
            # Prefer a file whose basename (without suffix) matches voice_id
            from pathlib import Path as _P
            exact = next((k for k in onnx_candidates if _P(k).stem == voice_id), None)
            onnx_rel = exact or onnx_candidates[0]

        # Find the matching sidecar json if present
        if onnx_rel:
            candidate_json = f"{onnx_rel}.json"
            if candidate_json in files:
                json_rel = candidate_json
            elif json_rel is None:
                # Fall back to conventional sidecar naming even if not listed explicitly
                json_rel = candidate_json

    if not onnx_rel:
        raise ValueError(f"voices.json entry for {voice_id} missing '.onnx' file path")

    local_onnx = Path(_hf_download("rhasspy/piper-voices", onnx_rel, repo_type="model"))
    local_json = Path(_hf_download("rhasspy/piper-voices", json_rel, repo_type="model")) if json_rel else None

    dest_onnx = VOICES_DIR / Path(onnx_rel).name
    if dest_onnx != local_onnx:
        dest_onnx.write_bytes(local_onnx.read_bytes())
    if local_json is not None:
        dest_json = VOICES_DIR / (Path(onnx_rel).name + ".json")
        if dest_json != local_json:
            dest_json.write_bytes(local_json.read_bytes())
    else:
        dest_json = VOICES_DIR / (Path(onnx_rel).name + ".json")
    return dest_onnx, dest_json


def ensure_voice_local(voice_id: str) -> Path:
    if voice_id.endswith(".onnx"):
        p = Path(voice_id)
        if not p.exists():
            raise FileNotFoundError(p)
        return p
    onnx_path = VOICES_DIR / f"{voice_id}.onnx"
    json_path = VOICES_DIR / f"{voice_id}.onnx.json"
    if onnx_path.exists() and json_path.exists():
        return onnx_path
    onnx_path, _ = voice_files_from_manifest(voice_id)
    return onnx_path


def _load_piper_voice(model_path: Path):
    try:
        from piper.voice import PiperVoice
    except Exception as e:
        raise RuntimeError("piper-tts is not installed") from e
    return PiperVoice.load(str(model_path))


def get_voice(voice_key: str):
    if voice_key.endswith(".onnx"):
        key = Path(voice_key).stem
        path = Path(voice_key)
    else:
        key = voice_key
        path = ensure_voice_local(voice_key)
    if key in _loaded:
        _loaded.move_to_end(key)
        return _loaded[key]
    v = _load_piper_voice(path)
    _loaded[key] = v
    _loaded.move_to_end(key)
    while len(_loaded) > _MAX_LOADED:
        _loaded.popitem(last=False)
    return v


def read_sample_rate_from_sidecar(model_path: Path) -> int:
    sidecar = model_path.with_suffix(model_path.suffix + ".json")  # .onnx.json
    if sidecar.exists():
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            sr = int(meta.get("sample_rate", 22050))
            return sr
        except Exception:
            pass
    name = model_path.name
    if "low" in name:
        return 16000
    return 22050


def list_local_voice_files() -> list[Path]:
    try:
        return sorted(VOICES_DIR.glob("*.onnx"))
    except Exception:
        return []


def list_local_voice_ids() -> list[str]:
    return [p.stem for p in list_local_voice_files()]
