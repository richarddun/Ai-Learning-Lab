import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.app import main
from backend.services import models


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_get_db
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_transcribe_success(client, monkeypatch):
    # Mock secret lookup and httpx client
    monkeypatch.setattr(main, "get_db_secret", lambda db, name: "KEY")

    class DummyResp:
        status_code = 200

        def json(self):
            return {"text": "hi"}

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

        async def post(self, *args, **kwargs):
            return DummyResp()

    monkeypatch.setattr(main, "httpx", type("httpx", (), {"AsyncClient": DummyAsyncClient}))

    files = {"file": ("a.wav", b"data", "audio/wav")}
    resp = client.post("/speech/transcribe", files=files)
    assert resp.status_code == 200
    assert resp.json() == {"text": "hi"}


def test_tts_and_voices_without_key(client):
    resp = client.post("/tts", json={"text": "hello", "voice_id": "v"})
    assert resp.status_code == 503
    resp = client.get("/tts/voices")
    assert resp.status_code == 503
