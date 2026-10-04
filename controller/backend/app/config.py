"""Controller settings, read from the environment (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage
    database_path: str = str(_REPO_ROOT / "data" / "agent_tester.db")
    database_url: str | None = None  # overrides database_path (any SQLAlchemy async URL)

    # HTTP
    cors_origins: str = ""  # the bundled UI proxies /api, so CORS is only for other origins
    api_token: str | None = None  # when set, every /api route except /api/health needs it
    max_upload_mb: int = 20

    # Execution
    runner_mode: Literal["inprocess", "docker"] = "inprocess"
    max_concurrent_runs: int = 2
    test_request_timeout_s: float = 30.0
    allow_literal_secrets: bool = False

    # Content shipped with the image
    presets_dir: str = str(_REPO_ROOT / "presets")
    samples_dir: str = str(_REPO_ROOT / "datasets" / "samples")
    # Base URL the demo agents call; the compose default is the bundled mock.
    demo_agent_url: str | None = None

    # Docker runner mode only
    jobs_dir: str = str(_REPO_ROOT / "data" / "jobs")
    compose_project_dir: str = "/workspace"
    host_project_dir: str = ""
    compose_file: str = "docker-compose.yml"
    tester_service: str = "tester"
    public_api_base: str = "http://controller:8000"

    log_level: str = "INFO"

    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        path = Path(self.database_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
