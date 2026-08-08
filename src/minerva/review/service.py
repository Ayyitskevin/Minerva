"""Complete-or-refuse claim review over existing append-only research state."""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, replace
from hashlib import sha256
from typing import Any, cast

from minerva.assist.models import ModelProvider
from minerva.core.db import Database
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.evidence.integrity import (
    SnapshotCache,
    VerifiedCitation,
    new_snapshot_cache,
    verify_evidence_reference,
)
from minerva.evidence.models import EvidenceStance
from minerva.research.models import (
    Claim,
    ClaimStatus,
    FindingStatus,
    StatementKind,
    claim_status_evidence_valid,
)
from minerva.research.service import ResearchService
from minerva.review.models import (
    CLAIM_REVIEW_ALGORITHM,
    CLAIM_REVIEW_ALGORITHM_VERSION,
    CLAIM_REVIEW_SCHEMA_VERSION,
    AffectedFinding,
    AffectedInference,
    ClaimEvidenceReference,
    ClaimReviewBounds,
    ClaimReviewCue,
    ClaimReviewResult,
    ClaimReviewSemanticBoundary,
    ClaimReviewWork,
    ClaimStatusSnapshot,
    CorrectionRecord,
    EvidenceWithdrawalImpact,
    InferencePromotionRecord,
    StanceCounts,
)

DEFAULT_CLAIM_REVIEW_BOUNDS = ClaimReviewBounds()

_MAX_EVIDENCE_CARDS = 200
_MAX_AFFECTED_RECORDS = 500
_MAX_RELATIONSHIPS = 5_000
_MAX_SNAPSHOT_BYTES = 67_108_864
_MIN_SQLITE_VM_STEPS = 1_000
_MAX_SQLITE_VM_STEPS = 16_000_000
_QUERY_PROGRESS_GRANULARITY = 1_000
_SQL_IDENTIFIER_CHUNK = 200
_MISSION_ID = re.compile(r"mis_[0-9a-f]{32}\Z")
_CLAIM_ID = re.compile(r"clm_[0-9a-f]{32}\Z")

_GAP_EXPLANATIONS = {
    "no_active_evidence": "No evidence card in this claim is currently active.",
    "no_active_support": "The active ledger contains no supporting evidence card.",
    "no_active_opposition": "The active ledger contains no opposing evidence card.",
    "status_required_active_stance_missing": (
        "The recorded workflow status no longer has every active stance it requires."
    ),
}

_IMPACT_EXPLANATIONS = {
    "active_stance_contradiction": (
        "The active ledger contains both supporting and opposing evidence."
    ),
    "withdrawn_evidence_history_present": (
        "One or more evidence cards have an append-only withdrawal record."
    ),
    "recorded_status_requirement_unmet": (
        "The recorded status is retained, but its active-evidence requirement is unmet."
    ),
    "live_material_finding_uses_withdrawn_evidence": (
        "An unretracted material finding cites withdrawn evidence and blocks applicable synthesis."
    ),
    "optional_statement_uses_withdrawn_evidence": (
        "An unretracted assumption or unresolved question retains an optional withdrawn citation."
    ),
    "retracted_finding_history_present": (
        "A related finding retraction remains in the append-only history."
    ),
    "live_inference_uses_withdrawn_evidence": (
        "An unretracted adopted inference cites evidence that is no longer active."
    ),
    "retracted_inference_history_present": (
        "A related adopted-inference retraction remains in the append-only history."
    ),
    "promoted_finding_remains_independently_asserted": (
        "A retracted inference's promoted finding remains asserted until separately retracted."
    ),
    "live_inference_remains_after_promoted_finding_retraction": (
        "Retracting a promoted finding does not retract its still-live source inference."
    ),
}


class ClaimReviewService:
    """Derive structural gaps and correction impacts without writing research state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def review_claim(
        self,
        *,
        mission_id: str,
        claim_id: str,
        bounds: ClaimReviewBounds = DEFAULT_CLAIM_REVIEW_BOUNDS,
    ) -> ClaimReviewResult:
        safe_bounds = _validate_bounds(bounds)
        _validate_scope_ids(mission_id=mission_id, claim_id=claim_id)
        research = ResearchService(self.database)

        with self.database.read() as connection:
            connection.execute("PRAGMA query_only = ON")
            with _bounded_query_work(connection, safe_bounds.max_sqlite_vm_steps):
                _require_mission(connection, mission_id)
                _require_claim_scope(connection, mission_id=mission_id, claim_id=claim_id)
                status_row = _verify_claim_relationships(
                    connection,
                    mission_id=mission_id,
                    claim_id=claim_id,
                )
                try:
                    claim = research.get_claim(claim_id, connection=connection)
                except (KeyError, TypeError, ValueError) as error:
                    raise IntegrityError(
                        "claim_review_inconsistent",
                        "Stored claim review state is invalid.",
                    ) from error
                _verify_claim_model(
                    claim,
                    status_row=status_row,
                    mission_id=mission_id,
                    claim_id=claim_id,
                )

                evidence_rows = _claim_evidence_rows(
                    connection,
                    mission_id=mission_id,
                    claim_id=claim_id,
                    limit=safe_bounds.max_evidence_cards,
                )
                target_evidence_ids = tuple(str(row["id"]) for row in evidence_rows)
                target_evidence_set = frozenset(target_evidence_ids)
                withdrawn_target_ids = tuple(
                    str(row["id"]) for row in evidence_rows if row["withdrawal_id"] is not None
                )

                finding_ids = _affected_finding_ids(
                    connection,
                    mission_id=mission_id,
                    claim_id=claim_id,
                    target_evidence_ids=target_evidence_ids,
                    withdrawn_target_ids=withdrawn_target_ids,
                    limit=safe_bounds.max_affected_records,
                )
                inference_ids = _affected_inference_ids(
                    connection,
                    mission_id=mission_id,
                    claim_id=claim_id,
                    withdrawn_target_ids=withdrawn_target_ids,
                    finding_ids=finding_ids,
                    limit=safe_bounds.max_affected_records,
                )
                if len(finding_ids) + len(inference_ids) > safe_bounds.max_affected_records:
                    _raise_work_limit()

                finding_rows = _finding_rows(
                    connection,
                    mission_id=mission_id,
                    finding_ids=finding_ids,
                )
                inference_rows = _inference_rows(
                    connection,
                    mission_id=mission_id,
                    inference_ids=inference_ids,
                )
                finding_citations = _citation_map(
                    connection,
                    mission_id=mission_id,
                    table="finding_citations",
                    owner_column="finding_id",
                    owner_ids=finding_ids,
                    limit=safe_bounds.max_relationships,
                )
                relationship_count = sum(len(items) for items in finding_citations.values())
                inference_citations = _citation_map(
                    connection,
                    mission_id=mission_id,
                    table="agent_inference_citations",
                    owner_column="inference_id",
                    owner_ids=inference_ids,
                    limit=safe_bounds.max_relationships - relationship_count,
                )
                relationship_count += sum(len(items) for items in inference_citations.values())
                additional_promotion_relationships = _verify_promotion_citation_lineage(
                    connection,
                    inference_rows=inference_rows,
                    inference_citations=inference_citations,
                    finding_citations=finding_citations,
                    mission_id=mission_id,
                    limit=safe_bounds.max_relationships - relationship_count,
                )
                relationship_count += additional_promotion_relationships

                citation_ids = set(target_evidence_ids)
                for items in (*finding_citations.values(), *inference_citations.values()):
                    citation_ids.update(items)
                distinct_snapshot_count, distinct_snapshot_bytes = _snapshot_work(
                    connection,
                    mission_id=mission_id,
                    evidence_ids=tuple(sorted(citation_ids)),
                    max_snapshot_bytes=safe_bounds.max_snapshot_bytes,
                )

                snapshot_cache = new_snapshot_cache()
                verified_by_id = _verify_citations(
                    connection,
                    mission_id=mission_id,
                    evidence_ids=tuple(sorted(citation_ids)),
                    snapshot_cache=snapshot_cache,
                )
                evidence = _evidence_references(
                    evidence_rows,
                    mission_id=mission_id,
                    claim_id=claim_id,
                    verified_by_id=verified_by_id,
                    snapshot_cache=snapshot_cache,
                    target_evidence_set=target_evidence_set,
                )
                findings = _affected_findings(
                    finding_rows,
                    citation_map=finding_citations,
                    target_evidence_set=target_evidence_set,
                    verified_by_id=verified_by_id,
                )
                inferences = _affected_inferences(
                    inference_rows,
                    citation_map=inference_citations,
                    verified_by_id=verified_by_id,
                )

        active_counts = _stance_counts(item for item in evidence if item.withdrawal is None)
        withdrawn_counts = _stance_counts(item for item in evidence if item.withdrawal is not None)
        active_stances = {item.stance for item in evidence if item.withdrawal is None}
        required_stances = _required_active_stances(claim.status)
        missing_required = tuple(
            stance for stance in required_stances if stance not in active_stances
        )
        derived_status_valid = claim_status_evidence_valid(
            claim.status,
            has_active_support=EvidenceStance.SUPPORTS in active_stances,
            has_active_opposition=EvidenceStance.OPPOSES in active_stances,
        )
        if derived_status_valid != claim.status_evidence_valid:
            raise IntegrityError(
                "claim_review_inconsistent", "Stored claim review state is invalid."
            )

        gap_codes = _gap_codes(
            active_counts=active_counts,
            missing_required_stances=missing_required,
        )
        impact_codes = _impact_codes(
            evidence=evidence,
            findings=findings,
            inferences=inferences,
            active_support_and_opposition_present=(
                EvidenceStance.SUPPORTS in active_stances
                and EvidenceStance.OPPOSES in active_stances
            ),
            status_evidence_valid=derived_status_valid,
        )
        withdrawal_impacts = _withdrawal_impacts(
            evidence=evidence,
            findings=findings,
            inferences=inferences,
            missing_required_stances=missing_required,
        )
        cues = _review_cues(
            gap_codes=gap_codes,
            impact_codes=impact_codes,
            evidence=evidence,
            findings=findings,
            inferences=inferences,
        )
        work = ClaimReviewWork(
            evidence_card_count=len(evidence),
            affected_finding_count=len(findings),
            affected_inference_count=len(inferences),
            citation_relationship_count=relationship_count,
            distinct_snapshot_count=distinct_snapshot_count,
            distinct_snapshot_bytes=distinct_snapshot_bytes,
        )
        provisional = ClaimReviewResult(
            schema_version=CLAIM_REVIEW_SCHEMA_VERSION,
            kind="evidence_gap_and_retraction_impact",
            algorithm=CLAIM_REVIEW_ALGORITHM,
            algorithm_version=CLAIM_REVIEW_ALGORITHM_VERSION,
            completion_policy="complete_or_refuse",
            complete=True,
            truncated=False,
            mission_id=mission_id,
            claim_id=claim.id,
            question_id=claim.question_id,
            claim_statement=claim.statement,
            falsification_criteria=claim.falsification_criteria,
            claim_creator_id=claim.creator_id,
            claim_run_id=claim.run_id,
            claim_created_at=claim.created_at,
            recorded_status=ClaimStatusSnapshot(
                status=claim.status,
                version=claim.version,
                reason=claim.status_reason,
                creator_id=claim.status_creator_id,
                run_id=claim.status_run_id,
                changed_at=claim.status_changed_at,
                required_active_stances=required_stances,
                missing_required_active_stances=missing_required,
                evidence_valid=derived_status_valid,
            ),
            active_stance_counts=active_counts,
            withdrawn_stance_counts=withdrawn_counts,
            active_support_and_opposition_present=(
                EvidenceStance.SUPPORTS in active_stances
                and EvidenceStance.OPPOSES in active_stances
            ),
            gap_codes=gap_codes,
            impact_codes=impact_codes,
            bounds=safe_bounds,
            work=work,
            evidence=evidence,
            affected_findings=findings,
            affected_inferences=inferences,
            withdrawal_impacts=withdrawal_impacts,
            review_cues=cues,
            semantic_notice=(
                "Claim Review reports structural ledger absences, active stance conflict, and "
                "append-only correction effects. It does not determine truth, calculate "
                "confidence, recommend or change claim status, or perform a correction; every "
                "correction remains a separate explicit human operation."
            ),
            semantic_boundary=ClaimReviewSemanticBoundary(),
            review_receipt_sha256="",
        )
        return replace(
            provisional,
            review_receipt_sha256=_review_receipt_digest(provisional),
        )


def _validate_bounds(bounds: ClaimReviewBounds) -> ClaimReviewBounds:
    if not isinstance(bounds, ClaimReviewBounds):
        raise IntegrityError("claim_review_bounds_invalid", "Claim review bounds are invalid.")
    values = (
        bounds.max_evidence_cards,
        bounds.max_affected_records,
        bounds.max_relationships,
        bounds.max_snapshot_bytes,
        bounds.max_sqlite_vm_steps,
    )
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise IntegrityError("claim_review_bounds_invalid", "Claim review bounds are invalid.")
    if (
        not 1 <= bounds.max_evidence_cards <= _MAX_EVIDENCE_CARDS
        or not 1 <= bounds.max_affected_records <= _MAX_AFFECTED_RECORDS
        or not 1 <= bounds.max_relationships <= _MAX_RELATIONSHIPS
        or not 1 <= bounds.max_snapshot_bytes <= _MAX_SNAPSHOT_BYTES
        or not _MIN_SQLITE_VM_STEPS <= bounds.max_sqlite_vm_steps <= _MAX_SQLITE_VM_STEPS
    ):
        raise IntegrityError("claim_review_bounds_invalid", "Claim review bounds are invalid.")
    return bounds


def _validate_scope_ids(*, mission_id: object, claim_id: object) -> None:
    if not isinstance(mission_id, str) or _MISSION_ID.fullmatch(mission_id) is None:
        raise NotFoundError("mission_not_found")
    if not isinstance(claim_id, str) or _CLAIM_ID.fullmatch(claim_id) is None:
        raise IntegrityError(
            "claim_review_scope_invalid",
            "The claim review scope is invalid for this mission.",
        )


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
                "claim_review_work_limit",
                "The complete claim review exceeds its configured work limits.",
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)


def _raise_work_limit() -> None:
    raise IntegrityError(
        "claim_review_work_limit",
        "The complete claim review exceeds its configured work limits.",
    )


def _require_mission(connection: sqlite3.Connection, mission_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM research_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        is None
    ):
        raise NotFoundError("mission_not_found")


def _require_claim_scope(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM claims WHERE id = ? AND mission_id = ?",
            (claim_id, mission_id),
        ).fetchone()
        is None
    ):
        raise IntegrityError(
            "claim_review_scope_invalid",
            "The claim review scope is invalid for this mission.",
        )


def _verify_claim_relationships(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
) -> sqlite3.Row:
    claim_row = connection.execute(
        "SELECT mission_id, question_id FROM claims WHERE id = ?",
        (claim_id,),
    ).fetchone()
    if claim_row is None or str(claim_row["mission_id"]) != mission_id:
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )
    if (
        connection.execute(
            "SELECT 1 FROM research_questions WHERE id = ? AND mission_id = ?",
            (str(claim_row["question_id"]), mission_id),
        ).fetchone()
        is None
    ):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )

    summary = connection.execute(
        """
        SELECT COUNT(*) AS event_count,
               MIN(version) AS minimum_version,
               MAX(version) AS maximum_version,
               SUM(CASE WHEN mission_id = ? THEN 0 ELSE 1 END) AS foreign_event_count
        FROM claim_status_events
        WHERE claim_id = ?
        """,
        (mission_id, claim_id),
    ).fetchone()
    if summary is None:
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )
    try:
        event_count = int(summary["event_count"])
        minimum_version = int(summary["minimum_version"])
        maximum_version = int(summary["maximum_version"])
        foreign_event_count = int(summary["foreign_event_count"])
    except (TypeError, ValueError) as error:
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        ) from error
    if (
        event_count < 1
        or minimum_version != 1
        or maximum_version != event_count
        or foreign_event_count != 0
    ):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )

    status_row = connection.execute(
        """
        SELECT mission_id, status, version, reason, creator_id, run_id, created_at
        FROM claim_status_events
        WHERE claim_id = ?
        ORDER BY version DESC
        LIMIT 1
        """,
        (claim_id,),
    ).fetchone()
    if (
        status_row is None
        or not isinstance(status_row, sqlite3.Row)
        or str(status_row["mission_id"]) != mission_id
    ):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )
    return cast(sqlite3.Row, status_row)


def _verify_claim_model(
    claim: Claim,
    *,
    status_row: sqlite3.Row,
    mission_id: str,
    claim_id: str,
) -> None:
    if (
        claim.id != claim_id
        or claim.mission_id != mission_id
        or claim.status.value != str(status_row["status"])
        or claim.version != int(status_row["version"])
        or claim.status_reason != str(status_row["reason"])
        or claim.status_creator_id != str(status_row["creator_id"])
        or claim.status_run_id != str(status_row["run_id"])
        or claim.status_changed_at != str(status_row["created_at"])
    ):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )


def _claim_evidence_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    rows = tuple(
        connection.execute(
            """
            SELECT evidence.id, evidence.mission_id, evidence.claim_id,
                   evidence.snapshot_id, evidence.snapshot_sha256,
                   evidence.start_byte, evidence.end_byte, evidence.quote,
                   evidence.stance, evidence.supersedes_evidence_id,
                   evidence.creator_id, evidence.run_id, evidence.created_at,
                   withdrawal.id AS withdrawal_id,
                   withdrawal.reason AS withdrawal_reason,
                   withdrawal.mission_id AS withdrawal_mission_id,
                   withdrawal.creator_id AS withdrawal_creator_id,
                   withdrawal.run_id AS withdrawal_run_id,
                   withdrawal.created_at AS withdrawal_created_at
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.claim_id = ?
            ORDER BY evidence.created_at ASC, evidence.id ASC
            LIMIT ?
            """,
            (claim_id, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    _verify_related_row_missions(
        rows,
        expected_ids=tuple(str(row["id"]) for row in rows),
        mission_id=mission_id,
        correction_prefixes=("withdrawal",),
    )
    return rows


def _affected_finding_ids(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    target_evidence_ids: tuple[str, ...],
    withdrawn_target_ids: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    identifiers: set[str] = set()
    rows = connection.execute(
        """
        SELECT finding.id
        FROM findings AS finding INDEXED BY idx_findings_claim
        JOIN finding_retractions AS retraction
          ON retraction.finding_id = finding.id
        WHERE finding.mission_id = ? AND finding.claim_id = ?
        ORDER BY finding.created_at ASC, finding.id ASC
        LIMIT ?
        """,
        (mission_id, claim_id, limit + 1),
    )
    identifiers.update(str(row["id"]) for row in rows)
    if len(identifiers) > limit:
        _raise_work_limit()

    if target_evidence_ids:
        placeholders = _placeholders(target_evidence_ids)
        rows = connection.execute(
            f"""
            SELECT DISTINCT finding.id AS finding_id
            FROM findings AS finding INDEXED BY idx_findings_mission
            JOIN finding_citations AS citation INDEXED BY idx_finding_citations_finding
              ON citation.finding_id = finding.id
            JOIN finding_retractions AS retraction
              ON retraction.finding_id = finding.id
            WHERE finding.mission_id = ?
              AND citation.evidence_id IN ({placeholders})
            ORDER BY finding.id ASC
            LIMIT ?
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, *target_evidence_ids, limit + 1),
        )
        identifiers.update(str(row["finding_id"]) for row in rows)
        if len(identifiers) > limit:
            _raise_work_limit()

    if withdrawn_target_ids:
        placeholders = _placeholders(withdrawn_target_ids)
        rows = connection.execute(
            f"""
            SELECT DISTINCT finding.id AS finding_id
            FROM findings AS finding INDEXED BY idx_findings_mission
            JOIN finding_citations AS citation INDEXED BY idx_finding_citations_finding
              ON citation.finding_id = finding.id
            WHERE finding.mission_id = ?
              AND citation.evidence_id IN ({placeholders})
            ORDER BY finding.id ASC
            LIMIT ?
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, *withdrawn_target_ids, limit + 1),
        )
        identifiers.update(str(row["finding_id"]) for row in rows)
        if len(identifiers) > limit:
            _raise_work_limit()
    return tuple(sorted(identifiers))


def _affected_inference_ids(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
    withdrawn_target_ids: tuple[str, ...],
    finding_ids: tuple[str, ...],
    limit: int,
) -> tuple[str, ...]:
    identifiers = {
        str(row["id"])
        for row in connection.execute(
            """
            SELECT inference.id
            FROM agent_inferences AS inference INDEXED BY idx_agent_inferences_claim
            JOIN agent_inference_retractions AS retraction
              ON retraction.inference_id = inference.id
            WHERE inference.mission_id = ? AND inference.claim_id = ?
            ORDER BY inference.created_at ASC, inference.id ASC
            LIMIT ?
            """,
            (mission_id, claim_id, limit + 1),
        )
    }
    if len(identifiers) > limit:
        _raise_work_limit()
    if withdrawn_target_ids:
        placeholders = _placeholders(withdrawn_target_ids)
        rows = connection.execute(
            f"""
            SELECT DISTINCT inference.id AS inference_id
            FROM agent_inferences AS inference INDEXED BY idx_agent_inferences_claim
            JOIN agent_inference_citations AS citation
              INDEXED BY idx_agent_inference_citations_inference
              ON citation.inference_id = inference.id
            WHERE inference.mission_id = ? AND inference.claim_id = ?
              AND citation.evidence_id IN ({placeholders})
            ORDER BY inference.id ASC
            LIMIT ?
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, claim_id, *withdrawn_target_ids, limit + 1),
        )
        identifiers.update(str(row["inference_id"]) for row in rows)
        if len(identifiers) > limit:
            _raise_work_limit()
    if finding_ids:
        placeholders = _placeholders(finding_ids)
        rows = connection.execute(
            f"""
            SELECT DISTINCT inference.id AS inference_id
            FROM agent_inferences AS inference INDEXED BY idx_agent_inferences_mission
            JOIN agent_inference_promotions AS promotion
              ON promotion.inference_id = inference.id
            WHERE inference.mission_id = ?
              AND promotion.finding_id IN ({placeholders})
            ORDER BY inference.id ASC
            LIMIT ?
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, *finding_ids, limit + 1),
        )
        identifiers.update(str(row["inference_id"]) for row in rows)
        if len(identifiers) > limit:
            _raise_work_limit()
    return tuple(sorted(identifiers))


def _finding_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    finding_ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    if not finding_ids:
        return ()
    placeholders = _placeholders(finding_ids)
    rows = tuple(
        connection.execute(
            f"""
            SELECT finding.id, finding.mission_id, finding.claim_id,
                   finding.statement, finding.statement_kind, finding.status,
                   finding.uncertainty, finding.creator_id, finding.run_id,
                   finding.created_at,
                   retraction.id AS retraction_id,
                   retraction.reason AS retraction_reason,
                   retraction.mission_id AS retraction_mission_id,
                   retraction.creator_id AS retraction_creator_id,
                   retraction.run_id AS retraction_run_id,
                   retraction.created_at AS retraction_created_at
            FROM findings AS finding
            LEFT JOIN finding_retractions AS retraction
              ON retraction.finding_id = finding.id
            WHERE finding.id IN ({placeholders})
            ORDER BY finding.created_at ASC, finding.id ASC
            """,  # noqa: S608 - only placeholders are composed.
            finding_ids,
        )
    )
    _verify_related_row_missions(
        rows,
        expected_ids=finding_ids,
        mission_id=mission_id,
        correction_prefixes=("retraction",),
    )
    return rows


def _inference_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    inference_ids: tuple[str, ...],
) -> tuple[sqlite3.Row, ...]:
    if not inference_ids:
        return ()
    placeholders = _placeholders(inference_ids)
    rows = tuple(
        connection.execute(
            f"""
            SELECT inference.id, inference.mission_id, inference.claim_id,
                   inference.statement, inference.uncertainty,
                   inference.provider, inference.model,
                   inference.creator_id, inference.run_id, inference.created_at,
                   retraction.id AS retraction_id,
                   retraction.reason AS retraction_reason,
                   retraction.mission_id AS retraction_mission_id,
                   retraction.creator_id AS retraction_creator_id,
                   retraction.run_id AS retraction_run_id,
                   retraction.created_at AS retraction_created_at,
                   promotion.id AS promotion_id,
                   promotion.finding_id AS promoted_finding_id,
                   promotion.mission_id AS promotion_mission_id,
                   promotion.creator_id AS promotion_creator_id,
                   promotion.run_id AS promotion_run_id,
                   promotion.created_at AS promotion_created_at,
                   promoted_finding.id AS promoted_finding_row_id,
                   promoted_finding.mission_id AS promoted_finding_mission_id,
                   promoted_finding.claim_id AS promoted_finding_claim_id,
                   promoted_finding.statement AS promoted_finding_statement,
                   promoted_finding.statement_kind AS promoted_finding_statement_kind,
                   promoted_finding.uncertainty AS promoted_finding_uncertainty,
                   promoted_retraction.id AS promoted_retraction_id,
                   promoted_retraction.id IS NOT NULL AS promoted_finding_retracted,
                   promoted_retraction.mission_id AS promoted_retraction_mission_id
            FROM agent_inferences AS inference
            LEFT JOIN agent_inference_retractions AS retraction
              ON retraction.inference_id = inference.id
            LEFT JOIN agent_inference_promotions AS promotion
              ON promotion.inference_id = inference.id
            LEFT JOIN findings AS promoted_finding
              ON promoted_finding.id = promotion.finding_id
            LEFT JOIN finding_retractions AS promoted_retraction
              ON promoted_retraction.finding_id = promotion.finding_id
            WHERE inference.id IN ({placeholders})
            ORDER BY inference.created_at ASC, inference.id ASC
            """,  # noqa: S608 - only placeholders are composed.
            inference_ids,
        )
    )
    _verify_related_row_missions(
        rows,
        expected_ids=inference_ids,
        mission_id=mission_id,
        correction_prefixes=("retraction", "promotion", "promoted_retraction"),
    )
    _verify_promotion_targets(rows, mission_id=mission_id)
    return rows


def _verify_related_row_missions(
    rows: tuple[sqlite3.Row, ...],
    *,
    expected_ids: tuple[str, ...],
    mission_id: str,
    correction_prefixes: tuple[str, ...],
) -> None:
    resolved_ids = tuple(str(row["id"]) for row in rows)
    if len(resolved_ids) != len(expected_ids) or set(resolved_ids) != set(expected_ids):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )
    for row in rows:
        if str(row["mission_id"]) != mission_id:
            raise IntegrityError(
                "claim_review_inconsistent",
                "Stored claim review state is invalid.",
            )
        for prefix in correction_prefixes:
            if row[f"{prefix}_id"] is not None and str(row[f"{prefix}_mission_id"]) != mission_id:
                raise IntegrityError(
                    "claim_review_inconsistent",
                    "Stored claim review state is invalid.",
                )


def _verify_promotion_targets(
    rows: tuple[sqlite3.Row, ...],
    *,
    mission_id: str,
) -> None:
    for row in rows:
        if row["promotion_id"] is None:
            continue
        if (
            row["promoted_finding_row_id"] is None
            or str(row["promoted_finding_row_id"]) != str(row["promoted_finding_id"])
            or str(row["promoted_finding_mission_id"]) != mission_id
            or str(row["promoted_finding_claim_id"]) != str(row["claim_id"])
            or str(row["promoted_finding_statement"]) != str(row["statement"])
            or str(row["promoted_finding_statement_kind"]) != StatementKind.AGENT_INFERENCE.value
            or str(row["promoted_finding_uncertainty"]) != str(row["uncertainty"])
        ):
            raise IntegrityError(
                "claim_review_inconsistent",
                "Stored claim review state is invalid.",
            )


def _verify_promotion_citation_lineage(
    connection: sqlite3.Connection,
    *,
    inference_rows: tuple[sqlite3.Row, ...],
    inference_citations: dict[str, tuple[str, ...]],
    finding_citations: dict[str, tuple[str, ...]],
    mission_id: str,
    limit: int,
) -> int:
    additional_relationships = 0
    for row in inference_rows:
        if row["promotion_id"] is None:
            continue
        inference_id = str(row["id"])
        expected = inference_citations.get(inference_id, ())
        promoted_finding_id = str(row["promoted_finding_id"])
        counted = finding_citations.get(promoted_finding_id)
        if counted is not None:
            if counted != expected:
                raise IntegrityError(
                    "claim_review_inconsistent",
                    "Stored claim review state is invalid.",
                )
            continue
        citations = tuple(
            connection.execute(
                """
                SELECT mission_id, evidence_id
                FROM finding_citations
                WHERE finding_id = ?
                ORDER BY evidence_id ASC
                LIMIT ?
                """,
                (promoted_finding_id, len(expected) + 1),
            )
        )
        if (
            any(str(item["mission_id"]) != mission_id for item in citations)
            or tuple(str(item["evidence_id"]) for item in citations) != expected
        ):
            raise IntegrityError(
                "claim_review_inconsistent",
                "Stored claim review state is invalid.",
            )
        additional_relationships += len(citations)
        if additional_relationships > limit:
            _raise_work_limit()
    return additional_relationships


def _citation_map(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    table: str,
    owner_column: str,
    owner_ids: tuple[str, ...],
    limit: int,
) -> dict[str, tuple[str, ...]]:
    if not owner_ids:
        return {}
    if limit < 1:
        _raise_work_limit()
    if (table, owner_column) not in {
        ("finding_citations", "finding_id"),
        ("agent_inference_citations", "inference_id"),
    }:
        raise AssertionError("citation table is not allowlisted")
    placeholders = _placeholders(owner_ids)
    rows = tuple(
        connection.execute(
            f"""
            SELECT {owner_column} AS owner_id, mission_id, evidence_id
            FROM {table}
            WHERE {owner_column} IN ({placeholders})
            ORDER BY {owner_column} ASC, evidence_id ASC
            LIMIT ?
            """,  # noqa: S608 - identifiers are allowlisted and values are parameters.
            (*owner_ids, limit + 1),
        )
    )
    if len(rows) > limit:
        _raise_work_limit()
    grouped: dict[str, list[str]] = {owner_id: [] for owner_id in owner_ids}
    for row in rows:
        if str(row["mission_id"]) != mission_id:
            raise IntegrityError(
                "claim_review_inconsistent",
                "Stored claim review state is invalid.",
            )
        grouped[str(row["owner_id"])].append(str(row["evidence_id"]))
    return {owner_id: tuple(items) for owner_id, items in grouped.items()}


def _snapshot_work(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    evidence_ids: tuple[str, ...],
    max_snapshot_bytes: int,
) -> tuple[int, int]:
    if not evidence_ids:
        return 0, 0
    snapshot_ids: set[str] = set()
    resolved_evidence_ids: set[str] = set()
    for identifiers in _identifier_chunks(evidence_ids):
        placeholders = _placeholders(identifiers)
        rows = connection.execute(
            f"""
            SELECT id, snapshot_id
            FROM evidence_cards
            WHERE mission_id = ? AND id IN ({placeholders})
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, *identifiers),
        )
        for row in rows:
            resolved_evidence_ids.add(str(row["id"]))
            snapshot_ids.add(str(row["snapshot_id"]))
    if resolved_evidence_ids != set(evidence_ids):
        raise IntegrityError(
            "claim_review_inconsistent",
            "Stored claim review state is invalid.",
        )

    total_bytes = 0
    resolved_snapshot_ids: set[str] = set()
    for identifiers in _identifier_chunks(tuple(sorted(snapshot_ids))):
        placeholders = _placeholders(identifiers)
        rows = connection.execute(
            f"""
            SELECT id, byte_length, LENGTH(content) AS stored_content_bytes
            FROM source_snapshots
            WHERE mission_id = ? AND id IN ({placeholders})
            """,  # noqa: S608 - only placeholders are composed.
            (mission_id, *identifiers),
        )
        for row in rows:
            resolved_snapshot_ids.add(str(row["id"]))
            try:
                actual_bytes = int(row["stored_content_bytes"])
                declared_bytes = int(row["byte_length"])
            except (TypeError, ValueError) as error:
                raise IntegrityError(
                    "snapshot_tampered",
                    "Stored source snapshot integrity failed.",
                ) from error
            if actual_bytes != declared_bytes:
                raise IntegrityError(
                    "snapshot_tampered",
                    "Stored source snapshot integrity failed.",
                )
            total_bytes += actual_bytes
            if total_bytes > max_snapshot_bytes:
                _raise_work_limit()
    if resolved_snapshot_ids != snapshot_ids:
        raise IntegrityError(
            "snapshot_tampered",
            "Stored source snapshot integrity failed.",
        )
    return len(snapshot_ids), total_bytes


def _verify_citations(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    evidence_ids: tuple[str, ...],
    snapshot_cache: SnapshotCache,
) -> dict[str, VerifiedCitation]:
    return {
        evidence_id: verify_evidence_reference(
            connection,
            evidence_id=evidence_id,
            mission_id=mission_id,
            allow_withdrawn=True,
            snapshot_cache=snapshot_cache,
        )
        for evidence_id in evidence_ids
    }


def _evidence_references(
    rows: tuple[sqlite3.Row, ...],
    *,
    mission_id: str,
    claim_id: str,
    verified_by_id: dict[str, VerifiedCitation],
    snapshot_cache: SnapshotCache,
    target_evidence_set: frozenset[str],
) -> tuple[ClaimEvidenceReference, ...]:
    references: list[ClaimEvidenceReference] = []
    for row in rows:
        evidence_id = str(row["id"])
        verified = verified_by_id[evidence_id]
        if (
            verified.mission_id != mission_id
            or verified.claim_id != claim_id
            or verified.snapshot_id != str(row["snapshot_id"])
            or verified.snapshot_sha256 != str(row["snapshot_sha256"])
            or verified.start_byte != int(row["start_byte"])
            or verified.end_byte != int(row["end_byte"])
            or verified.quote != str(row["quote"])
            or verified.stance.value != str(row["stance"])
            or verified.withdrawn != (row["withdrawal_id"] is not None)
        ):
            raise IntegrityError(
                "claim_review_inconsistent", "Stored claim review state is invalid."
            )
        supersedes = (
            str(row["supersedes_evidence_id"])
            if row["supersedes_evidence_id"] is not None
            else None
        )
        if supersedes is not None and supersedes not in target_evidence_set:
            raise IntegrityError(
                "evidence_supersession_invalid", "Stored evidence history is invalid."
            )
        snapshot_row, raw_content = snapshot_cache[verified.snapshot_id]
        quote_bytes = raw_content[verified.start_byte : verified.end_byte]
        if quote_bytes != verified.quote.encode("utf-8"):
            raise IntegrityError("citation_tampered", "Stored citation integrity failed.")
        withdrawal = _correction_record(row, prefix="withdrawal")
        if withdrawal is not None and (
            verified.withdrawal_reason != withdrawal.reason
            or verified.withdrawn_at != withdrawal.created_at
        ):
            raise IntegrityError(
                "claim_review_inconsistent", "Stored claim review state is invalid."
            )
        references.append(
            ClaimEvidenceReference(
                evidence_id=evidence_id,
                source_id=str(snapshot_row["source_id"]),
                source_label=verified.source_label,
                snapshot_id=verified.snapshot_id,
                snapshot_sha256=verified.snapshot_sha256,
                media_type=str(snapshot_row["media_type"]),
                start_byte=verified.start_byte,
                end_byte=verified.end_byte,
                quote_byte_length=len(quote_bytes),
                quote_sha256=sha256(quote_bytes).hexdigest(),
                stance=verified.stance,
                supersedes_evidence_id=supersedes,
                creator_id=str(row["creator_id"]),
                run_id=str(row["run_id"]),
                created_at=str(row["created_at"]),
                withdrawal=withdrawal,
            )
        )
    result = tuple(references)
    _verify_supersession_graph(result)
    return result


def _verify_supersession_graph(
    evidence: tuple[ClaimEvidenceReference, ...],
) -> None:
    parent_by_id = {item.evidence_id: item.supersedes_evidence_id for item in evidence}
    for evidence_id in parent_by_id:
        seen: set[str] = set()
        cursor: str | None = evidence_id
        while cursor is not None:
            if cursor in seen:
                raise IntegrityError(
                    "evidence_supersession_invalid",
                    "Stored evidence history is invalid.",
                )
            seen.add(cursor)
            cursor = parent_by_id.get(cursor)


def _affected_findings(
    rows: tuple[sqlite3.Row, ...],
    *,
    citation_map: dict[str, tuple[str, ...]],
    target_evidence_set: frozenset[str],
    verified_by_id: dict[str, VerifiedCitation],
) -> tuple[AffectedFinding, ...]:
    result: list[AffectedFinding] = []
    for row in rows:
        finding_id = str(row["id"])
        evidence_ids = citation_map.get(finding_id, ())
        kind = _statement_kind(row["statement_kind"])
        retraction = _correction_record(row, prefix="retraction")
        if kind.requires_citation and not evidence_ids:
            raise IntegrityError(
                "uncited_material_finding",
                "A material finding is missing required citations.",
            )
        linked_claim = str(row["claim_id"]) if row["claim_id"] is not None else None
        for evidence_id in evidence_ids:
            verified = verified_by_id[evidence_id]
            if linked_claim is not None and verified.claim_id != linked_claim:
                raise IntegrityError(
                    "finding_citation_scope_invalid",
                    "A finding citation evaluates a different claim.",
                )
        target_ids = tuple(item for item in evidence_ids if item in target_evidence_set)
        withdrawn_ids = tuple(item for item in evidence_ids if verified_by_id[item].withdrawn)
        withdrawn_target_ids = tuple(item for item in target_ids if item in withdrawn_ids)
        effect_codes: list[str] = []
        if retraction is not None:
            effect_codes.extend(("finding_excluded_from_synthesis", "history_retained"))
        elif withdrawn_ids and kind.requires_citation:
            effect_codes.append("mission_synthesis_blocked_by_live_material_finding")
            if linked_claim is not None:
                effect_codes.append("claim_synthesis_blocked_by_live_material_finding")
        elif withdrawn_ids:
            effect_codes.append("optional_statement_retains_withdrawn_citation")
        result.append(
            AffectedFinding(
                finding_id=finding_id,
                claim_id=linked_claim,
                statement=str(row["statement"]),
                statement_kind=kind,
                status=_finding_status(row["status"]),
                uncertainty=str(row["uncertainty"]),
                evidence_ids=evidence_ids,
                target_evidence_ids=target_ids,
                withdrawn_evidence_ids=withdrawn_ids,
                withdrawn_target_evidence_ids=withdrawn_target_ids,
                material=kind.requires_citation,
                effect_codes=tuple(effect_codes),
                creator_id=str(row["creator_id"]),
                run_id=str(row["run_id"]),
                created_at=str(row["created_at"]),
                retraction=retraction,
            )
        )
    return tuple(result)


def _affected_inferences(
    rows: tuple[sqlite3.Row, ...],
    *,
    citation_map: dict[str, tuple[str, ...]],
    verified_by_id: dict[str, VerifiedCitation],
) -> tuple[AffectedInference, ...]:
    result: list[AffectedInference] = []
    for row in rows:
        inference_id = str(row["id"])
        evidence_ids = citation_map.get(inference_id, ())
        if not evidence_ids:
            raise IntegrityError(
                "uncited_agent_inference",
                "An adopted inference is missing required citations.",
            )
        claim_id = str(row["claim_id"])
        for evidence_id in evidence_ids:
            if verified_by_id[evidence_id].claim_id != claim_id:
                raise IntegrityError(
                    "inference_citation_scope_invalid",
                    "An inference citation evaluates a different claim.",
                )
        withdrawn_ids = tuple(item for item in evidence_ids if verified_by_id[item].withdrawn)
        retraction = _correction_record(row, prefix="retraction")
        promotion = _promotion_record(row)
        effect_codes: list[str] = []
        if retraction is not None:
            effect_codes.extend(("inference_excluded_from_markdown", "history_retained"))
            if promotion is not None and not promotion.finding_retracted:
                effect_codes.append("promoted_finding_remains_independently_asserted")
        else:
            if withdrawn_ids:
                effect_codes.append("live_inference_citation_no_longer_active")
                if promotion is None:
                    effect_codes.append("inference_promotion_blocked")
            if promotion is not None and promotion.finding_retracted:
                effect_codes.append("live_inference_remains_after_promoted_finding_retraction")
        result.append(
            AffectedInference(
                inference_id=inference_id,
                claim_id=claim_id,
                statement=str(row["statement"]),
                uncertainty=str(row["uncertainty"]),
                provider=_model_provider(row["provider"]),
                model=str(row["model"]),
                evidence_ids=evidence_ids,
                withdrawn_evidence_ids=withdrawn_ids,
                active_citation_policy_satisfied=not withdrawn_ids,
                effect_codes=tuple(effect_codes),
                promotion=promotion,
                creator_id=str(row["creator_id"]),
                run_id=str(row["run_id"]),
                created_at=str(row["created_at"]),
                retraction=retraction,
            )
        )
    return tuple(result)


def _correction_record(row: sqlite3.Row, *, prefix: str) -> CorrectionRecord | None:
    identifier = row[f"{prefix}_id"]
    if identifier is None:
        return None
    return CorrectionRecord(
        id=str(identifier),
        reason=str(row[f"{prefix}_reason"]),
        creator_id=str(row[f"{prefix}_creator_id"]),
        run_id=str(row[f"{prefix}_run_id"]),
        created_at=str(row[f"{prefix}_created_at"]),
    )


def _promotion_record(row: sqlite3.Row) -> InferencePromotionRecord | None:
    identifier = row["promotion_id"]
    if identifier is None:
        return None
    return InferencePromotionRecord(
        id=str(identifier),
        finding_id=str(row["promoted_finding_id"]),
        creator_id=str(row["promotion_creator_id"]),
        run_id=str(row["promotion_run_id"]),
        created_at=str(row["promotion_created_at"]),
        finding_retracted=bool(row["promoted_finding_retracted"]),
    )


def _statement_kind(value: object) -> StatementKind:
    try:
        return StatementKind(str(value))
    except ValueError as error:
        raise IntegrityError(
            "claim_review_inconsistent", "Stored claim review state is invalid."
        ) from error


def _finding_status(value: object) -> FindingStatus:
    try:
        return FindingStatus(str(value))
    except ValueError as error:
        raise IntegrityError(
            "claim_review_inconsistent", "Stored claim review state is invalid."
        ) from error


def _model_provider(value: object) -> ModelProvider:
    try:
        return ModelProvider(str(value))
    except ValueError as error:
        raise IntegrityError(
            "claim_review_inconsistent", "Stored claim review state is invalid."
        ) from error


def _stance_counts(items: Iterator[ClaimEvidenceReference]) -> StanceCounts:
    counts = Counter(item.stance for item in items)
    return StanceCounts(
        supports=counts[EvidenceStance.SUPPORTS],
        opposes=counts[EvidenceStance.OPPOSES],
        context=counts[EvidenceStance.CONTEXT],
        inconclusive=counts[EvidenceStance.INCONCLUSIVE],
        total=sum(counts.values()),
    )


def _required_active_stances(status: ClaimStatus) -> tuple[EvidenceStance, ...]:
    if status is ClaimStatus.PROVISIONALLY_SUPPORTED:
        return (EvidenceStance.SUPPORTS,)
    if status is ClaimStatus.CONTESTED:
        return (EvidenceStance.SUPPORTS, EvidenceStance.OPPOSES)
    if status is ClaimStatus.UNSUPPORTED:
        return (EvidenceStance.OPPOSES,)
    return ()


def _gap_codes(
    *,
    active_counts: StanceCounts,
    missing_required_stances: tuple[EvidenceStance, ...],
) -> tuple[str, ...]:
    codes: list[str] = []
    if active_counts.total == 0:
        codes.append("no_active_evidence")
    if active_counts.supports == 0:
        codes.append("no_active_support")
    if active_counts.opposes == 0:
        codes.append("no_active_opposition")
    if missing_required_stances:
        codes.append("status_required_active_stance_missing")
    return tuple(codes)


def _impact_codes(
    *,
    evidence: tuple[ClaimEvidenceReference, ...],
    findings: tuple[AffectedFinding, ...],
    inferences: tuple[AffectedInference, ...],
    active_support_and_opposition_present: bool,
    status_evidence_valid: bool,
) -> tuple[str, ...]:
    codes: list[str] = []
    if active_support_and_opposition_present:
        codes.append("active_stance_contradiction")
    if any(item.withdrawal is not None for item in evidence):
        codes.append("withdrawn_evidence_history_present")
    if not status_evidence_valid:
        codes.append("recorded_status_requirement_unmet")
    if any(
        item.retraction is None and item.material and item.withdrawn_evidence_ids
        for item in findings
    ):
        codes.append("live_material_finding_uses_withdrawn_evidence")
    if any(
        item.retraction is None and not item.material and item.withdrawn_evidence_ids
        for item in findings
    ):
        codes.append("optional_statement_uses_withdrawn_evidence")
    if any(item.retraction is not None for item in findings):
        codes.append("retracted_finding_history_present")
    if any(item.retraction is None and item.withdrawn_evidence_ids for item in inferences):
        codes.append("live_inference_uses_withdrawn_evidence")
    if any(item.retraction is not None for item in inferences):
        codes.append("retracted_inference_history_present")
    if any(
        "promoted_finding_remains_independently_asserted" in item.effect_codes
        for item in inferences
    ):
        codes.append("promoted_finding_remains_independently_asserted")
    if any(
        "live_inference_remains_after_promoted_finding_retraction" in item.effect_codes
        for item in inferences
    ):
        codes.append("live_inference_remains_after_promoted_finding_retraction")
    return tuple(codes)


def _withdrawal_impacts(
    *,
    evidence: tuple[ClaimEvidenceReference, ...],
    findings: tuple[AffectedFinding, ...],
    inferences: tuple[AffectedInference, ...],
    missing_required_stances: tuple[EvidenceStance, ...],
) -> tuple[EvidenceWithdrawalImpact, ...]:
    impacts: list[EvidenceWithdrawalImpact] = []
    for item in evidence:
        if item.withdrawal is None:
            continue
        active_material = tuple(
            finding.finding_id
            for finding in findings
            if finding.retraction is None
            and finding.material
            and item.evidence_id in finding.evidence_ids
        )
        active_optional = tuple(
            finding.finding_id
            for finding in findings
            if finding.retraction is None
            and not finding.material
            and item.evidence_id in finding.evidence_ids
        )
        retracted_findings = tuple(
            finding.finding_id
            for finding in findings
            if finding.retraction is not None and item.evidence_id in finding.evidence_ids
        )
        active_inferences = tuple(
            inference.inference_id
            for inference in inferences
            if inference.retraction is None and item.evidence_id in inference.evidence_ids
        )
        retracted_inferences = tuple(
            inference.inference_id
            for inference in inferences
            if inference.retraction is not None and item.evidence_id in inference.evidence_ids
        )
        effect_codes = ["removed_from_active_evidence_set", "history_retained"]
        if item.stance in missing_required_stances:
            effect_codes.append("current_claim_status_requirement_unmet")
        if active_material:
            effect_codes.append("live_material_finding_affected")
        if active_optional:
            effect_codes.append("optional_statement_retains_withdrawn_citation")
        if active_inferences:
            effect_codes.append("live_inference_citation_no_longer_active")
            if any(
                inference.promotion is None
                for inference in inferences
                if inference.inference_id in active_inferences
            ):
                effect_codes.append("inference_promotion_blocked")
        impacts.append(
            EvidenceWithdrawalImpact(
                evidence_id=item.evidence_id,
                withdrawal_id=item.withdrawal.id,
                stance=item.stance,
                effect_codes=tuple(effect_codes),
                active_material_finding_ids=active_material,
                active_optional_finding_ids=active_optional,
                retracted_finding_ids=retracted_findings,
                active_inference_ids=active_inferences,
                retracted_inference_ids=retracted_inferences,
                direct_superseding_evidence_ids=tuple(
                    candidate.evidence_id
                    for candidate in evidence
                    if candidate.supersedes_evidence_id == item.evidence_id
                ),
            )
        )
    return tuple(impacts)


def _review_cues(
    *,
    gap_codes: tuple[str, ...],
    impact_codes: tuple[str, ...],
    evidence: tuple[ClaimEvidenceReference, ...],
    findings: tuple[AffectedFinding, ...],
    inferences: tuple[AffectedInference, ...],
) -> tuple[ClaimReviewCue, ...]:
    cues = [
        ClaimReviewCue(code=code, explanation=_GAP_EXPLANATIONS[code], record_ids=())
        for code in gap_codes
    ]
    withdrawn_ids = tuple(item.evidence_id for item in evidence if item.withdrawal is not None)
    for code in impact_codes:
        if code == "withdrawn_evidence_history_present":
            record_ids = withdrawn_ids
        elif code in {
            "live_material_finding_uses_withdrawn_evidence",
            "optional_statement_uses_withdrawn_evidence",
            "retracted_finding_history_present",
        }:
            record_ids = tuple(
                item.finding_id
                for item in findings
                if (
                    code == "live_material_finding_uses_withdrawn_evidence"
                    and item.retraction is None
                    and item.material
                    and item.withdrawn_evidence_ids
                )
                or (
                    code == "optional_statement_uses_withdrawn_evidence"
                    and item.retraction is None
                    and not item.material
                    and item.withdrawn_evidence_ids
                )
                or (code == "retracted_finding_history_present" and item.retraction is not None)
            )
        elif code in {
            "live_inference_uses_withdrawn_evidence",
            "retracted_inference_history_present",
            "promoted_finding_remains_independently_asserted",
            "live_inference_remains_after_promoted_finding_retraction",
        }:
            record_ids = tuple(
                item.inference_id
                for item in inferences
                if (
                    code == "live_inference_uses_withdrawn_evidence"
                    and item.retraction is None
                    and item.withdrawn_evidence_ids
                )
                or (code == "retracted_inference_history_present" and item.retraction is not None)
                or (
                    code == "promoted_finding_remains_independently_asserted"
                    and code in item.effect_codes
                )
                or (
                    code == "live_inference_remains_after_promoted_finding_retraction"
                    and code in item.effect_codes
                )
            )
        else:
            record_ids = ()
        cues.append(
            ClaimReviewCue(
                code=code,
                explanation=_IMPACT_EXPLANATIONS[code],
                record_ids=record_ids,
            )
        )
    return tuple(cues)


def _placeholders(values: Sequence[object]) -> str:
    if not values:
        raise AssertionError("SQL placeholder list cannot be empty")
    return ",".join("?" for _ in values)


def _identifier_chunks(values: tuple[str, ...]) -> Iterator[tuple[str, ...]]:
    for start in range(0, len(values), _SQL_IDENTIFIER_CHUNK):
        yield values[start : start + _SQL_IDENTIFIER_CHUNK]


def _review_receipt_digest(result: ClaimReviewResult) -> str:
    payload = asdict(result)
    payload.pop("review_receipt_sha256")
    return sha256(_canonical_json_bytes(payload)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
