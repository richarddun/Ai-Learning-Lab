"""Simple secret storage with reversible encryption.

This module provides a very lightweight way to encrypt API keys before
storing them in the database. It intentionally avoids external
dependencies by using HMAC-SHA256 as a keystream generator.

Security note: This is a pragmatic improvement over plaintext storage,
but not a substitute for dedicated secret management. Keep the master
key safe and out of version control.
"""

from __future__ import annotations

import base64
import hmac
import os
import struct
from hashlib import sha256
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from . import models


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MASTER_KEY_FILE = PROJECT_ROOT / ".secrets_key"


def _load_master_key() -> bytes:
    # Priority: env var, then file, else generate
    env_key = os.getenv("APP_SECRET_KEY")
    if env_key:
        try:
            # Allow either raw or base64
            try:
                return base64.urlsafe_b64decode(env_key.encode())
            except Exception:
                return env_key.encode()
        except Exception:
            pass

    if MASTER_KEY_FILE.exists():
        data = MASTER_KEY_FILE.read_bytes()
        return data.strip()

    key = os.urandom(32)
    try:
        MASTER_KEY_FILE.write_bytes(key)
        try:
            os.chmod(MASTER_KEY_FILE, 0o600)
        except Exception:
            pass
    except Exception:
        # If we can't write, fallback to ephemeral key (secrets won't roundtrip after restart)
        pass
    return key


_MASTER_KEY = _load_master_key()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        msg = nonce + struct.pack(">I", counter)
        block = hmac.new(key, msg, sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def encrypt(plaintext: str) -> str:
    data = plaintext.encode("utf-8")
    nonce = os.urandom(16)
    ks = _keystream(_MASTER_KEY, nonce, len(data))
    ct = bytes([a ^ b for a, b in zip(data, ks)])
    payload = b"\x01" + nonce + ct  # versioned
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decrypt(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode("ascii"))
    if not raw or raw[0] != 1:
        raise ValueError("Unsupported secret format")
    nonce = raw[1:17]
    ct = raw[17:]
    ks = _keystream(_MASTER_KEY, nonce, len(ct))
    pt = bytes([a ^ b for a, b in zip(ct, ks)])
    return pt.decode("utf-8")


def get_secret(db: Session, name: str) -> Optional[str]:
    rec = db.query(models.ApiSecret).filter(models.ApiSecret.name == name).first()
    if rec and rec.value_enc:
        try:
            return decrypt(rec.value_enc)
        except Exception:
            return None
    # Fallback to environment for development only if enabled
    if os.getenv("ALLOW_ENV_SECRETS", "0") in ("1", "true", "True"):
        return os.getenv(name)
    return None


def set_secret(db: Session, name: str, value: str) -> None:
    enc = encrypt(value)
    rec = db.query(models.ApiSecret).filter(models.ApiSecret.name == name).first()
    if rec:
        rec.value_enc = enc
    else:
        rec = models.ApiSecret(name=name, value_enc=enc)
        db.add(rec)
    db.commit()


def delete_secret(db: Session, name: str) -> None:
    rec = db.query(models.ApiSecret).filter(models.ApiSecret.name == name).first()
    if rec:
        db.delete(rec)
        db.commit()
