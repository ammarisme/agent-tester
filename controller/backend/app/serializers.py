"""ORM rows → API models."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.models import Agent, CaseResult, Dataset, DatasetCase, TestRun
from app.schemas import (
    AgentOut,
    CaseOut,
    DatasetOut,
    ResultDetail,
    ResultRow,
    RunAgentRef,
    RunOut,
    RunProgress,
)

PREVIEW_CHARS = 280


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops tzinfo; values are always stored in UTC.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def agent_out(a: Agent) -> AgentOut:
    return AgentOut(
        id=a.id,
        name=a.name,
        description=a.description or "",
        contract=_loads(a.contract_json, {}),
        params=_loads(a.params_json, {}),
        enabled=a.enabled,
        created_at=iso(a.created_at),
        updated_at=iso(a.updated_at),
    )


def dataset_out(d: Dataset, case_count: int, tags: list[str] | None = None) -> DatasetOut:
    return DatasetOut(
        id=d.id,
        name=d.name,
        description=d.description or "",
        source_type=d.source_type,
        uri=d.uri,
        case_count=case_count,
        tags=tags or [],
        created_at=iso(d.created_at),
        updated_at=iso(d.updated_at),
    )


def case_out(c: DatasetCase) -> CaseOut:
    return CaseOut(
        id=c.case_key,
        input=_loads(c.input_json, None),
        expected=_loads(c.expected_json, None),
        tags=_loads(c.tags_json, []),
    )


def case_dict(c: DatasetCase) -> dict[str, Any]:
    """Full case for the runner, including extra keys templates read as case.*."""
    return {**_loads(c.extra_json, {}), **case_out(c).model_dump()}


def run_out(r: TestRun) -> RunOut:
    status = "queued" if r.status == "pending" else r.status  # 0.1 used "pending"
    duration = None
    if r.started_at and r.finished_at:
        duration = (r.finished_at - r.started_at).total_seconds() * 1000
    return RunOut(
        id=r.id,
        name=r.name,
        status=status,
        dataset_id=r.dataset_id,
        dataset_name=r.dataset_name,
        dataset_uri=r.dataset_uri,
        agents=[RunAgentRef(**a) for a in _loads(r.agents_json, [])],
        options=_loads(r.options_json, {}),
        progress=RunProgress(completed=r.completed or 0, total=r.total or 0),
        summary=_loads(r.summary_json, None),
        error=r.error,
        tester_version=r.tester_version,
        created_at=iso(r.created_at),
        started_at=iso(r.started_at),
        finished_at=iso(r.finished_at),
        duration_ms=duration,
    )


def _preview(text: str | None) -> str | None:
    if text is None or len(text) <= PREVIEW_CHARS:
        return text
    return text[: PREVIEW_CHARS - 1] + "…"


def result_row(r: CaseResult) -> ResultRow:
    return ResultRow(
        id=r.id,
        agent_id=r.agent_id,
        agent_name=r.agent_name,
        case_id=r.case_key,
        trial=r.trial or 0,
        tags=_loads(r.tags_json, []),
        outcome_class=r.outcome_class,
        passed=r.passed,
        failures=_loads(r.failures_json, []),
        latency_ms=r.latency_ms,
        status_code=r.status_code,
        error=r.error,
        final_text_preview=_preview(r.final_text),
    )


def result_detail(r: CaseResult) -> ResultDetail:
    return ResultDetail(
        **result_row(r).model_dump(),
        input=_loads(r.input_json, None),
        expected=_loads(r.expected_json, None),
        final_text=r.final_text,
        metrics=_loads(r.metrics_json, {}),
        extracted=_loads(r.extracted_json, {}),
        trajectory=_loads(r.trajectory_json, {}),
    )
