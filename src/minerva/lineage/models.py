"""Deterministic read models for one claim's provenance lineage graph."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from minerva.assist.models import ModelProvider
from minerva.evidence.models import EvidenceStance
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind

CLAIM_LINEAGE_SCHEMA_VERSION = "minerva.claim-lineage.v1"
CLAIM_LINEAGE_NODE_SET_SCHEMA_VERSION = "minerva.claim-lineage-nodes.v1"
CLAIM_LINEAGE_EDGE_SET_SCHEMA_VERSION = "minerva.claim-lineage-edges.v1"
CLAIM_LINEAGE_SNAPSHOT_SET_SCHEMA_VERSION = "minerva.claim-lineage-snapshots.v1"
CLAIM_LINEAGE_ALGORITHM = "structural-ledger-lineage"
CLAIM_LINEAGE_ALGORITHM_VERSION = "1"
CLAIM_LINEAGE_SCOPE = "claim_owned_closure_v1"


class ClaimLineageNodeKind(StrEnum):
    QUESTION = "question"
    CLAIM = "claim"
    CLAIM_STATUS_EVENT = "claim_status_event"
    SNAPSHOT = "snapshot"
    EVIDENCE = "evidence"
    EVIDENCE_WITHDRAWAL = "evidence_withdrawal"
    FINDING = "finding"
    FINDING_RETRACTION = "finding_retraction"
    AGENT_INFERENCE = "agent_inference"
    AGENT_INFERENCE_RETRACTION = "agent_inference_retraction"
    AGENT_INFERENCE_PROMOTION = "agent_inference_promotion"


class ClaimLineageRelation(StrEnum):
    QUESTION_HAS_CLAIM = "question_has_claim"
    CLAIM_HAS_STATUS_EVENT = "claim_has_status_event"
    STATUS_EVENT_PRECEDES = "status_event_precedes"
    CLAIM_HAS_EVIDENCE = "claim_has_evidence"
    EVIDENCE_CITES_SNAPSHOT = "evidence_cites_snapshot"
    EVIDENCE_SUPERSEDES_EVIDENCE = "evidence_supersedes_evidence"
    EVIDENCE_HAS_WITHDRAWAL = "evidence_has_withdrawal"
    CLAIM_HAS_FINDING = "claim_has_finding"
    FINDING_CITES_EVIDENCE = "finding_cites_evidence"
    FINDING_HAS_RETRACTION = "finding_has_retraction"
    CLAIM_HAS_AGENT_INFERENCE = "claim_has_agent_inference"
    AGENT_INFERENCE_CITES_EVIDENCE = "agent_inference_cites_evidence"
    AGENT_INFERENCE_HAS_RETRACTION = "agent_inference_has_retraction"
    AGENT_INFERENCE_HAS_PROMOTION = "agent_inference_has_promotion"
    PROMOTION_CREATED_FINDING = "promotion_created_finding"


@dataclass(frozen=True, slots=True)
class ClaimLineageBounds:
    max_nodes: int = 1_000
    max_edges: int = 2_000
    max_citation_bytes: int = 16_777_216
    max_snapshot_bytes: int = 16_777_216
    max_output_bytes: int = 67_108_864
    max_sqlite_vm_steps: int = 4_000_000


@dataclass(frozen=True, slots=True)
class LineageProvenance:
    creator_id: str
    run_id: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class QuestionLineageData:
    mission_id: str
    question_text: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class ClaimLineageData:
    mission_id: str
    question_id: str
    statement: str
    falsification_criteria: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class ClaimStatusEventLineageData:
    mission_id: str
    claim_id: str
    version: int
    status: ClaimStatus
    reason: str
    is_current: bool
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class SnapshotLineageData:
    mission_id: str
    source_id: str
    source_kind: str
    source_original_label: str
    source_url_metadata: str | None
    source_provenance: LineageProvenance
    snapshot_sha256: str
    byte_length: int
    encoding: str
    media_type: str
    snapshot_original_label: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class EvidenceLineageData:
    mission_id: str
    claim_id: str
    snapshot_id: str
    snapshot_sha256: str
    start_byte: int
    end_byte: int
    quote: str
    quote_utf8_base64: str
    quote_byte_length: int
    quote_sha256: str
    stance: EvidenceStance
    supersedes_evidence_id: str | None
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class FindingLineageData:
    mission_id: str
    claim_id: str
    statement: str
    statement_kind: StatementKind
    status: FindingStatus
    uncertainty: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class AgentInferenceLineageData:
    mission_id: str
    claim_id: str
    statement: str
    uncertainty: str
    provider: ModelProvider
    model: str
    request_sha256: str
    candidate_index: int
    response_sha256: str
    system_prompt_version: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class CorrectionLineageData:
    mission_id: str
    target_id: str
    reason: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class PromotionLineageData:
    mission_id: str
    inference_id: str
    finding_id: str
    provenance: LineageProvenance


type ClaimLineageNodePayload = (
    QuestionLineageData
    | ClaimLineageData
    | ClaimStatusEventLineageData
    | SnapshotLineageData
    | EvidenceLineageData
    | FindingLineageData
    | AgentInferenceLineageData
    | CorrectionLineageData
    | PromotionLineageData
)


@dataclass(frozen=True, slots=True)
class ClaimLineageNode:
    node_id: str
    kind: ClaimLineageNodeKind
    state: str
    payload: ClaimLineageNodePayload


@dataclass(frozen=True, slots=True)
class ClaimLineageEdge:
    relation: ClaimLineageRelation
    source_node_id: str
    target_node_id: str
    provenance: LineageProvenance


@dataclass(frozen=True, slots=True)
class ClaimLineageKindCount:
    kind: str
    count: int


@dataclass(frozen=True, slots=True)
class ClaimLineageWork:
    node_count: int
    edge_count: int
    status_event_count: int
    evidence_count: int
    finding_count: int
    inference_count: int
    correction_count: int
    promotion_count: int
    citation_edge_count: int
    citation_bytes: int
    distinct_snapshot_count: int
    distinct_snapshot_bytes: int
    graph_payload_bytes: int


@dataclass(frozen=True, slots=True)
class ClaimLineageSemanticBoundary:
    read_only: bool = True
    structural_topology_only: bool = True
    complete_claim_owned_scope: bool = True
    includes_corrected_history: bool = True
    mission_wide: bool = False
    includes_claimless_dependents: bool = False
    determines_truth: bool = False
    calculates_confidence: bool = False
    recommends_or_alters_claim_status: bool = False
    creates_or_changes_research_state: bool = False
    creates_research_queue: bool = False
    writes_audit_event_or_export: bool = False
    modifies_source_or_snapshot_bytes: bool = False
    invokes_model_provider: bool = False
    invokes_network: bool = False
    exposes_external_agent_protocol: bool = False
    requires_separate_human_action_for_corrections: bool = True


@dataclass(frozen=True, slots=True)
class ClaimLineageResult:
    schema_version: str
    kind: str
    algorithm: str
    algorithm_version: str
    scope: str
    completion_policy: str
    complete: bool
    truncated: bool
    mission_id: str
    claim_id: str
    question_id: str
    root_node_id: str
    bounds: ClaimLineageBounds
    work: ClaimLineageWork
    node_kind_counts: tuple[ClaimLineageKindCount, ...]
    edge_kind_counts: tuple[ClaimLineageKindCount, ...]
    nodes: tuple[ClaimLineageNode, ...]
    edges: tuple[ClaimLineageEdge, ...]
    node_set_sha256: str
    edge_set_sha256: str
    snapshot_set_sha256: str
    excluded_record_kinds: tuple[str, ...]
    scope_notice: str
    semantic_notice: str
    semantic_boundary: ClaimLineageSemanticBoundary
    lineage_receipt_sha256: str
