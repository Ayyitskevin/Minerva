"""Local HTTP security boundary for the loopback review server.

The middleware in this module deliberately implements the ASGI interface directly.
It buffers at most the configured request-body limit before handing a replayable body
to the framework, so requests without a trustworthy ``Content-Length`` receive the
same protection as requests that provide one.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "LocalSecurityMiddleware",
    "SecurityMiddleware",
]

_PRODUCTION_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
_TEST_HOST_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\Z")
_MAX_CONTENT_LENGTH_DIGITS: Final = 20
_MAX_REQUEST_MESSAGES: Final = 1_024

_CSP: Final = (
    b"default-src 'none'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
    b"form-action 'self'; img-src 'self'; style-src 'self'; script-src 'self'; "
    b"connect-src 'self'; font-src 'self'"
)
_SECURITY_HEADERS: Final[tuple[tuple[bytes, bytes], ...]] = (
    (b"content-security-policy", _CSP),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (
        b"permissions-policy",
        b"camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    ),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"x-permitted-cross-domain-policies", b"none"),
    (b"cache-control", b"no-store"),
)
_MANAGED_SECURITY_HEADER_NAMES: Final = frozenset(name for name, _ in _SECURITY_HEADERS)

_ERROR_BODIES: Final = {
    400: b'{"error":{"code":"invalid_request","message":"Request rejected."}}\n',
    403: b'{"error":{"code":"forbidden","message":"Request rejected."}}\n',
    413: b'{"error":{"code":"request_too_large","message":"Request rejected."}}\n',
}


class _MalformedRequestError(Exception):
    """Internal signal for a generic 400 response."""


class _RequestTooLargeError(Exception):
    """Internal signal for a generic 413 response."""


@dataclass(frozen=True, slots=True)
class _Authority:
    hostname: str
    port: int | None


def _parse_port(value: str) -> int | None:
    if not value or not value.isascii() or not value.isdecimal():
        return None
    port = int(value)
    if not 1 <= port <= 65_535:
        return None
    return port


def _parse_authority(raw_value: bytes) -> _Authority | None:
    try:
        value = raw_value.decode("ascii")
    except UnicodeDecodeError:
        return None

    if not value or value != value.strip() or any(char in value for char in "/?#@,\\"):
        return None

    if value.startswith("["):
        closing_bracket = value.find("]")
        if closing_bracket < 0:
            return None
        hostname = value[1:closing_bracket].lower()
        remainder = value[closing_bracket + 1 :]
        if not hostname or "[" in hostname or "]" in hostname:
            return None
        if not remainder:
            port = None
        elif remainder.startswith(":"):
            port = _parse_port(remainder[1:])
            if port is None:
                return None
        else:
            return None
    else:
        if "[" in value or "]" in value or value.count(":") > 1:
            return None
        if ":" in value:
            hostname, port_text = value.rsplit(":", 1)
            port = _parse_port(port_text)
            if port is None:
                return None
        else:
            hostname = value
            port = None
        hostname = hostname.lower()

    if not hostname or hostname.endswith("."):
        return None
    return _Authority(hostname=hostname, port=port)


def _normalize_test_host(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("allowed test hosts must be strings")
    try:
        hostname = value.encode("ascii").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("allowed test hosts must be ASCII hostnames") from error
    if not _TEST_HOST_RE.fullmatch(hostname):
        raise ValueError("allowed test hosts must be hostnames without a port")
    return hostname


def _header_values(scope: Scope, header_name: bytes) -> list[bytes]:
    return [value for name, value in scope.get("headers", []) if name.lower() == header_name]


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _origin_is_allowed(
    raw_origin: bytes,
    *,
    request_scheme: str,
    request_authority: _Authority,
    allowed_hosts: frozenset[str],
) -> bool:
    try:
        origin = raw_origin.decode("ascii")
    except UnicodeDecodeError:
        return False

    if not origin or origin != origin.strip() or any(character in origin for character in ",\r\n"):
        return False

    try:
        parsed = urlsplit(origin)
        origin_port = parsed.port
    except ValueError:
        return False

    if (
        parsed.scheme not in {"http", "https"}
        or parsed.scheme != request_scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.hostname is None
    ):
        return False

    origin_hostname = parsed.hostname.lower()
    if origin_hostname not in allowed_hosts or origin_hostname != request_authority.hostname:
        return False

    effective_origin_port = origin_port or _default_port(parsed.scheme)
    effective_host_port = request_authority.port or _default_port(request_scheme)
    return effective_origin_port == effective_host_port


def _parse_content_length(scope: Scope, *, maximum: int) -> int | None:
    values = _header_values(scope, b"content-length")
    if not values:
        return None
    if len(values) != 1:
        raise _MalformedRequestError
    raw_value = values[0]
    if not raw_value or any(byte < ord("0") or byte > ord("9") for byte in raw_value):
        raise _MalformedRequestError
    if len(raw_value) > _MAX_CONTENT_LENGTH_DIGITS:
        raise _MalformedRequestError
    try:
        declared_length = int(raw_value)
    except ValueError:
        raise _MalformedRequestError from None
    if declared_length > maximum:
        raise _RequestTooLargeError
    return declared_length


async def _buffer_request(receive: Receive, *, maximum: int) -> bytes:
    content = bytearray()
    message_count = 0

    while True:
        message_count += 1
        if message_count > _MAX_REQUEST_MESSAGES:
            raise _MalformedRequestError
        message = await receive()
        if message.get("type") != "http.request":
            raise _MalformedRequestError
        body = message.get("body", b"")
        if not isinstance(body, bytes):
            raise _MalformedRequestError
        if len(content) + len(body) > maximum:
            raise _RequestTooLargeError
        content.extend(body)
        if not bool(message.get("more_body", False)):
            return bytes(content)


def _replay_receive(content: bytes) -> Receive:
    pending = True

    async def replay() -> Message:
        nonlocal pending
        if pending:
            pending = False
            return {"type": "http.request", "body": content, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    return replay


def _secured_headers(headers: Sequence[tuple[bytes, bytes]]) -> list[tuple[bytes, bytes]]:
    safe_headers = [
        (name, value)
        for name, value in headers
        if name.lower() not in _MANAGED_SECURITY_HEADER_NAMES
        and not name.lower().startswith(b"access-control-")
    ]
    safe_headers.extend(_SECURITY_HEADERS)
    return safe_headers


def _secured_send(send: Send) -> Send:
    async def send_with_security_headers(message: Message) -> None:
        if message.get("type") == "http.response.start":
            raw_headers = message.get("headers", [])
            if not isinstance(raw_headers, (list, tuple)):
                raw_headers = []
            secured_message = dict(message)
            secured_message["headers"] = _secured_headers(raw_headers)
            await send(secured_message)
            return
        await send(message)

    return send_with_security_headers


async def _send_error(send: Send, status: int) -> None:
    body = _ERROR_BODIES[status]
    headers = _secured_headers(
        (
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
        )
    )
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


class LocalSecurityMiddleware:
    """Enforce Minerva's loopback-only HTTP boundary before framework parsing."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_request_body_bytes: int = 1_048_576,
        allowed_test_hosts: Collection[str] = (),
    ) -> None:
        if (
            isinstance(max_request_body_bytes, bool)
            or not isinstance(max_request_body_bytes, int)
            or max_request_body_bytes < 0
        ):
            raise ValueError("max_request_body_bytes must be a non-negative integer")
        normalized_test_hosts = {_normalize_test_host(host) for host in allowed_test_hosts}
        self._app = app
        self._maximum_body_bytes = max_request_body_bytes
        self._allowed_hosts = frozenset(_PRODUCTION_HOSTS | normalized_test_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]
        if scope_type == "lifespan":
            await self._app(scope, receive, send)
            return
        if scope_type != "http":
            # Only HTTP carries the Host, Origin, and body checks below. A
            # websocket handshake ignores CSP and same-origin rules, so anything
            # that is not HTTP is refused rather than forwarded unchecked.
            if scope_type == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return

        host_values = _header_values(scope, b"host")
        if len(host_values) != 1:
            await _send_error(send, 400)
            return
        request_authority = _parse_authority(host_values[0])
        if request_authority is None or request_authority.hostname not in self._allowed_hosts:
            await _send_error(send, 400)
            return

        request_scheme_value = scope.get("scheme")
        if not isinstance(request_scheme_value, str):
            await _send_error(send, 400)
            return
        request_scheme = request_scheme_value.lower()
        if request_scheme not in {"http", "https"}:
            await _send_error(send, 400)
            return

        origin_values = _header_values(scope, b"origin")
        if len(origin_values) > 1 or (
            origin_values
            and not _origin_is_allowed(
                origin_values[0],
                request_scheme=request_scheme,
                request_authority=request_authority,
                allowed_hosts=self._allowed_hosts,
            )
        ):
            await _send_error(send, 403)
            return

        try:
            declared_length = _parse_content_length(
                scope,
                maximum=self._maximum_body_bytes,
            )
            buffered_content = await _buffer_request(
                receive,
                maximum=self._maximum_body_bytes,
            )
            if declared_length is not None and declared_length != len(buffered_content):
                raise _MalformedRequestError
        except _RequestTooLargeError:
            await _send_error(send, 413)
            return
        except _MalformedRequestError:
            await _send_error(send, 400)
            return

        await self._app(
            scope,
            _replay_receive(buffered_content),
            _secured_send(send),
        )


SecurityMiddleware = LocalSecurityMiddleware
