"""Deterministic read models for claim gaps and correction impacts."""

from __future__ import annotations

from dataclasses import dataclass

from minerva.assist.models import ModelProvider
from minerva.evidence.models import EvidenceStance
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind

CLAIM_REVIEW_SCHEMA_VERSION = "minerva.claim-review.v1"
CLAIM_REVIEW_ALGORITHM = "structural-ledger-review"
CLAIM_REVIEW_ALGORITHM_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ClaimReviewBounds:
    max_evidence_cards: int = 200
    max_affected_records: int = 200
    max_relationships: int = 2_000
    max_snapshot_bytes: int = 16_777_216
    max_sqlite_vm_steps: int = 4_000_000


@dataclass(frozen=True, slots=True)
class CorrectionRecord:
    id: str
    reason: str
    creator_id: str
    run_id: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StanceCounts:
    supports: int
    opposes: int
    context: int
    inconclusive: int
    total: int


@dataclass(frozen=True, slots=True)
class ClaimStatusSnapshot:
    status: ClaimStatus
    version: int
    reason: str
    creator_id: str
    run_id: str
    changed_at: str
    required_active_stances: tuple[EvidenceStance, ...]
    missing_required_active_stances: tuple[EvidenceStance, ...]
    evidence_valid: bool


@dataclass(frozen=True, slots=True)
class ClaimEvidenceReference:
    evidence_id: str
    source_id: str
    source_label: str
    snapshot_id: str
    snapshot_sha256: str
    media_type: str
    start_byte: int
    end_byte: int
    quote_byte_length: int
    quote_sha256: str
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    creator_id: str
    run_id: str
    created_at: str
    withdrawal: CorrectionRecord | None


@dataclass(frozen=True, slots=True)
class AffectedFinding:
    finding_id: str
    claim_id: str | None
    statement: str
    statement_kind: StatementKind
    status: FindingStatus
    uncertainty: str
    evidence_ids: tuple[str, ...]
    target_evidence_ids: tuple[str, ...]
    withdrawn_evidence_ids: tuple[str, ...]
    withdrawn_target_evidence_ids: tuple[str, ...]
    material: bool
    effect_codes: tuple[str, ...]
    creator_id: str
    run_id: str
    created_at: str
    retraction: CorrectionRecord | None


@dataclass(frozen=True, slots=True)
class InferencePromotionRecord:
    id: str
    finding_id: str
    creator_id: str
    run_id: str
    created_at: str
    finding_retracted: bool


@dataclass(frozen=True, slots=True)
class AffectedInference:
    inference_id: str
    claim_id: str
    statement: str
    uncertainty: str
    provider: ModelProvider
    model: str
    evidence_ids: tuple[str, ...]
    withdrawn_evidence_ids: tuple[str, ...]
    active_citation_policy_satisfied: bool
    effect_codes: tuple[str, ...]
    promotion: InferencePromotionRecord | None
    creator_id: str
    run_id: str
    created_at: str
    retraction: CorrectionRecord | None


@dataclass(frozen=True, slots=True)
class EvidenceWithdrawalImpact:
    evidence_id: str
    withdrawal_id: str
    stance: EvidenceStance
    effect_codes: tuple[str, ...]
    active_material_finding_ids: tuple[str, ...]
    active_optional_finding_ids: tuple[str, ...]
    retracted_finding_ids: tuple[str, ...]
    active_inference_ids: tuple[str, ...]
    retracted_inference_ids: tuple[str, ...]
    direct_superseding_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimReviewCue:
    code: str
    explanation: str
    record_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimReviewWork:
    evidence_card_count: int
    affected_finding_count: int
    affected_inference_count: int
    citation_relationship_count: int
    distinct_snapshot_count: int
    distinct_snapshot_bytes: int


@dataclass(frozen=True, slots=True)
class ClaimReviewSemanticBoundary:
    read_only: bool = True
    structural_observations_only: bool = True
    determines_truth: bool = False
    calculates_confidence: bool = False
    recommends_claim_status: bool = False
    alters_claim_status: bool = False
    creates_or_withdraws_evidence: bool = False
    creates_or_retracts_findings: bool = False
    creates_retracts_or_promotes_inferences: bool = False
    creates_research_queue: bool = False
    writes_audit_event: bool = False
    invokes_model_provider: bool = False
    invokes_network: bool = False
    requires_separate_human_correction: bool = True


@dataclass(frozen=True, slots=True)
class ClaimReviewResult:
    schema_version: str
    kind: str
    algorithm: str
    algorithm_version: str
    completion_policy: str
    complete: bool
    truncated: bool
    mission_id: str
    claim_id: str
    question_id: str
    claim_statement: str
    falsification_criteria: str
    claim_creator_id: str
    claim_run_id: str
    claim_created_at: str
    recorded_status: ClaimStatusSnapshot
    active_stance_counts: StanceCounts
    withdrawn_stance_counts: StanceCounts
    active_support_and_opposition_present: bool
    gap_codes: tuple[str, ...]
    impact_codes: tuple[str, ...]
    bounds: ClaimReviewBounds
    work: ClaimReviewWork
    evidence: tuple[ClaimEvidenceReference, ...]
    affected_findings: tuple[AffectedFinding, ...]
    affected_inferences: tuple[AffectedInference, ...]
    withdrawal_impacts: tuple[EvidenceWithdrawalImpact, ...]
    review_cues: tuple[ClaimReviewCue, ...]
    semantic_notice: str
    semantic_boundary: ClaimReviewSemanticBoundary
    review_receipt_sha256: str
