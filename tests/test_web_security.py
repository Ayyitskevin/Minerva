from __future__ import annotations

import asyncio
from collections.abc import Sequence

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minerva.web.security import (
    CSRF_COOKIE_NAME,
    CSRF_FORM_FIELD,
    CsrfProtector,
    LocalSecurityMiddleware,
)

pytestmark = pytest.mark.security


_CSRF_SECRET = b"minerva-test-csrf-secret-is-at-least-32-bytes"
_GENERIC_ERRORS = {
    400: {"error": {"code": "invalid_request", "message": "Request rejected."}},
    403: {"error": {"code": "forbidden", "message": "Request rejected."}},
    413: {"error": {"code": "request_too_large", "message": "Request rejected."}},
}


def _build_app(
    *,
    maximum_body_bytes: int = 4_096,
    allowed_test_hosts: Sequence[str] = (),
) -> tuple[ASGIApp, CsrfProtector]:
    app = FastAPI()
    csrf = CsrfProtector(_CSRF_SECRET)

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/size")
    async def body_size(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    @app.get("/attempt-cors")
    async def attempt_cors() -> JSONResponse:
        return JSONResponse(
            {"ok": True},
            headers={
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.post("/csrf")
    async def csrf_mutation(request: Request) -> JSONResponse:
        form = await request.form()
        submitted_value = form.get(csrf.form_field)
        submitted_token = submitted_value if isinstance(submitted_value, str) else None
        if not csrf.validate(request.cookies.get(csrf.cookie_name), submitted_token):
            return JSONResponse(_GENERIC_ERRORS[403], status_code=403)
        return JSONResponse({"ok": True})

    return (
        LocalSecurityMiddleware(
            app,
            max_request_body_bytes=maximum_body_bytes,
            allowed_test_hosts=allowed_test_hosts,
        ),
        csrf,
    )


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8080", "127.0.0.1", "127.0.0.1:8080", "[::1]", "[::1]:8080"],
)
def test_production_loopback_hosts_are_accepted(host: str) -> None:
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host})

    assert response.status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "testserver",
        "example.test",
        "127.0.0.2",
        "0.0.0.0",
        "localhost.",
        "localhost:0",
        "localhost:65536",
        "::1",
        "http://localhost",
    ],
)
def test_non_loopback_or_malformed_hosts_are_rejected_without_reflection(host: str) -> None:
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host})

    assert response.status_code == 400
    assert response.json() == _GENERIC_ERRORS[400]
    assert host not in response.text


def test_test_host_requires_explicit_constructor_allowance() -> None:
    denied_app, _ = _build_app()
    allowed_app, _ = _build_app(allowed_test_hosts=("testserver",))

    with TestClient(denied_app) as denied_client:
        denied = denied_client.get("/ok")
    with TestClient(allowed_app) as allowed_client:
        allowed = allowed_client.get("/ok")

    assert denied.status_code == 400
    assert allowed.status_code == 200


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("localhost", "http://localhost"),
        ("localhost:80", "http://localhost"),
        ("localhost:8080", "http://localhost:8080"),
        ("127.0.0.1:8080", "http://127.0.0.1:8080"),
        ("[::1]:8080", "http://[::1]:8080"),
        ("testserver", "http://testserver"),
    ],
)
def test_matching_loopback_origin_is_accepted(host: str, origin: str) -> None:
    app, _ = _build_app(allowed_test_hosts=("testserver",))
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host, "Origin": origin})

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("localhost:8080", "http://localhost:8081"),
        ("localhost", "http://localhost:8080"),
        ("localhost", "https://localhost"),
        ("localhost", "http://127.0.0.1"),
        ("localhost", "http://example.test"),
        ("localhost", "http://localhost/path"),
        ("localhost", "http://user@localhost"),
        ("localhost", "null"),
    ],
)
def test_invalid_origin_is_rejected_without_reflection(host: str, origin: str) -> None:
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host, "Origin": origin})

    assert response.status_code == 403
    assert response.json() == _GENERIC_ERRORS[403]
    assert origin not in response.text


def test_origin_is_optional() -> None:
    app, _ = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": "localhost:9000"})

    assert response.status_code == 200


def test_security_headers_are_strict_on_success_and_error() -> None:
    app, _ = _build_app(allowed_test_hosts=("testserver",))
    with TestClient(app) as client:
        responses = (client.get("/ok"), client.get("/ok", headers={"Host": "evil.test"}))

    for response in responses:
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "object-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "'unsafe-inline'" not in csp
        assert "'unsafe-eval'" not in csp
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["cross-origin-opener-policy"] == "same-origin"
        assert response.headers["cross-origin-resource-policy"] == "same-origin"
        assert response.headers["cache-control"] == "no-store"


def test_cors_headers_are_never_emitted_even_if_downstream_attempts_them() -> None:
    app, _ = _build_app(allowed_test_hosts=("testserver",))
    with TestClient(app) as client:
        response = client.get(
            "/attempt-cors",
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 200
    assert not any(name.lower().startswith("access-control-") for name in response.headers)


def _http_scope(headers: Sequence[tuple[bytes, bytes]]) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/size",
        "raw_path": b"/size",
        "query_string": b"",
        "root_path": "",
        "headers": list(headers),
        "client": ("127.0.0.1", 40_000),
        "server": ("127.0.0.1", 80),
        "state": {},
    }


def _invoke_asgi(
    app: ASGIApp,
    *,
    headers: Sequence[tuple[bytes, bytes]],
    request_messages: Sequence[Message],
) -> tuple[list[Message], int]:
    sent: list[Message] = []
    receive_count = 0
    position = 0

    async def receive() -> Message:
        nonlocal position, receive_count
        receive_count += 1
        if position >= len(request_messages):
            return {"type": "http.disconnect"}
        message = request_messages[position]
        position += 1
        return message

    async def send(message: Message) -> None:
        sent.append(message)

    async def run() -> None:
        await app(_http_scope(headers), receive, send)

    asyncio.run(run())
    return sent, receive_count


def _asgi_response(messages: Sequence[Message]) -> tuple[int, dict[bytes, bytes], bytes]:
    start = next(message for message in messages if message["type"] == "http.response.start")
    status = start["status"]
    headers = dict(start.get("headers", []))
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return status, headers, body


def test_declared_oversized_body_is_rejected_before_receive() -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"), (b"content-length", b"9")),
        request_messages=({"type": "http.request", "body": b"not-read"},),
    )
    status, _, body = _asgi_response(messages)

    assert status == 413
    assert receive_count == 0
    assert b"not-read" not in body


def test_chunked_body_without_content_length_is_bounded_and_not_reflected() -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"), (b"transfer-encoding", b"chunked")),
        request_messages=(
            {"type": "http.request", "body": b"private", "more_body": True},
            {"type": "http.request", "body": b"payload", "more_body": False},
        ),
    )
    status, _, body = _asgi_response(messages)

    assert status == 413
    assert receive_count == 2
    assert b"private" not in body
    assert b"payload" not in body


def test_missing_content_length_body_is_replayed_to_fastapi() -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    messages, _ = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"),),
        request_messages=(
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ),
    )
    status, _, body = _asgi_response(messages)

    assert status == 200
    assert body == b'{"size":6}'


@pytest.mark.parametrize("length", [b"-1", b"1x", b""])
def test_malformed_content_length_gets_generic_error(length: bytes) -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"), (b"content-length", length)),
        request_messages=({"type": "http.request", "body": b""},),
    )
    status, _, body = _asgi_response(messages)

    assert status == 400
    assert receive_count == 0
    assert body.endswith(b"\n")
    if length:
        assert length not in body


def test_csrf_tokens_are_random_signed_and_cookie_safe() -> None:
    csrf = CsrfProtector(_CSRF_SECRET)
    first = csrf.issue_token()
    second = csrf.issue_token()

    assert first != second
    assert csrf.validate(first, first)
    assert csrf.validate(second, second)
    cookie_header = csrf.cookie_header(first)
    assert cookie_header.startswith(f"{CSRF_COOKIE_NAME}=")
    assert "HttpOnly" in cookie_header
    assert "SameSite=Strict" in cookie_header
    assert "Path=/" in cookie_header
    assert "Domain=" not in cookie_header


def _post_csrf(app: ASGIApp, *, cookie_token: str | None, form_token: str | None) -> JSONResponse:
    headers = {"Origin": "http://testserver"}
    if cookie_token is not None:
        headers["Cookie"] = f"{CSRF_COOKIE_NAME}={cookie_token}"
    data = {} if form_token is None else {CSRF_FORM_FIELD: form_token}
    with TestClient(app) as client:
        response = client.post("/csrf", headers=headers, data=data)
    return response


def test_csrf_valid_cookie_and_form_pair_is_accepted() -> None:
    app, csrf = _build_app(allowed_test_hosts=("testserver",))
    token = csrf.issue_token()

    response = _post_csrf(app, cookie_token=token, form_token=token)

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("case", ["missing_cookie", "missing_form", "tampered", "different"])
def test_csrf_missing_or_tampered_pair_is_rejected_without_reflection(case: str) -> None:
    app, csrf = _build_app(allowed_test_hosts=("testserver",))
    token = csrf.issue_token()
    other = csrf.issue_token()
    tampered = f"{token[:-1]}{'A' if token[-1] != 'A' else 'B'}"
    values = {
        "missing_cookie": (None, token),
        "missing_form": (token, None),
        "tampered": (token, tampered),
        "different": (token, other),
    }
    cookie_token, form_token = values[case]

    response = _post_csrf(app, cookie_token=cookie_token, form_token=form_token)

    assert response.status_code == 403
    assert response.json() == _GENERIC_ERRORS[403]
    assert token not in response.text
    assert other not in response.text


def test_csrf_rejects_invalid_configuration_and_malformed_tokens() -> None:
    with pytest.raises(ValueError, match="at least 32 bytes"):
        CsrfProtector(b"too-short")

    csrf = CsrfProtector(_CSRF_SECRET)
    valid = csrf.issue_token()
    assert not csrf.validate(valid, "not-a-token")
    assert not csrf.validate(valid, "\N{SNOWMAN}")
    assert not csrf.validate(None, None)
    with pytest.raises(ValueError, match="invalid token"):
        csrf.cookie_header("not-a-token")


def test_pathological_content_length_is_rejected_without_integer_conversion_or_reflection() -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    pathological = b"9" * 5_000
    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"), (b"content-length", pathological)),
        request_messages=({"type": "http.request", "body": b"not-read"},),
    )
    status, _, body = _asgi_response(messages)

    assert status == 400
    assert receive_count == 0
    assert body == b'{"error":{"code":"invalid_request","message":"Request rejected."}}\n'
    assert pathological not in body


def test_excessive_empty_request_message_stream_is_bounded() -> None:
    app, _ = _build_app(maximum_body_bytes=8)
    request_messages: tuple[Message, ...] = tuple(
        {"type": "http.request", "body": b"", "more_body": True} for _ in range(1_025)
    )

    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"),),
        request_messages=request_messages,
    )
    status, _, body = _asgi_response(messages)

    assert status == 400
    assert receive_count == 1_024
    assert body == b'{"error":{"code":"invalid_request","message":"Request rejected."}}\n'


def test_buffered_request_is_replayed_as_one_terminal_message() -> None:
    captured: list[Message] = []

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        captured.append(await receive())
        captured.append(await receive())
        await send(
            {
                "type": "http.response.start",
                "status": 204,
                "headers": [],
            }
        )
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    app = LocalSecurityMiddleware(downstream, max_request_body_bytes=8)
    messages, receive_count = _invoke_asgi(
        app,
        headers=((b"host", b"localhost"),),
        request_messages=(
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ),
    )

    status, _, _ = _asgi_response(messages)
    assert status == 204
    assert receive_count == 2
    assert captured == [
        {"type": "http.request", "body": b"abcdef", "more_body": False},
        {"type": "http.request", "body": b"", "more_body": False},
    ]


@pytest.mark.parametrize("invalid_limit", [True, -1, 1.5, "8"])
def test_request_body_limit_requires_a_nonnegative_exact_integer(
    invalid_limit: object,
) -> None:
    app = FastAPI()
    with pytest.raises(ValueError, match="non-negative integer"):
        LocalSecurityMiddleware(app, max_request_body_bytes=invalid_limit)  # type: ignore[arg-type]
