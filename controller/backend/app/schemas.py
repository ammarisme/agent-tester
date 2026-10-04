"""Request/response models for the HTTP API."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


# ── Agents ────────────────────────────────────────────────────────────


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    contract: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    contract: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    contract: dict[str, Any]
    params: dict[str, Any]
    enabled: bool
    created_at: str | None
    updated_at: str | None


class AgentTestRequest(BaseModel):
    """Dry-run a (possibly unsaved) contract against one input."""

    contract: dict[str, Any]
    params: dict[str, Any] = Field(default_factory=dict)
    input: Any = None
    expected: dict[str, Any] | None = None


# ── Datasets ──────────────────────────────────────────────────────────


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    source_type: Literal["local", "uri"] = "local"
    uri: str | None = None
    cases: list[dict[str, Any]] = Field(default_factory=list)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    uri: str | None = None


class DatasetOut(BaseModel):
    id: str
    name: str
    description: str
    source_type: str
    uri: str | None
    case_count: int
    tags: list[str] = Field(default_factory=list)
    created_at: str | None
    updated_at: str | None


class CaseOut(BaseModel):
    id: str
    input: Any
    expected: dict[str, Any] | None
    tags: list[str]


class ParseRequest(BaseModel):
    text: str
    filename: str | None = None


class ParseResult(BaseModel):
    format: str | None
    count: int
    preview: list[CaseOut]
    errors: list[dict[str, Any]]


# ── Runs ──────────────────────────────────────────────────────────────


class RunCreate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    agent_ids: list[str] = Field(min_length=1)
    dataset_id: str | None = None
    dataset_uri: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class RunAgentRef(BaseModel):
    id: str
    name: str


class RunProgress(BaseModel):
    completed: int
    total: int


class RunOut(BaseModel):
    id: str
    name: str | None
    status: str
    dataset_id: str | None
    dataset_name: str | None
    dataset_uri: str | None
    agents: list[RunAgentRef]
    options: dict[str, Any]
    progress: RunProgress
    summary: dict[str, Any] | None
    error: str | None
    tester_version: str | None
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    duration_ms: float | None


class ResultRow(BaseModel):
    id: int
    agent_id: str
    agent_name: str | None
    case_id: str
    trial: int
    tags: list[str]
    outcome_class: str
    passed: bool | None
    failures: list[str]
    latency_ms: float | None
    status_code: int | None
    error: str | None
    final_text_preview: str | None


class ResultDetail(ResultRow):
    input: Any
    expected: dict[str, Any] | None
    final_text: str | None
    metrics: dict[str, Any]
    extracted: dict[str, Any]
    trajectory: dict[str, Any]


# ── Meta ──────────────────────────────────────────────────────────────


class Meta(BaseModel):
    version: str
    tester_version: str
    runner_mode: str
    auth_enabled: bool
    max_concurrent_runs: int
    outcome_classes: dict[str, str]
    allow_literal_secrets: bool


class DemoOut(BaseModel):
    agent_ids: list[str]
    dataset_id: str
