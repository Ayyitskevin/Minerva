"""Shared commands and queries for research state."""

from __future__ import annotations

import sqlite3

from minerva.core.audit import AuditRecorder, AuditSink
from minerva.core.db import Database
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import Clock, IdentityContext, IdFactory, new_id, utc_now, validate_text
from minerva.evidence.integrity import verify_evidence_reference
from minerva.research.models import (
    CitationStatus,
    Claim,
    ClaimStatus,
    Finding,
    FindingStatus,
    Mission,
    Question,
    StatementKind,
)


class ResearchService:
    def __init__(
        self,
        database: Database,
        *,
        audit: AuditSink | None = None,
        clock: Clock = utc_now,
        id_factory: IdFactory = new_id,
    ) -> None:
        self.database = database
        self._clock = clock
        self._id_factory = id_factory
        self._audit = audit or AuditRecorder(clock=clock, id_factory=id_factory)

    def create_mission(
        self,
        *,
        title: str,
        objective: str,
        identity: IdentityContext,
    ) -> Mission:
        title = validate_text(title, field="title", maximum=200, allow_newlines=False)
        objective = validate_text(objective, field="objective", maximum=2_000)
        mission_id = self._id_factory("mis")
        created_at = self._clock()
        with self.database.transaction() as connection:
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO research_missions(
                    id, title, objective, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mission_id, title, objective, identity.actor_id, identity.run_id, created_at),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="research.mission.created",
                entity_type="research_mission",
                entity_id=mission_id,
                mission_id=mission_id,
                details={},
            )
        return Mission(
            mission_id,
            title,
            objective,
            identity.actor_id,
            identity.run_id,
            created_at,
        )

    def add_question(
        self,
        *,
        mission_id: str,
        text: str,
        identity: IdentityContext,
    ) -> Question:
        text = validate_text(text, field="question", maximum=2_000)
        question_id = self._id_factory("que")
        created_at = self._clock()
        with self.database.transaction() as connection:
            _require_mission(connection, mission_id)
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO research_questions(
                    id, mission_id, question_text, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    question_id,
                    mission_id,
                    text,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="research.question.created",
                entity_type="research_question",
                entity_id=question_id,
                mission_id=mission_id,
                details={},
            )
        return Question(
            question_id,
            mission_id,
            text,
            identity.actor_id,
            identity.run_id,
            created_at,
        )

    def add_claim(
        self,
        *,
        mission_id: str,
        question_id: str,
        statement: str,
        falsification_criteria: str,
        identity: IdentityContext,
    ) -> Claim:
        statement = validate_text(statement, field="claim", maximum=2_000)
        falsification_criteria = validate_text(
            falsification_criteria,
            field="falsification_criteria",
            maximum=2_000,
        )
        claim_id = self._id_factory("clm")
        status_id = self._id_factory("cst")
        created_at = self._clock()
        with self.database.transaction() as connection:
            question = connection.execute(
                "SELECT 1 FROM research_questions WHERE id = ? AND mission_id = ?",
                (question_id, mission_id),
            ).fetchone()
            if question is None:
                raise NotFoundError("question_not_found")
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO claims(
                    id, mission_id, question_id, statement, falsification_criteria,
                    creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    mission_id,
                    question_id,
                    statement,
                    falsification_criteria,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO claim_status_events(
                    id, claim_id, mission_id, version, status, reason,
                    creator_id, run_id, created_at
                ) VALUES (?, ?, ?, 1, 'open', ?, ?, ?, ?)
                """,
                (
                    status_id,
                    claim_id,
                    mission_id,
                    "Claim registered for evaluation.",
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="research.claim.created",
                entity_type="claim",
                entity_id=claim_id,
                mission_id=mission_id,
                details={"initial_status": ClaimStatus.OPEN.value},
            )
        return Claim(
            claim_id,
            mission_id,
            question_id,
            statement,
            falsification_criteria,
            ClaimStatus.OPEN,
            1,
            "Claim registered for evaluation.",
            identity.actor_id,
            identity.run_id,
            created_at,
            True,
            identity.actor_id,
            identity.run_id,
            created_at,
        )

    def set_claim_status(
        self,
        *,
        claim_id: str,
        status: ClaimStatus,
        reason: str,
        expected_version: int,
        identity: IdentityContext,
    ) -> Claim:
        if not isinstance(status, ClaimStatus):
            raise IntegrityError("claim_status_invalid", "Claim status is invalid.")
        reason = validate_text(reason, field="reason", maximum=1_000)
        if isinstance(expected_version, bool) or expected_version < 1:
            raise IntegrityError("claim_version_invalid", "Claim version must be positive.")
        created_at = self._clock()
        event_id = self._id_factory("cst")
        with self.database.transaction() as connection:
            claim = _claim_row(connection, claim_id)
            current_version = int(claim["version"])
            if current_version != expected_version:
                raise ConflictError(
                    "claim_version_conflict",
                    "The claim changed; reload it before updating status.",
                )
            if str(claim["status"]) == status.value:
                raise ConflictError(
                    "claim_status_unchanged",
                    "The claim already has the requested status.",
                )
            _require_status_evidence(connection, claim_id=claim_id, status=status)
            self._audit.ensure_run(connection, identity)
            next_version = current_version + 1
            connection.execute(
                """
                INSERT INTO claim_status_events(
                    id, claim_id, mission_id, version, status, reason,
                    creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    claim_id,
                    str(claim["mission_id"]),
                    next_version,
                    status.value,
                    reason,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            self._audit.record(
                connection,
                identity=identity,
                event_type="research.claim.status_changed",
                entity_type="claim",
                entity_id=claim_id,
                mission_id=str(claim["mission_id"]),
                details={
                    "from": str(claim["status"]),
                    "to": status.value,
                    "version": next_version,
                },
            )
            return Claim(
                id=str(claim["id"]),
                mission_id=str(claim["mission_id"]),
                question_id=str(claim["question_id"]),
                statement=str(claim["statement"]),
                falsification_criteria=str(claim["falsification_criteria"]),
                status=status,
                version=next_version,
                status_reason=reason,
                status_creator_id=identity.actor_id,
                status_run_id=identity.run_id,
                status_changed_at=created_at,
                status_evidence_valid=True,
                creator_id=str(claim["creator_id"]),
                run_id=str(claim["run_id"]),
                created_at=str(claim["created_at"]),
            )

    def add_finding(
        self,
        *,
        mission_id: str,
        statement: str,
        statement_kind: StatementKind,
        status: FindingStatus,
        uncertainty: str,
        evidence_ids: tuple[str, ...],
        identity: IdentityContext,
        claim_id: str | None = None,
    ) -> Finding:
        if not isinstance(statement_kind, StatementKind):
            raise IntegrityError("statement_kind_invalid", "Statement class is invalid.")
        if not isinstance(status, FindingStatus):
            raise IntegrityError("finding_status_invalid", "Finding status is invalid.")
        statement = validate_text(statement, field="finding", maximum=4_000)
        uncertainty = uncertainty.strip()
        if len(uncertainty) > 2_000 or "\x00" in uncertainty:
            raise IntegrityError("uncertainty_invalid", "Uncertainty exceeds its size limit.")
        unique_evidence = tuple(dict.fromkeys(evidence_ids))
        if statement_kind.requires_citation and not unique_evidence:
            raise IntegrityError(
                "finding_citation_required",
                "This statement class requires at least one citation.",
            )
        finding_id = self._id_factory("fnd")
        created_at = self._clock()
        with self.database.transaction() as connection:
            _require_mission(connection, mission_id)
            if claim_id is not None:
                claim = connection.execute(
                    "SELECT 1 FROM claims WHERE id = ? AND mission_id = ?",
                    (claim_id, mission_id),
                ).fetchone()
                if claim is None:
                    raise NotFoundError("claim_not_found")
            for evidence_id in unique_evidence:
                citation = verify_evidence_reference(
                    connection,
                    evidence_id=evidence_id,
                    mission_id=mission_id,
                    allow_withdrawn=False,
                )
                if claim_id is not None and citation.claim_id != claim_id:
                    raise IntegrityError(
                        "finding_citation_scope_invalid",
                        "A finding citation must evaluate its linked claim.",
                    )
            self._audit.ensure_run(connection, identity)
            connection.execute(
                """
                INSERT INTO findings(
                    id, mission_id, claim_id, statement, statement_kind, status,
                    uncertainty, creator_id, run_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    finding_id,
                    mission_id,
                    claim_id,
                    statement,
                    statement_kind.value,
                    status.value,
                    uncertainty,
                    identity.actor_id,
                    identity.run_id,
                    created_at,
                ),
            )
            for evidence_id in unique_evidence:
                connection.execute(
                    """
                    INSERT INTO finding_citations(
                        finding_id, mission_id, evidence_id, creator_id, run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_id,
                        mission_id,
                        evidence_id,
                        identity.actor_id,
                        identity.run_id,
                        created_at,
                    ),
                )
            self._audit.record(
                connection,
                identity=identity,
                event_type="research.finding.created",
                entity_type="finding",
                entity_id=finding_id,
                mission_id=mission_id,
                details={
                    "citation_count": len(unique_evidence),
                    "statement_kind": statement_kind.value,
                    "status": status.value,
                },
            )
        return Finding(
            finding_id,
            mission_id,
            claim_id,
            statement,
            statement_kind,
            status,
            uncertainty,
            unique_evidence,
            (CitationStatus.ACTIVE if unique_evidence else CitationStatus.NOT_APPLICABLE),
            identity.actor_id,
            identity.run_id,
            created_at,
        )

    def get_mission(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Mission:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.get_mission(mission_id, connection=owned_connection)
        row = connection.execute(
            """
            SELECT id, title, objective, creator_id, run_id, created_at
            FROM research_missions WHERE id = ?
            """,
            (mission_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("mission_not_found")
        return _mission_from_row(row)

    def list_missions(
        self,
        *,
        limit: int = 100,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[Mission, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 200:
            raise IntegrityError(
                "pagination_invalid",
                "Mission page size must be between 1 and 200.",
            )
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_missions(limit=limit, connection=owned_connection)
        rows = connection.execute(
            """
            SELECT id, title, objective, creator_id, run_id, created_at
            FROM research_missions ORDER BY created_at ASC, id ASC LIMIT ?
            """,
            (limit,),
        )
        return tuple(_mission_from_row(row) for row in rows)

    def page_missions(
        self,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[Mission, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_missions(
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        if after is None:
            rows = list(
                connection.execute(
                    """
                    SELECT id, title, objective, creator_id, run_id, created_at
                    FROM research_missions
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (limit + 1,),
                )
            )
        else:
            created_at, item_id = after
            rows = list(
                connection.execute(
                    """
                    SELECT id, title, objective, creator_id, run_id, created_at
                    FROM research_missions
                    WHERE created_at > ? OR (created_at = ? AND id > ?)
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (created_at, created_at, item_id, limit + 1),
                )
            )
        page_rows, next_position = _slice_page(rows, limit)
        return tuple(_mission_from_row(row) for row in page_rows), next_position

    def get_claim(
        self,
        claim_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> Claim:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.get_claim(claim_id, connection=owned_connection)
        return _claim_from_row(_claim_row(connection, claim_id))

    def list_questions(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[Question, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_questions(mission_id, connection=owned_connection)
        _require_mission(connection, mission_id)
        rows = connection.execute(
            """
            SELECT id, mission_id, question_text, creator_id, run_id, created_at
            FROM research_questions
            WHERE mission_id = ? ORDER BY created_at ASC, id ASC
            """,
            (mission_id,),
        )
        return tuple(_question_from_row(row) for row in rows)

    def page_questions(
        self,
        mission_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[Question, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_questions(
                    mission_id,
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        _require_mission(connection, mission_id)
        if after is None:
            rows = list(
                connection.execute(
                    """
                    SELECT id, mission_id, question_text, creator_id, run_id, created_at
                    FROM research_questions
                    WHERE mission_id = ?
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (mission_id, limit + 1),
                )
            )
        else:
            created_at, item_id = after
            rows = list(
                connection.execute(
                    """
                    SELECT id, mission_id, question_text, creator_id, run_id, created_at
                    FROM research_questions
                    WHERE mission_id = ?
                      AND (created_at > ? OR (created_at = ? AND id > ?))
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (mission_id, created_at, created_at, item_id, limit + 1),
                )
            )
        page_rows, next_position = _slice_page(rows, limit)
        return tuple(_question_from_row(row) for row in page_rows), next_position

    def list_claims(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[Claim, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_claims(mission_id, connection=owned_connection)
        _require_mission(connection, mission_id)
        rows = connection.execute(
            _CLAIM_SELECT + " WHERE c.mission_id = ? ORDER BY c.created_at, c.id",
            (mission_id,),
        )
        return tuple(_claim_from_row(row) for row in rows)

    def page_claims(
        self,
        mission_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[Claim, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_claims(
                    mission_id,
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        _require_mission(connection, mission_id)
        if after is None:
            rows = list(
                connection.execute(
                    _CLAIM_SELECT
                    + " WHERE c.mission_id = ?"
                    + " ORDER BY c.created_at ASC, c.id ASC LIMIT ?",
                    (mission_id, limit + 1),
                )
            )
        else:
            created_at, item_id = after
            rows = list(
                connection.execute(
                    _CLAIM_SELECT
                    + " WHERE c.mission_id = ?"
                    + " AND (c.created_at > ? OR (c.created_at = ? AND c.id > ?))"
                    + " ORDER BY c.created_at ASC, c.id ASC LIMIT ?",
                    (mission_id, created_at, created_at, item_id, limit + 1),
                )
            )
        page_rows, next_position = _slice_page(rows, limit)
        return tuple(_claim_from_row(row) for row in page_rows), next_position

    def list_findings(
        self,
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[Finding, ...]:
        if connection is None:
            with self.database.read() as owned_connection:
                return self.list_findings(mission_id, connection=owned_connection)
        _require_mission(connection, mission_id)
        rows = list(
            connection.execute(
                """
                SELECT id, mission_id, claim_id, statement, statement_kind, status,
                       uncertainty, creator_id, run_id, created_at
                FROM findings WHERE mission_id = ? ORDER BY created_at, id
                """,
                (mission_id,),
            )
        )
        return _findings_from_rows(connection, mission_id=mission_id, rows=rows)

    def page_findings(
        self,
        mission_id: str,
        *,
        limit: int,
        after: tuple[str, str] | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[tuple[Finding, ...], tuple[str, str] | None]:
        _validate_page_request(limit, after)
        if connection is None:
            with self.database.read() as owned_connection:
                return self.page_findings(
                    mission_id,
                    limit=limit,
                    after=after,
                    connection=owned_connection,
                )
        _require_mission(connection, mission_id)
        if after is None:
            rows = list(
                connection.execute(
                    """
                    SELECT id, mission_id, claim_id, statement, statement_kind, status,
                           uncertainty, creator_id, run_id, created_at
                    FROM findings WHERE mission_id = ?
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (mission_id, limit + 1),
                )
            )
        else:
            created_at, item_id = after
            rows = list(
                connection.execute(
                    """
                    SELECT id, mission_id, claim_id, statement, statement_kind, status,
                           uncertainty, creator_id, run_id, created_at
                    FROM findings
                    WHERE mission_id = ?
                      AND (created_at > ? OR (created_at = ? AND id > ?))
                    ORDER BY created_at ASC, id ASC LIMIT ?
                    """,
                    (mission_id, created_at, created_at, item_id, limit + 1),
                )
            )
        page_rows, next_position = _slice_page(rows, limit)
        return (
            _findings_from_rows(connection, mission_id=mission_id, rows=page_rows),
            next_position,
        )


def _validate_page_request(limit: int, after: tuple[str, str] | None) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise IntegrityError(
            "pagination_invalid",
            "Collection page size must be between 1 and 200.",
        )
    if after is None:
        return
    if not isinstance(after, tuple) or len(after) != 2:
        raise IntegrityError("pagination_invalid", "The pagination cursor is invalid.")
    created_at, item_id = after
    if (
        not isinstance(created_at, str)
        or not isinstance(item_id, str)
        or not created_at
        or not item_id
        or len(created_at) > 64
        or len(item_id) > 100
        or "\x00" in created_at
        or "\x00" in item_id
    ):
        raise IntegrityError("pagination_invalid", "The pagination cursor is invalid.")


def _slice_page(
    rows: list[sqlite3.Row],
    limit: int,
    *,
    timestamp_field: str = "created_at",
) -> tuple[list[sqlite3.Row], tuple[str, str] | None]:
    page_rows = rows[:limit]
    if len(rows) <= limit:
        return page_rows, None
    last = page_rows[-1]
    return page_rows, (str(last[timestamp_field]), str(last["id"]))


def _question_from_row(row: sqlite3.Row) -> Question:
    return Question(
        str(row["id"]),
        str(row["mission_id"]),
        str(row["question_text"]),
        str(row["creator_id"]),
        str(row["run_id"]),
        str(row["created_at"]),
    )


def _findings_from_rows(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    rows: list[sqlite3.Row],
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for row in rows:
        citation_rows = list(
            connection.execute(
                """
                SELECT evidence_id FROM finding_citations
                WHERE finding_id = ? ORDER BY evidence_id
                """,
                (str(row["id"]),),
            )
        )
        citation_ids = tuple(str(item["evidence_id"]) for item in citation_rows)
        citation_status = _finding_citation_status(
            connection,
            mission_id=mission_id,
            claim_id=(str(row["claim_id"]) if row["claim_id"] is not None else None),
            evidence_ids=citation_ids,
        )
        findings.append(
            Finding(
                id=str(row["id"]),
                mission_id=str(row["mission_id"]),
                claim_id=(str(row["claim_id"]) if row["claim_id"] is not None else None),
                statement=str(row["statement"]),
                statement_kind=StatementKind(str(row["statement_kind"])),
                status=FindingStatus(str(row["status"])),
                uncertainty=str(row["uncertainty"]),
                evidence_ids=citation_ids,
                citation_status=citation_status,
                creator_id=str(row["creator_id"]),
                run_id=str(row["run_id"]),
                created_at=str(row["created_at"]),
            )
        )
    return tuple(findings)


def _require_mission(connection: sqlite3.Connection, mission_id: str) -> None:
    if (
        connection.execute(
            "SELECT 1 FROM research_missions WHERE id = ?",
            (mission_id,),
        ).fetchone()
        is None
    ):
        raise NotFoundError("mission_not_found")


_CLAIM_SELECT = """
SELECT c.id, c.mission_id, c.question_id, c.statement, c.falsification_criteria,
       c.creator_id, c.run_id, c.created_at, s.status, s.version,
       s.reason AS status_reason, s.creator_id AS status_creator_id,
       s.run_id AS status_run_id, s.created_at AS status_changed_at,
       EXISTS (
           SELECT 1 FROM evidence_cards AS e
           WHERE e.claim_id = c.id AND e.stance = 'supports'
             AND NOT EXISTS (
                 SELECT 1 FROM evidence_withdrawals AS w WHERE w.evidence_id = e.id
             )
       ) AS has_active_support,
       EXISTS (
           SELECT 1 FROM evidence_cards AS e
           WHERE e.claim_id = c.id AND e.stance = 'opposes'
             AND NOT EXISTS (
                 SELECT 1 FROM evidence_withdrawals AS w WHERE w.evidence_id = e.id
             )
       ) AS has_active_opposition
FROM claims AS c
JOIN claim_status_events AS s
  ON s.claim_id = c.id
 AND s.version = (
     SELECT MAX(s2.version) FROM claim_status_events AS s2 WHERE s2.claim_id = c.id
 )
""".strip()


def _claim_row(connection: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    row = connection.execute(_CLAIM_SELECT + " WHERE c.id = ?", (claim_id,)).fetchone()
    if row is None:
        raise NotFoundError("claim_not_found")
    if not isinstance(row, sqlite3.Row):
        raise IntegrityError("database_row_invalid", "Stored claim state is invalid.")
    return row


def _active_evidence_stances(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
) -> set[str]:
    rows = connection.execute(
        """
        SELECT DISTINCT e.stance
        FROM evidence_cards AS e
        LEFT JOIN evidence_withdrawals AS w ON w.evidence_id = e.id
        WHERE e.claim_id = ? AND w.id IS NULL
        ORDER BY e.stance
        """,
        (claim_id,),
    )
    return {str(row["stance"]) for row in rows}


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


def _require_status_evidence(
    connection: sqlite3.Connection,
    *,
    claim_id: str,
    status: ClaimStatus,
) -> None:
    stances = _active_evidence_stances(connection, claim_id=claim_id)
    if not _claim_status_evidence_valid(
        status,
        has_active_support="supports" in stances,
        has_active_opposition="opposes" in stances,
    ):
        raise IntegrityError(
            "claim_status_evidence_required",
            "The requested claim status requires active supporting or opposing evidence.",
        )


def _finding_citation_status(
    connection: sqlite3.Connection,
    *,
    mission_id: str,
    claim_id: str | None,
    evidence_ids: tuple[str, ...],
) -> CitationStatus:
    if not evidence_ids:
        return CitationStatus.NOT_APPLICABLE
    withdrawn = False
    for evidence_id in evidence_ids:
        citation = verify_evidence_reference(
            connection,
            evidence_id=evidence_id,
            mission_id=mission_id,
            allow_withdrawn=True,
        )
        if claim_id is not None and citation.claim_id != claim_id:
            raise IntegrityError(
                "finding_citation_scope_invalid",
                "A finding citation evaluates a different claim.",
            )
        withdrawn = withdrawn or citation.withdrawn
    return CitationStatus.WITHDRAWN if withdrawn else CitationStatus.ACTIVE


def _claim_from_row(row: sqlite3.Row) -> Claim:
    return Claim(
        id=str(row["id"]),
        mission_id=str(row["mission_id"]),
        question_id=str(row["question_id"]),
        statement=str(row["statement"]),
        status_reason=str(row["status_reason"]),
        status_creator_id=str(row["status_creator_id"]),
        status_run_id=str(row["status_run_id"]),
        status_changed_at=str(row["status_changed_at"]),
        status_evidence_valid=_claim_status_evidence_valid(
            ClaimStatus(str(row["status"])),
            has_active_support=bool(row["has_active_support"]),
            has_active_opposition=bool(row["has_active_opposition"]),
        ),
        falsification_criteria=str(row["falsification_criteria"]),
        status=ClaimStatus(str(row["status"])),
        version=int(row["version"]),
        creator_id=str(row["creator_id"]),
        run_id=str(row["run_id"]),
        created_at=str(row["created_at"]),
    )


def _mission_from_row(row: sqlite3.Row) -> Mission:
    return Mission(
        id=str(row["id"]),
        title=str(row["title"]),
        objective=str(row["objective"]),
        creator_id=str(row["creator_id"]),
        run_id=str(row["run_id"]),
        created_at=str(row["created_at"]),
    )
