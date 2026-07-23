"""Read-only fulfillment of validated local research requests."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database
from minerva.core.errors import (
    ConflictError,
    IntegrityError,
    NotFoundError,
    SecurityBoundaryError,
)
from minerva.integrations.research_request import (
    MAX_EXPECTED_ACTIVE_CITATION_IDS,
    RESEARCH_RESULT_SCHEMA_VERSION,
    ResearchRequestDocument,
    serialize_research_result,
)
from minerva.synthesis.service import (
    MAX_SYNTHESIS_RECORDS,
    SynthesisService,
    write_research_request_artifacts,
)

_FULFILLED_STATUS = "fulfilled"
MAX_REQUEST_QUERY_VM_STEPS = 8_000_000
_QUERY_PROGRESS_GRANULARITY = 1_000


@dataclass(frozen=True, slots=True)
class ResearchRequestFulfillmentResult:
    """Deterministic fulfillment metadata without filesystem references."""

    schema_version: str
    status: str
    request_digest: str
    output_schema_version: str
    output_sha256: str


class ResearchRequestFulfillmentService:
    """Resolve one validated request without mutating research state."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self._synthesis = SynthesisService(database)

    def fulfill(
        self,
        *,
        request: ResearchRequestDocument,
        output_dir: Path,
    ) -> ResearchRequestFulfillmentResult:
        requested = request.request
        expected_citation_ids = requested.evidence_selection.expected_active_citation_ids

        with self.database.read() as connection:
            connection.execute("PRAGMA query_only = ON")
            with _bounded_query_work(connection):
                mission = connection.execute(
                    "SELECT 1 FROM research_missions WHERE id = ?",
                    (requested.mission_id,),
                ).fetchone()
                if mission is None:
                    raise NotFoundError("mission_not_found")
                claim = connection.execute(
                    """
                    SELECT claim.mission_id
                    FROM claims AS claim
                    WHERE claim.id = ?
                      AND EXISTS (
                          SELECT 1
                          FROM claim_status_events AS status
                               INDEXED BY idx_claim_status_claim
                          WHERE status.claim_id = claim.id
                      )
                    """,
                    (requested.claim_id,),
                ).fetchone()
                if claim is None:
                    raise NotFoundError("claim_not_found")
                if str(claim["mission_id"]) != requested.mission_id:
                    raise SecurityBoundaryError(
                        "request_claim_scope_invalid",
                        "The requested claim is outside the mission scope.",
                    )

                _validate_evidence_selection(
                    connection,
                    claim_id=requested.claim_id,
                    expected_citation_ids=expected_citation_ids,
                )

                brief_json = self._synthesis.build_research_packet_json(
                    requested.mission_id,
                    connection=connection,
                    claim_id=requested.claim_id,
                )

        output_sha256 = sha256(brief_json).hexdigest()
        result_json = serialize_research_result(
            request_digest=request.request_digest,
            output_artifact_sha256=output_sha256,
        )
        write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=brief_json,
            result_json=result_json,
        )
        return ResearchRequestFulfillmentResult(
            schema_version=RESEARCH_RESULT_SCHEMA_VERSION,
            status=_FULFILLED_STATUS,
            request_digest=request.request_digest,
            output_schema_version=requested.requested_output_schema,
            output_sha256=output_sha256,
        )


def _validate_evidence_selection(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    expected_citation_ids: tuple[str, ...],
) -> None:
    """Fail closed on scope, withdrawal, or active-ledger drift with bounded queries."""

    selected: dict[str, bool] = {}
    for citation_id in expected_citation_ids:
        row = connection.execute(
            """
            SELECT evidence.claim_id,
                   withdrawal.evidence_id IS NOT NULL AS withdrawn
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.id = ?
            """,
            (citation_id,),
        ).fetchone()
        if row is not None and str(row["claim_id"]) == claim_id:
            selected[citation_id] = bool(row["withdrawn"])

    if any(citation_id not in selected for citation_id in expected_citation_ids):
        raise SecurityBoundaryError(
            "request_evidence_scope_invalid",
            "Requested evidence is outside the claim scope.",
        )
    if any(selected[citation_id] for citation_id in expected_citation_ids):
        raise IntegrityError(
            "request_evidence_withdrawn",
            "The request selects withdrawn evidence.",
        )

    active_citation_ids = tuple(
        str(row["id"])
        for row in connection.execute(
            """
            SELECT evidence.id
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.claim_id = ?
              AND withdrawal.evidence_id IS NULL
            ORDER BY evidence.id
            LIMIT ?
            """,
            (claim_id, MAX_EXPECTED_ACTIVE_CITATION_IDS + 1),
        )
    )
    if expected_citation_ids != active_citation_ids:
        raise ConflictError(
            "request_evidence_selection_changed",
            "The active evidence selection has changed.",
        )

    history = list(
        connection.execute(
            """
            SELECT evidence.id,
                   withdrawal.evidence_id IS NOT NULL AS withdrawn
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.claim_id = ?
            ORDER BY evidence.created_at, evidence.id
            LIMIT ?
            """,
            (claim_id, MAX_SYNTHESIS_RECORDS + 1),
        )
    )
    if len(history) > MAX_SYNTHESIS_RECORDS:
        raise IntegrityError(
            "brief_work_limit",
            "The research brief exceeds synthesis limits.",
        )


@contextmanager
def _bounded_query_work(connection: sqlite3.Connection) -> Iterator[None]:
    """Bound cumulative SQLite VM work for one request fulfillment snapshot."""

    callbacks_remaining = MAX_REQUEST_QUERY_VM_STEPS // _QUERY_PROGRESS_GRANULARITY
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
        error_code = getattr(error, "sqlite_errorcode", None)
        if exhausted and error_code == sqlite3.SQLITE_INTERRUPT:
            raise IntegrityError(
                "brief_work_limit",
                "The research brief exceeds synthesis limits.",
            ) from error
        raise
    finally:
        connection.set_progress_handler(None, 0)
