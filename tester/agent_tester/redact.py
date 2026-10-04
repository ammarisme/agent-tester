"""Keep secrets out of stored trajectories.

Two layers:
1. Sensitive-looking header values are replaced with ``***``.
2. The resolved value of every env var referenced by the contract is scrubbed
   from all recorded strings (URLs, bodies, errors, extracted fields).
"""

from __future__ import annotations

import os
import re
from typing import Any

from agent_tester.template import referenced_env_vars, secret_allowed

REDACTED = "***"
_SENSITIVE_HEADER = re.compile(
    r"^(authorization|proxy-authorization|cookie|set-cookie)$|token|secret|password|api[-_]?key|session",
    re.IGNORECASE,
)
_MIN_SECRET_LEN = 4


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    return {k: (REDACTED if _SENSITIVE_HEADER.search(k) else v) for k, v in headers.items()}


def secret_values(contract: Any) -> list[str]:
    values = []
    for name in referenced_env_vars(contract):
        if not secret_allowed(name):
            continue
        value = os.environ.get(name)
        if value and len(value) >= _MIN_SECRET_LEN:
            values.append(value)
    # Longest first so overlapping secrets are fully masked.
    return sorted(set(values), key=len, reverse=True)


def scrub(node: Any, secrets: list[str]) -> Any:
    if not secrets:
        return node
    if isinstance(node, str):
        for s in secrets:
            if s in node:
                node = node.replace(s, REDACTED)
        return node
    if isinstance(node, list):
        return [scrub(x, secrets) for x in node]
    if isinstance(node, dict):
        return {k: scrub(v, secrets) for k, v in node.items()}
    return node
