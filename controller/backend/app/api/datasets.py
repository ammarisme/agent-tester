from __future__ import annotations

import json
import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tester import Case, DatasetParseError, parse_cases
from app.db import get_db
from app.errors import ApiError, not_found
from app.models import Dataset, DatasetCase
from app.schemas import (
    CaseOut,
    DatasetCreate,
    DatasetOut,
    DatasetUpdate,
    Page,
    ParseRequest,
    ParseResult,
)
from app.serializers import case_out, dataset_out
from app.services.import_dataset import (
    case_rows,
    detect_format,
    parse_or_raise,
    read_upload,
    validate_case_dicts,
)
from app.services.runs import dataset_cases, require_http_uri

router = APIRouter(prefix="/datasets", tags=["datasets"])
PREVIEW_CASES = 20


async def _get(db: AsyncSession, dataset_id: str) -> Dataset:
    ds = await db.get(Dataset, dataset_id)
    if ds is None:
        raise not_found("dataset")
    return ds


async def _stats(db: AsyncSession, dataset_ids: list[str]) -> dict[str, tuple[int, list[str]]]:
    if not dataset_ids:
        return {}
    counts = dict(
        (
            await db.execute(
                select(DatasetCase.dataset_id, func.count(DatasetCase.id))
                .where(DatasetCase.dataset_id.in_(dataset_ids))
                .group_by(DatasetCase.dataset_id)
            )
        ).all()
    )
    tags: dict[str, set[str]] = {i: set() for i in dataset_ids}
    rows = await db.execute(
        select(DatasetCase.dataset_id, DatasetCase.tags_json).where(
            DatasetCase.dataset_id.in_(dataset_ids), DatasetCase.tags_json != "[]"
        )
    )
    for ds_id, raw in rows:
        tags[ds_id].update(json.loads(raw or "[]"))
    return {i: (counts.get(i, 0), sorted(tags[i])) for i in dataset_ids}


async def _out(db: AsyncSession, ds: Dataset) -> DatasetOut:
    count, tags = (await _stats(db, [ds.id]))[ds.id]
    return dataset_out(ds, count, tags)


async def _fetch_remote(uri: str) -> list[Case]:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(uri)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiError(502, f"could not fetch {uri}: {exc}") from exc
    try:
        return parse_cases(resp.text, uri.split("?")[0])
    except DatasetParseError as exc:
        raise ApiError(422, f"remote dataset is invalid: {exc}", exc.errors) from exc


@router.get("", response_model=list[DatasetOut], summary="List datasets")
async def list_datasets(db: AsyncSession = Depends(get_db)) -> list[DatasetOut]:
    rows = list((await db.execute(select(Dataset).order_by(Dataset.created_at.desc()))).scalars())
    stats = await _stats(db, [d.id for d in rows])
    return [dataset_out(d, *stats[d.id]) for d in rows]


@router.post("", response_model=DatasetOut, status_code=201, summary="Create a dataset")
async def create_dataset(body: DatasetCreate, db: AsyncSession = Depends(get_db)) -> DatasetOut:
    uri = require_http_uri(body.uri or "", "uri") if body.source_type == "uri" else None
    cases = validate_case_dicts(body.cases) if body.cases else []
    ds = Dataset(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        description=body.description,
        source_type=body.source_type,
        uri=uri,
    )
    db.add(ds)
    db.add_all(case_rows(ds.id, cases))
    await db.commit()
    return await _out(db, ds)


@router.post(
    "/parse",
    response_model=ParseResult,
    summary="Preview how text would import",
    description="Parses JSON / JSONL / CSV text without saving. Always 200; problems are in `errors`.",
)
async def parse_preview(body: ParseRequest) -> ParseResult:
    fmt = detect_format(body.text, body.filename)
    try:
        cases = parse_cases(body.text, body.filename)
    except DatasetParseError as exc:
        return ParseResult(format=fmt, count=0, preview=[], errors=exc.errors)
    preview = [
        CaseOut(
            id=c.id,
            input=c.input,
            expected=c.expected.model_dump(exclude_unset=True) if c.expected else None,
            tags=c.tags,
        )
        for c in cases[:PREVIEW_CASES]
    ]
    return ParseResult(format=fmt, count=len(cases), preview=preview, errors=[])


@router.get("/{dataset_id}", response_model=DatasetOut, summary="Get a dataset")
async def get_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> DatasetOut:
    return await _out(db, await _get(db, dataset_id))


@router.patch("/{dataset_id}", response_model=DatasetOut, summary="Update a dataset")
async def update_dataset(
    dataset_id: str, body: DatasetUpdate, db: AsyncSession = Depends(get_db)
) -> DatasetOut:
    ds = await _get(db, dataset_id)
    if body.name is not None:
        ds.name = body.name.strip()
    if body.description is not None:
        ds.description = body.description
    if body.uri is not None:
        if ds.source_type != "uri":
            raise ApiError(400, "only URI datasets have a uri")
        ds.uri = require_http_uri(body.uri, "uri")
    await db.commit()
    await db.refresh(ds)
    return await _out(db, ds)


@router.delete("/{dataset_id}", status_code=204, summary="Delete a dataset")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)) -> None:
    ds = await _get(db, dataset_id)
    await db.execute(delete(DatasetCase).where(DatasetCase.dataset_id == dataset_id))
    await db.delete(ds)
    await db.commit()


@router.get("/{dataset_id}/cases", response_model=Page[CaseOut], summary="List cases")
async def list_cases(
    dataset_id: str,
    q: str | None = Query(default=None, description="Substring match on id, input or tags"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> Page[CaseOut]:
    ds = await _get(db, dataset_id)
    if ds.source_type == "uri" and ds.uri:
        cases = [
            CaseOut(
                id=c.id,
                input=c.input,
                expected=c.expected.model_dump(exclude_unset=True) if c.expected else None,
                tags=c.tags,
            )
            for c in await _fetch_remote(ds.uri)
        ]
        if q:
            needle = q.lower()
            cases = [c for c in cases if needle in json.dumps(c.model_dump()).lower()]
        return Page(
            items=cases[offset : offset + limit], total=len(cases), limit=limit, offset=offset
        )

    stmt = select(DatasetCase).where(DatasetCase.dataset_id == dataset_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                DatasetCase.case_key.ilike(like),
                DatasetCase.input_json.ilike(like),
                DatasetCase.tags_json.ilike(like),
            )
        )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(DatasetCase.position, DatasetCase.id).limit(limit).offset(offset)
        )
    ).scalars()
    return Page(items=[case_out(r) for r in rows], total=total, limit=limit, offset=offset)


@router.post("/{dataset_id}/import", response_model=DatasetOut, summary="Import cases from a file")
async def import_cases(
    dataset_id: str,
    file: UploadFile = File(..., description="JSON, JSONL or CSV"),
    mode: Literal["replace", "append"] = Query(default="replace"),
    db: AsyncSession = Depends(get_db),
) -> DatasetOut:
    ds = await _get(db, dataset_id)
    if ds.source_type == "uri":
        raise ApiError(400, "URI datasets are fetched at run time and cannot be imported into")
    cases = parse_or_raise(await read_upload(file), file.filename)
    start = 0
    if mode == "replace":
        await db.execute(delete(DatasetCase).where(DatasetCase.dataset_id == dataset_id))
    else:
        existing = {c.id for c in await dataset_cases(db, dataset_id)}
        clashes = sorted({c.id for c in cases} & existing)
        if clashes:
            raise ApiError(
                409,
                f"{len(clashes)} case id(s) already exist: {', '.join(clashes[:5])}"
                + ("…" if len(clashes) > 5 else ""),
            )
        start = len(existing)
    db.add_all(case_rows(ds.id, cases, start))
    await db.commit()
    await db.refresh(ds)
    return await _out(db, ds)


@router.get("/{dataset_id}/export", summary="Download cases as JSONL")
async def export_cases(dataset_id: str, db: AsyncSession = Depends(get_db)) -> Response:
    ds = await _get(db, dataset_id)
    cases = (
        await _fetch_remote(ds.uri)
        if ds.source_type == "uri" and ds.uri
        else await dataset_cases(db, dataset_id)
    )
    body = (
        "\n".join(c.model_dump_json(exclude_none=True, exclude_defaults=True) for c in cases) + "\n"
    )
    safe = (
        "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in ds.name).strip("-") or "dataset"
    )
    return Response(
        body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{safe}.jsonl"'},
    )
