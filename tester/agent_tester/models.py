"""Typed contracts for jobs, agents, datasets and results.

These models are the single source of truth: the controller validates against
them, the runner executes them, and ``agent-tester schema`` exports them as
JSON Schema (see ``shared/schemas``).
"""

from __future__ import annotations

import re
import uuid
from typing import Any, Literal

from jsonpath_ng import parse as jsonpath_parse
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from agent_tester.predicate import PredicateError, parse_predicate

HttpMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

# Ordered from "best" to "worst"; the UI and reports rely on this order.
OUTCOME_CLASSES: dict[str, str] = {
    "success": "The agent responded and every expectation (if any) held.",
    "failed_assert": "The agent responded, but at least one expectation failed.",
    "agent_error": "The agent returned a non-2xx status or reported a failed terminal state.",
    "timeout": "The request or poll loop exceeded its time budget.",
    "transport_error": "The runner could not reach the agent (DNS, connection refused, TLS).",
    "config_error": "The request could not be built: template, missing secret, or contract problem.",
}

ERROR_CLASSES = frozenset({"agent_error", "timeout", "transport_error", "config_error"})


def _validate_jsonpath_map(mapping: dict[str, str], where: str) -> dict[str, str]:
    for name, path in mapping.items():
        if not name:
            raise ValueError(f"{where}: field names must be non-empty")
        if path == "$":
            continue
        try:
            jsonpath_parse(path)
        except Exception as exc:
            raise ValueError(f"{where}.{name}: invalid JSONPath {path!r} ({exc})") from exc
    return mapping


class InvokeSpec(BaseModel):
    """How to call the agent for one case."""

    model_config = ConfigDict(extra="forbid")

    method: HttpMethod = "POST"
    url: str = Field(min_length=1, description="Target URL. Supports {{ templates }}.")
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: Any = Field(
        default=None,
        description="JSON body. Strings inside are templates; a lone '{{ expr }}' keeps its type.",
    )
    timeout_s: float = Field(default=60, gt=0, le=3600)


class PollSpec(BaseModel):
    """Optional second phase for agents that accept work and finish later."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"] = "GET"
    url_template: str = Field(min_length=1)
    headers: dict[str, str] = Field(default_factory=dict)
    body_template: Any = None
    interval_s: float = Field(default=2, ge=0.05, le=600)
    timeout_s: float = Field(default=600, gt=0, le=86400)
    done_when: str = Field(
        min_length=1,
        description="Predicate on the poll response, e.g. \"status in ['COMPLETED','FAILED']\".",
    )
    failed_when: str | None = Field(
        default="status in ['FAILED','ERROR','CANCELLED']",
        description="Predicate that marks a terminal response as an agent failure.",
    )
    extract: dict[str, str] = Field(default_factory=dict)

    @field_validator("done_when", "failed_when")
    @classmethod
    def _check_predicate(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            parse_predicate(v)
        except PredicateError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("extract")
    @classmethod
    def _check_extract(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_jsonpath_map(v, "poll.extract")


class AgentContract(BaseModel):
    """Declarative HTTP contract: invoke, optionally poll, then extract fields."""

    model_config = ConfigDict(extra="forbid")

    invoke: InvokeSpec
    poll: PollSpec | None = None
    extract: dict[str, str] = Field(
        default_factory=dict,
        description="Field name → JSONPath. 'final_text' is scored; numeric fields become metrics.",
    )

    @field_validator("extract")
    @classmethod
    def _check_extract(cls, v: dict[str, str]) -> dict[str, str]:
        return _validate_jsonpath_map(v, "extract")


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(min_length=1)
    contract: AgentContract
    params: dict[str, Any] = Field(default_factory=dict)


class Expectations(BaseModel):
    """Deterministic checks. Unknown keys are rejected so typos surface early."""

    model_config = ConfigDict(extra="forbid")

    equals: Any = None
    contains: list[str] | None = None
    not_contains: list[str] | None = None
    regex: str | None = None
    jsonpath_equals: dict[str, Any] | None = None
    max_latency_ms: float | None = Field(default=None, gt=0)

    @field_validator("contains", "not_contains", mode="before")
    @classmethod
    def _one_or_many(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("regex")
    @classmethod
    def _check_regex(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                re.compile(v)
            except re.error as exc:
                raise ValueError(f"invalid regex {v!r}: {exc}") from exc
        return v

    def is_empty(self) -> bool:
        return not self.model_fields_set


class Case(BaseModel):
    """One evaluation case. Extra keys are kept and exposed to templates as case.*."""

    model_config = ConfigDict(extra="allow")

    id: str
    input: Any = None
    expected: Expectations | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("id", mode="before")
    @classmethod
    def _coerce_id(cls, v: Any) -> Any:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(v)
        return v

    @field_validator("tags", mode="before")
    @classmethod
    def _coerce_tags(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [t.strip() for t in re.split(r"[,;|]", v) if t.strip()]
        return v

    @field_validator("expected", mode="before")
    @classmethod
    def _empty_expected(cls, v: Any) -> Any:
        return None if v in ({}, "", None) else v


class DatasetRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[Case] | None = None
    uri: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one(self) -> DatasetRef:
        if (self.cases is None) == (self.uri is None):
            raise ValueError("dataset must provide exactly one of 'cases' or 'uri'")
        return self


class EvalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    concurrency: int = Field(default=8, ge=1, le=256)
    repeats: int = Field(
        default=1, ge=1, le=100, description="Trials per case. >1 measures consistency."
    )
    score_expectations: bool = Field(
        default=True,
        validation_alias=AliasChoices("score_expectations", "pass_fail_mode"),
        description="Evaluate each case's 'expected' block. Off = outcome classes only.",
    )
    body_truncate_chars: int = Field(default=32000, ge=256)


class EvalJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agents: list[AgentSpec] = Field(min_length=1)
    dataset: DatasetRef
    callback_url: str | None = None
    options: EvalOptions = Field(default_factory=EvalOptions)


class CaseResult(BaseModel):
    agent_id: str
    agent_name: str
    case_id: str
    trial: int = 0
    tags: list[str] = Field(default_factory=list)
    input: Any = None
    expected: dict[str, Any] | None = None
    outcome_class: str
    passed: bool | None = None
    failures: list[str] = Field(default_factory=list)
    latency_ms: float | None = None
    status_code: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    extracted: dict[str, Any] = Field(default_factory=dict)
    trajectory: dict[str, Any] = Field(default_factory=dict)
    final_text: str | None = None
    error: str | None = None


class RunResults(BaseModel):
    run_id: str
    status: Literal["completed", "failed", "cancelled"]
    case_results: list[CaseResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    tester_version: str | None = None
