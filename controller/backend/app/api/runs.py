from __future__ import annotations

import csv
import io
import json
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tester import RunResults
from agent_tester.report import junit_xml
from app.db import get_db
from app.errors import ApiError
from app.models import CaseResult, TestRun
from app.schemas import Page, ResultDetail, ResultRow, RunCreate, RunOut
from app.serializers import result_detail, result_row, run_out
from app.services.runner import RunManager
from app.services.runs import ACTIVE_STATUSES, build_run, ensure_exists, finish, replace_results

router = APIRouter(prefix="/runs", tags=["runs"])


def manager(request: Request) -> RunManager:
    return request.app.state.runs


async def _get(db: AsyncSession, run_id: str) -> TestRun:
    return ensure_exists(await db.get(TestRun, run_id))


async def _submit(db: AsyncSession, runs: RunManager, body: RunCreate) -> RunOut:
    run, job = await build_run(db, body)
    db.add(run)
    await db.commit()
    runs.submit(job)
    return run_out(run)


@router.get("", response_model=Page[RunOut], summary="List runs, newest first")
async def list_runs(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Match run name, dataset or agent name"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[RunOut]:
    stmt = select(TestRun)
    if status:
        stmt = stmt.where(TestRun.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                TestRun.name.ilike(like),
                TestRun.dataset_name.ilike(like),
                TestRun.agents_json.ilike(like),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(stmt.order_by(TestRun.created_at.desc()).limit(limit).offset(offset))
    ).scalars()
    return Page(items=[run_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("", response_model=RunOut, status_code=201, summary="Start a run")
async def create_run(
    body: RunCreate, db: AsyncSession = Depends(get_db), runs: RunManager = Depends(manager)
) -> RunOut:
    return await _submit(db, runs, body)


@router.get("/{run_id}", response_model=RunOut, summary="Get a run")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)) -> RunOut:
    return run_out(await _get(db, run_id))


@router.post("/{run_id}/cancel", response_model=RunOut, summary="Cancel a queued or running run")
async def cancel_run(
    run_id: str, db: AsyncSession = Depends(get_db), runs: RunManager = Depends(manager)
) -> RunOut:
    run = await _get(db, run_id)
    if run.status not in ACTIVE_STATUSES:
        raise ApiError(409, f"run is already {run.status}")
    if not runs.cancel(run_id):
        # Orphaned (e.g. controller restarted): nothing is executing it.
        finish(run, "cancelled", error="Cancelled.")
        await db.commit()
    else:
        await runs.wait(run_id)
    await db.refresh(run)
    return run_out(run)


@router.post(
    "/{run_id}/rerun",
    response_model=RunOut,
    status_code=201,
    summary="Run again with the same setup",
)
async def rerun(
    run_id: str, db: AsyncSession = Depends(get_db), runs: RunManager = Depends(manager)
) -> RunOut:
    src = await _get(db, run_id)
    agents = json.loads(src.agents_json or "[]")
    options = json.loads(src.options_json or "{}")
    body = RunCreate(
        name=src.name,
        agent_ids=[a["id"] for a in agents],
        dataset_id=src.dataset_id,
        dataset_uri=src.dataset_uri if not src.dataset_id else None,
        options=options,
    )
    return await _submit(db, runs, body)


@router.delete("/{run_id}", status_code=204, summary="Delete a run and its results")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)) -> None:
    run = await _get(db, run_id)
    if run.status in ACTIVE_STATUSES:
        raise ApiError(409, "cancel the run before deleting it")
    await db.execute(delete(CaseResult).where(CaseResult.run_id == run_id))
    await db.delete(run)
    await db.commit()


def _result_filters(stmt, agent_id, outcome, passed, q):
    if agent_id:
        stmt = stmt.where(CaseResult.agent_id == agent_id)
    if outcome:
        stmt = stmt.where(CaseResult.outcome_class.in_(outcome.split(",")))
    if passed is not None:
        stmt = stmt.where(CaseResult.passed.is_(passed))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                CaseResult.case_key.ilike(like),
                CaseResult.final_text.ilike(like),
                CaseResult.error.ilike(like),
                CaseResult.failures_json.ilike(like),
                CaseResult.tags_json.ilike(like),
            )
        )
    return stmt


_SORTS = {
    "case": (CaseResult.case_key, CaseResult.agent_id, CaseResult.trial),
    "latency": (CaseResult.latency_ms.desc(),),
    "outcome": (CaseResult.outcome_class, CaseResult.case_key),
}


@router.get("/{run_id}/results", response_model=Page[ResultRow], summary="List case results")
async def list_results(
    run_id: str,
    agent_id: str | None = None,
    outcome: str | None = Query(default=None, description="Comma-separated outcome classes"),
    passed: bool | None = None,
    q: str | None = None,
    sort: Literal["case", "latency", "outcome"] = "case",
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[ResultRow]:
    await _get(db, run_id)
    stmt = _result_filters(
        select(CaseResult).where(CaseResult.run_id == run_id), agent_id, outcome, passed, q
    )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(*_SORTS[sort]).limit(limit).offset(offset))).scalars()
    return Page(items=[result_row(r) for r in rows], total=total, limit=limit, offset=offset)


@router.get(
    "/{run_id}/results/{result_id}",
    response_model=ResultDetail,
    summary="Get one result with its trajectory",
)
async def get_result(
    run_id: str, result_id: int, db: AsyncSession = Depends(get_db)
) -> ResultDetail:
    row = await db.get(CaseResult, result_id)
    if row is None or row.run_id != run_id:
        raise ApiError(404, "result not found")
    return result_detail(row)


@router.get("/{run_id}/export", summary="Download results (json, csv or junit)")
async def export_results(
    run_id: str,
    format: Literal["json", "csv", "junit"] = "json",
    db: AsyncSession = Depends(get_db),
) -> Response:
    run = await _get(db, run_id)
    rows = (
        await db.execute(
            select(CaseResult).where(CaseResult.run_id == run_id).order_by(*_SORTS["case"])
        )
    ).scalars()
    details = [result_detail(r) for r in rows]
    stem = f"run-{run_id[:8]}"
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(
            [
                "agent",
                "case_id",
                "trial",
                "outcome",
                "passed",
                "latency_ms",
                "status_code",
                "failures",
                "error",
                "tags",
                "final_text",
            ]
        )
        for d in details:
            w.writerow(
                [
                    d.agent_name or d.agent_id,
                    d.case_id,
                    d.trial + 1,
                    d.outcome_class,
                    "" if d.passed is None else d.passed,
                    "" if d.latency_ms is None else round(d.latency_ms, 1),
                    d.status_code or "",
                    "; ".join(d.failures),
                    d.error or "",
                    ",".join(d.tags),
                    d.final_text or "",
                ]
            )
        return Response(
            buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )

    results = RunResults.model_validate(
        {
            "run_id": run.id,
            "status": run.status
            if run.status in ("completed", "failed", "cancelled")
            else "completed",
            "summary": json.loads(run.summary_json or "{}"),
            "error": run.error,
            "tester_version": run.tester_version,
            "case_results": [
                {
                    **d.model_dump(exclude={"id", "final_text_preview"}),
                    "agent_name": d.agent_name or d.agent_id,
                }
                for d in details
            ],
        }
    )
    if format == "junit":
        return Response(
            junit_xml(results),
            media_type="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{stem}.junit.xml"'},
        )
    return Response(
        results.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
    )


@router.post("/{run_id}/results", summary="Ingest results (used by the Docker runner)")
async def ingest_results(
    run_id: str, body: RunResults, db: AsyncSession = Depends(get_db)
) -> dict[str, bool]:
    run = await _get(db, run_id)
    if body.run_id != run_id:
        raise ApiError(400, "run_id in body does not match the URL")
    if run.status == "cancelled":
        return {"ok": False}
    await replace_results(db, run_id, body.case_results)
    run.total = run.completed = len(body.case_results)
    run.tester_version = body.tester_version
    finish(run, body.status, summary=body.summary, error=body.error)
    await db.commit()
    return {"ok": True}
