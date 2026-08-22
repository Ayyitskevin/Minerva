"""Bounded guided-intake receipts and results."""

from __future__ import annotations

from dataclasses import dataclass

from minerva.evidence.models import EvidenceCard, EvidenceStance


@dataclass(frozen=True, slots=True)
class EvidenceIntakeCandidate:
    rank: int
    start_byte: int
    end_byte: int
    quote_sha256: str
    context_start_byte: int
    context_end_byte: int
    context: str


@dataclass(frozen=True, slots=True)
class EvidenceIntakeSemanticBoundary:
    exact_quote_match_only: bool = True
    immutable_snapshot_verified: bool = True
    single_evidence_card_only: bool = True
    operator_supplied_stance: bool = True
    append_only_audit_required: bool = True
    determines_truth_or_confidence: bool = False
    infers_stance: bool = False
    performs_fuzzy_or_model_matching: bool = False
    imports_or_modifies_sources: bool = False
    invokes_provider_or_network: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceIntakePreview:
    schema_version: str
    kind: str
    algorithm: str
    algorithm_version: int
    mission_id: str
    claim_id: str
    source_id: str
    snapshot_id: str
    snapshot_sha256: str
    snapshot_byte_length: int
    quote: str
    quote_sha256: str
    mission_audit_sequence: int
    candidate_count: int
    candidates: tuple[EvidenceIntakeCandidate, ...]
    intake_preview_sha256: str
    semantic_notice: str
    semantic_boundary: EvidenceIntakeSemanticBoundary


@dataclass(frozen=True, slots=True)
class EvidenceIntakeResult:
    schema_version: str
    kind: str
    status: str
    mission_id: str
    claim_id: str
    snapshot_id: str
    snapshot_sha256: str
    intake_preview_sha256: str
    candidate_rank: int
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    evidence: EvidenceCard
    creation_audit_event_id: str
    semantic_notice: str
    semantic_boundary: EvidenceIntakeSemanticBoundary
