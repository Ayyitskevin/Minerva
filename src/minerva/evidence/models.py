"""Evidence card and exact-citation domain objects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EvidenceStance(StrEnum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    CONTEXT = "context"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class EvidenceCard:
    id: str
    mission_id: str
    claim_id: str
    snapshot_id: str
    snapshot_sha256: str
    start_byte: int
    end_byte: int
    quote: str
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    creator_id: str
    run_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    evidence: EvidenceCard
    citation_id: str
    snapshot_sha256: str
    source_label: str
    withdrawn: bool
    withdrawal_reason: str | None
    withdrawn_at: str | None
    withdrawn_by: str | None


@dataclass(frozen=True, slots=True)
class LensCandidateConfirmation:
    """Operator-confirmed coordinates for one captured Lens candidate."""

    rank: int
    snapshot_sha256: str
    start_byte: int
    end_byte: int
    quote_sha256: str


@dataclass(frozen=True, slots=True)
class LensEvidenceAdoptionSemanticBoundary:
    single_candidate_only: bool = True
    receipt_strictly_verified: bool = True
    current_database_exactly_reproduced: bool = True
    candidate_explicitly_confirmed: bool = True
    normal_evidence_validation_applied: bool = True
    creates_one_evidence_card: bool = True
    writes_append_only_audit_history: bool = True
    operator_supplied_stance: bool = True
    lens_search_remains_read_only: bool = True
    rank_used_as_epistemic_weight: bool = False
    performs_bulk_or_automatic_adoption: bool = False
    determines_truth_or_source_quality: bool = False
    calculates_confidence: bool = False
    alters_claim_status: bool = False
    creates_or_retracts_findings: bool = False
    persists_agent_inference: bool = False
    modifies_source_or_snapshot_bytes: bool = False
    invokes_model_provider_or_network: bool = False
    exposes_external_agent_protocol: bool = False


@dataclass(frozen=True, slots=True)
class LensEvidenceAdoptionResult:
    schema_version: str
    kind: str
    status: str
    mission_id: str
    claim_id: str
    retrieval_receipt_sha256: str
    query_sha256: str
    snapshot_set_sha256: str
    candidate_rank: int
    source_id: str
    snapshot_id: str
    snapshot_sha256: str
    start_byte: int
    end_byte: int
    quote_sha256: str
    retrieval_truncated: bool
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    evidence: EvidenceCard
    adoption_audit_event_id: str
    semantic_notice: str
    semantic_boundary: LensEvidenceAdoptionSemanticBoundary
