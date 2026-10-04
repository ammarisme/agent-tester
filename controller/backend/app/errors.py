"""One error shape for every failure: ``{"detail": str, "errors": [{loc, message}]}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, detail: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.errors = errors or []


def not_found(kind: str) -> ApiError:
    return ApiError(404, f"{kind} not found")


def pydantic_errors(exc: ValidationError, prefix: str = "") -> list[dict[str, Any]]:
    out = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"])
        out.append({"loc": f"{prefix}.{loc}".strip(".") if prefix else loc, "message": err["msg"]})
    return out


def invalid(detail: str, errors: list[dict[str, Any]]) -> ApiError:
    return ApiError(422, detail, errors)


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        body: dict[str, Any] = {"detail": exc.detail}
        if exc.errors:
            body["errors"] = exc.errors
        return JSONResponse(body, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "loc": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
                "message": e["msg"],
            }
            for e in exc.errors()
        ]
        return JSONResponse({"detail": "request is invalid", "errors": errors}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )
