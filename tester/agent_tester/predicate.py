"""Tiny, safe predicate language for poll termination.

Grammar (one comparison per predicate, no ``eval``)::

    <path>                     truthy and present
    <path> == <literal>
    <path> != <literal>
    <path> in [<literal>, …]
    <path> not in [<literal>, …]

``<path>`` is a JSONPath; a bare name like ``status`` means ``$.status`` and
dotted names like ``result.state`` work too. Literals are JSON or
Python-style (single quotes allowed).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from jsonpath_ng import parse as jsonpath_parse

_PATTERN = re.compile(
    r"^\s*(?P<path>[^\s=!]+)\s*(?:(?P<op>==|!=|not\s+in|in)\s*(?P<lit>.+?))?\s*$",
    re.DOTALL,
)
_MISSING = object()


class PredicateError(ValueError):
    pass


@dataclass(frozen=True)
class Predicate:
    source: str
    path: str
    op: str | None
    literal: Any
    _compiled: Any

    def evaluate(self, payload: Any) -> bool:
        value = _MISSING
        if isinstance(payload, (dict, list)):
            matches = self._compiled.find(payload)
            if matches:
                value = matches[0].value
        if self.op is None:
            return value is not _MISSING and bool(value)
        if value is _MISSING:
            return self.op in ("!=", "not in")
        if self.op == "==":
            return value == self.literal
        if self.op == "!=":
            return value != self.literal
        if self.op == "in":
            return value in self.literal
        return value not in self.literal


def _parse_literal(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise PredicateError(f"cannot parse literal {text!r}") from exc


def parse_predicate(source: str) -> Predicate:
    match = _PATTERN.match(source or "")
    if not match:
        raise PredicateError(
            f"invalid predicate {source!r}; expected e.g. \"status in ['DONE','FAILED']\""
        )
    path = match.group("path")
    op = match.group("op")
    op = re.sub(r"\s+", " ", op) if op else None
    literal = _parse_literal(match.group("lit")) if op else None
    if op in ("in", "not in") and not isinstance(literal, (list, tuple, set)):
        raise PredicateError(f"'{op}' needs a list literal, got {match.group('lit')!r}")
    jp = path if path.startswith("$") else f"$.{path}"
    try:
        compiled = jsonpath_parse(jp)
    except Exception as exc:
        raise PredicateError(f"invalid path {path!r} in predicate: {exc}") from exc
    if isinstance(literal, (tuple, set)):
        literal = list(literal)
    return Predicate(source=source, path=jp, op=op, literal=literal, _compiled=compiled)
