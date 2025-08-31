from fastapi.testclient import TestClient
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.app import main
from backend.services import models


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Force .env path to a temp file and disable env fallback
    env_path = tmp_path / ".env"
    env_path.write_text("")
    monkeypatch.setattr(main, "ENV_PATH", env_path)
    monkeypatch.setenv("ALLOW_ENV_SECRETS", "0")

    # Use an in-memory SQLite DB to avoid leaking state from local.db
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


def test_api_key_crud(client):
    resp = client.get("/settings/api_keys")
    assert resp.status_code == 200
    assert resp.json() == {"keys": []}

    resp = client.post("/settings/api_keys", json={"name": "TEST_KEY", "value": "123"})
    assert resp.status_code == 200

    resp = client.get("/settings/api_keys")
    assert resp.json() == {"keys": [{"name": "TEST_KEY", "has_value": True}]}

    resp = client.post("/settings/api_keys", json={"name": "TEST_KEY", "value": "456"})
    assert resp.status_code == 200
    resp = client.get("/settings/api_keys")
    assert resp.json() == {"keys": [{"name": "TEST_KEY", "has_value": True}]}

    resp = client.delete("/settings/api_keys/TEST_KEY")
    assert resp.status_code == 200
    resp = client.get("/settings/api_keys")
    assert resp.json() == {"keys": []}
