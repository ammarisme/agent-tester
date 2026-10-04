"""Run (agent × case × trial) evaluations with bounded concurrency."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from agent_tester._version import __version__
from agent_tester.dataset import load_dataset
from agent_tester.invoke import invoke_agent
from agent_tester.models import AgentSpec, Case, CaseResult, EvalJob, RunResults
from agent_tester.redact import scrub, secret_values
from agent_tester.scoring import score
from agent_tester.stats import aggregate

ResultCallback = Callable[[CaseResult, int, int], Awaitable[None] | None]
"""Called after each result with (result, completed, total)."""


def _metrics(latency_ms: float, extracted: dict[str, Any], n_polls: int) -> dict[str, float]:
    metrics: dict[str, float] = {"latency_ms": latency_ms}
    if n_polls:
        metrics["n_polls"] = float(n_polls)
    for key, value in extracted.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            metrics[key] = float(value)
    return metrics


async def evaluate_case(
    client: httpx.AsyncClient,
    agent: AgentSpec,
    case: Case,
    *,
    trial: int = 0,
    score_expectations: bool = True,
    truncate: int = 32000,
    secrets: list[str] | None = None,
) -> CaseResult:
    out = await invoke_agent(client, agent, case, truncate=truncate, trial=trial)
    outcome = out.outcome_class
    passed: bool | None = None
    failures: list[str] = []

    if score_expectations and case.expected is not None:
        if outcome == "success":
            passed, failures = score(
                case.expected,
                final_text=out.final_text,
                response=out.response,
                extracted=out.extracted,
                latency_ms=out.latency_ms,
            )
            if passed is False:
                outcome = "failed_assert"
        elif not case.expected.is_empty():
            # A case with expectations that never got a usable answer did not pass.
            passed = False
            failures = [f"not scored: {outcome}"]

    result = CaseResult(
        agent_id=agent.id,
        agent_name=agent.name,
        case_id=case.id,
        trial=trial,
        tags=case.tags,
        input=case.input,
        expected=case.expected.model_dump(exclude_unset=True) if case.expected else None,
        outcome_class=outcome,
        passed=passed,
        failures=failures,
        latency_ms=out.latency_ms,
        status_code=out.status_code,
        metrics=_metrics(out.latency_ms, out.extracted, out.n_polls),
        extracted=out.extracted,
        trajectory=out.trajectory(),
        final_text=out.final_text,
        error=out.error,
    )
    if secrets is None:
        secrets = secret_values(agent.contract.model_dump())
    if secrets:
        result = CaseResult.model_validate(scrub(result.model_dump(), secrets))
    return result


async def run_job(
    job: EvalJob,
    *,
    cases: list[Case] | None = None,
    on_result: ResultCallback | None = None,
    client: httpx.AsyncClient | None = None,
    allow_file_datasets: bool = True,
) -> RunResults:
    """Evaluate every agent on every case ``options.repeats`` times.

    Results come back in a stable order (agent, case, trial) regardless of
    completion order. Cancellation propagates to the caller.
    """
    owns_client = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        if cases is None:
            cases = await load_dataset(job.dataset, client=client, allow_files=allow_file_datasets)
        opts = job.options
        sem = asyncio.Semaphore(opts.concurrency)
        secrets = {a.id: secret_values(a.contract.model_dump()) for a in job.agents}
        plan = [(a, c, t) for a in job.agents for c in cases for t in range(opts.repeats)]
        total = len(plan)
        results: list[CaseResult | None] = [None] * total
        completed = 0

        async def one(index: int, agent: AgentSpec, case: Case, trial: int) -> None:
            nonlocal completed
            async with sem:
                result = await evaluate_case(
                    client,
                    agent,
                    case,
                    trial=trial,
                    score_expectations=opts.score_expectations,
                    truncate=opts.body_truncate_chars,
                    secrets=secrets[agent.id],
                )
            results[index] = result
            completed += 1
            if on_result is not None:
                maybe = on_result(result, completed, total)
                if inspect.isawaitable(maybe):
                    await maybe

        await asyncio.gather(*(one(i, *item) for i, item in enumerate(plan)))
        final = [r for r in results if r is not None]
        return RunResults(
            run_id=job.run_id,
            status="completed",
            case_results=final,
            summary=aggregate(final),
            tester_version=__version__,
        )
    finally:
        if owns_client:
            await client.aclose()


async def invoke_once(
    agent: AgentSpec,
    case: Case,
    *,
    client: httpx.AsyncClient | None = None,
    truncate: int = 32000,
) -> CaseResult:
    """Dry-run a single case (used by the UI's "Test request" panel)."""
    owns = client is None
    client = client or httpx.AsyncClient(follow_redirects=True)
    try:
        return await evaluate_case(client, agent, case, truncate=truncate)
    finally:
        if owns:
            await client.aclose()
