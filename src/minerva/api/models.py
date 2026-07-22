"""Strict public API contracts, separate from SQLite rows and domain internals."""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.research.models import (
    CitationStatus,
    Claim,
    ClaimStatus,
    Finding,
    FindingStatus,
    Mission,
    Question,
    StatementKind,
)
from minerva.sources.models import SourceSnapshot

Identifier = Annotated[str, Field(min_length=1, max_length=100)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MissionCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2_000)


class QuestionCreate(StrictModel):
    text: str = Field(min_length=1, max_length=2_000)


class ClaimCreate(StrictModel):
    question_id: Identifier
    statement: str = Field(min_length=1, max_length=2_000)
    falsification_criteria: str = Field(min_length=1, max_length=2_000)


class ClaimStatusUpdate(StrictModel):
    status: ClaimStatus
    reason: str = Field(min_length=1, max_length=1_000)


class SourceImport(StrictModel):
    content: str = Field(min_length=1, max_length=1_048_576)
    original_label: str = Field(min_length=1, max_length=500)
    media_type: str = Field(default="text/plain", min_length=3, max_length=100)
    url_metadata: str | None = Field(default=None, min_length=1, max_length=2_000)


class EvidenceCreate(StrictModel):
    claim_id: Identifier
    snapshot_id: Identifier
    start_byte: int = Field(strict=True, ge=0)
    end_byte: int = Field(strict=True, gt=0)
    quote: str = Field(min_length=1, max_length=100_000)
    stance: EvidenceStance
    supersedes_evidence_id: Identifier | None = None


class FindingCreate(StrictModel):
    claim_id: Identifier | None = None
    statement: str = Field(min_length=1, max_length=4_000)
    statement_kind: StatementKind
    status: FindingStatus
    uncertainty: str = Field(default="", max_length=2_000)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=100)


class MissionRead(StrictModel):
    id: str
    title: str
    objective: str
    created_at: str


class QuestionRead(StrictModel):
    id: str
    mission_id: str
    text: str
    created_at: str


class ClaimRead(StrictModel):
    id: str
    mission_id: str
    question_id: str
    statement: str
    falsification_criteria: str
    status: ClaimStatus
    version: int
    status_reason: str
    status_creator_id: str
    status_run_id: str
    status_changed_at: str
    status_evidence_valid: bool
    etag: str
    created_at: str


class SourceSnapshotRead(StrictModel):
    source_id: str
    snapshot_id: str
    mission_id: str
    sha256: str
    byte_length: int
    encoding: str
    media_type: str
    original_label: str
    url_metadata: str | None
    imported_at: str


class EvidenceRead(StrictModel):
    id: str
    mission_id: str
    claim_id: str
    snapshot_id: str
    start_byte: int
    end_byte: int
    quote: str
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    created_at: str


class LedgerEntryRead(StrictModel):
    evidence: EvidenceRead
    citation_id: str
    snapshot_sha256: str
    source_label: str
    withdrawn: bool
    withdrawal_reason: str | None
    withdrawn_at: str | None
    withdrawn_by: str | None


class FindingRead(StrictModel):
    id: str
    mission_id: str
    claim_id: str | None
    statement: str
    statement_kind: StatementKind
    status: FindingStatus
    uncertainty: str
    evidence_ids: list[str]
    citation_status: CitationStatus
    created_at: str


class MissionCollection(StrictModel):
    items: list[MissionRead]
    next_cursor: str | None


class QuestionCollection(StrictModel):
    items: list[QuestionRead]
    next_cursor: str | None


class ClaimCollection(StrictModel):
    items: list[ClaimRead]
    next_cursor: str | None


class SourceCollection(StrictModel):
    items: list[SourceSnapshotRead]
    next_cursor: str | None


class FindingCollection(StrictModel):
    items: list[FindingRead]
    next_cursor: str | None


class ClaimLedgerRead(StrictModel):
    claim: ClaimRead
    entries: list[LedgerEntryRead]
    next_cursor: str | None


class BriefPreviewRead(StrictModel):
    schema_version: str
    export_digest: str
    markdown_sha256: str
    json_sha256: str
    markdown: str
    json_document: dict[str, Any]


class HealthRead(StrictModel):
    status: str


class ReadyCheckRead(StrictModel):
    name: str
    ok: bool
    message: str


class ReadinessRead(StrictModel):
    status: str
    checks: list[ReadyCheckRead]


class LimitsRead(StrictModel):
    source_bytes: int
    request_body_bytes: int
    mission_page_size: int
    assistant_context_bytes: int
    assistant_evidence_cards: int
    assistant_candidates: int


class CapabilityManifestRead(StrictModel):
    schema_version: str
    api_version: str
    local_only: bool
    loopback_only: bool
    external_egress: str
    supported_external_providers: list[str]
    identity_boundary: str
    citation_scheme: str
    brief_schema_version: str
    capabilities: list[str]
    unavailable: list[str]
    limits: LimitsRead


def mission_read(value: Mission) -> MissionRead:
    return MissionRead(
        id=value.id,
        title=value.title,
        objective=value.objective,
        created_at=value.created_at,
    )


def question_read(value: Question) -> QuestionRead:
    return QuestionRead(
        id=value.id,
        mission_id=value.mission_id,
        text=value.text,
        created_at=value.created_at,
    )


def claim_read(value: Claim) -> ClaimRead:
    return ClaimRead(
        id=value.id,
        status_reason=value.status_reason,
        status_creator_id=value.status_creator_id,
        status_run_id=value.status_run_id,
        status_changed_at=value.status_changed_at,
        status_evidence_valid=value.status_evidence_valid,
        mission_id=value.mission_id,
        question_id=value.question_id,
        statement=value.statement,
        falsification_criteria=value.falsification_criteria,
        status=value.status,
        version=value.version,
        etag=value.etag,
        created_at=value.created_at,
    )


def snapshot_read(value: SourceSnapshot) -> SourceSnapshotRead:
    return SourceSnapshotRead(
        source_id=value.source_id,
        snapshot_id=value.snapshot_id,
        mission_id=value.mission_id,
        sha256=value.sha256,
        byte_length=value.byte_length,
        encoding=value.encoding,
        media_type=value.media_type,
        original_label=value.original_label,
        url_metadata=value.url_metadata,
        imported_at=value.imported_at,
    )


def evidence_read(value: EvidenceCard) -> EvidenceRead:
    return EvidenceRead(
        id=value.id,
        mission_id=value.mission_id,
        claim_id=value.claim_id,
        snapshot_id=value.snapshot_id,
        start_byte=value.start_byte,
        end_byte=value.end_byte,
        quote=value.quote,
        stance=value.stance,
        supersedes_evidence_id=value.supersedes_evidence_id,
        created_at=value.created_at,
    )


def finding_read(value: Finding) -> FindingRead:
    return FindingRead(
        id=value.id,
        mission_id=value.mission_id,
        claim_id=value.claim_id,
        statement=value.statement,
        statement_kind=value.statement_kind,
        status=value.status,
        uncertainty=value.uncertainty,
        citation_status=value.citation_status,
        evidence_ids=list(value.evidence_ids),
        created_at=value.created_at,
    )
