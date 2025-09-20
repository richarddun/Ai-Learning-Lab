from __future__ import annotations
import os
from typing import Optional, Protocol


class SecretsProvider(Protocol):
    """Abstract provider for retrieving API keys/secrets.

    Implementations should return None if a secret is missing, not raise.
    """

    def get(self, name: str) -> Optional[str]:
        ...


class EnvSecretsProvider:
    """Default secrets provider backed by environment variables."""

    def __init__(self, prefix: str | None = None):
        self.prefix = prefix or ""

    def get(self, name: str) -> Optional[str]:
        key = f"{self.prefix}{name}" if self.prefix else name
        val = os.getenv(key)
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

