import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))
import pytest

from backend.services import openrouter


class DummySession:
    def close(self):
        pass


@pytest.fixture(autouse=True)
def dummy_session(monkeypatch):
    monkeypatch.setattr(openrouter, "SessionLocal", lambda: DummySession())


class DummyResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": "Hello"}}]}


class DummyStream:
    lines = [
        'data: {"choices":[{"delta":{"content":"He"}}]}',
        'data: {"choices":[{"delta":{"content":"llo"}}]}',
        'data: [DONE]',
    ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def raise_for_status(self):
        pass

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class DummyClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def post(self, url, json, headers):
        return DummyResponse()

    def stream(self, method, url, json, headers):
        return DummyStream()


@pytest.mark.asyncio
async def test_chat_with_openrouter_no_key(monkeypatch):
    monkeypatch.setattr(openrouter, "get_db_secret", lambda db, name: None)
    result = await openrouter.chat_with_openrouter(message="hi")
    assert result == "OpenRouter API key is not configured."


@pytest.mark.asyncio
async def test_chat_with_openrouter_success(monkeypatch):
    monkeypatch.setattr(openrouter, "get_db_secret", lambda db, name: "key")
    monkeypatch.setattr(openrouter.httpx, "AsyncClient", DummyClient)
    result = await openrouter.chat_with_openrouter(message="hi")
    assert result == "Hello"


@pytest.mark.asyncio
async def test_stream_chat_with_openrouter_no_key(monkeypatch):
    monkeypatch.setattr(openrouter, "get_db_secret", lambda db, name: None)
    tokens = [t async for t in openrouter.stream_chat_with_openrouter(message="hi")]
    assert tokens == ["OpenRouter API key is not configured."]


@pytest.mark.asyncio
async def test_stream_chat_with_openrouter_success(monkeypatch):
    monkeypatch.setattr(openrouter, "get_db_secret", lambda db, name: "key")
    monkeypatch.setattr(openrouter.httpx, "AsyncClient", DummyClient)
    tokens = []
    async for tok in openrouter.stream_chat_with_openrouter(message="hi"):
        tokens.append(tok)
    assert "".join(tokens) == "Hello"
