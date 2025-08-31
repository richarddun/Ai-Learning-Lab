import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.services import models, secrets


@pytest.fixture(autouse=True)
def fixed_master_key(monkeypatch):
    monkeypatch.setattr(secrets, "_MASTER_KEY", b"A" * 32)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_encrypt_decrypt_roundtrip():
    token = secrets.encrypt("secret")
    assert token != "secret"
    assert secrets.decrypt(token) == "secret"


def test_set_get_delete_secret(db_session):
    secrets.set_secret(db_session, "API", "123")
    assert secrets.get_secret(db_session, "API") == "123"

    secrets.set_secret(db_session, "API", "456")
    assert secrets.get_secret(db_session, "API") == "456"

    secrets.delete_secret(db_session, "API")
    assert secrets.get_secret(db_session, "API") is None


def test_get_secret_env_fallback(monkeypatch, db_session):
    monkeypatch.setenv("ALLOW_ENV_SECRETS", "1")
    monkeypatch.setenv("ENV_ONLY", "VALUE")
    assert secrets.get_secret(db_session, "ENV_ONLY") == "VALUE"
