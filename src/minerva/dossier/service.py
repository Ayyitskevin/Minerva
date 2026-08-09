"""Atomic composition of existing deterministic review receipts."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, fields, replace
from hashlib import sha256
from typing import Any, Never, cast

from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.dossier.models import (
    REVIEW_DOSSIER_ALGORITHM,
    REVIEW_DOSSIER_ALGORITHM_VERSION,
    REVIEW_DOSSIER_COMPONENT_SET_SCHEMA_VERSION,
    REVIEW_DOSSIER_SCHEMA_VERSION,
    REVIEW_DOSSIER_SCOPE,
    ReviewDossierBounds,
    ReviewDossierComponentReceipt,
    ReviewDossierCrossChecks,
    ReviewDossierResult,
    ReviewDossierSemanticBoundary,
    ReviewDossierWork,
)
from minerva.lens.models import (
    LENS_ALGORITHM,
    LENS_ALGORITHM_VERSION,
    LENS_REPLAY_SCHEMA_VERSION,
    LENS_RESULT_KIND,
    LENS_SCHEMA_VERSION,
    LensReceiptCheckBoundary,
    LensReplayResult,
    LensSearchResult,
)
from minerva.lens.receipt import (
    _replay_lens_receipt_in_snapshot,
    verify_lens_receipt,
)
from minerva.lens.service import LensService
from minerva.lineage.models import (
    CLAIM_LINEAGE_ALGORITHM,
    CLAIM_LINEAGE_ALGORITHM_VERSION,
    CLAIM_LINEAGE_SCHEMA_VERSION,
    CLAIM_LINEAGE_SCOPE,
    AgentInferenceLineageData,
    ClaimLineageData,
    ClaimLineageNodeKind,
    ClaimLineageRelation,
    ClaimLineageResult,
    ClaimStatusEventLineageData,
    CorrectionLineageData,
    EvidenceLineageData,
    FindingLineageData,
    PromotionLineageData,
    SnapshotLineageData,
)
from minerva.lineage.service import (
    ClaimLineageService,
    _lineage_receipt_digest,
)
from minerva.lineage.service import (
    _validate_bounds as _validate_lineage_bounds,
)
from minerva.research_queue.models import (
    MISSION_RESEARCH_QUEUE_ALGORITHM,
    MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION,
    MISSION_RESEARCH_QUEUE_SCHEMA_VERSION,
    MISSION_RESEARCH_QUEUE_SCOPE,
    MissionResearchQueueResult,
)
from minerva.research_queue.service import (
    MissionResearchQueueService,
    _claim_review_receipt_digest,
    _queue_receipt_digest,
)
from minerva.research_queue.service import (
    _validate_bounds as _validate_queue_bounds,
)
from minerva.review.models import (
    CLAIM_REVIEW_ALGORITHM,
    CLAIM_REVIEW_ALGORITHM_VERSION,
    CLAIM_REVIEW_SCHEMA_VERSION,
    AffectedFinding,
    AffectedInference,
    ClaimEvidenceReference,
    ClaimReviewResult,
    CorrectionRecord,
    InferencePromotionRecord,
)

DEFAULT_REVIEW_DOSSIER_BOUNDS = ReviewDossierBounds()

_MAX_OUTPUT_BYTES = 134_217_728
_MIN_SQLITE_VM_STEPS = 1_000
_MAX_SQLITE_VM_STEPS = 16_000_000
_QUERY_PROGRESS_GRANULARITY = 1_000
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")
_COMPONENT_ORDER = (
    "mission_research_queue",
    "claim_review",
    "claim_lineage",
    "lens_search",
    "lens_replay",
)
_COMPLETION_POLICY = "complete_or_refuse"
_MISSION_QUEUE_KIND = "mission_research_queue"
_CLAIM_REVIEW_KIND = "evidence_gap_and_retraction_impact"
_CLAIM_LINEAGE_KIND = "claim_lineage_graph"
_LENS_REPLAY_KIND = "current_database_exact_reproduction"
_LENS_REPLAY_STATUS = "reproduced"
_EXCLUDED_RECORD_KINDS = (
    "foreign_mission_records",
    "sibling_claim_full_reviews_and_lineage",
    "claimless_lineage_nodes",
    "reverse_dependents_outside_claim_review_scope",
    "unreferenced_snapshots",
    "nonmatching_lens_passages",
    "audit_events",
    "research_runs",
    "brief_exports",
    "ephemeral_assistance_candidates",
    "external_agent_protocols",
)


class ReviewDossierService:
    """Compose review views inside one query-only SQLite snapshot."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def build_dossier(
        self,
        *,
        mission_id: str,
        claim_id: str,
        lens_receipt: LensSearchResult,
        bounds: ReviewDossierBounds = DEFAULT_REVIEW_DOSSIER_BOUNDS,
    ) -> ReviewDossierResult:
        safe_bounds = _validate_bounds(bounds)
        _validate_scope(mission_id=mission_id, claim_id=claim_id)
        verified_lens = verify_lens_receipt(lens_receipt)
        if verified_lens.mission_id != mission_id:
            _raise_scope_invalid()

        try:
            with self.database.read() as connection:
                connection.execute("PRAGMA query_only = ON")
                with _bounded_query_work(connection, safe_bounds.max_sqlite_vm_steps):
                    lens_replay = _replay_lens_receipt_in_snapshot(
                        LensService(self.database),
                        verified_lens,
                        connection=connection,
                    )
                    mission_queue, claim_review = MissionResearchQueueService(
                        self.database
                    )._build_queue_in_snapshot(
                        mission_id=mission_id,
                        bounds=safe_bounds.mission_queue,
                        connection=connection,
                        focal_claim_id=claim_id,
                    )
                    if claim_review is None:
                        _raise_scope_invalid()
                    claim_lineage = ClaimLineageService(self.database)._build_graph_in_snapshot(
                        mission_id=mission_id,
                        claim_id=claim_id,
                        bounds=safe_bounds.claim_lineage,
                        connection=connection,
                    )
        except (IntegrityError, NotFoundError):
            raise
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise IntegrityError(
                "review_dossier_inconsistent",
                "The local review dossier components are inconsistent.",
            ) from error

        cross_checks = _cross_checks(
            mission_id=mission_id,
            claim_id=claim_id,
            mission_queue=mission_queue,
            claim_review=claim_review,
            claim_lineage=claim_lineage,
            lens_search=verified_lens,
            lens_replay=lens_replay,
        )
        if not all(getattr(cross_checks, field.name) for field in fields(cross_checks)):
            _raise_inconsistent()

        component_receipts = _component_receipts(
            mission_queue=mission_queue,
            claim_review=claim_review,
            claim_lineage=claim_lineage,
            lens_search=verified_lens,
            lens_replay=lens_replay,
        )
        component_set_sha256 = _component_set_digest(
            mission_id=mission_id,
            claim_id=claim_id,
            component_receipts=component_receipts,
        )
        work = ReviewDossierWork(
            component_count=len(component_receipts),
            reviewed_claim_count=mission_queue.work.reviewed_claim_count,
            queue_item_count=mission_queue.work.item_count,
            claim_review_evidence_card_count=claim_review.work.evidence_card_count,
            lineage_node_count=claim_lineage.work.node_count,
            lineage_edge_count=claim_lineage.work.edge_count,
            lens_searched_snapshot_count=verified_lens.searched_snapshot_count,
            lens_searched_corpus_bytes=verified_lens.searched_corpus_bytes,
            lens_result_count=verified_lens.result_count,
            canonical_output_bytes=0,
        )
        provisional = ReviewDossierResult(
            schema_version=REVIEW_DOSSIER_SCHEMA_VERSION,
            kind="review_dossier",
            algorithm=REVIEW_DOSSIER_ALGORITHM,
            algorithm_version=REVIEW_DOSSIER_ALGORITHM_VERSION,
            scope=REVIEW_DOSSIER_SCOPE,
            completion_policy="complete_or_refuse",
            complete=True,
            truncated=False,
            lens_retrieval_truncated=verified_lens.truncated,
            mission_id=mission_id,
            claim_id=claim_id,
            question_id=claim_review.question_id,
            bounds=safe_bounds,
            work=work,
            component_order=_COMPONENT_ORDER,
            mission_research_queue=mission_queue,
            claim_review=claim_review,
            claim_lineage=claim_lineage,
            lens_search=verified_lens,
            lens_replay=lens_replay,
            cross_checks=cross_checks,
            component_receipts=component_receipts,
            component_set_sha256=component_set_sha256,
            excluded_record_kinds=_EXCLUDED_RECORD_KINDS,
            scope_notice=(
                "This dossier composes one complete mission review index, its retained "
                "focal Claim Review, the focal claim-owned lineage, and one operator-"
                "supplied Lens receipt reproduced against the same current read snapshot."
            ),
            semantic_notice=(
                "Composition does not make queue cues actionable or connect Lens candidates "
                "to the claim. Lens candidates remain unassessed leads, not evidence; "
                "correction or adoption requires a separate audited human operation."
            ),
            semantic_boundary=ReviewDossierSemanticBoundary(),
            dossier_receipt_sha256="",
        )
        result = _finalize_output_size(provisional)
        if result.work.canonical_output_bytes > safe_bounds.max_output_bytes:
            _raise_work_limit()
        return replace(
            result,
            dossier_receipt_sha256=_dossier_receipt_digest(result),
        )


def _validate_bounds(bounds: ReviewDossierBounds) -> ReviewDossierBounds:
    if not isinstance(bounds, ReviewDossierBounds):
        _raise_bounds_invalid()
    try:
        queue_bounds = _validate_queue_bounds(bounds.mission_queue)
        lineage_bounds = _validate_lineage_bounds(bounds.claim_lineage)
    except IntegrityError as error:
        raise IntegrityError(
            "review_dossier_bounds_invalid",
            "Review dossier bounds are invalid.",
        ) from error
    if (
        isinstance(bounds.max_output_bytes, bool)
        or not isinstance(bounds.max_output_bytes, int)
        or isinstance(bounds.max_sqlite_vm_steps, bool)
        or not isinstance(bounds.max_sqlite_vm_steps, int)
        or not 1 <= bounds.max_output_bytes <= _MAX_OUTPUT_BYTES
        or not _MIN_SQLITE_VM_STEPS <= bounds.max_sqlite_vm_steps <= _MAX_SQLITE_VM_STEPS
        or queue_bounds.max_sqlite_vm_steps != bounds.max_sqlite_vm_steps
        or lineage_bounds.max_sqlite_vm_steps != bounds.max_sqlite_vm_steps
    ):
        _raise_bounds_invalid()
    return bounds


def _validate_scope(*, mission_id: object, claim_id: object) -> None:
    if not isinstance(mission_id, str) or _MISSION_ID.fullmatch(mission_id) is None:
        raise NotFoundError("mission_not_found")
    if not isinstance(claim_id, str) or _CLAIM_ID.fullmatch(claim_id) is None:
        _raise_scope_invalid()


def _cross_checks(
    *,
    mission_id: str,
    claim_id: str,
    mission_queue: MissionResearchQueueResult,
    claim_review: ClaimReviewResult,
    claim_lineage: ClaimLineageResult,
    lens_search: LensSearchResult,
    lens_replay: LensReplayResult,
) -> ReviewDossierCrossChecks:
    summaries = tuple(item for item in mission_queue.reviewed_claims if item.claim_id == claim_id)
    summary = summaries[0] if len(summaries) == 1 else None
    selected_items = tuple(item for item in mission_queue.items if item.claim_id == claim_id)
    reason_by_code = {item.code: item for item in mission_queue.reason_catalog}
    expected_items = tuple(
        (
            cue.code,
            reason_by_code[cue.code].category if cue.code in reason_by_code else None,
            cue.explanation,
            cue.record_ids,
            claim_review.review_receipt_sha256,
        )
        for cue in claim_review.review_cues
    )
    actual_items = tuple(
        (
            item.reason_code,
            item.reason_category,
            item.explanation,
            item.record_ids,
            item.source_review_receipt_sha256,
        )
        for item in selected_items
    )
    queue_review_receipt_matches = bool(
        summary is not None
        and summary.review_receipt_sha256 == claim_review.review_receipt_sha256
        and _claim_review_receipt_digest(claim_review) == claim_review.review_receipt_sha256
    )
    queue_review_cues_match = bool(
        summary is not None
        and summary.reason_codes == claim_review.gap_codes + claim_review.impact_codes
        and summary.item_count == len(claim_review.review_cues)
        and actual_items == expected_items
    )
    summary_matches = bool(
        summary is not None
        and summary.question_id == claim_review.question_id
        and summary.claim_statement == claim_review.claim_statement
        and summary.recorded_status == claim_review.recorded_status.status
        and summary.recorded_status_version == claim_review.recorded_status.version
        and summary.claim_created_at == claim_review.claim_created_at
    )
    claim_matches, status_matches = _review_lineage_claim_status_matches(
        claim_review,
        claim_lineage,
        expected_claim_id=claim_id,
    )
    claim_node_ids = tuple(
        node.node_id for node in claim_lineage.nodes if node.kind is ClaimLineageNodeKind.CLAIM
    )
    focal_identifiers_match = (
        claim_review.claim_id == claim_id
        and claim_lineage.claim_id == claim_id
        and claim_lineage.root_node_id == claim_id
        and claim_node_ids == (claim_id,)
    )
    evidence_matches = _review_lineage_evidence_matches(claim_review, claim_lineage)
    owned_records_match = _review_lineage_owned_records_match(claim_review, claim_lineage)
    return ReviewDossierCrossChecks(
        component_missions_match=(
            mission_queue.mission_id
            == claim_review.mission_id
            == claim_lineage.mission_id
            == lens_search.mission_id
            == mission_id
        ),
        focal_claim_is_reviewed_once=(
            len(summaries) == 1 and summary_matches and focal_identifiers_match
        ),
        focal_question_matches=(
            claim_review.question_id == claim_lineage.question_id
            and (summary is not None and summary.question_id == claim_lineage.question_id)
        ),
        queue_review_receipt_matches=queue_review_receipt_matches,
        queue_review_cues_match=queue_review_cues_match,
        review_lineage_claim_matches=claim_matches,
        review_lineage_status_matches=status_matches,
        review_lineage_evidence_matches=evidence_matches,
        review_lineage_owned_records_match=owned_records_match,
        shared_snapshot_identities_match=_shared_snapshot_identities_match(
            claim_lineage,
            lens_search,
        ),
        lens_current_database_exact_match=(
            lens_replay.schema_version == LENS_REPLAY_SCHEMA_VERSION
            and lens_replay.kind == _LENS_REPLAY_KIND
            and lens_replay.status == _LENS_REPLAY_STATUS
            and lens_replay.receipt_schema_version == lens_search.schema_version
            and lens_replay.algorithm == lens_search.algorithm
            and lens_replay.algorithm_version == lens_search.algorithm_version
            and lens_replay.unicode_database_version == lens_search.unicode_database_version
            and lens_replay.query_sha256 == lens_search.query_sha256
            and lens_replay.snapshot_set_sha256 == lens_search.snapshot_set_sha256
            and lens_replay.searched_snapshot_count == lens_search.searched_snapshot_count
            and lens_replay.result_count == lens_search.result_count
            and lens_replay.exact_receipt_match
            and lens_replay.current_database_snapshot_matched
            and not lens_replay.historical_corpus_replay
            and lens_replay.searched_snapshot_content_verified
            and lens_replay.semantic_boundary
            == LensReceiptCheckBoundary(reads_research_database=True)
            and lens_replay.retrieval_receipt_sha256 == lens_search.retrieval_receipt_sha256
        ),
    )


def _review_lineage_claim_status_matches(
    review: ClaimReviewResult,
    lineage: ClaimLineageResult,
    *,
    expected_claim_id: str,
) -> tuple[bool, bool]:
    claim_nodes = tuple(
        node
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.CLAIM and isinstance(node.payload, ClaimLineageData)
    )
    status_payloads = tuple(
        node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.CLAIM_STATUS_EVENT
        and isinstance(node.payload, ClaimStatusEventLineageData)
        and node.payload.is_current
    )
    claim_node = claim_nodes[0] if len(claim_nodes) == 1 else None
    claim_payload = cast(ClaimLineageData, claim_node.payload) if claim_node is not None else None
    status_payload = status_payloads[0] if len(status_payloads) == 1 else None
    claim_matches = bool(
        claim_node is not None
        and claim_node.node_id == expected_claim_id
        and review.claim_id == expected_claim_id
        and lineage.claim_id == expected_claim_id
        and lineage.root_node_id == expected_claim_id
        and claim_payload is not None
        and claim_payload.mission_id == review.mission_id
        and claim_payload.question_id == review.question_id
        and claim_payload.statement == review.claim_statement
        and claim_payload.falsification_criteria == review.falsification_criteria
        and claim_payload.provenance.creator_id == review.claim_creator_id
        and claim_payload.provenance.run_id == review.claim_run_id
        and claim_payload.provenance.recorded_at == review.claim_created_at
    )
    status_matches = bool(
        status_payload is not None
        and status_payload.mission_id == review.mission_id
        and status_payload.claim_id == review.claim_id
        and status_payload.version == review.recorded_status.version
        and status_payload.status == review.recorded_status.status
        and status_payload.reason == review.recorded_status.reason
        and status_payload.provenance.creator_id == review.recorded_status.creator_id
        and status_payload.provenance.run_id == review.recorded_status.run_id
        and status_payload.provenance.recorded_at == review.recorded_status.changed_at
    )
    return claim_matches, status_matches


def _review_lineage_evidence_matches(
    review: ClaimReviewResult,
    lineage: ClaimLineageResult,
) -> bool:
    evidence_nodes = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.EVIDENCE
        and isinstance(node.payload, EvidenceLineageData)
    }
    snapshot_nodes = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.SNAPSHOT
        and isinstance(node.payload, SnapshotLineageData)
    }
    withdrawal_nodes = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.EVIDENCE_WITHDRAWAL
        and isinstance(node.payload, CorrectionLineageData)
    }
    return all(
        _evidence_matches_lineage(
            item,
            mission_id=review.mission_id,
            claim_id=review.claim_id,
            evidence_nodes=evidence_nodes,
            snapshot_nodes=snapshot_nodes,
            withdrawal_nodes=withdrawal_nodes,
        )
        for item in review.evidence
    ) and set(evidence_nodes) == {item.evidence_id for item in review.evidence}


def _evidence_matches_lineage(
    item: ClaimEvidenceReference,
    *,
    mission_id: str,
    claim_id: str,
    evidence_nodes: dict[str, EvidenceLineageData],
    snapshot_nodes: dict[str, SnapshotLineageData],
    withdrawal_nodes: dict[str, CorrectionLineageData],
) -> bool:
    evidence = evidence_nodes.get(item.evidence_id)
    snapshot = snapshot_nodes.get(item.snapshot_id)
    if evidence is None or snapshot is None:
        return False
    base_matches = (
        evidence.mission_id == mission_id
        and evidence.claim_id == claim_id
        and evidence.snapshot_id == item.snapshot_id
        and evidence.snapshot_sha256 == item.snapshot_sha256
        and evidence.start_byte == item.start_byte
        and evidence.end_byte == item.end_byte
        and evidence.quote_byte_length == item.quote_byte_length
        and evidence.quote_sha256 == item.quote_sha256
        and evidence.stance == item.stance
        and evidence.supersedes_evidence_id == item.supersedes_evidence_id
        and evidence.provenance.creator_id == item.creator_id
        and evidence.provenance.run_id == item.run_id
        and evidence.provenance.recorded_at == item.created_at
        and snapshot.source_id == item.source_id
        and snapshot.source_original_label == item.source_label
        and snapshot.snapshot_sha256 == item.snapshot_sha256
        and snapshot.media_type == item.media_type
    )
    if not base_matches:
        return False
    if item.withdrawal is None:
        return not any(
            payload.target_id == item.evidence_id for payload in withdrawal_nodes.values()
        )
    withdrawal = withdrawal_nodes.get(item.withdrawal.id)
    return bool(
        withdrawal is not None
        and withdrawal.target_id == item.evidence_id
        and withdrawal.reason == item.withdrawal.reason
        and withdrawal.provenance.creator_id == item.withdrawal.creator_id
        and withdrawal.provenance.run_id == item.withdrawal.run_id
        and withdrawal.provenance.recorded_at == item.withdrawal.created_at
    )


def _review_lineage_owned_records_match(
    review: ClaimReviewResult,
    lineage: ClaimLineageResult,
) -> bool:
    finding_nodes = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.FINDING
        and isinstance(node.payload, FindingLineageData)
    }
    finding_states = {
        node.node_id: node.state
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.FINDING
    }
    inference_nodes = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.AGENT_INFERENCE
        and isinstance(node.payload, AgentInferenceLineageData)
    }
    finding_retractions = {
        node.payload.target_id: (node.node_id, node.payload)
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.FINDING_RETRACTION
        and isinstance(node.payload, CorrectionLineageData)
    }
    inference_retractions = {
        node.payload.target_id: (node.node_id, node.payload)
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.AGENT_INFERENCE_RETRACTION
        and isinstance(node.payload, CorrectionLineageData)
    }
    promotions = {
        node.payload.inference_id: (node.node_id, node.payload)
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.AGENT_INFERENCE_PROMOTION
        and isinstance(node.payload, PromotionLineageData)
    }
    finding_citations = _edge_targets(
        lineage,
        relation=ClaimLineageRelation.FINDING_CITES_EVIDENCE,
    )
    inference_citations = _edge_targets(
        lineage,
        relation=ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE,
    )
    owned_findings = tuple(
        item for item in review.affected_findings if item.claim_id == review.claim_id
    )
    owned_inferences = tuple(
        item for item in review.affected_inferences if item.claim_id == review.claim_id
    )
    return all(
        _finding_matches(
            item,
            finding_nodes.get(item.finding_id),
            citations=finding_citations.get(item.finding_id, ()),
            retraction=finding_retractions.get(item.finding_id),
        )
        for item in owned_findings
    ) and all(
        _inference_matches(
            item,
            inference_nodes.get(item.inference_id),
            citations=inference_citations.get(item.inference_id, ()),
            retraction=inference_retractions.get(item.inference_id),
            promotion=promotions.get(item.inference_id),
            finding_states=finding_states,
        )
        for item in owned_inferences
    )


def _edge_targets(
    lineage: ClaimLineageResult,
    *,
    relation: ClaimLineageRelation,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for edge in lineage.edges:
        if edge.relation is relation:
            result.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    return {owner_id: tuple(sorted(targets)) for owner_id, targets in result.items()}


def _finding_matches(
    item: AffectedFinding,
    payload: FindingLineageData | None,
    *,
    citations: tuple[str, ...],
    retraction: tuple[str, CorrectionLineageData] | None,
) -> bool:
    return bool(
        payload is not None
        and payload.claim_id == item.claim_id
        and payload.statement == item.statement
        and payload.statement_kind == item.statement_kind
        and payload.status == item.status
        and payload.uncertainty == item.uncertainty
        and payload.provenance.creator_id == item.creator_id
        and payload.provenance.run_id == item.run_id
        and payload.provenance.recorded_at == item.created_at
        and citations == tuple(sorted(item.evidence_ids))
        and _correction_matches(item.retraction, retraction)
    )


def _inference_matches(
    item: AffectedInference,
    payload: AgentInferenceLineageData | None,
    *,
    citations: tuple[str, ...],
    retraction: tuple[str, CorrectionLineageData] | None,
    promotion: tuple[str, PromotionLineageData] | None,
    finding_states: dict[str, str],
) -> bool:
    return bool(
        payload is not None
        and payload.claim_id == item.claim_id
        and payload.statement == item.statement
        and payload.uncertainty == item.uncertainty
        and payload.provider == item.provider
        and payload.model == item.model
        and payload.provenance.creator_id == item.creator_id
        and payload.provenance.run_id == item.run_id
        and payload.provenance.recorded_at == item.created_at
        and citations == tuple(sorted(item.evidence_ids))
        and _correction_matches(item.retraction, retraction)
        and _promotion_matches(item.promotion, promotion, finding_states=finding_states)
    )


def _correction_matches(
    expected: CorrectionRecord | None,
    actual: tuple[str, CorrectionLineageData] | None,
) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    node_id, payload = actual
    return (
        node_id == expected.id
        and payload.reason == expected.reason
        and payload.provenance.creator_id == expected.creator_id
        and payload.provenance.run_id == expected.run_id
        and payload.provenance.recorded_at == expected.created_at
    )


def _promotion_matches(
    expected: InferencePromotionRecord | None,
    actual: tuple[str, PromotionLineageData] | None,
    *,
    finding_states: dict[str, str],
) -> bool:
    if expected is None:
        return actual is None
    if actual is None:
        return False
    node_id, payload = actual
    return (
        node_id == expected.id
        and payload.inference_id is not None
        and payload.finding_id == expected.finding_id
        and payload.provenance.creator_id == expected.creator_id
        and payload.provenance.run_id == expected.run_id
        and payload.provenance.recorded_at == expected.created_at
        and expected.finding_retracted == (finding_states.get(expected.finding_id) == "retracted")
    )


def _shared_snapshot_identities_match(
    lineage: ClaimLineageResult,
    lens: LensSearchResult,
) -> bool:
    lineage_snapshots = {
        node.node_id: node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.SNAPSHOT
        and isinstance(node.payload, SnapshotLineageData)
    }
    for snapshot in lens.searched_snapshots:
        lineage_snapshot = lineage_snapshots.get(snapshot.snapshot_id)
        if lineage_snapshot is not None and not (
            lineage_snapshot.source_id == snapshot.source_id
            and lineage_snapshot.snapshot_sha256 == snapshot.snapshot_sha256
            and lineage_snapshot.byte_length == snapshot.byte_length
            and lineage_snapshot.media_type == snapshot.media_type
            and lineage_snapshot.snapshot_original_label == snapshot.original_label
        ):
            return False
    return True


def _component_receipts(
    *,
    mission_queue: MissionResearchQueueResult,
    claim_review: ClaimReviewResult,
    claim_lineage: ClaimLineageResult,
    lens_search: LensSearchResult,
    lens_replay: LensReplayResult,
) -> tuple[ReviewDossierComponentReceipt, ...]:
    if (
        mission_queue.schema_version != MISSION_RESEARCH_QUEUE_SCHEMA_VERSION
        or mission_queue.kind != _MISSION_QUEUE_KIND
        or mission_queue.algorithm != MISSION_RESEARCH_QUEUE_ALGORITHM
        or mission_queue.algorithm_version != MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION
        or mission_queue.scope != MISSION_RESEARCH_QUEUE_SCOPE
        or mission_queue.completion_policy != _COMPLETION_POLICY
        or not mission_queue.complete
        or mission_queue.truncated
        or _queue_receipt_digest(mission_queue) != mission_queue.queue_receipt_sha256
        or claim_review.schema_version != CLAIM_REVIEW_SCHEMA_VERSION
        or claim_review.kind != _CLAIM_REVIEW_KIND
        or claim_review.algorithm != CLAIM_REVIEW_ALGORITHM
        or claim_review.algorithm_version != CLAIM_REVIEW_ALGORITHM_VERSION
        or claim_review.completion_policy != _COMPLETION_POLICY
        or not claim_review.complete
        or claim_review.truncated
        or _claim_review_receipt_digest(claim_review) != claim_review.review_receipt_sha256
        or claim_lineage.schema_version != CLAIM_LINEAGE_SCHEMA_VERSION
        or claim_lineage.kind != _CLAIM_LINEAGE_KIND
        or claim_lineage.algorithm != CLAIM_LINEAGE_ALGORITHM
        or claim_lineage.algorithm_version != CLAIM_LINEAGE_ALGORITHM_VERSION
        or claim_lineage.scope != CLAIM_LINEAGE_SCOPE
        or claim_lineage.completion_policy != _COMPLETION_POLICY
        or not claim_lineage.complete
        or claim_lineage.truncated
        or _lineage_receipt_digest(claim_lineage) != claim_lineage.lineage_receipt_sha256
        or lens_search.schema_version != LENS_SCHEMA_VERSION
        or lens_search.kind != LENS_RESULT_KIND
        or lens_search.algorithm != LENS_ALGORITHM
        or lens_search.algorithm_version != LENS_ALGORITHM_VERSION
        or lens_replay.schema_version != LENS_REPLAY_SCHEMA_VERSION
        or lens_replay.kind != _LENS_REPLAY_KIND
        or lens_replay.status != _LENS_REPLAY_STATUS
        or lens_replay.receipt_schema_version != LENS_SCHEMA_VERSION
        or lens_replay.algorithm != LENS_ALGORITHM
        or lens_replay.algorithm_version != LENS_ALGORITHM_VERSION
        or not lens_replay.exact_receipt_match
        or not lens_replay.current_database_snapshot_matched
        or lens_replay.historical_corpus_replay
        or not lens_replay.searched_snapshot_content_verified
        or lens_replay.semantic_boundary != LensReceiptCheckBoundary(reads_research_database=True)
    ):
        _raise_inconsistent()
    replay_digest = sha256(_canonical_json_bytes(asdict(lens_replay))).hexdigest()
    return (
        ReviewDossierComponentReceipt(
            kind=mission_queue.kind,
            schema_version=mission_queue.schema_version,
            algorithm=mission_queue.algorithm,
            algorithm_version=mission_queue.algorithm_version,
            receipt_sha256=mission_queue.queue_receipt_sha256,
        ),
        ReviewDossierComponentReceipt(
            kind=claim_review.kind,
            schema_version=claim_review.schema_version,
            algorithm=claim_review.algorithm,
            algorithm_version=claim_review.algorithm_version,
            receipt_sha256=claim_review.review_receipt_sha256,
        ),
        ReviewDossierComponentReceipt(
            kind=claim_lineage.kind,
            schema_version=claim_lineage.schema_version,
            algorithm=claim_lineage.algorithm,
            algorithm_version=claim_lineage.algorithm_version,
            receipt_sha256=claim_lineage.lineage_receipt_sha256,
        ),
        ReviewDossierComponentReceipt(
            kind=lens_search.kind,
            schema_version=lens_search.schema_version,
            algorithm=lens_search.algorithm,
            algorithm_version=lens_search.algorithm_version,
            receipt_sha256=lens_search.retrieval_receipt_sha256,
        ),
        ReviewDossierComponentReceipt(
            kind=lens_replay.kind,
            schema_version=lens_replay.schema_version,
            algorithm=lens_replay.algorithm,
            algorithm_version=lens_replay.algorithm_version,
            receipt_sha256=replay_digest,
        ),
    )


def _component_set_digest(
    *,
    mission_id: str,
    claim_id: str,
    component_receipts: tuple[ReviewDossierComponentReceipt, ...],
) -> str:
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": REVIEW_DOSSIER_COMPONENT_SET_SCHEMA_VERSION,
                "algorithm": REVIEW_DOSSIER_ALGORITHM,
                "algorithm_version": REVIEW_DOSSIER_ALGORITHM_VERSION,
                "scope": REVIEW_DOSSIER_SCOPE,
                "mission_id": mission_id,
                "claim_id": claim_id,
                "components": [asdict(item) for item in component_receipts],
            }
        )
    ).hexdigest()


def _dossier_receipt_digest(result: ReviewDossierResult) -> str:
    payload = asdict(result)
    payload.pop("dossier_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _finalize_output_size(result: ReviewDossierResult) -> ReviewDossierResult:
    output_bytes = 0
    for _ in range(10):
        candidate = replace(
            result,
            work=replace(result.work, canonical_output_bytes=output_bytes),
            dossier_receipt_sha256="0" * 64,
        )
        measured = len(_canonical_json_bytes(asdict(candidate)))
        if measured == output_bytes:
            return replace(
                result,
                work=replace(result.work, canonical_output_bytes=measured),
            )
        output_bytes = measured
    _raise_inconsistent()


@contextmanager
def _bounded_query_work(
    connection: sqlite3.Connection,
    max_sqlite_vm_steps: int,
) -> Iterator[None]:
    callbacks_remaining = max_sqlite_vm_steps // _QUERY_PROGRESS_GRANULARITY
    exhausted = False

    def progress() -> int:
        nonlocal callbacks_remaining, exhausted
        callbacks_remaining -= 1
        if callbacks_remaining <= 0:
            exhausted = True
            return 1
        return 0

    connection.set_progress_handler(progress, _QUERY_PROGRESS_GRANULARITY)
    try:
        yield
    except sqlite3.DatabaseError as error:
        if exhausted and getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_INTERRUPT:
            raise IntegrityError(
                "review_dossier_work_limit",
                "The complete local review dossier exceeds its configured work limits.",
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _raise_bounds_invalid() -> Never:
    raise IntegrityError(
        "review_dossier_bounds_invalid",
        "Review dossier bounds are invalid.",
    )


def _raise_scope_invalid() -> Never:
    raise IntegrityError(
        "review_dossier_scope_invalid",
        "The local review dossier scope is invalid.",
    )


def _raise_work_limit() -> Never:
    raise IntegrityError(
        "review_dossier_work_limit",
        "The complete local review dossier exceeds its configured work limits.",
    )


def _raise_inconsistent() -> Never:
    raise IntegrityError(
        "review_dossier_inconsistent",
        "The local review dossier components are inconsistent.",
    )
