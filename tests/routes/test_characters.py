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


def test_character_crud_and_prompt(client, monkeypatch):
    # Create
    resp = client.post(
        "/characters",
        json={"name": "Hero", "system_prompt": "", "voice_id": "", "avatar": ""},
    )
    assert resp.status_code == 200
    char_id = resp.json()["id"]

    # List
    resp = client.get("/characters")
    assert resp.json()["characters"][0]["name"] == "Hero"

    # Update
    resp = client.put(f"/characters/{char_id}", json={"system_prompt": "Be nice"})
    assert resp.json()["system_prompt"] == "Be nice"

    # Suggest system prompt
    async def fake_prompt(*args, **kwargs):
        return "You are a kind assistant."

    monkeypatch.setattr(main, "chat_with_openrouter", fake_prompt)
    resp = client.post(
        "/characters/suggest_system_prompt",
        json={"genres": ["fantasy"], "traits": ["brave"]},
    )
    assert resp.status_code == 200
    assert "prompt" in resp.json()

    # Delete
    resp = client.delete(f"/characters/{char_id}")
    assert resp.json() == {"deleted": True}
    assert client.get("/characters").json()["characters"] == []
