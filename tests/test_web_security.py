from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from minerva.web import security as web_security
from minerva.web.security import LocalSecurityMiddleware

pytestmark = pytest.mark.security


_GENERIC_ERRORS = {
    400: {"error": {"code": "invalid_request", "message": "Request rejected."}},
    403: {"error": {"code": "forbidden", "message": "Request rejected."}},
    413: {"error": {"code": "request_too_large", "message": "Request rejected."}},
}


def _build_app(
    *,
    maximum_body_bytes: int = 4_096,
    allowed_test_hosts: Sequence[str] = (),
) -> ASGIApp:
    app = FastAPI()

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

    return LocalSecurityMiddleware(
        app,
        max_request_body_bytes=maximum_body_bytes,
        allowed_test_hosts=allowed_test_hosts,
    )


@pytest.mark.parametrize(
    "host",
    ["localhost", "localhost:8080", "127.0.0.1", "127.0.0.1:8080", "[::1]", "[::1]:8080"],
)
def test_production_loopback_hosts_are_accepted(host: str) -> None:
    app = _build_app()
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
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host})

    assert response.status_code == 400
    assert response.json() == _GENERIC_ERRORS[400]
    assert host not in response.text


def test_test_host_requires_explicit_constructor_allowance() -> None:
    denied_app = _build_app()
    allowed_app = _build_app(allowed_test_hosts=("testserver",))

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
    app = _build_app(allowed_test_hosts=("testserver",))
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
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": host, "Origin": origin})

    assert response.status_code == 403
    assert response.json() == _GENERIC_ERRORS[403]
    assert origin not in response.text


def test_origin_is_optional() -> None:
    app = _build_app()
    with TestClient(app) as client:
        response = client.get("/ok", headers={"Host": "localhost:9000"})

    assert response.status_code == 200


def test_security_headers_are_strict_on_success_and_error() -> None:
    app = _build_app(allowed_test_hosts=("testserver",))
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
    app = _build_app(allowed_test_hosts=("testserver",))
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
    app = _build_app(maximum_body_bytes=8)
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
    app = _build_app(maximum_body_bytes=8)
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
    app = _build_app(maximum_body_bytes=8)
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
    app = _build_app(maximum_body_bytes=8)
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


def test_pathological_content_length_is_rejected_without_integer_conversion_or_reflection() -> None:
    app = _build_app(maximum_body_bytes=8)
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
    app = _build_app(maximum_body_bytes=8)
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


@pytest.mark.security
def test_websocket_scopes_are_refused_without_reaching_the_application() -> None:
    """Host, Origin, and body checks are HTTP-only, so no other scope may pass.

    A browser WebSocket handshake ignores CSP and the same-origin rules the
    middleware relies on, so forwarding one unchecked would reopen the exact
    cross-origin path the middleware exists to close.
    """

    reached: list[str] = []

    async def sentinel(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(str(scope["type"]))

    middleware = LocalSecurityMiddleware(sentinel, max_request_body_bytes=1024)
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    async def receive() -> Message:  # pragma: no cover - never awaited
        raise AssertionError("websocket scope must not read from the client")

    asyncio.run(
        middleware(
            {"type": "websocket", "path": "/", "headers": []},
            receive,
            send,
        )
    )

    assert reached == []
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.security
def test_lifespan_scopes_still_reach_the_application() -> None:
    """The scope allowlist must not break application startup and shutdown."""

    reached: list[str] = []

    async def sentinel(scope: Scope, receive: Receive, send: Send) -> None:
        reached.append(str(scope["type"]))

    middleware = LocalSecurityMiddleware(sentinel, max_request_body_bytes=1024)

    async def send(_message: Message) -> None:  # pragma: no cover - unused
        raise AssertionError("lifespan handling is delegated to the application")

    async def receive() -> Message:  # pragma: no cover - unused
        raise AssertionError("lifespan handling is delegated to the application")

    asyncio.run(middleware({"type": "lifespan"}, receive, send))

    assert reached == ["lifespan"]


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# The documents that tell a reader what defends the local HTTP boundary. Game
# plans, DECISIONS.md, and the execution state are records of what happened and
# are deliberately not in this list.
_SECURITY_DOCUMENTS = ("SECURITY.md", "docs/ARCHITECTURE.md", "docs/THREAT_MODEL.md")

# What a security document calls a control -> the object in
# `minerva.web.security` that has to exist for the claim to be true.
_DOCUMENTED_WEB_CONTROLS = {
    "CSRF": "CsrfProtector",
    "Origin": "LocalSecurityMiddleware",
}

# A statement naming a control the code does not have must qualify it: as an
# absence, or as a requirement on work that has not happened yet.
_QUALIFIERS = ("must", "future", "would", "does not exist", "no longer")

# ...and must not assert it as present anyway.
_PRESENT_TENSE_CLAIMS = ("exists", "existing", "reserved", "already", "in place")


def _sentences(paragraph: str) -> Iterator[str]:
    yield from (part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip())


def _statements(markdown: str) -> Iterator[str]:
    """Yield the sentence-sized claims a Markdown document makes.

    Table cells are yielded whole and one at a time: a mitigation named in one
    column is not qualified by prose in another. Everything else is unwrapped to
    one string per paragraph or list item before it is split on sentence
    punctuation, because these documents hard-wrap and a single claim routinely
    spans two source lines.
    """

    wrapped: list[str] = []
    for line in [*markdown.splitlines(), ""]:
        stripped = line.strip()
        if (not stripped or stripped.startswith(("|", "-", "*", "#", ">"))) and wrapped:
            yield from _sentences(" ".join(wrapped))
            wrapped = []
        if stripped.startswith("|"):
            yield from (cell.strip() for cell in stripped.strip("|").split("|") if cell.strip())
        elif stripped:
            wrapped.append(stripped)


def _names(text: str, control: str) -> bool:
    return re.search(rf"\b{re.escape(control)}\b", text, re.IGNORECASE) is not None


def _is_qualified(statement: str, control: str) -> bool:
    lowered = statement.lower()
    qualified = any(marker in lowered for marker in (*_QUALIFIERS, f"no {control.lower()}"))
    return qualified and not any(claim in lowered for claim in _PRESENT_TENSE_CLAIMS)


def _controls_the_code_lacks() -> dict[str, str]:
    return {
        control: symbol
        for control, symbol in _DOCUMENTED_WEB_CONTROLS.items()
        if not hasattr(web_security, symbol)
    }


def _security_documents() -> dict[str, str]:
    return {
        name: (_REPOSITORY_ROOT / name).read_text(encoding="utf-8") for name in _SECURITY_DOCUMENTS
    }


@pytest.mark.security
def test_security_documents_do_not_present_a_control_the_code_lacks() -> None:
    """A security document may not name a control this module does not expose.

    Deleting the unwired `CsrfProtector` took a false affordance out of a module
    where a test could fail on it and left four copies of it in SECURITY.md, the
    architecture, and the threat model -- which is where an auditor looks. This
    pins those documents to the module the way the capability manifest is pinned
    to the CLI parser: a control the code does not have may be named only as an
    absence or as a requirement on a form that does not exist yet, never as
    something Minerva has.

    The qualifier rule is the net that fails closed, because a sentence that
    asserts a missing control flatly carries no qualifier at all.
    `_PRESENT_TENSE_CLAIMS` is a second, weaker net for sentences carrying both
    a qualifier and an existence claim ("a CSRF primitive exists and must be
    wired into any future form"); being a denylist, it cannot be complete.
    """

    documents = _security_documents()

    unmentioned = sorted(
        control
        for control in _DOCUMENTED_WEB_CONTROLS
        if not any(_names(text, control) for text in documents.values())
    )
    assert not unmentioned, (
        "no security document names these controls any more, so this test proves nothing "
        f"about them; either the documents lost a claim or the pairing is dead: {unmentioned}"
    )

    missing = _controls_the_code_lacks()
    unqualified = sorted(
        f"{name}: {statement}"
        for name, text in documents.items()
        for statement in _statements(text)
        for control in missing
        if _names(statement, control) and not _is_qualified(statement, control)
    )
    assert not unqualified, (
        f"a security document presents a control `minerva.web.security` does not expose "
        f"({missing}): {unqualified}"
    )


@pytest.mark.security
def test_threat_model_mitigations_name_only_controls_that_exist() -> None:
    """The `Current controls` column has no honest way to name a missing control.

    Prose can qualify a claim; a cell in a column headed `Current controls`
    cannot, because the column heading has already said the claim is present
    tense. The cross-site-request-forgery row listed a "signed SameSite CSRF
    primitive" there after the primitive had been deleted.
    """

    document = (_REPOSITORY_ROOT / "docs/THREAT_MODEL.md").read_text(encoding="utf-8")
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in document.splitlines()
        if line.startswith("|")
    ]
    header = next(index for index, row in enumerate(rows) if "Current controls" in row)
    column = rows[header].index("Current controls")
    mitigations = [row[column] for row in rows[header + 2 :] if len(row) == len(rows[header])]

    assert any(
        _names(mitigation, control)
        for mitigation in mitigations
        for control in _DOCUMENTED_WEB_CONTROLS
    ), "no mitigation names a control this test knows about, so it would prove nothing"

    claimed = sorted(
        f"{control}: {mitigation}"
        for mitigation in mitigations
        for control in _controls_the_code_lacks()
        if _names(mitigation, control)
    )
    assert not claimed, (
        f"the threat model lists a control `minerva.web.security` does not expose as a "
        f"current mitigation: {claimed}"
    )
