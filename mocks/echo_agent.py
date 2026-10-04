"""Mock HTTP agents for smoke tests and the in-app demo.

- ``POST /v1/chat``   deterministic echo with small latency jitter
- ``POST /v1/flaky``  echo that is sometimes slow, sometimes wrong, sometimes 503
- ``POST /v1/jobs`` + ``GET /v1/jobs/{id}``  async submit-then-poll agent
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="Agent Tester mock agents", version="0.2.0")

MAX_JITTER_MS = float(os.environ.get("MOCK_JITTER_MS", "60"))
FLAKY_ERROR_RATE = float(os.environ.get("MOCK_FLAKY_ERROR_RATE", "0.08"))
FLAKY_WRONG_RATE = float(os.environ.get("MOCK_FLAKY_WRONG_RATE", "0.12"))
POLLS_UNTIL_DONE = int(os.environ.get("MOCK_POLLS_UNTIL_DONE", "2"))

_jobs: dict[str, dict[str, Any]] = {}


class ChatRequest(BaseModel):
    message: str = ""
    session_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    echoed: str
    session_id: str | None = None
    tokens: int


def _echo(text: str) -> str:
    text = (text or "").strip()
    return f"Echo: {text}" if text else "Echo: (empty)"


async def _jitter(max_ms: float) -> None:
    await asyncio.sleep(random.uniform(0, max_ms) / 1000)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    await _jitter(MAX_JITTER_MS)
    reply = _echo(body.message)
    return ChatResponse(
        reply=reply, echoed=body.message, session_id=body.session_id, tokens=len(reply.split())
    )


@app.post("/v1/flaky", response_model=ChatResponse)
async def flaky(body: ChatRequest):
    # Long-tailed latency: most requests are quick, a few are slow.
    await asyncio.sleep(random.lognormvariate(4.5, 0.8) / 1000)
    roll = random.random()
    if roll < FLAKY_ERROR_RATE:
        return JSONResponse({"error": "upstream model overloaded"}, status_code=503)
    wrong = roll < FLAKY_ERROR_RATE + FLAKY_WRONG_RATE
    reply = "I'm not sure how to help with that." if wrong else _echo(body.message)
    return ChatResponse(
        reply=reply, echoed=body.message, session_id=body.session_id, tokens=len(reply.split())
    )


class JobSubmit(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


@app.post("/v1/jobs")
async def submit_job(body: JobSubmit) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    message = body.message or str(body.payload.get("message", ""))
    _jobs[job_id] = {"id": job_id, "status": "RUNNING", "polls": 0, "message": message}
    return {"id": job_id, "status": "RUNNING"}


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        return JSONResponse({"id": job_id, "error": "not_found"}, status_code=404)
    job["polls"] += 1
    if job["status"] == "RUNNING" and job["polls"] >= POLLS_UNTIL_DONE:
        job["status"] = "COMPLETED"
        job["response"] = f"Async echo: {job['message']}"
    return {"id": job["id"], "status": job["status"], "response": job.get("response")}
