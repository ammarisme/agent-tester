"""Sandboxed template rendering and ${ENV} secret resolution.

Rules:

- Strings are Jinja templates rendered in a *sandboxed* environment with
  ``StrictUndefined``, so a missing ``input.foo`` is an error, not "".
- A string that is exactly one expression (``"{{ input }}"``,
  ``"{{ agent.params.max_tokens }}"``) keeps the expression's native type.
- ``${NAME}`` is replaced with the environment variable ``NAME`` — only in
  contract text, never in values coming from datasets, so a dataset cannot
  pull secrets out of the runner. ``$${NAME}`` yields a literal ``${NAME}``.
  Inside expressions, use ``{{ secret('NAME') }}``.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from jinja2 import StrictUndefined, TemplateError, Undefined
from jinja2.sandbox import SandboxedEnvironment

ENV_REF = re.compile(r"(?<!\$)\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ESCAPED_ENV_REF = re.compile(r"\$\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_CALL = re.compile(r"""secret\(\s*['"]([A-Za-z_][A-Za-z0-9_]*)['"]\s*\)""")
_SINGLE_EXPR = re.compile(r"^\s*\{\{(?P<expr>(?:(?!\{\{|\}\}).)+)\}\}\s*$", re.DOTALL)

# Variables the runner itself uses; contracts may never read them.
_INTERNAL_ENV = frozenset({"API_TOKEN", "AGENT_TESTER_CALLBACK_TOKEN", "DATABASE_URL"})

_jinja = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)
_jinja.globals.update(
    uuid=lambda: str(uuid.uuid4()),
    now_iso=lambda: datetime.now(timezone.utc).isoformat(),
)


class ContractRenderError(ValueError):
    """Raised when a contract cannot be turned into a concrete request."""

    def __init__(self, where: str, message: str) -> None:
        super().__init__(f"{where}: {message}")
        self.where = where


def secret_allowed(name: str) -> bool:
    if name in _INTERNAL_ENV:
        return False
    pattern = os.environ.get("AGENT_TESTER_SECRET_PATTERN")
    return not pattern or re.fullmatch(pattern, name) is not None


def lookup_secret(name: str) -> str:
    if not secret_allowed(name):
        raise KeyError(f"environment variable '{name}' is not allowed by the secret policy")
    value = os.environ.get(name)
    if value is None:
        raise KeyError(f"environment variable '{name}' is not set on the runner")
    return value


_jinja.globals["secret"] = lookup_secret


def referenced_env_vars(node: Any) -> set[str]:
    """All ${NAME} / secret('NAME') references inside a (nested) contract structure."""
    found: set[str] = set()
    if isinstance(node, str):
        found.update(ENV_REF.findall(node))
        found.update(_SECRET_CALL.findall(node))
    elif isinstance(node, dict):
        for k, v in node.items():
            found |= referenced_env_vars(k) | referenced_env_vars(v)
    elif isinstance(node, list):
        for v in node:
            found |= referenced_env_vars(v)
    return found


@lru_cache(maxsize=1024)
def _compile_template(source: str):
    return _jinja.from_string(source)


@lru_cache(maxsize=1024)
def _compile_expression(source: str):
    return _jinja.compile_expression(source, undefined_to_none=False)


def _prepare(source: str) -> str:
    """Turn ${NAME} into a sandboxed call so secrets are inserted as values.

    Values rendered from datasets are never re-scanned for ${...}.
    """
    source = _ESCAPED_ENV_REF.sub(lambda m: "{{ '${' }}" + m.group(1) + "}", source)
    return ENV_REF.sub(lambda m: "{{ secret('" + m.group(1) + "') }}", source)


def _render_string(source: str, ctx: dict[str, Any], where: str) -> Any:
    prepared = _prepare(source) if "${" in source else source
    try:
        single = _SINGLE_EXPR.match(prepared)
        if single:
            value = _compile_expression(single.group("expr").strip())(**ctx)
            if isinstance(value, Undefined):
                value._fail_with_undefined_error()
            return value
        if "{{" in prepared or "{%" in prepared or "{#" in prepared:
            return _compile_template(prepared).render(**ctx)
        return prepared
    except KeyError as exc:
        raise ContractRenderError(where, str(exc.args[0]) if exc.args else str(exc)) from exc
    except TemplateError as exc:
        raise ContractRenderError(where, f"template error: {exc}") from exc


def render_value(node: Any, ctx: dict[str, Any], where: str = "template") -> Any:
    """Render every string in a JSON-like structure."""
    if isinstance(node, str):
        return _render_string(node, ctx, where)
    if isinstance(node, list):
        return [render_value(x, ctx, f"{where}[{i}]") for i, x in enumerate(node)]
    if isinstance(node, dict):
        return {str(k): render_value(v, ctx, f"{where}.{k}") for k, v in node.items()}
    return node


def render_headers(headers: dict[str, str], ctx: dict[str, Any], where: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        value = render_value(v, ctx, f"{where}.{k}")
        out[str(k)] = "" if value is None else str(value)
    return out


def build_context(
    *,
    case: dict[str, Any],
    agent_params: dict[str, Any],
    extracted: dict[str, Any] | None = None,
    trial: int = 0,
) -> dict[str, Any]:
    return {
        "input": case.get("input"),
        "expected": case.get("expected"),
        "case": case,
        "agent": {"params": agent_params or {}},
        "extracted": extracted or {},
        "trial": trial,
    }
