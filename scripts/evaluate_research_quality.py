"""Measure structural research quality and operator effort on a persistent corpus."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from statistics import median

from minerva.core.db import Database
from minerva.core.doctor import run_doctor

SCHEMA_VERSION = "minerva.research-quality-evaluation.v1"
ALGORITHM = "aggregate-persistent-corpus-research-quality"
ALGORITHM_VERSION = 1

_STATE_COUNT_QUERIES = (
    ("agent_inference_citations", "SELECT COUNT(*) FROM agent_inference_citations"),
    ("agent_inference_promotions", "SELECT COUNT(*) FROM agent_inference_promotions"),
    ("agent_inference_retractions", "SELECT COUNT(*) FROM agent_inference_retractions"),
    ("agent_inferences", "SELECT COUNT(*) FROM agent_inferences"),
    ("audit_events", "SELECT COUNT(*) FROM audit_events"),
    ("brief_exports", "SELECT COUNT(*) FROM brief_exports"),
    ("claim_status_events", "SELECT COUNT(*) FROM claim_status_events"),
    ("claims", "SELECT COUNT(*) FROM claims"),
    ("evidence_cards", "SELECT COUNT(*) FROM evidence_cards"),
    ("evidence_withdrawals", "SELECT COUNT(*) FROM evidence_withdrawals"),
    ("finding_citations", "SELECT COUNT(*) FROM finding_citations"),
    ("finding_retractions", "SELECT COUNT(*) FROM finding_retractions"),
    ("findings", "SELECT COUNT(*) FROM findings"),
    ("research_missions", "SELECT COUNT(*) FROM research_missions"),
    ("research_questions", "SELECT COUNT(*) FROM research_questions"),
    ("research_runs", "SELECT COUNT(*) FROM research_runs"),
    ("schema_migrations", "SELECT COUNT(*) FROM schema_migrations"),
    ("source_snapshots", "SELECT COUNT(*) FROM source_snapshots"),
    ("sources", "SELECT COUNT(*) FROM sources"),
)


class EvaluationError(RuntimeError):
    """The corpus cannot support the requested evaluation."""


def _scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def _ppm(numerator: int, denominator: int) -> int | None:
    if denominator == 0:
        return None
    return numerator * 1_000_000 // denominator


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _elapsed_seconds(start: str, end: str) -> float:
    elapsed = (_parse_timestamp(end) - _parse_timestamp(start)).total_seconds()
    if elapsed < 0:
        raise EvaluationError("the corpus contains a negative research-path duration")
    return round(elapsed, 3)


def _summary(values: list[int] | list[float]) -> dict[str, int | float] | None:
    if not values:
        return None
    return {
        "minimum": min(values),
        "median": median(values),
        "maximum": max(values),
    }


def _logical_state_receipt(database: Database) -> str:
    with database.read() as connection:
        counts = [
            (table_name, _scalar(connection, query)) for table_name, query in _STATE_COUNT_QUERIES
        ]
    payload = json.dumps(counts, ensure_ascii=True, separators=(",", ":"))
    return sha256(payload.encode("ascii")).hexdigest()


def _quality_metrics(connection: sqlite3.Connection) -> dict[str, int | None]:
    claim_count = _scalar(connection, "SELECT COUNT(*) FROM claims")
    row = connection.execute(
        """
        WITH active_evidence AS (
            SELECT evidence.*
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            LEFT JOIN evidence_cards AS replacement
              ON replacement.supersedes_evidence_id = evidence.id
            WHERE withdrawal.id IS NULL AND replacement.id IS NULL
        ), mixed AS (
            SELECT claim_id FROM active_evidence
            GROUP BY claim_id
            HAVING SUM(stance = 'supports') > 0 AND SUM(stance = 'opposes') > 0
        ), latest_status AS (
            SELECT status.claim_id, status.status
            FROM claim_status_events AS status
            JOIN (
                SELECT claim_id, MAX(version) AS version
                FROM claim_status_events GROUP BY claim_id
            ) AS latest
              ON latest.claim_id = status.claim_id AND latest.version = status.version
        )
        SELECT
          (SELECT COUNT(*) FROM active_evidence) AS active_evidence_count,
          (SELECT COUNT(DISTINCT claim_id) FROM active_evidence)
            AS claims_with_active_evidence,
          (SELECT COUNT(DISTINCT claim_id) FROM active_evidence WHERE stance = 'opposes')
            AS claims_with_active_opposition,
          (SELECT COUNT(*) FROM mixed) AS mixed_stance_claims,
          (
            SELECT COUNT(*) FROM mixed
            JOIN latest_status ON latest_status.claim_id = mixed.claim_id
            WHERE latest_status.status IN ('contested', 'inconclusive')
          ) AS acknowledged_mixed_stance_claims,
          (
            SELECT COUNT(*) FROM findings WHERE status IN ('supported', 'contested')
          ) AS supported_or_contested_findings,
          (
            SELECT COUNT(DISTINCT finding.id)
            FROM findings AS finding
            JOIN finding_citations AS citation ON citation.finding_id = finding.id
            JOIN active_evidence AS evidence ON evidence.id = citation.evidence_id
            WHERE finding.status IN ('supported', 'contested')
          ) AS supported_or_contested_with_active_citation
        """
    ).fetchone()
    active_evidence_count = int(row["active_evidence_count"])
    claims_with_active_evidence = int(row["claims_with_active_evidence"])
    claims_with_active_opposition = int(row["claims_with_active_opposition"])
    mixed_stance_claims = int(row["mixed_stance_claims"])
    acknowledged_mixed_stance_claims = int(row["acknowledged_mixed_stance_claims"])
    supported_or_contested_findings = int(row["supported_or_contested_findings"])
    supported_or_contested_with_active_citation = int(
        row["supported_or_contested_with_active_citation"]
    )
    return {
        "active_evidence_card_count": active_evidence_count,
        "claims_with_active_evidence_count": claims_with_active_evidence,
        "claim_active_evidence_coverage_ppm": _ppm(claims_with_active_evidence, claim_count),
        "claims_with_active_opposition_count": claims_with_active_opposition,
        "mixed_active_stance_claim_count": mixed_stance_claims,
        "mixed_stance_status_acknowledgement_ppm": _ppm(
            acknowledged_mixed_stance_claims,
            mixed_stance_claims,
        ),
        "supported_or_contested_finding_count": supported_or_contested_findings,
        "supported_or_contested_finding_active_citation_coverage_ppm": _ppm(
            supported_or_contested_with_active_citation,
            supported_or_contested_findings,
        ),
    }


def _uncertainty_metrics(connection: sqlite3.Connection) -> dict[str, int | None]:
    finding_count = _scalar(connection, "SELECT COUNT(*) FROM findings")
    explicit_uncertainty_count = _scalar(
        connection,
        "SELECT COUNT(*) FROM findings WHERE length(trim(uncertainty)) > 0",
    )
    claim_count = _scalar(connection, "SELECT COUNT(*) FROM claims")
    claims_with_status = _scalar(
        connection,
        "SELECT COUNT(DISTINCT claim_id) FROM claim_status_events",
    )
    unresolved_count = _scalar(
        connection,
        """
        SELECT COUNT(*) FROM findings
        WHERE status = 'inconclusive' OR statement_kind = 'unresolved_question'
        """,
    )
    return {
        "finding_explicit_uncertainty_count": explicit_uncertainty_count,
        "finding_explicit_uncertainty_ppm": _ppm(explicit_uncertainty_count, finding_count),
        "claims_with_recorded_status_count": claims_with_status,
        "claims_with_recorded_status_ppm": _ppm(claims_with_status, claim_count),
        "inconclusive_or_unresolved_finding_count": unresolved_count,
    }


def _operator_effort_metrics(connection: sqlite3.Connection) -> dict[str, object]:
    rows = list(
        connection.execute(
            """
            WITH first_evidence AS (
                SELECT mission_id, MIN(sequence) AS sequence
                FROM audit_events
                WHERE event_type = 'evidence.card.created'
                GROUP BY mission_id
            )
            SELECT mission.created_at AS mission_created_at,
                   first_evidence.sequence AS first_evidence_sequence,
                   evidence_event.occurred_at AS first_evidence_at,
                   (
                       SELECT MIN(snapshot.imported_at)
                       FROM source_snapshots AS snapshot
                       WHERE snapshot.mission_id = mission.id
                         AND snapshot.imported_at <= evidence_event.occurred_at
                   ) AS first_source_at,
                   (
                       SELECT COUNT(*) FROM audit_events AS event
                       WHERE event.mission_id = mission.id
                         AND event.sequence <= first_evidence.sequence
                   ) AS audited_events_to_first_evidence
            FROM research_missions AS mission
            JOIN first_evidence ON first_evidence.mission_id = mission.id
            JOIN audit_events AS evidence_event
              ON evidence_event.sequence = first_evidence.sequence
            ORDER BY mission.created_at, mission.id
            """
        )
    )
    event_counts: list[int] = []
    mission_seconds: list[float] = []
    source_seconds: list[float] = []
    for row in rows:
        event_counts.append(int(row["audited_events_to_first_evidence"]))
        first_evidence_at = str(row["first_evidence_at"])
        mission_seconds.append(_elapsed_seconds(str(row["mission_created_at"]), first_evidence_at))
        if row["first_source_at"] is not None:
            source_seconds.append(_elapsed_seconds(str(row["first_source_at"]), first_evidence_at))
    return {
        "missions_reaching_first_evidence_count": len(rows),
        "audited_events_to_first_evidence": _summary(event_counts),
        "mission_to_first_evidence_seconds": _summary(mission_seconds),
        "source_to_first_evidence_seconds": _summary(source_seconds),
        "measurement_boundary": (
            "Audited domain events measure durable workflow actions; they do not count "
            "clicks, keystrokes, reading time, or unrecorded deliberation."
        ),
    }


def evaluate_research_quality(
    database: Database,
    *,
    minimum_missions: int = 3,
) -> dict[str, object]:
    """Return aggregate real-corpus measures without exposing content or identifiers."""

    if isinstance(minimum_missions, bool) or not isinstance(minimum_missions, int):
        raise EvaluationError("minimum_missions must be an integer")
    if minimum_missions < 1:
        raise EvaluationError("minimum_missions must be positive")

    state_before = _logical_state_receipt(database)
    doctor = run_doctor(database, deep=True)
    if not doctor.ok:
        raise EvaluationError("deep database integrity must pass before evaluation")

    with database.read() as connection:
        mission_count = _scalar(connection, "SELECT COUNT(*) FROM research_missions")
        if mission_count < minimum_missions:
            raise EvaluationError(
                f"evaluation requires at least {minimum_missions} missions; found {mission_count}"
            )
        claim_count = _scalar(connection, "SELECT COUNT(*) FROM claims")
        evidence_count = _scalar(connection, "SELECT COUNT(*) FROM evidence_cards")
        finding_count = _scalar(connection, "SELECT COUNT(*) FROM findings")
        audit_event_count = _scalar(connection, "SELECT COUNT(*) FROM audit_events")
        quality = _quality_metrics(connection)
        uncertainty = _uncertainty_metrics(connection)
        operator_effort = _operator_effort_metrics(connection)

    state_after = _logical_state_receipt(database)
    if state_after != state_before:
        raise EvaluationError("evaluation changed the durable corpus")

    return {
        "schema_version": SCHEMA_VERSION,
        "algorithm": ALGORITHM,
        "algorithm_version": ALGORITHM_VERSION,
        "corpus_scope": "owner-managed persistent local corpus",
        "mission_count": mission_count,
        "claim_count": claim_count,
        "evidence_card_count": evidence_count,
        "finding_count": finding_count,
        "audit_event_count": audit_event_count,
        "research_quality": quality,
        "uncertainty": uncertainty,
        "operator_effort": operator_effort,
        "deep_integrity": True,
        "logical_state_receipt_before": state_before,
        "logical_state_receipt_after": state_after,
        "read_only": True,
        "provider_invocation_count": 0,
        "network_invocation_count": 0,
        "privacy_boundary": "Aggregate metrics only; content, identifiers, and paths are omitted.",
        "limitations": [
            "Structural provenance metrics do not independently verify external truth "
            "or source quality.",
            "Audited events are a lower bound on operator effort, not interaction telemetry.",
            "This baseline measures the current corpus and must be repeated as genuine "
            "missions accrue.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--minimum-missions", type=int, default=3)
    args = parser.parse_args()
    try:
        result = evaluate_research_quality(
            Database(args.db),
            minimum_missions=args.minimum_missions,
        )
    except EvaluationError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
