"""Deterministic read models for the mission research review index."""

from __future__ import annotations

from dataclasses import dataclass

from minerva.research.models import ClaimStatus
from minerva.review.models import ClaimReviewBounds

MISSION_RESEARCH_QUEUE_SCHEMA_VERSION = "minerva.mission-research-queue.v1"
MISSION_RESEARCH_QUEUE_CLAIM_SET_SCHEMA_VERSION = "minerva.mission-research-queue-claims.v1"
MISSION_RESEARCH_QUEUE_REVIEW_SET_SCHEMA_VERSION = "minerva.mission-research-queue-claim-reviews.v1"
MISSION_RESEARCH_QUEUE_ITEM_SET_SCHEMA_VERSION = "minerva.mission-research-queue-items.v1"
MISSION_RESEARCH_QUEUE_ALGORITHM = "claim-review-cue-aggregation"
MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION = "1"
MISSION_RESEARCH_QUEUE_SCOPE = "mission_claim_review_cues_v1"


@dataclass(frozen=True, slots=True)
class MissionResearchQueueBounds:
    max_claims: int = 100
    max_items: int = 1_400
    max_evidence_cards: int = 5_000
    max_distinct_evidence_quote_bytes: int = 67_108_864
    max_affected_records: int = 10_000
    max_relationships: int = 50_000
    max_distinct_snapshot_bytes: int = 67_108_864
    max_output_bytes: int = 67_108_864
    max_sqlite_vm_steps: int = 8_000_000


@dataclass(frozen=True, slots=True)
class MissionResearchQueueReason:
    catalog_position: int
    code: str
    category: str
    explanation: str


@dataclass(frozen=True, slots=True)
class MissionResearchQueueReasonCount:
    code: str
    count: int


@dataclass(frozen=True, slots=True)
class MissionResearchQueueReviewedClaim:
    sequence: int
    claim_id: str
    question_id: str
    claim_statement: str
    recorded_status: ClaimStatus
    recorded_status_version: int
    claim_created_at: str
    reason_codes: tuple[str, ...]
    item_count: int
    review_receipt_sha256: str


@dataclass(frozen=True, slots=True)
class MissionResearchQueueItem:
    sequence: int
    kind: str
    claim_id: str
    question_id: str
    reason_code: str
    reason_category: str
    explanation: str
    record_ids: tuple[str, ...]
    source_review_receipt_sha256: str


@dataclass(frozen=True, slots=True)
class MissionResearchQueueWork:
    reviewed_claim_count: int
    item_count: int
    evidence_card_count: int
    distinct_evidence_quote_bytes: int
    affected_finding_count: int
    affected_inference_count: int
    affected_record_count: int
    citation_relationship_count: int
    distinct_snapshot_count: int
    distinct_snapshot_bytes: int
    canonical_output_bytes: int


@dataclass(frozen=True, slots=True)
class MissionResearchQueueSemanticBoundary:
    read_only: bool = True
    structural_review_index_only: bool = True
    current_claim_review_taxonomy_guarantees_a_cue: bool = True
    item_presence_means_action_required: bool = False
    item_presence_means_open_or_unresolved: bool = False
    item_order_is_priority_or_severity: bool = False
    assigns_work: bool = False
    records_completion_or_deferral: bool = False
    determines_truth: bool = False
    calculates_confidence: bool = False
    recommends_or_alters_claim_status: bool = False
    creates_or_changes_research_state: bool = False
    writes_audit_event_or_export: bool = False
    modifies_source_or_snapshot_bytes: bool = False
    invokes_claim_lineage: bool = False
    invokes_model_provider: bool = False
    invokes_network: bool = False
    exposes_external_agent_protocol: bool = False


@dataclass(frozen=True, slots=True)
class MissionResearchQueueResult:
    schema_version: str
    kind: str
    algorithm: str
    algorithm_version: str
    scope: str
    completion_policy: str
    complete: bool
    truncated: bool
    mission_id: str
    mission_title: str
    mission_objective: str
    mission_creator_id: str
    mission_run_id: str
    mission_created_at: str
    claim_review_schema_version: str
    claim_review_algorithm: str
    claim_review_algorithm_version: str
    claim_review_bounds: ClaimReviewBounds
    bounds: MissionResearchQueueBounds
    work: MissionResearchQueueWork
    ordering: tuple[str, ...]
    sequence_semantics: str
    reason_catalog: tuple[MissionResearchQueueReason, ...]
    reason_counts: tuple[MissionResearchQueueReasonCount, ...]
    reviewed_claims: tuple[MissionResearchQueueReviewedClaim, ...]
    items: tuple[MissionResearchQueueItem, ...]
    claim_set_sha256: str
    claim_review_set_sha256: str
    item_set_sha256: str
    excluded_record_kinds: tuple[str, ...]
    scope_notice: str
    semantic_notice: str
    semantic_boundary: MissionResearchQueueSemanticBoundary
    queue_receipt_sha256: str
