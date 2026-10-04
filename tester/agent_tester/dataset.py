"""Load and parse datasets (JSON array, {"cases": [...]}, JSONL, CSV).

Parsing collects *every* problem with its line number instead of stopping at
the first, so a 500-case import can be fixed in one pass.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError

from agent_tester.models import Case, DatasetRef

MAX_REPORTED_ERRORS = 50
_RESERVED_CSV = {"id", "case_id", "input", "expected", "tags"}


class DatasetParseError(ValueError):
    def __init__(self, errors: list[dict[str, Any]]) -> None:
        self.errors = errors[:MAX_REPORTED_ERRORS]
        head = "; ".join(
            f"line {e['line']}: {e['message']}" if e.get("line") else e["message"]
            for e in self.errors[:3]
        )
        more = f" (+{len(errors) - 3} more)" if len(errors) > 3 else ""
        super().__init__(f"{len(errors)} problem(s) in dataset: {head}{more}")


_CHECKS = "contains, not_contains, equals, regex, jsonpath_equals, max_latency_ms"


def _format_validation(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "case"
        if (
            err["type"] == "extra_forbidden"
            and len(err["loc"]) == 2
            and err["loc"][0] == "expected"
        ):
            parts.append(f"unknown check '{err['loc'][1]}' in expected (use one of: {_CHECKS})")
        else:
            parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)


def detect_format(text: str, filename: str | None) -> str:
    name = (filename or "").lower()
    for ext, fmt in ((".jsonl", "jsonl"), (".ndjson", "jsonl"), (".csv", "csv"), (".json", "json")):
        if name.endswith(ext):
            return fmt
    stripped = text.lstrip()
    if stripped.startswith(("[", "{")):
        try:
            json.loads(stripped)
            return "json"
        except json.JSONDecodeError:
            # Several objects (one per line) or a genuinely broken JSON file.
            return "jsonl" if stripped.startswith("{") else "json"
    return "csv"


def _raw_json(text: str) -> list[tuple[int | None, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DatasetParseError(
            [{"line": exc.lineno, "message": f"invalid JSON: {exc.msg}"}]
        ) from exc
    if isinstance(data, dict) and isinstance(data.get("cases"), list):
        data = data["cases"]
    elif isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise DatasetParseError([{"line": None, "message": "expected an array of cases"}])
    return [(None, item) for item in data]


def _raw_jsonl(text: str) -> tuple[list[tuple[int | None, Any]], list[dict[str, Any]]]:
    rows, errors = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            rows.append((lineno, json.loads(line)))
        except json.JSONDecodeError as exc:
            errors.append({"line": lineno, "message": f"invalid JSON: {exc.msg}"})
    return rows, errors


def _maybe_json(value: str) -> Any:
    value = value.strip()
    if value[:1] in ("{", "[", '"') or value in ("true", "false", "null"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass
    return value


def _raw_csv(text: str) -> list[tuple[int | None, Any]]:
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        lineno = reader.line_num
        row = {k.strip(): (v or "") for k, v in row.items() if k}
        case: dict[str, Any] = {"id": row.get("id") or row.get("case_id") or None}
        if row.get("input"):
            parsed = _maybe_json(row["input"])
            case["input"] = parsed if isinstance(parsed, (dict, list)) else {"message": parsed}
        else:
            # Every non-reserved column becomes an input field: id,message,locale → input.*
            case["input"] = {k: _maybe_json(v) for k, v in row.items() if k not in _RESERVED_CSV}
        if row.get("expected"):
            parsed = _maybe_json(row["expected"])
            case["expected"] = parsed if isinstance(parsed, dict) else {"contains": [str(parsed)]}
        if row.get("tags"):
            case["tags"] = row["tags"]
        rows.append((lineno, case))
    return rows


def parse_cases(text: str, filename: str | None = None) -> list[Case]:
    """Parse dataset text into validated cases or raise DatasetParseError."""
    if not text.strip():
        return []
    fmt = detect_format(text, filename)
    errors: list[dict[str, Any]] = []
    if fmt == "json":
        raw = _raw_json(text)
    elif fmt == "jsonl":
        raw, errors = _raw_jsonl(text)
    else:
        raw = _raw_csv(text)

    cases: list[Case] = []
    seen: dict[str, int] = {}
    for index, (lineno, item) in enumerate(raw, start=1):
        where = lineno if lineno is not None else None
        label = "" if where else f"case #{index}: "
        if not isinstance(item, dict):
            errors.append({"line": where, "message": f"{label}expected an object"})
            continue
        if item.get("id") in (None, "") and item.get("case_id") not in (None, ""):
            item = {**item, "id": item["case_id"]}
            item.pop("case_id", None)
        if item.get("id") in (None, ""):
            item = {**item, "id": f"case-{index}"}
        try:
            case = Case.model_validate(item)
        except ValidationError as exc:
            errors.append({"line": where, "message": f"{label}{_format_validation(exc)}"})
            continue
        if case.id in seen:
            errors.append(
                {
                    "line": where,
                    "message": f"duplicate id {case.id!r} (first seen in case #{seen[case.id]})",
                }
            )
            continue
        seen[case.id] = index
        cases.append(case)

    if errors:
        raise DatasetParseError(errors)
    return cases


async def load_dataset(
    ref: DatasetRef,
    *,
    client: httpx.AsyncClient | None = None,
    allow_files: bool = True,
) -> list[Case]:
    """Resolve a DatasetRef. ``allow_files=False`` restricts URIs to http(s)."""
    if ref.cases is not None:
        return list(ref.cases)
    assert ref.uri is not None
    uri = ref.uri
    if uri.startswith(("http://", "https://")):
        owns = client is None
        client = client or httpx.AsyncClient(timeout=120.0, follow_redirects=True)
        try:
            resp = await client.get(uri, headers=ref.headers, timeout=120.0)
            resp.raise_for_status()
            text = resp.text
        finally:
            if owns:
                await client.aclose()
        return parse_cases(text, uri.split("?")[0])
    if not allow_files:
        raise ValueError(f"dataset URI must be http(s):// here, got {uri!r}")
    path = Path(uri.removeprefix("file://"))
    return parse_cases(path.read_text(encoding="utf-8"), path.name)
