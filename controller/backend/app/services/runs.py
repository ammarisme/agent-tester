"""Turn API requests into EvalJobs and persist results."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tester import (
    AgentContract,
    AgentSpec,
    Case,
    CaseResult,
    DatasetRef,
    EvalJob,
    EvalOptions,
)
from app.config import settings
from app.errors import ApiError, invalid, pydantic_errors
from app.models import Agent, Dataset, DatasetCase, TestRun, utcnow
from app.models import CaseResult as CaseResultRow
from app.schemas import RunCreate
from app.serializers import case_dict

ACTIVE_STATUSES = ("queued", "running", "pending")


def validate_contract(contract: dict) -> AgentContract:
    try:
        return AgentContract.model_validate(contract)
    except ValidationError as exc:
        raise invalid("contract is invalid", pydantic_errors(exc, "contract")) from exc


def require_http_uri(uri: str, field: str = "dataset_uri") -> str:
    uri = uri.strip()
    if not uri.startswith(("http://", "https://")):
        raise invalid(
            "dataset URI must be http(s)",
            [{"loc": field, "message": "must start with http:// or https://"}],
        )
    return uri


async def dataset_cases(db: AsyncSession, dataset_id: str) -> list[Case]:
    rows = (
        await db.execute(
            select(DatasetCase)
            .where(DatasetCase.dataset_id == dataset_id)
            .order_by(DatasetCase.position, DatasetCase.id)
        )
    ).scalars()
    return [Case.model_validate(case_dict(r)) for r in rows]


async def build_run(db: AsyncSession, body: RunCreate) -> tuple[TestRun, EvalJob]:
    try:
        options = EvalOptions.model_validate(body.options)
    except ValidationError as exc:
        raise invalid("run options are invalid", pydantic_errors(exc, "options")) from exc

    specs: list[AgentSpec] = []
    for agent_id in dict.fromkeys(body.agent_ids):  # de-duplicate, keep order
        agent = await db.get(Agent, agent_id)
        if agent is None:
            raise invalid(
                "unknown agent", [{"loc": "agent_ids", "message": f"agent {agent_id} not found"}]
            )
        if not agent.enabled:
            raise invalid(
                "agent is disabled",
                [{"loc": "agent_ids", "message": f"'{agent.name}' is disabled"}],
            )
        try:
            contract = AgentContract.model_validate_json(agent.contract_json)
        except ValidationError as exc:
            raise invalid(
                f"agent '{agent.name}' has an invalid contract; edit it before running",
                pydantic_errors(exc, "contract"),
            ) from exc
        specs.append(
            AgentSpec(
                id=agent.id,
                name=agent.name,
                contract=contract,
                params=json.loads(agent.params_json or "{}"),
            )
        )

    dataset_name: str | None = None
    n_cases = 0
    if body.dataset_uri:
        ref = DatasetRef(uri=require_http_uri(body.dataset_uri))
        dataset_name = body.dataset_uri
    elif body.dataset_id:
        ds = await db.get(Dataset, body.dataset_id)
        if ds is None:
            raise invalid(
                "unknown dataset", [{"loc": "dataset_id", "message": "dataset not found"}]
            )
        dataset_name = ds.name
        if ds.source_type == "uri" and ds.uri:
            ref = DatasetRef(uri=ds.uri)
        else:
            cases = await dataset_cases(db, ds.id)
            if not cases:
                raise invalid(
                    "dataset is empty",
                    [
                        {
                            "loc": "dataset_id",
                            "message": f"'{ds.name}' has no cases; import some first",
                        }
                    ],
                )
            ref = DatasetRef(cases=cases)
            n_cases = len(cases)
    else:
        raise invalid(
            "choose a dataset",
            [{"loc": "dataset_id", "message": "dataset_id or dataset_uri is required"}],
        )

    run_id = str(uuid.uuid4())
    callback = (
        f"{settings.public_api_base}/api/runs/{run_id}/results"
        if settings.runner_mode == "docker"
        else None
    )
    job = EvalJob(run_id=run_id, agents=specs, dataset=ref, options=options, callback_url=callback)
    run = TestRun(
        id=run_id,
        name=(body.name or "").strip() or None,
        status="queued",
        options_json=options.model_dump_json(),
        dataset_id=body.dataset_id if not body.dataset_uri else None,
        dataset_name=dataset_name,
        dataset_uri=ref.uri,
        agents_json=json.dumps([{"id": s.id, "name": s.name} for s in specs]),
        total=len(specs) * n_cases * options.repeats,
        completed=0,
    )
    return run, job


def result_rows(run_id: str, results: Iterable[CaseResult]) -> list[CaseResultRow]:
    return [
        CaseResultRow(
            run_id=run_id,
            agent_id=r.agent_id,
            agent_name=r.agent_name,
            case_key=r.case_id,
            trial=r.trial,
            tags_json=json.dumps(r.tags),
            input_json=json.dumps(r.input),
            expected_json=json.dumps(r.expected) if r.expected is not None else None,
            outcome_class=r.outcome_class,
            passed=r.passed,
            failures_json=json.dumps(r.failures),
            latency_ms=r.latency_ms,
            status_code=r.status_code,
            metrics_json=json.dumps(r.metrics),
            extracted_json=json.dumps(r.extracted, default=str),
            trajectory_json=json.dumps(r.trajectory, default=str),
            final_text=r.final_text,
            error=r.error,
        )
        for r in results
    ]


async def replace_results(db: AsyncSession, run_id: str, results: list[CaseResult]) -> None:
    await db.execute(delete(CaseResultRow).where(CaseResultRow.run_id == run_id))
    db.add_all(result_rows(run_id, results))


def finish(
    run: TestRun, status: str, *, summary: dict | None = None, error: str | None = None
) -> None:
    run.status = status
    if summary is not None:
        run.summary_json = json.dumps(summary)
    run.error = error
    run.finished_at = utcnow()
    if run.started_at is None:
        run.started_at = run.finished_at


def ensure_exists(run: TestRun | None) -> TestRun:
    if run is None:
        raise ApiError(404, "run not found")
    return run
