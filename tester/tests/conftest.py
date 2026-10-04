from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from agent_tester.models import AgentSpec, Case


def make_agent(
    contract: dict[str, Any], params: dict[str, Any] | None = None, name: str = "a"
) -> AgentSpec:
    return AgentSpec.model_validate(
        {"id": name, "name": name, "contract": contract, "params": params or {}}
    )


def make_case(**kw: Any) -> Case:
    kw.setdefault("id", "c1")
    return Case.model_validate(kw)


def echo_contract(url: str = "http://agent.test/chat", **extra: Any) -> dict[str, Any]:
    return {
        "invoke": {
            "method": "POST",
            "url": url,
            "body_template": {"message": "{{ input.message }}"},
            **extra,
        },
        "extract": {"final_text": "$.reply"},
    }


@pytest.fixture
def mock_client() -> Callable[[Callable[[httpx.Request], httpx.Response]], httpx.AsyncClient]:
    clients: list[httpx.AsyncClient] = []

    def factory(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
        c = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        clients.append(c)
        return c

    return factory


def echo_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    return httpx.Response(200, json={"reply": f"Echo: {body.get('message', '')}", "tokens": 3})
