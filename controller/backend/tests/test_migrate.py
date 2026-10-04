"""Databases created by 0.1 must open without data loss."""

from __future__ import annotations

import sqlite3

from sqlalchemy.ext.asyncio import create_async_engine

from app.db import init_db

V01_SCHEMA = """
CREATE TABLE agents (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, contract_json TEXT NOT NULL,
  params_json TEXT NOT NULL, enabled BOOLEAN, created_at DATETIME, updated_at DATETIME);
CREATE TABLE test_runs (id VARCHAR(36) PRIMARY KEY, status VARCHAR(32) NOT NULL, options_json TEXT NOT NULL,
  dataset_id VARCHAR(36), dataset_uri VARCHAR(1024), summary_json TEXT, error TEXT,
  started_at DATETIME, finished_at DATETIME, created_at DATETIME);
CREATE TABLE case_results (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id VARCHAR(36), agent_id VARCHAR(36),
  case_key VARCHAR(255) NOT NULL, outcome_class VARCHAR(64) NOT NULL, passed BOOLEAN, latency_ms FLOAT,
  metrics_json TEXT NOT NULL, extracted_json TEXT NOT NULL, trajectory_json TEXT NOT NULL, final_text TEXT, error TEXT);
INSERT INTO agents VALUES ('a1', 'old', '{"invoke": {"url": "http://x"}}', '{}', 1, NULL, NULL);
INSERT INTO test_runs VALUES ('r1', 'pending', '{}', NULL, NULL, NULL, NULL, NULL, NULL, NULL);
"""


async def test_adds_missing_columns_and_keeps_rows(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(V01_SCHEMA)
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    await init_db(engine)
    await engine.dispose()
    with sqlite3.connect(path) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(test_runs)")}
        assert {"agents_json", "total", "completed", "name"} <= cols
        assert conn.execute("SELECT agents_json, total FROM test_runs").fetchone() == ("[]", 0)
        assert conn.execute("SELECT description FROM agents").fetchone() == ("",)
        assert "failures_json" in {r[1] for r in conn.execute("PRAGMA table_info(case_results)")}
