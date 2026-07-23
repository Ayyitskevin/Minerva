"""Deterministic, citation-verified research brief assembly and export."""

from __future__ import annotations

import contextlib
import errno
import html
import os
import sqlite3
import stat
from hashlib import sha256
from pathlib import Path
from typing import Any

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now
from minerva.evidence.integrity import VerifiedCitation, verify_evidence_reference
from minerva.integrations.research_packet import (
    CITATION_SCHEME,
    RESEARCH_PACKET_SCHEMA_VERSION,
    build_research_packet,
    serialize_research_packet,
)
from minerva.research.models import ClaimStatus, StatementKind
from minerva.sources.integrity import verify_snapshot_integrity
from minerva.synthesis.models import BriefArtifacts, ExportResult

BRIEF_SCHEMA_VERSION = RESEARCH_PACKET_SCHEMA_VERSION
MAX_EXPORT_BYTES = 5_242_880
_MARKDOWN_NAME = "research-brief.md"
_RESULT_NAME = "research-result.json"
MAX_SYNTHESIS_SOURCE_BYTES = 20_971_520
MAX_SYNTHESIS_RECORDS = 50_000
MAX_SYNTHESIS_REFERENCES = 20_000
_JSON_NAME = "research-brief.json"

_PACKET_AUDIT_EVENT_TYPES = (
    "evidence.card.created",
    "evidence.card.withdrawn",
    "research.claim.created",
    "research.claim.status_changed",
    "research.finding.created",
    "research.mission.created",
    "research.question.created",
    "source.snapshot.imported",
)


class SynthesisService:
    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
        max_export_bytes: int = MAX_EXPORT_BYTES,
    ) -> None:
        if (
            isinstance(max_export_bytes, bool)
            or not isinstance(max_export_bytes, int)
            or not 1_024 <= max_export_bytes <= 20_971_520
        ):
            raise ValueError("max_export_bytes is outside the supported range")
        self.database = database
        self._clock = clock
        self._id_factory = id_factory
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)
        self._max_export_bytes = max_export_bytes

    def build_brief(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
        claim_id: str | None = None,
    ) -> BriefArtifacts:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.build_brief(
                    mission_id,
                    connection=owned_connection,
                    claim_id=claim_id,
                )
        return _assemble_brief(
            connection,
            mission_id=mission_id,
            max_export_bytes=self._max_export_bytes,
            claim_id=claim_id,
        )

    def build_research_packet_json(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
        claim_id: str | None = None,
    ) -> bytes:
        """Assemble only the canonical JSON packet for JSON-only consumers."""

        if connection is None:
            with self.database.read() as owned_connection:
                return self.build_research_packet_json(
                    mission_id,
                    connection=owned_connection,
                    claim_id=claim_id,
                )
        return _assemble_brief(
            connection,
            mission_id=mission_id,
            max_export_bytes=self._max_export_bytes,
            claim_id=claim_id,
            include_markdown=False,
        ).json

    def export_brief(
        self,
        *,
        mission_id: str,
        output_dir: Path,
        identity: IdentityContext,
    ) -> ExportResult:
        with self.database.read() as connection:
            artifacts = _assemble_brief(
                connection,
                mission_id=mission_id,
                max_export_bytes=self._max_export_bytes,
            )
            audit_watermark = _audit_watermark(connection)

        root_fd = _open_output_directory(output_dir, create=True)
        written: list[_WrittenFile] = []
        export_id = self._id_factory("exp")
        created_at = self._clock()
        try:
            try:
                written.append(_write_exclusive(root_fd, _MARKDOWN_NAME, artifacts.markdown))
                written.append(_write_exclusive(root_fd, _JSON_NAME, artifacts.json))
                with self.database.transaction() as connection:
                    if _audit_watermark(connection) != audit_watermark:
                        raise ConflictError(
                            "export_snapshot_changed",
                            "Research state changed during export; retry the operation.",
                        )
                    self._audit.ensure_run(connection, identity)
                    connection.execute(
                        """
                        INSERT INTO brief_exports(
                            id, mission_id, schema_version, export_digest,
                            markdown_sha256, json_sha256, creator_id, run_id, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            export_id,
                            mission_id,
                            BRIEF_SCHEMA_VERSION,
                            artifacts.export_digest,
                            artifacts.markdown_sha256,
                            artifacts.json_sha256,
                            identity.actor_id,
                            identity.run_id,
                            created_at,
                        ),
                    )
                    self._audit.record(
                        connection,
                        identity=identity,
                        event_type="synthesis.brief.exported",
                        entity_type="research_brief",
                        entity_id=export_id,
                        mission_id=mission_id,
                        details={
                            "schema_version": BRIEF_SCHEMA_VERSION,
                            "export_digest": artifacts.export_digest,
                            "markdown_sha256": artifacts.markdown_sha256,
                            "json_sha256": artifacts.json_sha256,
                        },
                    )
            except BaseException:
                _clean_written(root_fd, written)
                raise
        finally:
            os.close(root_fd)

        return ExportResult(
            export_id=export_id,
            export_digest=artifacts.export_digest,
            markdown_sha256=artifacts.markdown_sha256,
            json_sha256=artifacts.json_sha256,
            markdown_path=output_dir / _MARKDOWN_NAME,
            json_path=output_dir / _JSON_NAME,
        )


def write_research_request_artifacts(
    *,
    output_dir: Path,
    brief_json: bytes,
    result_json: bytes,
) -> None:
    """Exclusively publish the fixed request-result files without database writes."""

    root_fd = _open_output_directory(output_dir, create=True)
    written: list[_WrittenFile] = []
    try:
        try:
            written.append(_write_exclusive(root_fd, _JSON_NAME, brief_json))
            written.append(_write_exclusive(root_fd, _RESULT_NAME, result_json))
        except BaseException:
            _clean_written(root_fd, written)
            raise
    finally:
        os.close(root_fd)


def _audit_watermark(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM audit_events").fetchone()
    return int(row[0])


def _preflight_synthesis(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str | None,
) -> None:
    if claim_id is not None:
        row = connection.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(ss.byte_length)
                    FROM source_snapshots AS ss
                    WHERE ss.mission_id = ?
                      AND EXISTS (
                          SELECT 1 FROM evidence_cards AS evidence
                          WHERE evidence.snapshot_id = ss.id
                            AND evidence.claim_id = ?
                      )
                ), 0) AS source_bytes,
                (
                    2 +
                    (SELECT COUNT(*) FROM claim_status_events WHERE claim_id = ?) +
                    (
                        SELECT COUNT(DISTINCT snapshot_id)
                        FROM evidence_cards WHERE claim_id = ?
                    ) +
                    (SELECT COUNT(*) FROM evidence_cards WHERE claim_id = ?) +
                    (SELECT COUNT(*) FROM findings WHERE claim_id = ?)
                ) AS record_count,
                (
                    SELECT COUNT(*)
                    FROM finding_citations AS reference
                    JOIN findings AS finding ON finding.id = reference.finding_id
                    WHERE finding.claim_id = ?
                ) AS reference_count
            """,
            (mission_id, claim_id, claim_id, claim_id, claim_id, claim_id, claim_id),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT
                COALESCE((
                    SELECT SUM(byte_length) FROM source_snapshots WHERE mission_id = ?
                ), 0) AS source_bytes,
                (
                    (SELECT COUNT(*) FROM research_questions WHERE mission_id = ?) +
                    (SELECT COUNT(*) FROM claims WHERE mission_id = ?) +
                    (SELECT COUNT(*) FROM claim_status_events WHERE mission_id = ?) +
                    (SELECT COUNT(*) FROM source_snapshots WHERE mission_id = ?) +
                    (SELECT COUNT(*) FROM evidence_cards WHERE mission_id = ?) +
                    (SELECT COUNT(*) FROM findings WHERE mission_id = ?)
                ) AS record_count,
                (
                    SELECT COUNT(*) FROM finding_citations WHERE mission_id = ?
                ) AS reference_count
            """,
            (mission_id,) * 8,
        ).fetchone()
    if row is None:
        raise IntegrityError("brief_work_limit", "The research brief exceeds synthesis limits.")
    if (
        int(row["source_bytes"]) > MAX_SYNTHESIS_SOURCE_BYTES
        or int(row["record_count"]) > MAX_SYNTHESIS_RECORDS
        or int(row["reference_count"]) > MAX_SYNTHESIS_REFERENCES
    ):
        raise IntegrityError("brief_work_limit", "The research brief exceeds synthesis limits.")


def _claim_status_evidence_valid(
    status: ClaimStatus,
    *,
    has_active_support: bool,
    has_active_opposition: bool,
) -> bool:
    if status is ClaimStatus.PROVISIONALLY_SUPPORTED:
        return has_active_support
    if status is ClaimStatus.CONTESTED:
        return has_active_support and has_active_opposition
    if status is ClaimStatus.UNSUPPORTED:
        return has_active_opposition
    return True


def _packet_audit_references(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str | None = None,
) -> list[dict[str, Any]]:
    if claim_id is None:
        mission_rows = list(
            connection.execute(
                """
                SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                       actor_id, run_id, occurred_at
                FROM audit_events
                WHERE mission_id = ? AND event_type IN (?, ?, ?, ?, ?, ?, ?, ?)
                ORDER BY sequence
                """,
                (mission_id, *_PACKET_AUDIT_EVENT_TYPES),
            )
        )
        run_ids = sorted({str(row["run_id"]) for row in mission_rows})
        run_rows: list[sqlite3.Row] = []
        for run_id in run_ids:
            rows = list(
                connection.execute(
                    """
                    SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                           actor_id, run_id, occurred_at
                    FROM audit_events
                    WHERE event_type = 'research.run.started'
                      AND entity_type = 'research_run'
                      AND entity_id = ?
                    """,
                    (run_id,),
                )
            )
            if len(rows) != 1:
                raise IntegrityError(
                    "packet_provenance_invalid",
                    "Research packet provenance could not be resolved.",
                )
            run_rows.append(rows[0])
        rows = sorted((*run_rows, *mission_rows), key=lambda row: int(row["sequence"]))
    else:
        rows = _scoped_packet_audit_rows(
            connection,
            mission_id=mission_id,
            claim_id=claim_id,
        )

    return [
        {
            "sequence": int(row["sequence"]),
            "id": str(row["id"]),
            "event_type": str(row["event_type"]),
            "entity_type": str(row["entity_type"]),
            "entity_id": str(row["entity_id"]),
            "mission_id": (str(row["mission_id"]) if row["mission_id"] is not None else None),
            "actor_id": str(row["actor_id"]),
            "run_id": str(row["run_id"]),
            "occurred_at": str(row["occurred_at"]),
        }
        for row in rows
    ]


def _scoped_packet_audit_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str,
) -> list[sqlite3.Row]:
    rows = list(
        connection.execute(
            """
            WITH relevant_events AS MATERIALIZED (
                SELECT audit.sequence, audit.id, audit.event_type, audit.entity_type,
                       audit.entity_id, audit.mission_id, audit.actor_id, audit.run_id,
                       audit.occurred_at
                FROM audit_events AS audit
                WHERE audit.mission_id = ?
                  AND audit.event_type IN (?, ?, ?, ?, ?, ?, ?, ?)
                  AND (
                      (audit.entity_type = 'research_mission' AND audit.entity_id = ?)
                      OR (
                          audit.entity_type = 'research_question'
                          AND EXISTS (
                              SELECT 1 FROM claims AS target
                              WHERE target.id = ? AND target.question_id = audit.entity_id
                          )
                      )
                      OR (audit.entity_type = 'claim' AND audit.entity_id = ?)
                      OR (
                          audit.entity_type = 'source_snapshot'
                          AND EXISTS (
                              SELECT 1 FROM evidence_cards AS evidence
                              WHERE evidence.claim_id = ?
                                AND evidence.snapshot_id = audit.entity_id
                          )
                      )
                      OR (
                          audit.entity_type = 'evidence_card'
                          AND EXISTS (
                              SELECT 1 FROM evidence_cards AS evidence
                              WHERE evidence.id = audit.entity_id
                                AND evidence.claim_id = ?
                          )
                      )
                      OR (
                          audit.entity_type = 'finding'
                          AND EXISTS (
                              SELECT 1 FROM findings AS finding
                              WHERE finding.id = audit.entity_id
                                AND finding.claim_id = ?
                          )
                      )
                  )
                ORDER BY audit.sequence
                LIMIT ?
            ),
            required_runs AS (
                SELECT DISTINCT run_id FROM relevant_events
            )
            SELECT sequence, id, event_type, entity_type, entity_id, mission_id,
                   actor_id, run_id, occurred_at
            FROM relevant_events
            UNION ALL
            SELECT started.sequence, started.id, started.event_type, started.entity_type,
                   started.entity_id, started.mission_id, started.actor_id, started.run_id,
                   started.occurred_at
            FROM audit_events AS started
            JOIN required_runs ON required_runs.run_id = started.entity_id
            WHERE started.event_type = 'research.run.started'
              AND started.entity_type = 'research_run'
            ORDER BY sequence
            LIMIT ?
            """,
            (
                mission_id,
                *_PACKET_AUDIT_EVENT_TYPES,
                mission_id,
                claim_id,
                claim_id,
                claim_id,
                claim_id,
                claim_id,
                MAX_SYNTHESIS_RECORDS + 1,
                MAX_SYNTHESIS_RECORDS + 1,
            ),
        )
    )
    if len(rows) > MAX_SYNTHESIS_RECORDS:
        raise IntegrityError("brief_work_limit", "The research brief exceeds synthesis limits.")

    mission_rows = [row for row in rows if str(row["event_type"]) != "research.run.started"]
    run_rows = [row for row in rows if str(row["event_type"]) == "research.run.started"]
    required_run_ids = {str(row["run_id"]) for row in mission_rows}
    if (
        len(run_rows) != len(required_run_ids)
        or {str(row["entity_id"]) for row in run_rows} != required_run_ids
        or any(str(row["run_id"]) != str(row["entity_id"]) for row in run_rows)
    ):
        raise IntegrityError(
            "packet_provenance_invalid",
            "Research packet provenance could not be resolved.",
        )
    return rows


def _packet_runs(
    connection: sqlite3.Connection,
    *,
    audit_references: list[dict[str, Any]],
) -> list[dict[str, str]]:
    run_ids = sorted({str(reference["run_id"]) for reference in audit_references})
    runs: list[dict[str, str]] = []
    for run_id in run_ids:
        row = connection.execute(
            """
            SELECT id, actor_id, actor_kind, purpose, created_at
            FROM research_runs WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise IntegrityError(
                "packet_provenance_invalid",
                "Research packet provenance could not be resolved.",
            )
        runs.append(
            {
                "id": str(row["id"]),
                "actor_id": str(row["actor_id"]),
                "actor_kind": str(row["actor_kind"]),
                "purpose": str(row["purpose"]),
                "created_at": str(row["created_at"]),
            }
        )
    return sorted(runs, key=lambda item: (item["created_at"], item["id"]))


def _assemble_brief(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    max_export_bytes: int,
    claim_id: str | None = None,
    include_markdown: bool = True,
) -> BriefArtifacts:
    mission = connection.execute(
        """
        SELECT id, title, objective, creator_id, run_id, created_at
        FROM research_missions WHERE id = ?
        """,
        (mission_id,),
    ).fetchone()
    if mission is None:
        raise NotFoundError("mission_not_found")

    selected_question_id: str | None = None
    if claim_id is not None:
        selected_claim = connection.execute(
            """
            SELECT question_id FROM claims
            WHERE id = ? AND mission_id = ?
            """,
            (claim_id, mission_id),
        ).fetchone()
        if selected_claim is None:
            raise NotFoundError("claim_not_found")
        selected_question_id = str(selected_claim["question_id"])

    _preflight_synthesis(connection, mission_id=mission_id, claim_id=claim_id)
    if selected_question_id is None:
        question_rows = connection.execute(
            """
            SELECT id, question_text, creator_id, run_id, created_at
            FROM research_questions
            WHERE mission_id = ? ORDER BY created_at, id
            """,
            (mission_id,),
        )
    else:
        question_rows = connection.execute(
            """
            SELECT id, question_text, creator_id, run_id, created_at
            FROM research_questions
            WHERE mission_id = ? AND id = ? ORDER BY created_at, id
            """,
            (mission_id, selected_question_id),
        )
    questions = [
        {
            "id": str(row["id"]),
            "text": str(row["question_text"]),
            "creator_id": str(row["creator_id"]),
            "run_id": str(row["run_id"]),
            "created_at": str(row["created_at"]),
            "epistemic_role": "research_question",
        }
        for row in question_rows
    ]

    if claim_id is None:
        source_rows = connection.execute(
            """
            SELECT ss.id, ss.source_id, ss.mission_id, ss.content, ss.sha256, ss.byte_length,
                   ss.encoding, ss.media_type, ss.original_label, ss.imported_at,
                   ss.creator_id, ss.run_id, s.url_metadata
            FROM source_snapshots AS ss
            JOIN sources AS s ON s.id = ss.source_id
            WHERE ss.mission_id = ? ORDER BY ss.imported_at, ss.id
            """,
            (mission_id,),
        )
    else:
        source_rows = connection.execute(
            """
            SELECT ss.id, ss.source_id, ss.mission_id, ss.content, ss.sha256, ss.byte_length,
                   ss.encoding, ss.media_type, ss.original_label, ss.imported_at,
                   ss.creator_id, ss.run_id, s.url_metadata
            FROM source_snapshots AS ss
            JOIN sources AS s ON s.id = ss.source_id
            WHERE ss.mission_id = ?
              AND EXISTS (
                  SELECT 1 FROM evidence_cards AS evidence
                  WHERE evidence.snapshot_id = ss.id AND evidence.claim_id = ?
              )
            ORDER BY ss.imported_at, ss.id
            """,
            (mission_id, claim_id),
        )
    sources: list[dict[str, Any]] = []
    for row in source_rows:
        verify_snapshot_integrity(connection, row)
        sources.append(
            {
                "snapshot_id": str(row["id"]),
                "source_id": str(row["source_id"]),
                "original_label": str(row["original_label"]),
                "media_type": str(row["media_type"]),
                "encoding": str(row["encoding"]),
                "byte_length": int(row["byte_length"]),
                "sha256": str(row["sha256"]),
                "imported_at": str(row["imported_at"]),
                "creator_id": str(row["creator_id"]),
                "run_id": str(row["run_id"]),
                "url_metadata": (
                    str(row["url_metadata"]) if row["url_metadata"] is not None else None
                ),
            }
        )

    if claim_id is None:
        evidence_rows = list(
            connection.execute(
                """
                SELECT e.id, e.claim_id, e.supersedes_evidence_id,
                       e.creator_id, e.run_id, e.created_at,
                       w.reason AS withdrawal_reason,
                       w.creator_id AS withdrawal_creator_id,
                       w.run_id AS withdrawal_run_id,
                       w.created_at AS withdrawn_at
                FROM evidence_cards AS e
                LEFT JOIN evidence_withdrawals AS w ON w.evidence_id = e.id
                WHERE e.mission_id = ? ORDER BY e.created_at, e.id
                """,
                (mission_id,),
            )
        )
    else:
        evidence_rows = list(
            connection.execute(
                """
                SELECT e.id, e.claim_id, e.supersedes_evidence_id,
                       e.creator_id, e.run_id, e.created_at,
                       w.reason AS withdrawal_reason,
                       w.creator_id AS withdrawal_creator_id,
                       w.run_id AS withdrawal_run_id,
                       w.created_at AS withdrawn_at
                FROM evidence_cards AS e
                LEFT JOIN evidence_withdrawals AS w ON w.evidence_id = e.id
                WHERE e.mission_id = ? AND e.claim_id = ?
                ORDER BY e.created_at, e.id
                """,
                (mission_id, claim_id),
            )
        )
    verified_citations: list[VerifiedCitation] = []
    supersedes: dict[str, str | None] = {}
    citation_provenance: dict[str, dict[str, str | None]] = {}
    for row in evidence_rows:
        evidence_id = str(row["id"])
        verified_citations.append(
            verify_evidence_reference(
                connection,
                evidence_id=evidence_id,
                mission_id=mission_id,
                allow_withdrawn=True,
            )
        )
        supersedes[evidence_id] = (
            str(row["supersedes_evidence_id"])
            if row["supersedes_evidence_id"] is not None
            else None
        )
        citation_provenance[evidence_id] = {
            "creator_id": str(row["creator_id"]),
            "run_id": str(row["run_id"]),
            "created_at": str(row["created_at"]),
            "withdrawal_reason": (
                str(row["withdrawal_reason"]) if row["withdrawal_reason"] is not None else None
            ),
            "withdrawal_creator_id": (
                str(row["withdrawal_creator_id"])
                if row["withdrawal_creator_id"] is not None
                else None
            ),
            "withdrawal_run_id": (
                str(row["withdrawal_run_id"]) if row["withdrawal_run_id"] is not None else None
            ),
            "withdrawn_at": (str(row["withdrawn_at"]) if row["withdrawn_at"] is not None else None),
        }

    verified_by_id = {citation.evidence_id: citation for citation in verified_citations}

    citations = [
        {
            "citation_id": citation.evidence_id,
            "claim_id": citation.claim_id,
            "snapshot_id": citation.snapshot_id,
            "snapshot_sha256": citation.snapshot_sha256,
            "source_label": citation.source_label,
            "location": {
                "scheme": CITATION_SCHEME,
                "start_byte": citation.start_byte,
                "end_byte": citation.end_byte,
            },
            "quote": citation.quote,
            "stance": citation.stance.value,
            "creator_id": citation_provenance[citation.evidence_id]["creator_id"],
            "run_id": citation_provenance[citation.evidence_id]["run_id"],
            "created_at": citation_provenance[citation.evidence_id]["created_at"],
            "withdrawn": citation.withdrawn,
            "withdrawal_reason": citation_provenance[citation.evidence_id]["withdrawal_reason"],
            "withdrawal_creator_id": citation_provenance[citation.evidence_id][
                "withdrawal_creator_id"
            ],
            "withdrawal_run_id": citation_provenance[citation.evidence_id]["withdrawal_run_id"],
            "withdrawn_at": citation_provenance[citation.evidence_id]["withdrawn_at"],
            "supersedes_citation_id": supersedes[citation.evidence_id],
        }
        for citation in verified_citations
    ]
    citations_by_claim: dict[str, list[dict[str, Any]]] = {}
    for citation in citations:
        citations_by_claim.setdefault(str(citation["claim_id"]), []).append(citation)

    if claim_id is None:
        claim_rows = connection.execute(
            """
            SELECT c.id, c.question_id, c.statement, c.falsification_criteria,
                   c.creator_id, c.run_id, c.created_at,
                   s.status, s.version, s.reason, s.creator_id AS status_creator_id,
                   s.run_id AS status_run_id, s.created_at AS status_changed_at,
                   (
                       SELECT COUNT(*) FROM claim_status_events AS history
                       WHERE history.claim_id = c.id
                   ) AS status_event_count
            FROM claims AS c
            JOIN claim_status_events AS s
              ON s.claim_id = c.id
             AND s.version = (
                 SELECT MAX(s2.version)
                 FROM claim_status_events AS s2
                 WHERE s2.claim_id = c.id
             )
            WHERE c.mission_id = ?
            ORDER BY c.created_at, c.id
            """,
            (mission_id,),
        )
    else:
        claim_rows = connection.execute(
            """
            SELECT c.id, c.question_id, c.statement, c.falsification_criteria,
                   c.creator_id, c.run_id, c.created_at,
                   s.status, s.version, s.reason, s.creator_id AS status_creator_id,
                   s.run_id AS status_run_id, s.created_at AS status_changed_at,
                   (
                       SELECT COUNT(*) FROM claim_status_events AS history
                       WHERE history.claim_id = c.id
                   ) AS status_event_count
            FROM claims AS c
            JOIN claim_status_events AS s
              ON s.claim_id = c.id
             AND s.version = (
                 SELECT MAX(s2.version)
                 FROM claim_status_events AS s2
                 WHERE s2.claim_id = c.id
             )
            WHERE c.mission_id = ? AND c.id = ?
            ORDER BY c.created_at, c.id
            """,
            (mission_id, claim_id),
        )
    claims: list[dict[str, Any]] = []
    for row in claim_rows:
        current_claim_id = str(row["id"])
        if int(row["status_event_count"]) != int(row["version"]):
            raise IntegrityError(
                "packet_provenance_invalid",
                "Research packet provenance could not be resolved.",
            )
        claim_citations = citations_by_claim.get(current_claim_id, [])
        active_support = any(
            item["stance"] == "supports" and not item["withdrawn"] for item in claim_citations
        )
        active_opposition = any(
            item["stance"] == "opposes" and not item["withdrawn"] for item in claim_citations
        )
        status = ClaimStatus(str(row["status"]))
        status_evidence_valid = _claim_status_evidence_valid(
            status,
            has_active_support=active_support,
            has_active_opposition=active_opposition,
        )
        claims.append(
            {
                "id": current_claim_id,
                "question_id": str(row["question_id"]),
                "statement": str(row["statement"]),
                "falsification_criteria": str(row["falsification_criteria"]),
                "creator_id": str(row["creator_id"]),
                "run_id": str(row["run_id"]),
                "created_at": str(row["created_at"]),
                "status": status.value,
                "version": int(row["version"]),
                "status_reason": str(row["reason"]),
                "status_creator_id": str(row["status_creator_id"]),
                "status_run_id": str(row["status_run_id"]),
                "status_changed_at": str(row["status_changed_at"]),
                "status_evidence_valid": status_evidence_valid,
                "epistemic_role": "claim_under_evaluation",
                "contested": (
                    status is ClaimStatus.CONTESTED or (active_support and active_opposition)
                ),
                "evidence_ledger": [
                    {
                        "citation_id": item["citation_id"],
                        "stance": item["stance"],
                        "withdrawn": item["withdrawn"],
                    }
                    for item in claim_citations
                ],
            }
        )

    material_findings: list[dict[str, Any]] = []
    assumptions: list[dict[str, Any]] = []
    unresolved_questions: list[dict[str, Any]] = []
    uncertainties: list[dict[str, str]] = []
    if claim_id is None:
        finding_rows = connection.execute(
            """
            SELECT id, claim_id, statement, statement_kind, status, uncertainty,
                   creator_id, run_id, created_at
            FROM findings WHERE mission_id = ? ORDER BY created_at, id
            """,
            (mission_id,),
        )
    else:
        finding_rows = connection.execute(
            """
            SELECT id, claim_id, statement, statement_kind, status, uncertainty,
                   creator_id, run_id, created_at
            FROM findings
            WHERE mission_id = ? AND claim_id = ?
            ORDER BY created_at, id
            """,
            (mission_id, claim_id),
        )
    for row in finding_rows:
        finding_id = str(row["id"])
        kind = StatementKind(str(row["statement_kind"]))
        evidence_ids = [
            str(item["evidence_id"])
            for item in connection.execute(
                """
                SELECT evidence_id FROM finding_citations
                WHERE finding_id = ? ORDER BY evidence_id
                """,
                (finding_id,),
            )
        ]
        if kind.requires_citation and not evidence_ids:
            raise IntegrityError(
                "uncited_material_finding",
                "A material finding is missing required citations.",
            )
        linked_claim = str(row["claim_id"]) if row["claim_id"] is not None else None
        for evidence_id in evidence_ids:
            verified = verified_by_id.get(evidence_id)
            if verified is None:
                raise IntegrityError("citation_tampered", "Stored citation integrity failed.")
            if verified.withdrawn:
                raise IntegrityError(
                    "citation_withdrawn", "Withdrawn evidence cannot support a finding."
                )
            if linked_claim is not None and verified.claim_id != linked_claim:
                raise IntegrityError(
                    "finding_citation_scope_invalid",
                    "A finding citation evaluates a different claim.",
                )
        item = {
            "id": finding_id,
            "claim_id": linked_claim,
            "statement": str(row["statement"]),
            "statement_kind": kind.value,
            "status": str(row["status"]),
            "citation_ids": evidence_ids,
            "uncertainty": str(row["uncertainty"]),
            "creator_id": str(row["creator_id"]),
            "run_id": str(row["run_id"]),
            "created_at": str(row["created_at"]),
        }
        if kind is StatementKind.ASSUMPTION:
            assumptions.append(item)
        elif kind is StatementKind.UNRESOLVED_QUESTION:
            unresolved_questions.append(item)
        else:
            material_findings.append(item)
        if str(row["uncertainty"]):
            uncertainties.append({"finding_id": finding_id, "text": str(row["uncertainty"])})

    audit_references = _packet_audit_references(
        connection,
        mission_id=mission_id,
        claim_id=claim_id,
    )
    runs = _packet_runs(connection, audit_references=audit_references)

    payload: dict[str, Any] = {
        "schema_version": BRIEF_SCHEMA_VERSION,
        "doctrine": (
            "Minerva records evidence and uncertainty; it does not manufacture certainty."
        ),
        "ownership": {
            "system": "minerva",
            "researches": True,
            "executes": False,
            "approves": False,
            "orchestrates": False,
            "publishes": False,
        },
        "mission": {
            "id": str(mission["id"]),
            "title": str(mission["title"]),
            "objective": str(mission["objective"]),
            "creator_id": str(mission["creator_id"]),
            "run_id": str(mission["run_id"]),
            "created_at": str(mission["created_at"]),
            "epistemic_role": "research_scope",
        },
        "questions": questions,
        "claims": claims,
        "findings": material_findings,
        "assumptions": assumptions,
        "unresolved_questions": unresolved_questions,
        "uncertainties": uncertainties,
        "citations": citations,
        "sources": sources,
        "runs": runs,
        "audit_references": audit_references,
        "integrity": {
            "citation_scheme": CITATION_SCHEME,
            "source_digest_algorithm": "sha256",
            "export_digest_algorithm": "sha256-canonical-json-v1",
            "material_statement_policy": (
                "Findings, calculations, and recommendations require exact citations; "
                "claims are labeled propositions under evaluation; assumptions and "
                "unresolved questions are explicitly non-evidentiary."
            ),
        },
    }

    try:
        document = build_research_packet(payload)
        json_bytes = serialize_research_packet(document)
    except ValueError as error:
        raise IntegrityError(
            "packet_integrity_invalid",
            "Research packet integrity validation failed.",
        ) from error
    validated_payload = document.brief.model_dump(mode="json")
    export_digest = document.export_digest
    markdown_bytes = (
        _render_markdown(
            validated_payload,
            export_digest=export_digest,
        ).encode("utf-8")
        if include_markdown
        else b""
    )

    if len(json_bytes) > max_export_bytes or (
        include_markdown and len(markdown_bytes) > max_export_bytes
    ):
        raise IntegrityError("brief_too_large", "The research brief exceeds the export limit.")

    return BriefArtifacts(
        payload=validated_payload,
        export_digest=export_digest,
        markdown=markdown_bytes,
        json=json_bytes,
        markdown_sha256=sha256(markdown_bytes).hexdigest(),
        json_sha256=sha256(json_bytes).hexdigest(),
    )


def _render_markdown(payload: dict[str, Any], *, export_digest: str) -> str:
    mission = payload["mission"]
    lines = [
        f"# Research brief: {_md_inline(mission['title'])}",
        "",
        "> Minerva records evidence and uncertainty; it does not manufacture certainty.",
        "",
        f"- Schema: **{BRIEF_SCHEMA_VERSION}**",
        f"- Export digest (SHA-256): **{export_digest}**",
        f"- Mission ID: **{mission['id']}**",
        "",
        "## Research scope (not a conclusion)",
        "",
        _md_paragraph(mission["objective"]),
        "",
        "## Research questions",
        "",
    ]
    questions = payload["questions"]
    if questions:
        for question in questions:
            lines.append(f"- **{question['id']}** — {_md_inline(question['text'])}")
    else:
        lines.append("_No questions recorded._")

    lines.extend(["", "## Claims under evaluation", ""])
    citation_lookup = {citation["citation_id"]: citation for citation in payload["citations"]}
    claims = payload["claims"]
    if not claims:
        lines.append("_No claims recorded._")
    for claim in claims:
        contested = " — **CONTESTED**" if claim["contested"] else ""
        lines.extend(
            [
                f"### Claim **{claim['id']}**{contested}",
                "",
                f"- Status: **{claim['status']}**",
                "- Status rationale: " + _md_inline(claim["status_reason"]),
                (
                    "- Status provenance: "
                    + _md_inline(claim["status_creator_id"])
                    + f" in run **{claim['status_run_id']}** at "
                    + _md_inline(claim["status_changed_at"])
                ),
                "- Statement (proposition under evaluation): " + _md_inline(claim["statement"]),
                "- Falsification criterion: " + _md_inline(claim["falsification_criteria"]),
                "",
                "#### Evidence ledger (supporting and opposing)",
                "",
            ]
        )
        if not claim["status_evidence_valid"]:
            lines.append(
                "**WARNING:** This recorded workflow status no longer has its required active "
                "evidence. The historical label is retained; no replacement conclusion is inferred."
            )
        if not claim["evidence_ledger"]:
            lines.append("_No evidence cards recorded._")
        for ledger_item in claim["evidence_ledger"]:
            citation = citation_lookup[ledger_item["citation_id"]]
            withdrawn = " — **WITHDRAWN**" if citation["withdrawn"] else ""
            lines.append(
                f"- **{citation['stance'].upper()}** "
                f"**[{citation['citation_id']}]**{withdrawn}: "
                f"{_md_inline(citation['quote'])}"
            )

    lines.extend(["", "## Evidence-backed findings", ""])
    if not payload["findings"]:
        lines.append("_No material findings recorded._")
    for finding in payload["findings"]:
        citation_text = " ".join(f"**[{item}]**" for item in finding["citation_ids"])
        lines.extend(
            [
                f"### Finding **{finding['id']}**",
                "",
                f"- Class: **{finding['statement_kind']}**",
                f"- Status: **{finding['status']}**",
                f"- Statement: {_md_inline(finding['statement'])}",
                f"- Citations: {citation_text}",
            ]
        )

    lines.extend(["", "## Assumptions (explicitly non-evidentiary)", ""])
    if not payload["assumptions"]:
        lines.append("_No assumptions recorded._")
    for assumption in payload["assumptions"]:
        lines.append(f"- **{assumption['id']}** — {_md_inline(assumption['statement'])}")

    lines.extend(["", "## Unresolved questions", ""])
    if not payload["unresolved_questions"]:
        lines.append("_No unresolved questions recorded._")
    for question in payload["unresolved_questions"]:
        lines.append(f"- **{question['id']}** — {_md_inline(question['statement'])}")

    lines.extend(["", "## Uncertainty", ""])
    if not payload["uncertainties"]:
        lines.append("_No explicit uncertainty statements recorded._")
    for uncertainty in payload["uncertainties"]:
        lines.append(
            f"- Finding **{uncertainty['finding_id']}**: {_md_inline(uncertainty['text'])}"
        )

    lines.extend(["", "## Source snapshots", ""])
    for source in payload["sources"]:
        url_note = (
            f"; inert URL metadata: {_md_inline(source['url_metadata'])}"
            if source["url_metadata"]
            else ""
        )
        lines.append(
            f"- **{source['snapshot_id']}** — {_md_inline(source['original_label'])}; "
            f"SHA-256 **{source['sha256']}**; {source['byte_length']} bytes; "
            f"**{source['media_type']}**{url_note}"
        )
    if not payload["sources"]:
        lines.append("_No source snapshots recorded._")

    lines.extend(["", "## Citation resolution", ""])
    if not payload["citations"]:
        lines.append("_No citations recorded._")
    for citation in payload["citations"]:
        location = citation["location"]
        withdrawal = " **WITHDRAWN**" if citation["withdrawn"] else ""
        lines.extend(
            [
                f"### **[{citation['citation_id']}]**{withdrawal}",
                "",
                f"- Source: **{citation['snapshot_id']}** ({_md_inline(citation['source_label'])})",
                f"- Snapshot SHA-256: **{citation['snapshot_sha256']}**",
                f"- Location: **{location['scheme']}:{location['start_byte']}:"
                f"{location['end_byte']}**",
                f"- Stance: **{citation['stance']}**",
                "",
                _md_quote(citation["quote"]),
                "",
            ]
        )

    lines.extend(
        [
            "## Integrity note",
            "",
            "Claims above are labeled propositions under evaluation. Evidence stances are "
            "classifications, not truth values or confidence scores. Every material finding "
            "resolves through its citation IDs to exact stored source bytes.",
            "",
        ]
    )
    return "\n".join(lines)


def _md_inline(value: object) -> str:
    text = html.escape(str(value), quote=False).replace("\\", "\\\\")
    for marker in ("*", "_", "[", "]", "#", "|"):
        text = text.replace(marker, "\\" + marker)
    return text.replace("\r", " ").replace("\n", "  ")


def _md_paragraph(value: object) -> str:
    return "\n\n".join(_md_inline(part) for part in str(value).splitlines())


def _md_quote(value: object) -> str:
    return "\n".join("> " + _md_inline(line) for line in str(value).splitlines())


class _WrittenFile:
    __slots__ = ("device", "inode", "name")

    def __init__(self, name: str, device: int, inode: int) -> None:
        self.name = name
        self.device = device
        self.inode = inode


def _open_output_directory(path: Path, *, create: bool) -> int:
    absolute = Path(os.path.abspath(path))
    if "\x00" in os.fspath(absolute):
        raise IntegrityError("export_path_invalid", "The export directory is invalid.")
    descriptor = os.open("/", os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    try:
        components = absolute.parts[1:]
        if not components:
            raise IntegrityError(
                "export_path_invalid",
                "The filesystem root may not be used as an export directory.",
            )
        for index, component in enumerate(components):
            is_final = index == len(components) - 1
            try:
                next_descriptor = os.open(
                    component,
                    os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=descriptor,
                )
            except FileNotFoundError:
                if not create or not is_final:
                    raise IntegrityError(
                        "export_path_invalid",
                        "The export directory does not exist.",
                    ) from None
                try:
                    os.mkdir(component, mode=0o700, dir_fd=descriptor)
                    next_descriptor = os.open(
                        component,
                        os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=descriptor,
                    )
                except OSError as error:
                    raise IntegrityError(
                        "export_path_invalid",
                        "The export directory could not be created safely.",
                    ) from error
            except OSError as error:
                if error.errno in {errno.ELOOP, errno.ENOTDIR}:
                    raise IntegrityError(
                        "export_symlink_rejected",
                        "Symbolic links are not accepted in export paths.",
                    ) from error
                raise IntegrityError(
                    "export_path_invalid",
                    "The export directory is invalid.",
                ) from error
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_exclusive(directory_fd: int, name: str, content: bytes) -> _WrittenFile:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
    except FileExistsError as error:
        raise ConflictError(
            "export_target_exists",
            "Refusing to overwrite an existing research brief.",
        ) from error
    metadata: os.stat_result | None = None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise IntegrityError(
                "export_write_failed",
                "The research brief could not be written.",
            )
        view = memoryview(content)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise IntegrityError(
                    "export_write_failed",
                    "The research brief could not be written.",
                )
            written += count
        os.fsync(descriptor)
        return _WrittenFile(name, metadata.st_dev, metadata.st_ino)
    except BaseException:
        if metadata is not None:
            with contextlib.suppress(OSError):
                current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == (metadata.st_dev, metadata.st_ino):
                    os.unlink(name, dir_fd=directory_fd)
        raise
    finally:
        os.close(descriptor)


def _clean_written(directory_fd: int, written: list[_WrittenFile]) -> None:
    for item in reversed(written):
        try:
            current = os.stat(item.name, dir_fd=directory_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (item.device, item.inode):
                os.unlink(item.name, dir_fd=directory_fd)
        except OSError:
            continue
