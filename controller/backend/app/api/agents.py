from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_tester import AgentSpec, Case, CaseResult, invoke_once
from app.config import settings
from app.db import get_db
from app.errors import ApiError, invalid, not_found
from app.models import Agent, TestRunAgent
from app.schemas import AgentCreate, AgentOut, AgentTestRequest, AgentUpdate
from app.security import literal_secret_errors
from app.serializers import agent_out
from app.services.runs import validate_contract

router = APIRouter(prefix="/agents", tags=["agents"])


def _check_contract(contract: dict) -> None:
    validate_contract(contract)
    if not settings.allow_literal_secrets:
        errors = literal_secret_errors(contract)
        if errors:
            raise invalid("contract contains a literal credential", errors)


async def _get(db: AsyncSession, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise not_found("agent")
    return agent


@router.get("", response_model=list[AgentOut], summary="List agents")
async def list_agents(db: AsyncSession = Depends(get_db)) -> list[AgentOut]:
    rows = (await db.execute(select(Agent).order_by(Agent.created_at.desc()))).scalars()
    return [agent_out(a) for a in rows]


@router.post("", response_model=AgentOut, status_code=201, summary="Create an agent")
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)) -> AgentOut:
    _check_contract(body.contract)
    agent = Agent(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        description=body.description,
        contract_json=json.dumps(body.contract),
        params_json=json.dumps(body.params),
        enabled=body.enabled,
    )
    db.add(agent)
    await db.commit()
    return agent_out(agent)


@router.post(
    "/test",
    response_model=CaseResult,
    summary="Dry-run a contract against one input",
    description="Sends one real request using the given (possibly unsaved) contract and "
    "returns the full trajectory. Nothing is stored.",
)
async def test_agent(body: AgentTestRequest) -> CaseResult:
    contract = validate_contract(body.contract)
    spec = AgentSpec(id="test", name="test", contract=contract, params=body.params)
    try:
        case = Case.model_validate({"id": "test", "input": body.input, "expected": body.expected})
    except ValueError as exc:
        raise invalid("test case is invalid", [{"loc": "expected", "message": str(exc)}]) from exc
    try:
        return await asyncio.wait_for(
            invoke_once(spec, case), timeout=settings.test_request_timeout_s
        )
    except asyncio.TimeoutError as exc:
        raise ApiError(
            504,
            f"test request did not finish within {settings.test_request_timeout_s:.0f}s; "
            "full runs use the contract's own timeouts",
        ) from exc


@router.get("/{agent_id}", response_model=AgentOut, summary="Get an agent")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)) -> AgentOut:
    return agent_out(await _get(db, agent_id))


@router.patch("/{agent_id}", response_model=AgentOut, summary="Update an agent")
async def update_agent(
    agent_id: str, body: AgentUpdate, db: AsyncSession = Depends(get_db)
) -> AgentOut:
    agent = await _get(db, agent_id)
    if body.contract is not None:
        _check_contract(body.contract)
        agent.contract_json = json.dumps(body.contract)
    if body.name is not None:
        agent.name = body.name.strip()
    if body.description is not None:
        agent.description = body.description
    if body.params is not None:
        agent.params_json = json.dumps(body.params)
    if body.enabled is not None:
        agent.enabled = body.enabled
    await db.commit()
    await db.refresh(agent)
    return agent_out(agent)


@router.post(
    "/{agent_id}/duplicate", response_model=AgentOut, status_code=201, summary="Copy an agent"
)
async def duplicate_agent(agent_id: str, db: AsyncSession = Depends(get_db)) -> AgentOut:
    src = await _get(db, agent_id)
    copy = Agent(
        id=str(uuid.uuid4()),
        name=f"{src.name} (copy)",
        description=src.description,
        contract_json=src.contract_json,
        params_json=src.params_json,
        enabled=src.enabled,
    )
    db.add(copy)
    await db.commit()
    return agent_out(copy)


@router.delete("/{agent_id}", status_code=204, summary="Delete an agent")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)) -> None:
    agent = await _get(db, agent_id)
    # Past runs keep their own snapshot of the agent name; drop legacy link rows.
    await db.execute(delete(TestRunAgent).where(TestRunAgent.agent_id == agent_id))
    await db.delete(agent)
    await db.commit()
