"""Read-only fulfillment of validated local research requests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, SecurityBoundaryError
from minerva.integrations.research_request import (
    MAX_EXPECTED_ACTIVE_CITATION_IDS,
    RESEARCH_RESULT_SCHEMA_VERSION,
    ResearchRequestDocument,
    serialize_research_result,
)
from minerva.research.service import ResearchService
from minerva.synthesis.service import SynthesisService, write_research_request_artifacts

_FULFILLED_STATUS = "fulfilled"


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
        self._research = ResearchService(database)
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
            mission = self._research.get_mission(
                requested.mission_id,
                connection=connection,
            )
            claim = self._research.get_claim(
                requested.claim_id,
                connection=connection,
            )
            if claim.mission_id != mission.id:
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
    if expected_citation_ids:
        placeholders = ",".join("?" for _item in expected_citation_ids)
        rows = connection.execute(
            f"""
            SELECT evidence.id, withdrawal.evidence_id IS NOT NULL AS withdrawn
            FROM evidence_cards AS evidence
            LEFT JOIN evidence_withdrawals AS withdrawal
              ON withdrawal.evidence_id = evidence.id
            WHERE evidence.claim_id = ?
              AND evidence.id IN ({placeholders})
            """,  # noqa: S608 - placeholders, never request values, form the SQL text.
            (claim_id, *expected_citation_ids),
        )
        selected = {str(row["id"]): bool(row["withdrawn"]) for row in rows}

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
