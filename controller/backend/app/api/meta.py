from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tester import OUTCOME_CLASSES
from agent_tester import __version__ as tester_version
from app import __version__
from app.config import settings
from app.db import get_db
from app.errors import ApiError
from app.models import Agent, Dataset
from app.schemas import DemoOut, Meta
from app.services.import_dataset import case_rows, parse_or_raise

log = logging.getLogger(__name__)
public = APIRouter(tags=["meta"])
router = APIRouter(tags=["meta"])

DEMO_AGENTS = ("mock-echo", "mock-flaky")
DEMO_DATASET = ("Smoke test", "smoke.jsonl")


def _demo_params(preset: dict[str, Any]) -> dict[str, Any]:
    params = dict(preset.get("params") or {})
    if settings.demo_agent_url:
        params["base_url"] = settings.demo_agent_url.rstrip("/")
    return params


def load_presets() -> list[dict[str, Any]]:
    root = Path(settings.presets_dir)
    out = []
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("skipping invalid preset %s", path)
            continue
        data["id"] = path.stem
        out.append(data)
    # Demo presets first: they work out of the box.
    return sorted(out, key=lambda p: (p.get("category") != "demo", p.get("name", "")))


@public.get("/health", summary="Liveness and database check")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    return {"status": "ok", "version": __version__}


@router.get("/meta", response_model=Meta, summary="Server capabilities for the UI")
async def meta() -> Meta:
    return Meta(
        version=__version__,
        tester_version=tester_version,
        runner_mode=settings.runner_mode,
        auth_enabled=bool(settings.api_token),
        max_concurrent_runs=settings.max_concurrent_runs,
        outcome_classes=OUTCOME_CLASSES,
        allow_literal_secrets=settings.allow_literal_secrets,
    )


@router.get("/presets", summary="Contract templates shipped with the server")
async def list_presets() -> list[dict[str, Any]]:
    return load_presets()


@router.post(
    "/demo",
    response_model=DemoOut,
    summary="Create the demo agents and dataset",
    description="Idempotent: reuses demo agents/dataset that already exist (matched by name).",
)
async def create_demo(db: AsyncSession = Depends(get_db)) -> DemoOut:
    presets = {p["id"]: p for p in load_presets()}
    agent_ids = []
    for preset_id in DEMO_AGENTS:
        preset = presets.get(preset_id)
        if preset is None:
            raise ApiError(500, f"demo preset '{preset_id}' is missing from {settings.presets_dir}")
        existing = (
            (await db.execute(select(Agent).where(Agent.name == preset["name"]))).scalars().first()
        )
        if existing is None:
            existing = Agent(
                id=str(uuid.uuid4()),
                name=preset["name"],
                description=preset.get("description", ""),
                contract_json=json.dumps(preset["contract"]),
                params_json=json.dumps(_demo_params(preset)),
                enabled=True,
            )
            db.add(existing)
        existing.enabled = True
        agent_ids.append(existing.id)

    name, filename = DEMO_DATASET
    ds = (await db.execute(select(Dataset).where(Dataset.name == name))).scalars().first()
    if ds is None:
        path = Path(settings.samples_dir) / filename
        if not path.exists():
            raise ApiError(500, f"sample dataset missing: {path}")
        cases = parse_or_raise(path.read_text(encoding="utf-8"), filename)
        ds = Dataset(
            id=str(uuid.uuid4()),
            name=name,
            description="Six quick cases exercising contains, regex, not_contains and latency budgets.",
            source_type="local",
        )
        db.add(ds)
        db.add_all(case_rows(ds.id, cases))
    await db.commit()
    return DemoOut(agent_ids=agent_ids, dataset_id=ds.id)
