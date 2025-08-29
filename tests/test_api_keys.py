from fastapi.testclient import TestClient
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.app import main


def test_api_key_crud(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("")
    monkeypatch.setattr(main, "ENV_PATH", env_path)

    client = TestClient(main.app)

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
