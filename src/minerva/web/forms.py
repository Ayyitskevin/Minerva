"""Strict local HTML-form parsing around the shared command layer."""

from __future__ import annotations

from collections.abc import Collection
from enum import StrEnum

from fastapi import Request
from starlette.responses import Response

from minerva.api.errors import ApiContractError
from minerva.core.errors import SecurityBoundaryError
from minerva.research.service import MAX_FINDING_CITATIONS
from minerva.web.security import CSRF_FORM_FIELD, CsrfProtector

_FORM_MEDIA_TYPE = "application/x-www-form-urlencoded"
_MAX_FORM_FIELDS = 20
_MAX_INTEGER_DIGITS = 20
_MAX_IDENTIFIER_LENGTH = 100


def _raw_header_values(request: Request, name: bytes) -> list[bytes]:
    return [
        value for raw_name, value in request.scope.get("headers", []) if raw_name.lower() == name
    ]


def _require_local_form_origin(request: Request) -> None:
    # LocalSecurityMiddleware has already validated the one supplied Origin.
    # Unsafe forms additionally require its presence instead of relying on the
    # middleware's safe-GET allowance for an omitted Origin.
    if len(_raw_header_values(request, b"origin")) != 1:
        raise SecurityBoundaryError("form_origin_required", "Request rejected.")


def _require_form_content_type(request: Request) -> None:
    values = _raw_header_values(request, b"content-type")
    if len(values) != 1:
        raise ApiContractError(
            "form_content_type_invalid",
            "The form request is invalid.",
            http_status=415,
        )
    try:
        media_type = values[0].decode("ascii").split(";", 1)[0].strip().lower()
    except UnicodeDecodeError:
        media_type = ""
    if media_type != _FORM_MEDIA_TYPE:
        raise ApiContractError(
            "form_content_type_invalid",
            "The form request is invalid.",
            http_status=415,
        )


async def read_strict_form(
    request: Request,
    *,
    csrf: CsrfProtector,
    required_fields: Collection[str],
) -> dict[str, str]:
    """Return one string per exact field after Origin and CSRF validation."""

    _require_local_form_origin(request)
    _require_form_content_type(request)
    form = await request.form()
    pairs = list(form.multi_items())
    csrf_values = [
        value for name, value in pairs if name == CSRF_FORM_FIELD and isinstance(value, str)
    ]
    if len(csrf_values) != 1 or not csrf.validate(
        request.cookies.get(csrf.cookie_name),
        csrf_values[0] if csrf_values else None,
    ):
        raise SecurityBoundaryError("csrf_invalid", "Request rejected.")

    expected = frozenset(required_fields) | {CSRF_FORM_FIELD}
    if len(pairs) > _MAX_FORM_FIELDS:
        raise ApiContractError(
            "form_contract_invalid",
            "The form request is invalid.",
            http_status=422,
        )
    fields: dict[str, str] = {}
    for name, value in pairs:
        if not isinstance(name, str) or not isinstance(value, str) or name in fields:
            raise ApiContractError(
                "form_contract_invalid",
                "The form request is invalid.",
                http_status=422,
            )
        fields[name] = value
    if frozenset(fields) != expected:
        raise ApiContractError(
            "form_contract_invalid",
            "The form request is invalid.",
            http_status=422,
        )
    return fields


def positive_form_integer(value: str) -> int:
    if (
        not value
        or len(value) > _MAX_INTEGER_DIGITS
        or not value.isascii()
        or not value.isdecimal()
    ):
        raise ApiContractError(
            "form_value_invalid",
            "A form value is invalid.",
            http_status=422,
        )
    parsed = int(value)
    if parsed < 1:
        raise ApiContractError(
            "form_value_invalid",
            "A form value is invalid.",
            http_status=422,
        )
    return parsed


def form_identifier(value: str) -> str:
    if not value or value != value.strip() or len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ApiContractError(
            "form_value_invalid",
            "A form value is invalid.",
            http_status=422,
        )
    return value


def optional_form_identifier(value: str) -> str | None:
    return None if not value else form_identifier(value)


def form_enum[T: StrEnum](enum_type: type[T], value: str) -> T:
    try:
        return enum_type(value)
    except ValueError:
        raise ApiContractError(
            "form_value_invalid",
            "A form value is invalid.",
            http_status=422,
        ) from None


def form_evidence_ids(value: str) -> tuple[str, ...]:
    identifiers = tuple(value.split())
    if len(identifiers) > MAX_FINDING_CITATIONS or len(set(identifiers)) != len(identifiers):
        raise ApiContractError(
            "form_value_invalid",
            "A form value is invalid.",
            http_status=422,
        )
    for identifier in identifiers:
        form_identifier(identifier)
    return identifiers


def csrf_token_for_request(request: Request, csrf: CsrfProtector) -> tuple[str, bool]:
    existing = request.cookies.get(csrf.cookie_name)
    if existing is not None and csrf.validate(existing, existing):
        return existing, False
    return csrf.issue_token(), True


def add_csrf_cookie(
    response: Response,
    *,
    request: Request,
    csrf: CsrfProtector,
    token: str,
) -> None:
    response.headers.append(
        "set-cookie",
        csrf.cookie_header(token, secure=request.url.scheme == "https"),
    )
