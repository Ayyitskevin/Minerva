"""Stable, non-reflective API error responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from minerva.core.errors import MinervaError


class ApiContractError(MinervaError):
    """An adapter-level contract failure with a stable status and code."""

    def __init__(self, code: str, message: str, *, http_status: int) -> None:
        super().__init__(code, message, http_status=http_status)


def error_document(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


async def _minerva_error_handler(_request: Request, error: Exception) -> Response:
    if not isinstance(error, MinervaError):
        return JSONResponse(
            error_document("internal_error", "The request could not be completed safely."),
            status_code=500,
        )
    return JSONResponse(
        error_document(error.code, error.public_message),
        status_code=error.http_status,
    )


async def _validation_error_handler(_request: Request, error: Exception) -> Response:
    if not isinstance(error, RequestValidationError):
        return JSONResponse(
            error_document("request_validation_failed", "Request validation failed."),
            status_code=422,
        )
    violations: list[dict[str, str]] = []
    for item in error.errors():
        raw_location = item.get("loc", ())
        location_parts = [
            str(part)
            for part in raw_location
            if isinstance(part, (str, int)) and str(part) not in {"body", "query", "path"}
        ]
        raw_type: Any = item.get("type", "invalid")
        violations.append(
            {
                "field": (
                    "unknown_field"
                    if str(raw_type) == "extra_forbidden"
                    else ".".join(location_parts) or "request"
                ),
                "type": str(raw_type),
            }
        )
    return JSONResponse(
        {
            **error_document("request_validation_failed", "Request validation failed."),
            "violations": violations[:20],
        },
        status_code=422,
    )


async def _http_error_handler(_request: Request, error: Exception) -> Response:
    status = error.status_code if isinstance(error, StarletteHTTPException) else 500
    codes = {
        404: ("not_found", "The requested resource was not found."),
        405: ("method_not_allowed", "The request method is not allowed."),
    }
    code, message = codes.get(
        status,
        ("request_rejected", "The request could not be completed safely."),
    )
    return JSONResponse(error_document(code, message), status_code=status)


async def _unexpected_error_handler(_request: Request, _error: Exception) -> Response:
    return JSONResponse(
        error_document("internal_error", "The request could not be completed safely."),
        status_code=500,
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(MinervaError, _minerva_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
    app.add_exception_handler(Exception, _unexpected_error_handler)
