"""ORM models. New columns must be nullable or have a server default so the
additive migrator in ``app.db`` can add them to existing databases."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    contract_json: Mapped[str] = mapped_column(Text, nullable=False)
    params_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=utcnow, onupdate=utcnow
    )

    cases: Mapped[list[DatasetCase]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", passive_deletes=True
    )


class DatasetCase(Base):
    __tablename__ = "dataset_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    case_key: Mapped[str] = mapped_column(String(255), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    expected_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Any other top-level keys of the case, available to templates as case.*.
    extra_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[Dataset] = relationship(back_populates="cases")


class TestRun(Base):
    __tablename__ = "test_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # queued → running → completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    options_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dataset_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_uri: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    # Snapshot of [{id, name}] at submit time, so renames/deletes don't rewrite history.
    agents_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    summary_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tester_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TestRunAgent(Base):
    """Kept for databases created by 0.1; new runs use TestRun.agents_json."""

    __tablename__ = "test_run_agents"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), primary_key=True
    )
    agent_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class CaseResult(Base):
    __tablename__ = "case_results"
    __table_args__ = (Index("ix_case_results_run_agent", "run_id", "agent_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(String(36), index=True)
    agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    case_key: Mapped[str] = mapped_column(String(255), nullable=False)
    trial: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_class: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    failures_json: Mapped[str] = mapped_column(
        Text, nullable=False, default="[]", server_default="[]"
    )
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    extracted_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    trajectory_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
