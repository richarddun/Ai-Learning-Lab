import json
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


def test_profiles_route(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "Alice"


def test_user_crud_and_chat(client, monkeypatch):
    # Create user
    resp = client.post("/users", json={"name": "Tester"})
    assert resp.status_code == 200
    user_id = resp.json()["id"]

    # List users
    resp = client.get("/users")
    assert resp.json()["users"][0]["name"] == "Tester"

    # Update preferences
    resp = client.put(f"/users/{user_id}/preferences", json={"preferences": "{\"lang\": \"en\"}"})
    assert resp.status_code == 200
    prefs = json.loads(resp.json()["preferences"])
    assert prefs["lang"] == "en"

    # Update avatar
    resp = client.put(f"/users/{user_id}/avatar", json={"avatar": "url"})
    assert resp.status_code == 200
    prefs = json.loads(resp.json()["preferences"])
    assert prefs["avatar"] == "url"

    # Update meta
    resp = client.put(
        f"/users/{user_id}/meta", json={"system_prompt": "hi", "voice_id": "v1"}
    )
    assert resp.status_code == 200
    prefs = json.loads(resp.json()["preferences"])
    assert prefs["system_prompt"] == "hi"
    assert prefs["voice_id"] == "v1"

    # Rename
    resp = client.put(f"/users/{user_id}/name", params={"name": "Renamed"})
    assert resp.json()["name"] == "Renamed"

    # Suggest conversation name with seed
    resp = client.get("/conversations/suggest_name", params={"seed": 123})
    assert "name" in resp.json()

    # Chat endpoint stores history
    async def fake_chat_with_openrouter(*args, **kwargs):
        return "bot reply"

    monkeypatch.setattr(main, "chat_with_openrouter", fake_chat_with_openrouter)
    resp = client.post(
        "/chat", json={"user_id": user_id, "message": "hello", "system_prompt": "s"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"response": "bot reply"}

    # History should contain user and bot messages
    history = client.get(f"/users/{user_id}/history").json()["history"]
    roles = [h["role"] for h in history]
    assert roles == ["user", "bot"]

    # Import additional history
    resp = client.post(
        f"/users/{user_id}/history/import",
        json={"messages": [{"role": "user", "content": "imported"}]},
    )
    assert resp.json() == {"imported": 1}

    history = client.get(f"/users/{user_id}/history").json()["history"]
    contents = [h["content"] for h in history]
    assert "imported" in contents

    # Suggest name from history (mocked)
    async def fake_title(*args, **kwargs):
        return "Amazing Chat Title For Tester"

    monkeypatch.setattr(main, "chat_with_openrouter", fake_title)
    resp = client.post(f"/users/{user_id}/suggest_name")
    assert resp.status_code == 200
    assert "name" in resp.json()

    # Delete user
    resp = client.delete(f"/users/{user_id}")
    assert resp.json() == {"deleted": True}
    assert client.get("/users").json()["users"] == []
