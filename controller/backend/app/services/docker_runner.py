"""RUNNER_MODE=docker: run each job in a throwaway tester container.

The controller writes the job file, starts ``docker compose run tester`` via
the Docker socket, and the tester POSTs results back to
``/api/runs/{id}/results``. Only needed when evaluations must be isolated from
the controller process; the default in-process runner needs none of this.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

from agent_tester import EvalJob
from app.config import settings

log = logging.getLogger(__name__)
STDERR_TAIL = 2000


def _host_path(container_path: Path) -> str:
    """Map a path inside the controller container to the same file on the Docker host."""
    host_root = Path(settings.host_project_dir)
    compose_root = Path(settings.compose_project_dir)
    try:
        rel = container_path.resolve().relative_to(compose_root.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"JOBS_DIR ({settings.jobs_dir}) must live under COMPOSE_PROJECT_DIR "
            f"({settings.compose_project_dir}) so the Docker host can mount it"
        ) from exc
    return str(host_root / rel)


def write_job_file(job: EvalJob) -> Path:
    jobs_dir = Path(settings.jobs_dir)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    path = jobs_dir / f"{job.run_id}.json"
    path.write_text(job.model_dump_json(indent=2), encoding="utf-8")
    return path


async def run_in_docker(job: EvalJob) -> tuple[int, str]:
    """Run the job to completion. Returns (exit code, stderr tail)."""
    if not settings.host_project_dir:
        raise RuntimeError(
            "RUNNER_MODE=docker requires HOST_PROJECT_DIR (absolute path on the Docker host)"
        )
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError(
            "docker CLI not found in the controller image; build with WITH_DOCKER_CLI=true"
        )

    job_path = write_job_file(job)
    cmd = [
        docker,
        "compose",
        "-f",
        str(Path(settings.host_project_dir) / settings.compose_file),
        "--project-directory",
        settings.host_project_dir,
        "run",
        "--rm",
        "-v",
        f"{_host_path(job_path)}:/job.json:ro",
    ]
    env = os.environ.copy()
    if settings.api_token:
        env["AGENT_TESTER_CALLBACK_TOKEN"] = settings.api_token
        cmd += ["-e", "AGENT_TESTER_CALLBACK_TOKEN"]
    cmd += [settings.tester_service, "run", "--job", "/job.json", "--quiet"]

    log.info("run %s: spawning tester container", job.run_id)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=settings.compose_project_dir if Path(settings.compose_project_dir).exists() else None,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await proc.communicate()
    except asyncio.CancelledError:
        proc.terminate()
        raise
    finally:
        job_path.unlink(missing_ok=True)
    tail = stderr.decode(errors="replace")[-STDERR_TAIL:]
    log.info("run %s: tester exited %s", job.run_id, proc.returncode)
    return proc.returncode or 0, tail
