from fastapi.testclient import TestClient

# Ensure the project root is on the Python path for test execution
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from backend.app import main
from backend.services import models
from backend.services.database import Base, engine, SessionLocal

# Ensure database tables exist for the test database
Base.metadata.create_all(bind=engine)

def test_chat_stream_persists_bot_message(monkeypatch):
    db = SessionLocal()
    user = models.User(name="StreamTester")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    async def fake_stream(*args, **kwargs):
        yield "hello"

    monkeypatch.setattr(main, "stream_chat_with_openrouter", fake_stream)

    client = TestClient(main.app)
    resp = client.post("/chat/stream", json={"user_id": user.id, "message": "Hi"})
    assert resp.status_code == 200
    assert resp.text == "hello"

    db = SessionLocal()
    bot_msg = (
        db.query(models.Message)
        .filter(models.Message.user_id == user.id, models.Message.role == "bot")
        .first()
    )
    db.close()

    assert bot_msg is not None
    assert bot_msg.content == "hello"
