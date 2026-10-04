"""Background execution of runs: queueing, live progress, cancellation.

In-process mode streams results into the database while the run executes, so
the UI can show progress and partial results. At most MAX_CONCURRENT_RUNS
execute at once; the rest wait as "queued".
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_tester import CaseResult, EvalJob, run_job
from agent_tester.stats import aggregate
from app.config import settings
from app.models import TestRun, utcnow
from app.services.docker_runner import run_in_docker
from app.services.runs import ACTIVE_STATUSES, finish, result_rows

log = logging.getLogger(__name__)
FLUSH_INTERVAL_S = 0.5


class RunManager:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory
        self._slots = asyncio.Semaphore(max(1, settings.max_concurrent_runs))
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ── lifecycle ────────────────────────────────────────────────────

    async def recover(self) -> None:
        """Runs that were active when the controller stopped can never finish."""
        async with self._sf() as db:
            result = await db.execute(
                update(TestRun)
                .where(TestRun.status.in_(ACTIVE_STATUSES))
                .values(
                    status="failed",
                    error="The controller restarted before this run finished. Re-run it.",
                    finished_at=utcnow(),
                )
            )
            await db.commit()
            if result.rowcount:
                log.warning("marked %s interrupted run(s) as failed", result.rowcount)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    # ── public API ───────────────────────────────────────────────────

    def submit(self, job: EvalJob) -> None:
        task = asyncio.create_task(self._execute(job), name=f"run-{job.run_id}")
        self._tasks[job.run_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(job.run_id, None))

    def is_active(self, run_id: str) -> bool:
        return run_id in self._tasks

    def cancel(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def wait(self, run_id: str) -> None:
        """Test helper: block until a run's task is done."""
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    # ── execution ────────────────────────────────────────────────────

    async def _set(self, run_id: str, **values: object) -> None:
        async with self._sf() as db:
            await db.execute(update(TestRun).where(TestRun.id == run_id).values(**values))
            await db.commit()

    async def _finish(self, run_id: str, status: str, **kw) -> None:
        async with self._sf() as db:
            run = await db.get(TestRun, run_id)
            if run is not None and run.status in ACTIVE_STATUSES:
                finish(run, status, **kw)
                await db.commit()

    async def _execute(self, job: EvalJob) -> None:
        collected: list[CaseResult] = []
        try:
            async with self._slots:
                await self._set(job.run_id, status="running", started_at=utcnow())
                if settings.runner_mode == "docker":
                    await self._execute_docker(job)
                else:
                    await self._execute_inprocess(job, collected)
        except asyncio.CancelledError:
            await self._finish(
                job.run_id,
                "cancelled",
                summary=aggregate(collected) if collected else None,
                error=f"Cancelled after {len(collected)} result(s).",
            )
        except Exception as exc:
            log.exception("run %s failed", job.run_id)
            await self._finish(
                job.run_id,
                "failed",
                summary=aggregate(collected) if collected else None,
                error=str(exc) or exc.__class__.__name__,
            )

    async def _execute_inprocess(self, job: EvalJob, collected: list[CaseResult]) -> None:
        pending: list[CaseResult] = []
        lock = asyncio.Lock()
        last_flush = time.monotonic()
        last_total = 0

        async def flush(total: int) -> None:
            nonlocal last_flush
            async with lock:
                # Snapshot under the lock so progress is monotonic even when
                # concurrent flushes acquire the lock out of order.
                batch = pending[:]
                pending.clear()
                completed = len(collected)
                last_flush = time.monotonic()
                async with self._sf() as db:
                    db.add_all(result_rows(job.run_id, batch))
                    await db.execute(
                        update(TestRun)
                        .where(TestRun.id == job.run_id)
                        .values(completed=completed, total=total)
                    )
                    await db.commit()

        async def on_result(result: CaseResult, completed: int, total: int) -> None:
            nonlocal last_total
            last_total = total
            collected.append(result)
            pending.append(result)
            if completed == total or time.monotonic() - last_flush >= FLUSH_INTERVAL_S:
                await flush(total)

        try:
            results = await run_job(job, on_result=on_result, allow_file_datasets=False)
        except asyncio.CancelledError:
            if pending:
                await asyncio.shield(flush(last_total))
            raise
        async with self._sf() as db:
            run = await db.get(TestRun, job.run_id)
            if run is None:  # deleted mid-run
                return
            run.tester_version = results.tester_version
            run.completed = run.total = len(results.case_results)
            finish(run, "completed", summary=results.summary)
            await db.commit()

    async def _execute_docker(self, job: EvalJob) -> None:
        code, stderr = await run_in_docker(job)
        async with self._sf() as db:
            run = (
                await db.execute(select(TestRun).where(TestRun.id == job.run_id))
            ).scalar_one_or_none()
            if run is not None and run.status in ACTIVE_STATUSES:
                # The tester exited without delivering results.
                detail = stderr.strip().splitlines()[-1] if stderr.strip() else "no output"
                finish(run, "failed", error=f"tester exited with code {code}: {detail}")
                await db.commit()
