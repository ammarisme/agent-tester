"""API tests run against a temp SQLite DB and a real (local) mock agent served
through httpx's ASGI transport, so nothing touches the network."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = tempfile.mkdtemp(prefix="agent-tester-test-")
os.environ["DATABASE_PATH"] = str(Path(_TMP) / "test.db")
os.environ.setdefault("API_TOKEN", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
from asgi_lifespan import LifespanManager  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "mocks"))

from echo_agent import app as mock_app  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base  # noqa: E402

MOCK_BASE = "http://mock.test"


@pytest.fixture(autouse=True)
def _route_agent_calls_to_mock(monkeypatch):
    """Send every outbound runner request to the in-process mock agent."""
    real = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        if "transport" not in kwargs and "app" not in kwargs:
            kwargs["transport"] = httpx.ASGITransport(app=mock_app)
        real(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app = create_app()
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api.test") as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


def echo_contract() -> dict:
    return {
        "invoke": {
            "method": "POST",
            "url": "{{ agent.params.base_url }}/v1/chat",
            "headers": {"Content-Type": "application/json"},
            "body_template": {"message": "{{ input.message }}"},
            "timeout_s": 10,
        },
        "extract": {"final_text": "$.reply", "tokens": "$.tokens"},
    }


async def make_agent(client, name="echo", contract=None) -> dict:
    resp = await client.post(
        "/api/agents",
        json={
            "name": name,
            "contract": contract or echo_contract(),
            "params": {"base_url": MOCK_BASE},
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_dataset(client, cases=None) -> dict:
    cases = cases or [
        {"id": "a", "input": {"message": "hi"}, "expected": {"contains": "hi"}, "tags": ["smoke"]},
        {"id": "b", "input": {"message": "yo"}, "expected": {"contains": "nope"}},
    ]
    resp = await client.post("/api/datasets", json={"name": "ds", "cases": cases})
    assert resp.status_code == 201, resp.text
    return resp.json()
