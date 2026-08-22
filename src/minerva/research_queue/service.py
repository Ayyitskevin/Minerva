"""Complete-or-refuse mission aggregation of deterministic Claim Review cues."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Any, Never

from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.evidence.integrity import SnapshotCache, VerifiedCitation, new_snapshot_cache
from minerva.research.service import ResearchService
from minerva.research_queue.models import (
    MISSION_RESEARCH_QUEUE_ALGORITHM,
    MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION,
    MISSION_RESEARCH_QUEUE_CLAIM_SET_SCHEMA_VERSION,
    MISSION_RESEARCH_QUEUE_ITEM_SET_SCHEMA_VERSION,
    MISSION_RESEARCH_QUEUE_REVIEW_SET_SCHEMA_VERSION,
    MISSION_RESEARCH_QUEUE_SCHEMA_VERSION,
    MISSION_RESEARCH_QUEUE_SCOPE,
    MissionResearchQueueBounds,
    MissionResearchQueueItem,
    MissionResearchQueueReason,
    MissionResearchQueueReasonCount,
    MissionResearchQueueResult,
    MissionResearchQueueReviewedClaim,
    MissionResearchQueueSemanticBoundary,
    MissionResearchQueueWork,
)
from minerva.review.models import (
    CLAIM_REVIEW_ALGORITHM,
    CLAIM_REVIEW_ALGORITHM_VERSION,
    CLAIM_REVIEW_CUE_CATALOG,
    CLAIM_REVIEW_SCHEMA_VERSION,
    ClaimReviewBounds,
    ClaimReviewResult,
)
from minerva.review.service import (
    ClaimReviewService,
    _ClaimReviewExecutionLimits,
    _review_cues,
)

DEFAULT_MISSION_RESEARCH_QUEUE_BOUNDS = MissionResearchQueueBounds()

_MAX_CLAIMS = 200
_MAX_ITEMS = len(CLAIM_REVIEW_CUE_CATALOG) * _MAX_CLAIMS
_MAX_EVIDENCE_CARDS = 40_000
_MAX_DISTINCT_EVIDENCE_QUOTE_BYTES = 67_108_864
_MAX_AFFECTED_RECORDS = 100_000
_MAX_RELATIONSHIPS = 1_000_000
_MAX_DISTINCT_SNAPSHOT_BYTES = 67_108_864
_MAX_OUTPUT_BYTES = 134_217_728
_MIN_SQLITE_VM_STEPS = 1_000
_MAX_SQLITE_VM_STEPS = 16_000_000
_QUERY_PROGRESS_GRANULARITY = 1_000
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")

_PER_CLAIM_MAX_EVIDENCE_CARDS = 200
_PER_CLAIM_MAX_AFFECTED_RECORDS = 500
_PER_CLAIM_MAX_RELATIONSHIPS = 5_000

_ORDERING = (
    "reviewed_claims:claim_created_at_ascending_then_claim_id_ascending",
    "items:reviewed_claim_order_then_claim_review_cue_catalog_order",
)
_SEQUENCE_SEMANTICS = "deterministic_display_order_not_priority"
_EXCLUDED_RECORD_KINDS = (
    "foreign_mission_records",
    "unrelated_claimless_findings",
    "lens_candidates",
    "claim_lineage_topology",
    "audit_events",
    "research_runs",
    "brief_exports",
    "reverse_dependents_outside_claim_review_scope",
)

_REASON_CATALOG = tuple(
    MissionResearchQueueReason(
        catalog_position=position,
        code=code,
        category=category,
        explanation=explanation,
    )
    for position, (code, category, explanation) in enumerate(
        CLAIM_REVIEW_CUE_CATALOG,
        start=1,
    )
)
_REASON_BY_CODE = {item.code: item for item in _REASON_CATALOG}
_REASON_POSITION = {item.code: item.catalog_position for item in _REASON_CATALOG}


class MissionResearchQueueService:
    """Build one deterministic mission review index without writing state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def build_queue(
        self,
        *,
        mission_id: str,
        bounds: MissionResearchQueueBounds = DEFAULT_MISSION_RESEARCH_QUEUE_BOUNDS,
        connection: sqlite3.Connection | None = None,
    ) -> MissionResearchQueueResult:
        result, _focal_review = self._build_queue(
            mission_id=mission_id,
            bounds=bounds,
            connection=connection,
            focal_claim_id=None,
            outer_work_guard=False,
        )
        return result

    def _build_queue_in_snapshot(
        self,
        *,
        mission_id: str,
        bounds: MissionResearchQueueBounds,
        connection: sqlite3.Connection,
        focal_claim_id: str,
    ) -> tuple[MissionResearchQueueResult, ClaimReviewResult | None]:
        """Build a queue in a caller-owned read snapshot and retain one review."""

        return self._build_queue(
            mission_id=mission_id,
            bounds=bounds,
            connection=connection,
            focal_claim_id=focal_claim_id,
            outer_work_guard=True,
        )

    def _build_queue(
        self,
        *,
        mission_id: str,
        bounds: MissionResearchQueueBounds,
        connection: sqlite3.Connection | None,
        focal_claim_id: str | None,
        outer_work_guard: bool,
    ) -> tuple[MissionResearchQueueResult, ClaimReviewResult | None]:
        safe_bounds = _validate_bounds(bounds)
        _validate_mission_id(mission_id)
        research = ResearchService(self.database)
        review_service = ClaimReviewService(self.database)
        review_bounds = ClaimReviewBounds(
            max_evidence_cards=_PER_CLAIM_MAX_EVIDENCE_CARDS,
            max_affected_records=_PER_CLAIM_MAX_AFFECTED_RECORDS,
            max_relationships=_PER_CLAIM_MAX_RELATIONSHIPS,
            max_snapshot_bytes=safe_bounds.max_distinct_snapshot_bytes,
            max_sqlite_vm_steps=safe_bounds.max_sqlite_vm_steps,
        )
        snapshot_cache = new_snapshot_cache()
        verified_citation_cache: dict[str, VerifiedCitation] = {}
        verified_citation_quote_bytes: dict[str, int] = {}

        reviewed_claims: list[MissionResearchQueueReviewedClaim] = []
        items: list[MissionResearchQueueItem] = []
        evidence_card_count = 0
        affected_finding_count = 0
        affected_inference_count = 0
        relationship_count = 0
        focal_review: ClaimReviewResult | None = None

        try:
            with _queue_connection(self.database, connection) as connection:
                connection.execute("PRAGMA query_only = ON")
                with _bounded_query_work(
                    connection,
                    safe_bounds.max_sqlite_vm_steps,
                    managed=not outer_work_guard,
                ):
                    mission = research.get_mission(mission_id, connection=connection)
                    claim_rows = list(
                        connection.execute(
                            """
                            SELECT claim.id, claim.question_id, claim.statement,
                                   claim.created_at,
                                   status.mission_id AS status_mission_id,
                                   status.status AS current_status,
                                   status.version AS current_status_version
                            FROM claims AS claim
                            LEFT JOIN claim_status_events AS status
                              ON status.claim_id = claim.id
                             AND status.version = (
                                 SELECT MAX(candidate.version)
                                 FROM claim_status_events AS candidate
                                 WHERE candidate.claim_id = claim.id
                             )
                            WHERE claim.mission_id = ?
                            ORDER BY claim.created_at ASC, claim.id ASC
                            LIMIT ?
                            """,
                            (mission_id, safe_bounds.max_claims + 1),
                        )
                    )
                    if len(claim_rows) > safe_bounds.max_claims:
                        _raise_work_limit()

                    for claim_position, row in enumerate(claim_rows, start=1):
                        claim_id = _stored_claim_id(row["id"])
                        question_id = _stored_string(row["question_id"])
                        claim_statement = _stored_string(row["statement"])
                        claim_created_at = _stored_string(row["created_at"])
                        status_mission_id = _stored_string(row["status_mission_id"])
                        current_status = _stored_string(row["current_status"])
                        current_status_version = _stored_nonnegative_int(
                            row["current_status_version"]
                        )
                        if status_mission_id != mission_id or current_status_version < 1:
                            _raise_inconsistent()
                        cached_snapshot_bytes = sum(
                            len(raw_content)
                            for _snapshot_row, raw_content in snapshot_cache.values()
                        )
                        execution_limits = _ClaimReviewExecutionLimits(
                            max_evidence_cards=review_bounds.max_evidence_cards,
                            max_affected_records=min(
                                review_bounds.max_affected_records,
                                safe_bounds.max_affected_records
                                - affected_finding_count
                                - affected_inference_count,
                            ),
                            max_relationships=min(
                                review_bounds.max_relationships,
                                safe_bounds.max_relationships - relationship_count,
                            ),
                            max_new_evidence_cards=min(
                                review_bounds.max_evidence_cards + review_bounds.max_relationships,
                                safe_bounds.max_evidence_cards - len(verified_citation_cache),
                            ),
                            max_new_evidence_quote_bytes=(
                                safe_bounds.max_distinct_evidence_quote_bytes
                                - sum(verified_citation_quote_bytes.values())
                            ),
                            max_new_snapshot_bytes=(
                                safe_bounds.max_distinct_snapshot_bytes - cached_snapshot_bytes
                            ),
                        )
                        try:
                            review = review_service._review_claim_in_snapshot(
                                mission_id=mission_id,
                                claim_id=claim_id,
                                bounds=review_bounds,
                                connection=connection,
                                snapshot_cache=snapshot_cache,
                                verified_citation_cache=verified_citation_cache,
                                verified_citation_quote_bytes=(verified_citation_quote_bytes),
                                execution_limits=execution_limits,
                            )
                        except IntegrityError as error:
                            if error.code == "claim_review_work_limit":
                                _raise_work_limit()
                            raise
                        _validate_review(
                            review,
                            mission_id=mission_id,
                            claim_id=claim_id,
                            question_id=question_id,
                            claim_statement=claim_statement,
                            claim_created_at=claim_created_at,
                            current_status=current_status,
                            current_status_version=current_status_version,
                            expected_bounds=review_bounds,
                        )
                        if claim_id == focal_claim_id:
                            focal_review = review

                        evidence_card_count = len(verified_citation_cache)
                        affected_finding_count += review.work.affected_finding_count
                        affected_inference_count += review.work.affected_inference_count
                        relationship_count += review.work.citation_relationship_count
                        _enforce_aggregate_work(
                            bounds=safe_bounds,
                            evidence_card_count=evidence_card_count,
                            affected_record_count=(
                                affected_finding_count + affected_inference_count
                            ),
                            relationship_count=relationship_count,
                            snapshot_cache=snapshot_cache,
                            verified_citation_quote_bytes=(verified_citation_quote_bytes),
                        )

                        cue_codes = tuple(cue.code for cue in review.review_cues)
                        summary = MissionResearchQueueReviewedClaim(
                            sequence=claim_position,
                            claim_id=review.claim_id,
                            question_id=review.question_id,
                            claim_statement=review.claim_statement,
                            recorded_status=review.recorded_status.status,
                            recorded_status_version=review.recorded_status.version,
                            claim_created_at=review.claim_created_at,
                            reason_codes=cue_codes,
                            item_count=len(review.review_cues),
                            review_receipt_sha256=review.review_receipt_sha256,
                        )
                        reviewed_claims.append(summary)
                        for cue in review.review_cues:
                            reason = _REASON_BY_CODE[cue.code]
                            items.append(
                                MissionResearchQueueItem(
                                    sequence=len(items) + 1,
                                    kind="structural_review_cue",
                                    claim_id=review.claim_id,
                                    question_id=review.question_id,
                                    reason_code=cue.code,
                                    reason_category=reason.category,
                                    explanation=cue.explanation,
                                    record_ids=cue.record_ids,
                                    source_review_receipt_sha256=(review.review_receipt_sha256),
                                )
                            )
                        if len(items) > safe_bounds.max_items:
                            _raise_work_limit()
        except (IntegrityError, NotFoundError):
            raise
        except (KeyError, TypeError, ValueError, UnicodeError) as error:
            raise IntegrityError(
                "mission_research_queue_inconsistent",
                "Stored mission research queue state is invalid.",
            ) from error

        reviewed_claim_tuple = tuple(reviewed_claims)
        item_tuple = tuple(items)
        distinct_snapshot_bytes = sum(
            len(raw_content) for _row, raw_content in snapshot_cache.values()
        )
        reason_counter = Counter(item.reason_code for item in item_tuple)
        reason_counts = tuple(
            MissionResearchQueueReasonCount(
                code=reason.code,
                count=reason_counter[reason.code],
            )
            for reason in _REASON_CATALOG
        )
        claim_set_sha256 = _claim_set_digest(
            mission_id=mission_id,
            reviewed_claims=reviewed_claim_tuple,
        )
        claim_review_set_sha256 = _claim_review_set_digest(
            mission_id=mission_id,
            reviewed_claims=reviewed_claim_tuple,
        )
        item_set_sha256 = _item_set_digest(
            mission_id=mission_id,
            items=item_tuple,
        )
        work = MissionResearchQueueWork(
            reviewed_claim_count=len(reviewed_claim_tuple),
            item_count=len(item_tuple),
            evidence_card_count=evidence_card_count,
            distinct_evidence_quote_bytes=sum(verified_citation_quote_bytes.values()),
            affected_finding_count=affected_finding_count,
            affected_inference_count=affected_inference_count,
            affected_record_count=affected_finding_count + affected_inference_count,
            citation_relationship_count=relationship_count,
            distinct_snapshot_count=len(snapshot_cache),
            distinct_snapshot_bytes=distinct_snapshot_bytes,
            canonical_output_bytes=0,
        )
        provisional = MissionResearchQueueResult(
            schema_version=MISSION_RESEARCH_QUEUE_SCHEMA_VERSION,
            kind="mission_research_queue",
            algorithm=MISSION_RESEARCH_QUEUE_ALGORITHM,
            algorithm_version=MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION,
            scope=MISSION_RESEARCH_QUEUE_SCOPE,
            completion_policy="complete_or_refuse",
            complete=True,
            truncated=False,
            mission_id=mission_id,
            mission_title=mission.title,
            mission_objective=mission.objective,
            mission_creator_id=mission.creator_id,
            mission_run_id=mission.run_id,
            mission_created_at=mission.created_at,
            claim_review_schema_version=CLAIM_REVIEW_SCHEMA_VERSION,
            claim_review_algorithm=CLAIM_REVIEW_ALGORITHM,
            claim_review_algorithm_version=CLAIM_REVIEW_ALGORITHM_VERSION,
            claim_review_bounds=review_bounds,
            bounds=safe_bounds,
            work=work,
            ordering=_ORDERING,
            sequence_semantics=_SEQUENCE_SEMANTICS,
            reason_catalog=_REASON_CATALOG,
            reason_counts=reason_counts,
            reviewed_claims=reviewed_claim_tuple,
            items=item_tuple,
            claim_set_sha256=claim_set_sha256,
            claim_review_set_sha256=claim_review_set_sha256,
            item_set_sha256=item_set_sha256,
            excluded_record_kinds=_EXCLUDED_RECORD_KINDS,
            scope_notice=(
                "This index reviews every owner-admitted claim in the named mission. "
                "Unrelated claimless findings and reverse dependents remain outside scope, "
                "although Claim Review may identify a claimless finding affected by a "
                "reviewed claim's correction history."
            ),
            semantic_notice=(
                "This is a deterministic structural review index, not a task system. The "
                "current Claim Review taxonomy emits at least one cue for every claim; an "
                "item therefore does not mean work is open, unresolved, required, severe, "
                "or prioritized. Historical cues may persist after a correction."
            ),
            semantic_boundary=MissionResearchQueueSemanticBoundary(),
            queue_receipt_sha256="",
        )
        result = _finalize_output_size(provisional)
        if result.work.canonical_output_bytes > safe_bounds.max_output_bytes:
            _raise_work_limit()
        return (
            replace(
                result,
                queue_receipt_sha256=_queue_receipt_digest(result),
            ),
            focal_review,
        )


def _validate_bounds(bounds: MissionResearchQueueBounds) -> MissionResearchQueueBounds:
    if not isinstance(bounds, MissionResearchQueueBounds):
        _raise_bounds_invalid()
    values = (
        bounds.max_claims,
        bounds.max_items,
        bounds.max_evidence_cards,
        bounds.max_distinct_evidence_quote_bytes,
        bounds.max_affected_records,
        bounds.max_relationships,
        bounds.max_distinct_snapshot_bytes,
        bounds.max_output_bytes,
        bounds.max_sqlite_vm_steps,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        _raise_bounds_invalid()
    if (
        not 1 <= bounds.max_claims <= _MAX_CLAIMS
        or not 1 <= bounds.max_items <= _MAX_ITEMS
        or not 1 <= bounds.max_evidence_cards <= _MAX_EVIDENCE_CARDS
        or not 1 <= bounds.max_distinct_evidence_quote_bytes <= _MAX_DISTINCT_EVIDENCE_QUOTE_BYTES
        or not 1 <= bounds.max_affected_records <= _MAX_AFFECTED_RECORDS
        or not 1 <= bounds.max_relationships <= _MAX_RELATIONSHIPS
        or not 1 <= bounds.max_distinct_snapshot_bytes <= _MAX_DISTINCT_SNAPSHOT_BYTES
        or not 1 <= bounds.max_output_bytes <= _MAX_OUTPUT_BYTES
        or not _MIN_SQLITE_VM_STEPS <= bounds.max_sqlite_vm_steps <= _MAX_SQLITE_VM_STEPS
    ):
        _raise_bounds_invalid()
    return bounds


def _validate_mission_id(mission_id: object) -> None:
    if not isinstance(mission_id, str) or _MISSION_ID.fullmatch(mission_id) is None:
        raise NotFoundError("mission_not_found")


def _validate_review(
    review: ClaimReviewResult,
    *,
    mission_id: str,
    claim_id: str,
    question_id: str,
    claim_statement: str,
    claim_created_at: str,
    current_status: str,
    current_status_version: int,
    expected_bounds: ClaimReviewBounds,
) -> None:
    if (
        not isinstance(review, ClaimReviewResult)
        or review.schema_version != CLAIM_REVIEW_SCHEMA_VERSION
        or review.algorithm != CLAIM_REVIEW_ALGORITHM
        or review.algorithm_version != CLAIM_REVIEW_ALGORITHM_VERSION
        or review.kind != "evidence_gap_and_retraction_impact"
        or review.completion_policy != "complete_or_refuse"
        or not review.complete
        or review.truncated
        or review.mission_id != mission_id
        or review.claim_id != claim_id
        or review.question_id != question_id
        or review.claim_statement != claim_statement
        or review.claim_created_at != claim_created_at
        or review.recorded_status.status.value != current_status
        or review.recorded_status.version != current_status_version
        or review.bounds != expected_bounds
        or _claim_review_receipt_digest(review) != review.review_receipt_sha256
        or review.work.evidence_card_count != len(review.evidence)
        or review.work.affected_finding_count != len(review.affected_findings)
        or review.work.affected_inference_count != len(review.affected_inferences)
        or review.work.citation_relationship_count < 0
        or review.work.distinct_snapshot_count < 0
        or review.work.distinct_snapshot_bytes < 0
    ):
        _raise_inconsistent()
    if (
        not isinstance(review.review_cues, tuple)
        or not isinstance(review.gap_codes, tuple)
        or not isinstance(review.impact_codes, tuple)
    ):
        _raise_inconsistent()
    affected_finding_ids = {item.finding_id for item in review.affected_findings}
    expected_relationship_count = sum(
        len(item.evidence_ids) for item in review.affected_findings
    ) + sum(len(item.evidence_ids) for item in review.affected_inferences)
    expected_relationship_count += sum(
        len(item.evidence_ids)
        for item in review.affected_inferences
        if item.promotion is not None and item.promotion.finding_id not in affected_finding_ids
    )
    if review.work.citation_relationship_count != expected_relationship_count:
        _raise_inconsistent()
    codes = tuple(cue.code for cue in review.review_cues)
    if (
        codes != review.gap_codes + review.impact_codes
        or any(
            _REASON_BY_CODE.get(code) is None or _REASON_BY_CODE[code].category != "structural_gap"
            for code in review.gap_codes
        )
        or any(
            _REASON_BY_CODE.get(code) is None
            or _REASON_BY_CODE[code].category != "structural_impact"
            for code in review.impact_codes
        )
    ):
        _raise_inconsistent()
    positions: list[int] = []
    for cue in review.review_cues:
        reason = _REASON_BY_CODE.get(cue.code)
        if (
            reason is None
            or cue.explanation != reason.explanation
            or not isinstance(cue.record_ids, tuple)
            or any(not isinstance(record_id, str) for record_id in cue.record_ids)
            or len(cue.record_ids) != len(set(cue.record_ids))
        ):
            _raise_inconsistent()
        positions.append(_REASON_POSITION[cue.code])
    if positions != sorted(positions) or len(codes) != len(set(codes)):
        _raise_inconsistent()
    if review.review_cues != _review_cues(
        gap_codes=review.gap_codes,
        impact_codes=review.impact_codes,
        evidence=review.evidence,
        findings=review.affected_findings,
        inferences=review.affected_inferences,
    ):
        _raise_inconsistent()


def _enforce_aggregate_work(
    *,
    bounds: MissionResearchQueueBounds,
    evidence_card_count: int,
    affected_record_count: int,
    relationship_count: int,
    snapshot_cache: SnapshotCache,
    verified_citation_quote_bytes: dict[str, int],
) -> None:
    snapshot_bytes = sum(len(raw_content) for _row, raw_content in snapshot_cache.values())
    if (
        evidence_card_count > bounds.max_evidence_cards
        or sum(verified_citation_quote_bytes.values()) > bounds.max_distinct_evidence_quote_bytes
        or affected_record_count > bounds.max_affected_records
        or relationship_count > bounds.max_relationships
        or snapshot_bytes > bounds.max_distinct_snapshot_bytes
    ):
        _raise_work_limit()


@contextmanager
def _queue_connection(
    database: Database,
    connection: sqlite3.Connection | None,
) -> Iterator[sqlite3.Connection]:
    if connection is not None:
        yield connection
        return
    with database.read() as opened:
        yield opened


@contextmanager
def _bounded_query_work(
    connection: sqlite3.Connection,
    max_sqlite_vm_steps: int,
    *,
    managed: bool = True,
) -> Iterator[None]:
    if not managed:
        yield
        return
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
                "mission_research_queue_work_limit",
                "The complete mission research queue exceeds its configured work limits.",
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _claim_set_digest(
    *,
    mission_id: str,
    reviewed_claims: tuple[MissionResearchQueueReviewedClaim, ...],
) -> str:
    claims = [
        {
            "sequence": item.sequence,
            "claim_id": item.claim_id,
            "question_id": item.question_id,
            "claim_statement": item.claim_statement,
            "recorded_status": item.recorded_status,
            "recorded_status_version": item.recorded_status_version,
            "claim_created_at": item.claim_created_at,
        }
        for item in reviewed_claims
    ]
    return _framed_digest(
        schema_version=MISSION_RESEARCH_QUEUE_CLAIM_SET_SCHEMA_VERSION,
        mission_id=mission_id,
        key="claims",
        value=claims,
    )


def _claim_review_set_digest(
    *,
    mission_id: str,
    reviewed_claims: tuple[MissionResearchQueueReviewedClaim, ...],
) -> str:
    reviews = [
        {
            "sequence": item.sequence,
            "claim_id": item.claim_id,
            "reason_codes": item.reason_codes,
            "item_count": item.item_count,
            "review_receipt_sha256": item.review_receipt_sha256,
        }
        for item in reviewed_claims
    ]
    return _framed_digest(
        schema_version=MISSION_RESEARCH_QUEUE_REVIEW_SET_SCHEMA_VERSION,
        mission_id=mission_id,
        key="claim_reviews",
        value=reviews,
    )


def _item_set_digest(
    *,
    mission_id: str,
    items: tuple[MissionResearchQueueItem, ...],
) -> str:
    return _framed_digest(
        schema_version=MISSION_RESEARCH_QUEUE_ITEM_SET_SCHEMA_VERSION,
        mission_id=mission_id,
        key="items",
        value=[asdict(item) for item in items],
    )


def _framed_digest(
    *,
    schema_version: str,
    mission_id: str,
    key: str,
    value: object,
) -> str:
    return sha256(
        _canonical_json_bytes(
            {
                "schema_version": schema_version,
                "algorithm": MISSION_RESEARCH_QUEUE_ALGORITHM,
                "algorithm_version": MISSION_RESEARCH_QUEUE_ALGORITHM_VERSION,
                "scope": MISSION_RESEARCH_QUEUE_SCOPE,
                "mission_id": mission_id,
                key: value,
            }
        )
    ).hexdigest()


def _claim_review_receipt_digest(review: ClaimReviewResult) -> str:
    payload = asdict(review)
    payload.pop("review_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _queue_receipt_digest(result: MissionResearchQueueResult) -> str:
    payload = asdict(result)
    payload.pop("queue_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _finalize_output_size(
    result: MissionResearchQueueResult,
) -> MissionResearchQueueResult:
    output_bytes = 0
    for _ in range(10):
        candidate = replace(
            result,
            work=replace(result.work, canonical_output_bytes=output_bytes),
            queue_receipt_sha256="0" * 64,
        )
        measured = len(_canonical_json_bytes(asdict(candidate)))
        if measured == output_bytes:
            return replace(
                result,
                work=replace(result.work, canonical_output_bytes=measured),
            )
        output_bytes = measured
    _raise_inconsistent()


def _stored_string(value: object) -> str:
    if not isinstance(value, str):
        _raise_inconsistent()
    return value


def _stored_claim_id(value: object) -> str:
    claim_id = _stored_string(value)
    if _CLAIM_ID.fullmatch(claim_id) is None:
        _raise_inconsistent()
    return claim_id


def _stored_nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _raise_inconsistent()
    return value


def _raise_bounds_invalid() -> Never:
    raise IntegrityError(
        "mission_research_queue_bounds_invalid",
        "Mission research queue bounds are invalid.",
    )


def _raise_work_limit() -> Never:
    raise IntegrityError(
        "mission_research_queue_work_limit",
        "The complete mission research queue exceeds its configured work limits.",
    )


def _raise_inconsistent() -> Never:
    raise IntegrityError(
        "mission_research_queue_inconsistent",
        "Stored mission research queue state is invalid.",
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
