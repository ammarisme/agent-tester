"""Execute one agent contract against one case: invoke, optionally poll, extract."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from jsonpath_ng import parse as jsonpath_parse

from agent_tester.models import AgentSpec, Case
from agent_tester.predicate import parse_predicate
from agent_tester.redact import redact_headers
from agent_tester.template import (
    ContractRenderError,
    build_context,
    render_headers,
    render_value,
)

MAX_POLL_STEPS_RECORDED = 200
# Poll responses that mean "try again" rather than "this will never work".
_RETRYABLE_POLL_STATUS = frozenset({408, 425, 429})


@dataclass
class InvokeOutcome:
    outcome_class: str
    latency_ms: float
    error: str | None = None
    status_code: int | None = None
    final_text: str | None = None
    response: Any = None
    extracted: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    n_polls: int = 0

    def trajectory(self) -> dict[str, Any]:
        out: dict[str, Any] = {"steps": self.steps}
        if self.warnings:
            out["warnings"] = self.warnings
        if self.n_polls > MAX_POLL_STEPS_RECORDED:
            out["poll_steps_omitted"] = self.n_polls - MAX_POLL_STEPS_RECORDED
        return out


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated {len(text) - limit} chars]"


def _parse_body(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def extract_fields(
    body: Any, raw_text: str, mapping: dict[str, str], warnings: list[str], phase: str
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, path in mapping.items():
        if path == "$":
            out[name] = raw_text if isinstance(body, (dict, list)) else body
            continue
        if not isinstance(body, (dict, list)):
            out[name] = None
            warnings.append(f"{phase} extract '{name}' ({path}): response is not JSON")
            continue
        matches = jsonpath_parse(path).find(body)
        if matches:
            out[name] = matches[0].value
        else:
            out[name] = None
            warnings.append(f"{phase} extract '{name}' ({path}) matched nothing")
    return out


def _transport_hint(exc: Exception, url: str) -> str:
    msg = str(exc) or exc.__class__.__name__
    if isinstance(exc, httpx.ConnectError) and ("localhost" in url or "127.0.0.1" in url):
        msg += (
            " — hint: inside Docker, localhost is the runner's own container; "
            "use the service name or host.docker.internal"
        )
    return msg


def _body_kwargs(body: Any) -> dict[str, Any]:
    if body is None:
        return {}
    if isinstance(body, (bytes, str)):
        return {"content": body}
    return {"json": body}


class _Timer:
    def __init__(self) -> None:
        self.t0 = time.perf_counter()

    def ms(self) -> float:
        return round((time.perf_counter() - self.t0) * 1000, 3)


async def invoke_agent(
    client: httpx.AsyncClient,
    agent: AgentSpec,
    case: Case,
    *,
    truncate: int = 32000,
    trial: int = 0,
) -> InvokeOutcome:
    contract = agent.contract
    case_dict = case.model_dump(mode="json")
    timer = _Timer()
    extracted: dict[str, Any] = {}
    warnings: list[str] = []
    steps: list[dict[str, Any]] = []

    def done(cls: str, **kw: Any) -> InvokeOutcome:
        return InvokeOutcome(
            outcome_class=cls,
            latency_ms=timer.ms(),
            extracted=extracted,
            steps=steps,
            warnings=warnings,
            **kw,
        )

    ctx = build_context(case=case_dict, agent_params=agent.params, trial=trial)
    spec = contract.invoke
    try:
        url = str(render_value(spec.url, ctx, "invoke.url"))
        headers = render_headers(spec.headers, ctx, "invoke.headers")
        body = render_value(spec.body_template, ctx, "invoke.body_template")
    except ContractRenderError as exc:
        steps.append({"phase": "invoke", "error": str(exc)})
        return done("config_error", error=str(exc))

    step: dict[str, Any] = {
        "phase": "invoke",
        "method": spec.method,
        "url": url,
        "request_headers": redact_headers(headers),
        "request_body": body,
        "started_ms": timer.ms(),
    }
    steps.append(step)
    try:
        resp = await client.request(
            spec.method, url, headers=headers, timeout=spec.timeout_s, **_body_kwargs(body)
        )
    except httpx.TimeoutException as exc:
        step.update(error=f"timeout after {spec.timeout_s}s", latency_ms=timer.ms())
        return done("timeout", error=f"invoke timed out after {spec.timeout_s}s ({exc!s})")
    except (httpx.HTTPError, OSError) as exc:
        msg = _transport_hint(exc, url)
        step.update(error=msg, latency_ms=timer.ms())
        return done("transport_error", error=msg)
    except (TypeError, ValueError) as exc:
        step.update(error=str(exc), latency_ms=timer.ms())
        return done("config_error", error=f"could not send request: {exc}")

    text = resp.text
    parsed = _parse_body(text)
    step.update(
        status_code=resp.status_code,
        content_type=resp.headers.get("content-type"),
        response_body=_truncate(text, truncate),
        latency_ms=round(timer.ms() - step["started_ms"], 3),
    )
    extracted.update(extract_fields(parsed, text, contract.extract, warnings, "invoke"))

    if resp.status_code >= 400:
        return done(
            "agent_error",
            error=f"HTTP {resp.status_code} {resp.reason_phrase}".strip(),
            status_code=resp.status_code,
            response=parsed,
            final_text=_final_text(extracted, text, contract.extract),
        )

    if contract.poll is None:
        return done(
            "success",
            status_code=resp.status_code,
            response=parsed,
            final_text=_final_text(extracted, text, contract.extract),
        )

    return await _poll(
        client,
        agent,
        case_dict,
        trial=trial,
        timer=timer,
        extracted=extracted,
        steps=steps,
        warnings=warnings,
        truncate=truncate,
        first_status=resp.status_code,
    )


def _final_text(extracted: dict[str, Any], raw: str, mapping: dict[str, str]) -> str | None:
    value = extracted.get("final_text") if "final_text" in mapping else raw
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


async def _poll(
    client: httpx.AsyncClient,
    agent: AgentSpec,
    case_dict: dict[str, Any],
    *,
    trial: int,
    timer: _Timer,
    extracted: dict[str, Any],
    steps: list[dict[str, Any]],
    warnings: list[str],
    truncate: int,
    first_status: int,
) -> InvokeOutcome:
    poll = agent.contract.poll
    assert poll is not None
    done_pred = parse_predicate(poll.done_when)
    failed_pred = parse_predicate(poll.failed_when) if poll.failed_when else None
    deadline = time.perf_counter() + poll.timeout_s
    mapping = {**agent.contract.extract, **poll.extract}
    n_polls = 0
    last_status: int | None = first_status
    last_body: Any = None
    last_text = ""

    def finish(cls: str, **kw: Any) -> InvokeOutcome:
        return InvokeOutcome(
            outcome_class=cls,
            latency_ms=timer.ms(),
            extracted=extracted,
            steps=steps,
            warnings=warnings,
            n_polls=n_polls,
            status_code=last_status,
            response=last_body,
            final_text=_final_text(extracted, last_text, mapping),
            **kw,
        )

    while True:
        ctx = build_context(
            case=case_dict, agent_params=agent.params, extracted=extracted, trial=trial
        )
        try:
            url = str(render_value(poll.url_template, ctx, "poll.url_template"))
            headers = render_headers(poll.headers, ctx, "poll.headers")
            body = render_value(poll.body_template, ctx, "poll.body_template")
        except ContractRenderError as exc:
            steps.append({"phase": "poll", "error": str(exc)})
            return finish("config_error", error=str(exc))

        n_polls += 1
        step: dict[str, Any] = {
            "phase": "poll",
            "attempt": n_polls,
            "method": poll.method,
            "url": url,
            "request_headers": redact_headers(headers),
            "started_ms": timer.ms(),
        }
        record = n_polls <= MAX_POLL_STEPS_RECORDED
        if record:
            steps.append(step)
        remaining = deadline - time.perf_counter()
        try:
            resp = await client.request(
                poll.method,
                url,
                headers=headers,
                timeout=max(1.0, min(60.0, remaining)),
                **_body_kwargs(body),
            )
        except (httpx.HTTPError, OSError) as exc:
            # Transient poll failures are retried until the poll deadline.
            step.update(error=_transport_hint(exc, url), latency_ms=timer.ms() - step["started_ms"])
        else:
            last_status = resp.status_code
            last_text = resp.text
            last_body = _parse_body(last_text)
            step.update(
                status_code=resp.status_code,
                response_body=_truncate(last_text, truncate),
                latency_ms=round(timer.ms() - step["started_ms"], 3),
            )
            if 400 <= resp.status_code < 500 and resp.status_code not in _RETRYABLE_POLL_STATUS:
                return finish("agent_error", error=f"poll returned HTTP {resp.status_code}")
            if resp.status_code < 400:
                extracted.update(
                    extract_fields(last_body, last_text, poll.extract, warnings, "poll")
                )
                if failed_pred and failed_pred.evaluate(last_body):
                    return finish("agent_error", error=f"terminal failure: {poll.failed_when}")
                if done_pred.evaluate(last_body):
                    return finish("success")

        if time.perf_counter() + poll.interval_s > deadline:
            state = extracted.get("status")
            detail = f" (last status: {state})" if state is not None else ""
            return finish(
                "timeout",
                error=f"poll did not satisfy done_when within {poll.timeout_s}s{detail}",
            )
        await asyncio.sleep(poll.interval_s)
