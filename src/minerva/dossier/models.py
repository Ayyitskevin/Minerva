"""Deterministic models for one atomic local review dossier."""

from __future__ import annotations

from dataclasses import dataclass, field

from minerva.lens.models import LensReplayResult, LensSearchResult
from minerva.lineage.models import ClaimLineageBounds, ClaimLineageResult
from minerva.research_queue.models import (
    MissionResearchQueueBounds,
    MissionResearchQueueResult,
)
from minerva.review.models import ClaimReviewResult

REVIEW_DOSSIER_SCHEMA_VERSION = "minerva.review-dossier.v1"
REVIEW_DOSSIER_COMPONENT_SET_SCHEMA_VERSION = "minerva.review-dossier-components.v1"
REVIEW_DOSSIER_ALGORITHM = "current-snapshot-review-composition"
REVIEW_DOSSIER_ALGORITHM_VERSION = "1"
REVIEW_DOSSIER_SCOPE = "mission_claim_with_captured_lens_v1"


@dataclass(frozen=True, slots=True)
class ReviewDossierBounds:
    mission_queue: MissionResearchQueueBounds = field(
        default_factory=lambda: MissionResearchQueueBounds(max_sqlite_vm_steps=4_000_000)
    )
    claim_lineage: ClaimLineageBounds = field(default_factory=ClaimLineageBounds)
    max_output_bytes: int = 134_217_728
    max_sqlite_vm_steps: int = 4_000_000


@dataclass(frozen=True, slots=True)
class ReviewDossierComponentReceipt:
    kind: str
    schema_version: str
    algorithm: str
    algorithm_version: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class ReviewDossierCrossChecks:
    component_missions_match: bool
    focal_claim_is_reviewed_once: bool
    focal_question_matches: bool
    queue_review_receipt_matches: bool
    queue_review_cues_match: bool
    review_lineage_claim_matches: bool
    review_lineage_status_matches: bool
    review_lineage_evidence_matches: bool
    review_lineage_owned_records_match: bool
    shared_snapshot_identities_match: bool
    lens_current_database_exact_match: bool


@dataclass(frozen=True, slots=True)
class ReviewDossierWork:
    component_count: int
    reviewed_claim_count: int
    queue_item_count: int
    claim_review_evidence_card_count: int
    lineage_node_count: int
    lineage_edge_count: int
    lens_searched_snapshot_count: int
    lens_searched_corpus_bytes: int
    lens_result_count: int
    canonical_output_bytes: int


@dataclass(frozen=True, slots=True)
class ReviewDossierSemanticBoundary:
    read_only: bool = True
    composition_only: bool = True
    current_database_snapshot_only: bool = True
    lens_association_is_operator_supplied: bool = True
    lens_candidates_assessed_against_claim: bool = False
    lens_candidates_are_evidence: bool = False
    queue_items_are_tasks: bool = False
    lineage_edges_establish_truth: bool = False
    determines_truth: bool = False
    calculates_confidence: bool = False
    recommends_or_alters_claim_status: bool = False
    creates_or_changes_research_state: bool = False
    writes_audit_event_or_export: bool = False
    modifies_sources_or_snapshots: bool = False
    invokes_model_provider: bool = False
    invokes_network: bool = False
    exposes_external_agent_protocol: bool = False
    requires_separate_human_action: bool = True


@dataclass(frozen=True, slots=True)
class ReviewDossierResult:
    schema_version: str
    kind: str
    algorithm: str
    algorithm_version: str
    scope: str
    completion_policy: str
    complete: bool
    truncated: bool
    lens_retrieval_truncated: bool
    mission_id: str
    claim_id: str
    question_id: str
    bounds: ReviewDossierBounds
    work: ReviewDossierWork
    component_order: tuple[str, ...]
    mission_research_queue: MissionResearchQueueResult
    claim_review: ClaimReviewResult
    claim_lineage: ClaimLineageResult
    lens_search: LensSearchResult
    lens_replay: LensReplayResult
    cross_checks: ReviewDossierCrossChecks
    component_receipts: tuple[ReviewDossierComponentReceipt, ...]
    component_set_sha256: str
    excluded_record_kinds: tuple[str, ...]
    scope_notice: str
    semantic_notice: str
    semantic_boundary: ReviewDossierSemanticBoundary
    dossier_receipt_sha256: str
