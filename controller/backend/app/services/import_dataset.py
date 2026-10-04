"""Dataset upload handling: size limits, decoding, parsing, row building."""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import UploadFile
from pydantic import ValidationError

from agent_tester import Case, DatasetParseError, parse_cases
from agent_tester.dataset import detect_format as _detect
from app.config import settings
from app.errors import ApiError, invalid
from app.models import DatasetCase


async def read_upload(file: UploadFile) -> str:
    limit = settings.max_upload_mb * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise ApiError(413, f"file is larger than {settings.max_upload_mb} MB")
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ApiError(400, "file is not UTF-8 text") from exc


def detect_format(text: str, filename: str | None) -> str | None:
    return _detect(text, filename) if text.strip() else None


def parse_or_raise(text: str, filename: str | None) -> list[Case]:
    try:
        return parse_cases(text, filename)
    except DatasetParseError as exc:
        raise invalid(str(exc), exc.errors) from exc


def validate_case_dicts(items: list[dict[str, Any]]) -> list[Case]:
    """Validate cases sent as JSON (not a file) with the same rules as imports."""
    text = json.dumps(items)
    try:
        return parse_cases(text, "cases.json")
    except DatasetParseError as exc:
        raise invalid(str(exc), exc.errors) from exc
    except ValidationError as exc:  # pragma: no cover - parse_cases wraps these
        raise invalid("invalid cases", [{"message": str(exc)}]) from exc


def case_rows(dataset_id: str, cases: list[Case], start: int = 0) -> list[DatasetCase]:
    return [
        DatasetCase(
            id=str(uuid.uuid4()),
            dataset_id=dataset_id,
            position=start + i,
            case_key=c.id,
            input_json=json.dumps(c.input),
            expected_json=(
                json.dumps(c.expected.model_dump(exclude_unset=True)) if c.expected else None
            ),
            tags_json=json.dumps(c.tags),
            extra_json=json.dumps(c.model_extra) if c.model_extra else None,
        )
        for i, c in enumerate(cases)
    ]
