"""Deterministic expectation checks. Each failure message says what and why."""

from __future__ import annotations

import json
import re
from typing import Any

from jsonpath_ng import parse as jsonpath_parse

from agent_tester.models import Expectations

_MISSING = object()


def _show(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = repr(text) if isinstance(value, str) else text
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _lookup(path: str, response: Any, extracted: dict[str, Any]) -> Any:
    if not path.startswith("$"):
        return extracted.get(path, _MISSING)
    if isinstance(response, (dict, list)):
        matches = jsonpath_parse(path).find(response)
        if matches:
            return matches[0].value
    return _MISSING


def score(
    expected: Expectations | None,
    *,
    final_text: str | None,
    response: Any,
    extracted: dict[str, Any],
    latency_ms: float | None,
) -> tuple[bool | None, list[str]]:
    """Return (passed, failures). ``passed`` is None when there is nothing to check."""
    if expected is None or expected.is_empty():
        return None, []

    text = final_text or ""
    failures: list[str] = []
    fields = expected.model_fields_set

    if "equals" in fields:
        want = expected.equals
        got: Any = text
        if not isinstance(want, str):
            try:
                got = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                got = text
        if got != want:
            failures.append(f"equals: expected {_show(want)}, got {_show(got)}")

    for needle in expected.contains or []:
        if needle not in text:
            failures.append(f"contains: missing {_show(needle)}")

    for needle in expected.not_contains or []:
        if needle in text:
            failures.append(f"not_contains: found {_show(needle)}")

    if expected.regex is not None and not re.search(expected.regex, text, re.DOTALL):
        failures.append(f"regex: /{expected.regex}/ did not match")

    for path, want in (expected.jsonpath_equals or {}).items():
        got = _lookup(path, response, extracted)
        if got is _MISSING:
            failures.append(f"jsonpath_equals: {path} not found (want {_show(want)})")
        elif got != want:
            failures.append(f"jsonpath_equals: {path} expected {_show(want)}, got {_show(got)}")

    budget = expected.max_latency_ms
    if budget is not None and latency_ms is not None and latency_ms > budget:
        failures.append(f"max_latency_ms: took {latency_ms:.0f} ms, budget {budget:.0f} ms")

    return not failures, failures
