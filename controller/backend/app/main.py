from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import settings
from app.db import SessionLocal, init_db
from app.errors import install_handlers
from app.services.runner import RunManager

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("agent_tester.controller")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    runs = RunManager(SessionLocal)
    await runs.recover()
    app.state.runs = runs
    log.info(
        "Agent Tester %s ready (runner=%s, auth=%s)",
        __version__,
        settings.runner_mode,
        "on" if settings.api_token else "off",
    )
    yield
    await runs.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Agent Tester API",
        version=__version__,
        description=(
            "Control plane for statistical evaluation of HTTP agents. "
            "When API_TOKEN is set, send `Authorization: Bearer <token>`."
        ),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    install_handlers(app)
    app.include_router(router)
    return app


app = create_app()
