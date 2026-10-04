"""API token auth and contract hygiene checks."""

from __future__ import annotations

import hmac
import re
from typing import Any

from fastapi import Header, HTTPException, status

from app.config import settings

_SENSITIVE_HEADER = re.compile(
    r"^(authorization|proxy-authorization|cookie)$|token|secret|password|api[-_]?key",
    re.IGNORECASE,
)
_REFERENCE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}|\{\{.*\}\}")


async def require_token(authorization: str | None = Header(default=None)) -> None:
    """When API_TOKEN is set, require ``Authorization: Bearer <token>``."""
    expected = settings.api_token
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.strip(), expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def literal_secret_errors(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Flag credential-looking headers whose values are literals, not ${VAR} refs.

    Contracts are stored in the database; credentials must stay in the runner's
    environment.
    """
    errors = []
    for phase in ("invoke", "poll"):
        spec = contract.get(phase) or {}
        headers = spec.get("headers") if isinstance(spec, dict) else None
        for name, value in (headers or {}).items():
            if not isinstance(value, str) or not _SENSITIVE_HEADER.search(name):
                continue
            stripped = re.sub(r"(?i)^(bearer|basic|token)\s+", "", value).strip()
            if stripped and not _REFERENCE.search(stripped):
                errors.append(
                    {
                        "loc": f"contract.{phase}.headers.{name}",
                        "message": (
                            "looks like a literal credential. Reference an environment "
                            'variable instead, e.g. "Bearer ${AGENT_API_KEY}".'
                        ),
                    }
                )
    return errors
