"""Versioned REST adapters over Minerva's shared command/query services."""

from __future__ import annotations

import base64
import json
import re
from hashlib import sha256
from typing import Annotated, Any, Final, cast

from fastapi import APIRouter, Depends, Header, Path, Query, Request, Response, status

from minerva.api.errors import ApiContractError
from minerva.api.models import (
    BriefPreviewRead,
    CapabilityManifestRead,
    ClaimCollection,
    ClaimCreate,
    ClaimLedgerRead,
    ClaimRead,
    ClaimStatusUpdate,
    EvidenceCreate,
    EvidenceRead,
    FindingCollection,
    FindingCreate,
    FindingRead,
    LedgerEntryRead,
    LimitsRead,
    MissionCollection,
    MissionCreate,
    MissionRead,
    QuestionCollection,
    QuestionCreate,
    QuestionRead,
    SourceCollection,
    SourceImport,
    SourceSnapshotRead,
    claim_read,
    evidence_read,
    finding_read,
    mission_read,
    question_read,
    snapshot_read,
)
from minerva.assist.service import (
    MAX_ASSISTANCE_CANDIDATES,
    MAX_ASSISTANCE_CONTEXT_BYTES,
    MAX_ASSISTANCE_EVIDENCE_CARDS,
)
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, SecurityBoundaryError
from minerva.core.types import IdentityContext, local_identity
from minerva.evidence.service import EvidenceService
from minerva.research.service import ResearchService
from minerva.sources.service import DEFAULT_MAX_SOURCE_BYTES, SourceService
from minerva.synthesis.service import BRIEF_SCHEMA_VERSION, CITATION_SCHEME, SynthesisService

API_VERSION: Final = "v1"
MAX_COLLECTION_PAGE_SIZE: Final = 200
_CURSOR_MAX_LENGTH: Final = 1_024
_PageLimit = Annotated[int, Query(ge=1, le=MAX_COLLECTION_PAGE_SIZE)]
_PageCursor = Annotated[str | None, Query(max_length=_CURSOR_MAX_LENGTH)]
_CURSOR_KINDS: Final = frozenset(
    {"missions", "questions", "claims", "sources", "findings", "claim-ledger"}
)
_CURSOR_ID_RE: Final = re.compile(r"[a-z]{3}_[0-9a-f]{32}\Z")
_CURSOR_TIMESTAMP_RE: Final = re.compile(r"[0-9T:+.Z-]{1,64}\Z")
CAPABILITY_SCHEMA_VERSION: Final = "minerva.capabilities.v2"
MAX_REQUEST_BODY_BYTES: Final = 5_242_880
MAX_MISSION_PAGE_SIZE: Final = 200

_RESOURCE_ID = Annotated[str, Path(min_length=1, max_length=100)]
_FORBIDDEN_IDENTITY_HEADERS: Final = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-actor",
        "x-actor-id",
        "x-authenticated-user",
        "x-minerva-actor",
        "x-minerva-actor-id",
        "x-user",
        "x-user-id",
    }
)
_CLAIM_ETAG_RE_TEMPLATE: Final = r'"claim-{claim_id}-v([1-9][0-9]*)"'


def _reject_external_identity_headers(request: Request) -> None:
    if any(name in request.headers for name in _FORBIDDEN_IDENTITY_HEADERS):
        raise SecurityBoundaryError(
            "external_identity_rejected",
            "External authentication and actor headers are not accepted.",
        )


def _request_identity(request: Request) -> IdentityContext:
    route = request.scope.get("route")
    route_path = getattr(route, "path", "/api/v1")
    if not isinstance(route_path, str):
        route_path = "/api/v1"
    return local_identity(purpose=f"api {request.method} {route_path}")


_Identity = Annotated[IdentityContext, Depends(_request_identity)]


def _expected_claim_version(claim_id: str, if_match: str | None) -> int:
    if if_match is None:
        raise ApiContractError(
            "if_match_required",
            "A current If-Match claim validator is required.",
            http_status=428,
        )
    if len(if_match) > 200:
        raise ApiContractError(
            "claim_precondition_failed",
            "The claim validator does not match the current resource.",
            http_status=412,
        )
    pattern = _CLAIM_ETAG_RE_TEMPLATE.format(claim_id=re.escape(claim_id))
    match = re.fullmatch(pattern, if_match)
    if match is None:
        raise ApiContractError(
            "claim_precondition_failed",
            "The claim validator does not match the current resource.",
            http_status=412,
        )
    return int(match.group(1))


def _cursor_scope(kind: str, scope: str) -> str:
    return sha256(f"{kind}\x00{scope}".encode("utf-8", errors="strict")).hexdigest()


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate cursor key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-standard cursor value")


def _cursor_payload_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii", errors="strict")


def _encode_cursor(
    *,
    kind: str,
    scope: str,
    position: tuple[str, str] | None,
) -> str | None:
    if position is None:
        return None
    if kind not in _CURSOR_KINDS:
        raise RuntimeError("unsupported internal cursor kind")
    created_at, item_id = position
    payload: dict[str, Any] = {
        "created_at": created_at,
        "id": item_id,
        "kind": kind,
        "scope": _cursor_scope(kind, scope),
        "v": 1,
    }
    return base64.urlsafe_b64encode(_cursor_payload_bytes(payload)).rstrip(b"=").decode("ascii")


def _decode_cursor(
    cursor: str | None,
    *,
    kind: str,
    scope: str,
) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        if (
            kind not in _CURSOR_KINDS
            or not cursor
            or len(cursor) > _CURSOR_MAX_LENGTH
            or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None
        ):
            raise ValueError("invalid cursor envelope")
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(
            (cursor + padding).encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        if len(raw) > 512:
            raise ValueError("cursor payload too large")
        decoded: Any = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(decoded, dict):
            raise ValueError("cursor is not an object")
        payload = cast(dict[str, Any], decoded)
        if set(payload) != {"created_at", "id", "kind", "scope", "v"}:
            raise ValueError("cursor keys invalid")
        created_at = payload["created_at"]
        item_id = payload["id"]
        if (
            type(payload["v"]) is not int
            or payload["v"] != 1
            or not isinstance(payload["kind"], str)
            or payload["kind"] != kind
            or not isinstance(payload["scope"], str)
            or payload["scope"] != _cursor_scope(kind, scope)
            or not isinstance(created_at, str)
            or _CURSOR_TIMESTAMP_RE.fullmatch(created_at) is None
            or not isinstance(item_id, str)
            or _CURSOR_ID_RE.fullmatch(item_id) is None
            or _cursor_payload_bytes(payload) != raw
        ):
            raise ValueError("cursor content invalid")
        canonical = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        if canonical != cursor:
            raise ValueError("cursor encoding invalid")
        return created_at, item_id
    except (UnicodeError, ValueError, TypeError) as error:
        raise ApiContractError(
            "pagination_cursor_invalid",
            "The pagination cursor is invalid for this collection.",
            http_status=422,
        ) from error


def create_api_router(database: Database) -> APIRouter:
    research = ResearchService(database)
    sources = SourceService(database)
    evidence = EvidenceService(database)
    synthesis = SynthesisService(database)
    router = APIRouter(
        prefix="/api/v1",
        dependencies=[
            Depends(_reject_external_identity_headers),
            Depends(_request_identity),
        ],
    )

    @router.get("/capabilities", response_model=CapabilityManifestRead)
    def capabilities() -> CapabilityManifestRead:
        return CapabilityManifestRead(
            schema_version=CAPABILITY_SCHEMA_VERSION,
            api_version=API_VERSION,
            local_only=False,
            loopback_only=True,
            external_egress="disabled_by_default_cli_only",
            supported_external_providers=["openai", "anthropic"],
            identity_boundary="local_os_user",
            citation_scheme=CITATION_SCHEME,
            brief_schema_version=BRIEF_SCHEMA_VERSION,
            capabilities=[
                "mission.create",
                "question.create",
                "claim.create",
                "claim.status.append",
                "source.utf8_bytes.import",
                "evidence.exact_byte_span.create",
                "finding.create",
                "claim.evidence_ledger.read",
                "brief.preview.markdown_json",
                "web.review",
                "assist.finding_candidates.preview.cli",
                "assist.finding_candidates.invoke.cli.byok.optional",
            ],
            unavailable=[
                "network.fetch",
                "model.invoke.api",
                "model.invoke.web",
                "model.output.auto_adopt",
                "provider.credential.persist",
                "mcp",
                "multi_user_auth",
                "publish",
                "remote_actor_headers",
            ],
            limits=LimitsRead(
                source_bytes=DEFAULT_MAX_SOURCE_BYTES,
                request_body_bytes=MAX_REQUEST_BODY_BYTES,
                mission_page_size=MAX_MISSION_PAGE_SIZE,
                assistant_context_bytes=MAX_ASSISTANCE_CONTEXT_BYTES,
                assistant_evidence_cards=MAX_ASSISTANCE_EVIDENCE_CARDS,
                assistant_candidates=MAX_ASSISTANCE_CANDIDATES,
            ),
        )

    @router.post(
        "/missions",
        response_model=MissionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_mission(payload: MissionCreate, identity: _Identity) -> MissionRead:
        return mission_read(
            research.create_mission(
                title=payload.title,
                objective=payload.objective,
                identity=identity,
            )
        )

    @router.get("/missions", response_model=MissionCollection)
    def list_missions(
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> MissionCollection:
        after = _decode_cursor(cursor, kind="missions", scope="global")
        items, next_position = research.page_missions(limit=limit, after=after)
        return MissionCollection(
            items=[mission_read(item) for item in items],
            next_cursor=_encode_cursor(
                kind="missions",
                scope="global",
                position=next_position,
            ),
        )

    @router.get("/missions/{mission_id}", response_model=MissionRead)
    def get_mission(mission_id: _RESOURCE_ID) -> MissionRead:
        return mission_read(research.get_mission(mission_id))

    @router.post(
        "/missions/{mission_id}/questions",
        response_model=QuestionRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_question(
        mission_id: _RESOURCE_ID,
        payload: QuestionCreate,
        identity: _Identity,
    ) -> QuestionRead:
        return question_read(
            research.add_question(
                mission_id=mission_id,
                text=payload.text,
                identity=identity,
            )
        )

    @router.get("/missions/{mission_id}/questions", response_model=QuestionCollection)
    def list_questions(
        mission_id: _RESOURCE_ID,
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> QuestionCollection:
        after = _decode_cursor(cursor, kind="questions", scope=mission_id)
        items, next_position = research.page_questions(
            mission_id,
            limit=limit,
            after=after,
        )
        return QuestionCollection(
            items=[question_read(item) for item in items],
            next_cursor=_encode_cursor(
                kind="questions",
                scope=mission_id,
                position=next_position,
            ),
        )

    @router.post(
        "/missions/{mission_id}/claims",
        response_model=ClaimRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_claim(
        mission_id: _RESOURCE_ID,
        payload: ClaimCreate,
        response: Response,
        identity: _Identity,
    ) -> ClaimRead:
        result = research.add_claim(
            mission_id=mission_id,
            question_id=payload.question_id,
            statement=payload.statement,
            falsification_criteria=payload.falsification_criteria,
            identity=identity,
        )
        response.headers["ETag"] = result.etag
        return claim_read(result)

    @router.get("/missions/{mission_id}/claims", response_model=ClaimCollection)
    def list_claims(
        mission_id: _RESOURCE_ID,
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> ClaimCollection:
        after = _decode_cursor(cursor, kind="claims", scope=mission_id)
        items, next_position = research.page_claims(
            mission_id,
            limit=limit,
            after=after,
        )
        return ClaimCollection(
            items=[claim_read(item) for item in items],
            next_cursor=_encode_cursor(
                kind="claims",
                scope=mission_id,
                position=next_position,
            ),
        )

    @router.get("/claims/{claim_id}", response_model=ClaimRead)
    def get_claim(claim_id: _RESOURCE_ID, response: Response) -> ClaimRead:
        result = research.get_claim(claim_id)
        response.headers["ETag"] = result.etag
        return claim_read(result)

    @router.patch("/claims/{claim_id}/status", response_model=ClaimRead)
    def update_claim_status(
        claim_id: _RESOURCE_ID,
        payload: ClaimStatusUpdate,
        response: Response,
        identity: _Identity,
        if_match: Annotated[str | None, Header(alias="If-Match", max_length=200)] = None,
    ) -> ClaimRead:
        expected_version = _expected_claim_version(claim_id, if_match)
        try:
            result = research.set_claim_status(
                claim_id=claim_id,
                status=payload.status,
                reason=payload.reason,
                expected_version=expected_version,
                identity=identity,
            )
        except ConflictError as error:
            if error.code == "claim_version_conflict":
                raise ApiContractError(
                    "claim_precondition_failed",
                    "The claim validator does not match the current resource.",
                    http_status=412,
                ) from error
            raise
        response.headers["ETag"] = result.etag
        return claim_read(result)

    @router.post(
        "/missions/{mission_id}/sources",
        response_model=SourceSnapshotRead,
        status_code=status.HTTP_201_CREATED,
    )
    def import_source(
        mission_id: _RESOURCE_ID,
        payload: SourceImport,
        identity: _Identity,
    ) -> SourceSnapshotRead:
        result = sources.import_bytes(
            mission_id=mission_id,
            content=payload.content.encode("utf-8", errors="strict"),
            original_label=payload.original_label,
            media_type=payload.media_type,
            url_metadata=payload.url_metadata,
            identity=identity,
        )
        return snapshot_read(result)

    @router.get("/missions/{mission_id}/sources", response_model=SourceCollection)
    def list_sources(
        mission_id: _RESOURCE_ID,
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> SourceCollection:
        after = _decode_cursor(cursor, kind="sources", scope=mission_id)
        items, next_position = sources.page_snapshots(
            mission_id,
            limit=limit,
            after=after,
        )
        return SourceCollection(
            items=[snapshot_read(item) for item in items],
            next_cursor=_encode_cursor(
                kind="sources",
                scope=mission_id,
                position=next_position,
            ),
        )

    @router.get("/snapshots/{snapshot_id}", response_model=SourceSnapshotRead)
    def get_snapshot(snapshot_id: _RESOURCE_ID) -> SourceSnapshotRead:
        return snapshot_read(sources.get_snapshot(snapshot_id))

    @router.post(
        "/missions/{mission_id}/evidence",
        response_model=EvidenceRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_evidence(
        mission_id: _RESOURCE_ID,
        payload: EvidenceCreate,
        identity: _Identity,
    ) -> EvidenceRead:
        result = evidence.add_evidence(
            mission_id=mission_id,
            claim_id=payload.claim_id,
            snapshot_id=payload.snapshot_id,
            start_byte=payload.start_byte,
            end_byte=payload.end_byte,
            quote=payload.quote,
            stance=payload.stance,
            supersedes_evidence_id=payload.supersedes_evidence_id,
            identity=identity,
        )
        return evidence_read(result)

    @router.get("/claims/{claim_id}/evidence", response_model=ClaimLedgerRead)
    def claim_ledger(
        claim_id: _RESOURCE_ID,
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> ClaimLedgerRead:
        after = _decode_cursor(cursor, kind="claim-ledger", scope=claim_id)
        with database.read() as connection:
            claim = research.get_claim(claim_id, connection=connection)
            ledger, next_position = evidence.page_ledger_for_claim(
                claim_id,
                limit=limit,
                after=after,
                connection=connection,
            )
        entries = [
            LedgerEntryRead(
                evidence=evidence_read(entry.evidence),
                citation_id=entry.citation_id,
                snapshot_sha256=entry.snapshot_sha256,
                source_label=entry.source_label,
                withdrawn=entry.withdrawn,
                withdrawal_reason=entry.withdrawal_reason,
                withdrawn_at=entry.withdrawn_at,
                withdrawn_by=entry.withdrawn_by,
            )
            for entry in ledger
        ]
        return ClaimLedgerRead(
            claim=claim_read(claim),
            entries=entries,
            next_cursor=_encode_cursor(
                kind="claim-ledger",
                scope=claim_id,
                position=next_position,
            ),
        )

    @router.post(
        "/missions/{mission_id}/findings",
        response_model=FindingRead,
        status_code=status.HTTP_201_CREATED,
    )
    def create_finding(
        mission_id: _RESOURCE_ID,
        payload: FindingCreate,
        identity: _Identity,
    ) -> FindingRead:
        result = research.add_finding(
            mission_id=mission_id,
            claim_id=payload.claim_id,
            statement=payload.statement,
            statement_kind=payload.statement_kind,
            status=payload.status,
            uncertainty=payload.uncertainty,
            evidence_ids=tuple(payload.evidence_ids),
            identity=identity,
        )
        return finding_read(result)

    @router.get("/missions/{mission_id}/findings", response_model=FindingCollection)
    def list_findings(
        mission_id: _RESOURCE_ID,
        limit: _PageLimit = 100,
        cursor: _PageCursor = None,
    ) -> FindingCollection:
        after = _decode_cursor(cursor, kind="findings", scope=mission_id)
        items, next_position = research.page_findings(
            mission_id,
            limit=limit,
            after=after,
        )
        return FindingCollection(
            items=[finding_read(item) for item in items],
            next_cursor=_encode_cursor(
                kind="findings",
                scope=mission_id,
                position=next_position,
            ),
        )

    @router.get("/missions/{mission_id}/brief-preview", response_model=BriefPreviewRead)
    def brief_preview(mission_id: _RESOURCE_ID) -> BriefPreviewRead:
        artifacts = synthesis.build_brief(mission_id)
        raw_document: Any = json.loads(artifacts.json)
        if not isinstance(raw_document, dict):
            raise IntegrityError(
                "brief_invalid",
                "The research brief could not be represented safely.",
            )
        document = cast(dict[str, Any], raw_document)
        return BriefPreviewRead(
            schema_version=BRIEF_SCHEMA_VERSION,
            export_digest=artifacts.export_digest,
            markdown_sha256=artifacts.markdown_sha256,
            json_sha256=artifacts.json_sha256,
            markdown=artifacts.markdown.decode("utf-8", errors="strict"),
            json_document=document,
        )

    return router
