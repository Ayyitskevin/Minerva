"""Operational integrity checks that do not mutate research state."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from hashlib import sha256
from importlib import resources

from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, MinervaError
from minerva.evidence.integrity import new_snapshot_cache, verify_evidence_reference
from minerva.research.models import StatementKind
from minerva.sources.integrity import verify_snapshot_integrity


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    message: str


@dataclass(frozen=True, slots=True)
class DoctorNotice:
    """An observation that needs an operator's attention but is not a failure.

    Notices never affect `DoctorReport.ok`, so they cannot make a healthy
    database look unready. Minerva reports remnants and never removes them:
    ADR 0004's rule that it must not delete what it cannot prove it created
    applies to crash residue too.
    """

    name: str
    count: int
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok: bool
    checks: tuple[DoctorCheck, ...]
    notices: tuple[DoctorNotice, ...] = ()


_ASSISTANCE_REQUESTED_EVENT = "assistance.invocation.requested"

_REQUIRED_TRIGGERS = frozenset(
    {
        "schema_migrations_no_update",
        "schema_migrations_no_delete",
        "research_runs_no_update",
        "research_runs_no_delete",
        "missions_no_update",
        "missions_no_delete",
        "questions_no_update",
        "questions_no_delete",
        "claims_no_update",
        "claims_no_delete",
        "claim_status_no_update",
        "claim_status_no_delete",
        "sources_no_update",
        "sources_no_delete",
        "snapshots_no_update",
        "snapshots_no_delete",
        "evidence_no_update",
        "evidence_no_delete",
        "withdrawals_no_update",
        "withdrawals_no_delete",
        "audit_no_update",
        "audit_no_delete",
        "findings_no_update",
        "findings_no_delete",
        "finding_citations_no_update",
        "finding_citations_no_delete",
        "finding_retractions_no_update",
        "finding_retractions_no_delete",
        "exports_no_update",
        "exports_no_delete",
        "agent_inferences_no_update",
        "agent_inferences_no_delete",
        "agent_inference_citations_no_update",
        "agent_inference_citations_no_delete",
        "agent_inference_retractions_no_update",
        "agent_inference_retractions_no_delete",
        "agent_inference_promotions_no_update",
        "agent_inference_promotions_no_delete",
    }
)
"""Declared floor for the append-only triggers a database must carry.

This set is *not* what the check enforces — `_packaged_trigger_fingerprints`
derives that from the packaged migrations, so a new migration's triggers become
required the moment it ships. The declared set is the cross-check in the other
direction: it catches a migration resource missing from the distribution, which
a derived-only set would silently accept as "nothing required".

Both halves exist because migration 0004 shipped two retraction triggers that
this hand-maintained set omitted, and doctor consequently reported a database
healthy after those triggers were dropped and the retraction row deleted.
`test_required_triggers_match_packaged_migrations` pins the two sets equal.
"""


BACKUP_ADVISORY_CHECKS = frozenset({"permissions", "wal"})
"""Checks that describe configuration rather than the trustworthiness of data.

A backup is refused when the data cannot be trusted, never because the file's
permissions are loose or its journal mode is unusual. Those are precisely the
databases an operator most wants a snapshot of before changing anything, and
both conditions are reported again by `doctor` on the copy, so nothing is
concealed by proceeding.

Membership is deliberately a short allowlist: any check not named here blocks a
backup, so a future check fails closed until someone decides otherwise.
"""


def run_doctor(database: Database, *, deep: bool = False) -> DoctorReport:
    checks: list[DoctorCheck] = []
    notices: list[DoctorNotice] = [_staging_remnant_notice(database)]
    if not database.exists():
        return DoctorReport(
            False,
            (DoctorCheck("database", False, "Database file is missing or unsafe."),),
            tuple(notices),
        )

    mode = os.stat(database.path, follow_symlinks=False).st_mode & 0o777
    permission_ok = mode & 0o077 == 0
    checks.append(
        DoctorCheck(
            "permissions",
            permission_ok,
            "owner-only database permissions"
            if permission_ok
            else "database is accessible to group or other users",
        )
    )

    try:
        version = database.schema_version()
    except MinervaError as error:
        checks.append(DoctorCheck("schema", False, error.public_message))
        return DoctorReport(False, tuple(checks), tuple(notices))
    expected = latest_schema_version()
    checks.append(
        DoctorCheck(
            "schema",
            version == expected,
            f"schema version {version} of {expected}",
        )
    )

    pages_ok, references_ok = database.integrity_check()
    checks.append(
        DoctorCheck(
            "sqlite_integrity",
            pages_ok,
            "ok" if pages_ok else "SQLite integrity validation failed.",
        )
    )
    if not pages_ok:
        return DoctorReport(False, tuple(checks), tuple(notices))

    try:
        with database.read() as connection:
            # The journal mode read here is the one stored in the file. Doctor
            # opens read-only, so it no longer forces WAL and then reports the
            # value it just forced.
            journal = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            checks.append(DoctorCheck("wal", journal == "wal", f"journal mode is {journal}"))
            checks.append(
                DoctorCheck(
                    "foreign_keys",
                    references_ok,
                    "recorded references resolve"
                    if references_ok
                    else "foreign-key references are unsatisfied",
                )
            )
            trigger_sql = {
                str(row["name"]): str(row["sql"])
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_schema WHERE type = 'trigger'"
                )
            }
            expected_triggers = _packaged_trigger_fingerprints()
            # Enforce every trigger the packaged migrations define, not a
            # hand-listed subset: a migration that adds a table must not be able
            # to leave its append-only triggers unchecked.
            required = frozenset(expected_triggers)
            missing = required - set(trigger_sql)
            altered = {
                name
                for name in required - missing
                if _sql_fingerprint(trigger_sql[name]) != expected_triggers.get(name)
            }
            triggers_ok = not missing and not altered
            checks.append(
                DoctorCheck(
                    "append_only_triggers",
                    triggers_ok,
                    "all append-only triggers match packaged definitions"
                    if triggers_ok
                    else "required append-only triggers are missing or altered",
                )
            )
            if deep:
                checks.extend(_deep_checks(connection))
                notices.append(_unfinished_assistance_notice(connection))
    except (sqlite3.Error, MinervaError) as error:
        message = (
            error.public_message
            if isinstance(error, MinervaError)
            else "Database validation failed safely."
        )
        checks.append(DoctorCheck("deep_integrity", False, message))

    return DoctorReport(all(item.ok for item in checks), tuple(checks), tuple(notices))


def _deep_checks(connection: sqlite3.Connection) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    snapshot_count = 0
    try:
        for row in connection.execute(
            """
            SELECT id, source_id, mission_id, content, sha256, byte_length,
                   encoding, media_type, creator_id, run_id
            FROM source_snapshots ORDER BY id
            """
        ):
            snapshot_count += 1
            verify_snapshot_integrity(connection, row)
        checks.append(
            DoctorCheck(
                "snapshot_integrity",
                True,
                f"verified {snapshot_count} immutable source snapshot(s)",
            )
        )
    except IntegrityError:
        checks.append(
            DoctorCheck(
                "snapshot_integrity",
                False,
                "one or more source snapshots failed integrity validation",
            )
        )

    evidence_count = 0
    evidence_snapshot_cache = new_snapshot_cache()
    try:
        for row in connection.execute("SELECT id, mission_id FROM evidence_cards ORDER BY id"):
            evidence_count += 1
            verify_evidence_reference(
                connection,
                evidence_id=str(row["id"]),
                mission_id=str(row["mission_id"]),
                allow_withdrawn=True,
                snapshot_cache=evidence_snapshot_cache,
            )
        checks.append(
            DoctorCheck(
                "citation_integrity",
                True,
                f"verified {evidence_count} exact citation(s)",
            )
        )
    except MinervaError:
        checks.append(
            DoctorCheck(
                "citation_integrity",
                False,
                "one or more citations failed integrity validation",
            )
        )

    finding_count = 0
    finding_snapshot_cache = new_snapshot_cache()
    try:
        for row in connection.execute(
            """
            SELECT id, mission_id, claim_id, statement_kind
            FROM findings AS finding
            WHERE NOT EXISTS (
                SELECT 1 FROM finding_retractions AS retraction
                WHERE retraction.finding_id = finding.id
            )
            ORDER BY id
            """
        ):
            finding_count += 1
            kind = StatementKind(str(row["statement_kind"]))
            citation_rows = list(
                connection.execute(
                    "SELECT evidence_id FROM finding_citations WHERE finding_id = ?",
                    (str(row["id"]),),
                )
            )
            if kind.requires_citation and not citation_rows:
                raise IntegrityError(
                    "uncited_material_finding",
                    "A material finding is missing required citations.",
                )
            for citation_row in citation_rows:
                citation = verify_evidence_reference(
                    connection,
                    evidence_id=str(citation_row["evidence_id"]),
                    mission_id=str(row["mission_id"]),
                    allow_withdrawn=not kind.requires_citation,
                    snapshot_cache=finding_snapshot_cache,
                )
                if row["claim_id"] is not None and citation.claim_id != str(row["claim_id"]):
                    raise IntegrityError(
                        "finding_citation_scope_invalid",
                        "A finding citation evaluates a different claim.",
                    )
        checks.append(
            DoctorCheck(
                "finding_integrity",
                True,
                f"verified {finding_count} finding(s)",
            )
        )
    except (ValueError, MinervaError):
        checks.append(
            DoctorCheck(
                "finding_integrity",
                False,
                "one or more findings failed citation policy",
            )
        )

    # Symmetric with findings: every citation of an unretracted adopted
    # inference must resolve to an existing, active evidence card that
    # evaluates the same claim in the same mission.
    inference_count = 0
    inference_snapshot_cache = new_snapshot_cache()
    try:
        for row in connection.execute(
            """
            SELECT id, mission_id, claim_id
            FROM agent_inferences AS inference
            WHERE NOT EXISTS (
                SELECT 1 FROM agent_inference_retractions AS retraction
                WHERE retraction.inference_id = inference.id
            )
            ORDER BY id
            """
        ):
            inference_count += 1
            citation_rows = list(
                connection.execute(
                    "SELECT evidence_id FROM agent_inference_citations WHERE inference_id = ?",
                    (str(row["id"]),),
                )
            )
            if not citation_rows:
                raise IntegrityError(
                    "uncited_agent_inference",
                    "An adopted inference is missing required citations.",
                )
            for citation_row in citation_rows:
                citation = verify_evidence_reference(
                    connection,
                    evidence_id=str(citation_row["evidence_id"]),
                    mission_id=str(row["mission_id"]),
                    allow_withdrawn=False,
                    snapshot_cache=inference_snapshot_cache,
                )
                if citation.claim_id != str(row["claim_id"]):
                    raise IntegrityError(
                        "inference_citation_scope_invalid",
                        "An inference citation evaluates a different claim.",
                    )
        checks.append(
            DoctorCheck(
                "inference_integrity",
                True,
                f"verified {inference_count} agent inference(s)",
            )
        )
    except MinervaError:
        checks.append(
            DoctorCheck(
                "inference_integrity",
                False,
                "one or more agent inferences failed citation policy",
            )
        )

    audit_count = 0
    try:
        for row in connection.execute("SELECT details_json FROM audit_events ORDER BY sequence"):
            audit_count += 1
            _parse_audit_details(str(row["details_json"]))
        checks.append(
            DoctorCheck(
                "audit_integrity",
                True,
                f"parsed {audit_count} append-only audit event(s)",
            )
        )
    except ValueError:
        checks.append(
            DoctorCheck(
                "audit_integrity",
                False,
                "one or more audit events contain malformed details",
            )
        )
    try:
        reconciled = _verify_material_audit_links(connection)
        checks.append(
            DoctorCheck(
                "material_audit_integrity",
                True,
                f"reconciled {reconciled} material row(s) to audit history",
            )
        )
    except (ValueError, MinervaError):
        checks.append(
            DoctorCheck(
                "material_audit_integrity",
                False,
                "one or more material rows do not match audit history",
            )
        )
    return checks


def _parse_audit_details(raw: str) -> dict[str, object]:
    raw.encode("utf-8", errors="strict")
    parsed: object = json.loads(
        raw,
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_json_constant,
    )
    if not isinstance(parsed, dict):
        raise ValueError("audit details must be an object")
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if raw != canonical:
        raise ValueError("audit details are not canonical JSON")
    return parsed


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise ValueError("duplicate audit detail key")
        parsed[key] = value
    return parsed


def _reject_json_constant(_value: str) -> object:
    raise ValueError("non-standard JSON constant")


def _details_match(actual: dict[str, object], expected: dict[str, object]) -> bool:
    return set(actual) == set(expected) and all(
        type(actual[key]) is type(value) and actual[key] == value for key, value in expected.items()
    )


def _one_event_details(
    connection: sqlite3.Connection,
    *,
    event_type: str,
    entity_type: str,
    entity_id: str,
    mission_id: str | None,
    actor_id: str,
    run_id: str,
) -> dict[str, object]:
    rows = list(
        connection.execute(
            """
            SELECT entity_type, mission_id, actor_id, run_id, details_json
            FROM audit_events
            WHERE event_type = ? AND entity_id = ?
            ORDER BY sequence
            """,
            (event_type, entity_id),
        )
    )
    if len(rows) != 1:
        raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
    row = rows[0]
    actual_mission = str(row["mission_id"]) if row["mission_id"] is not None else None
    if (
        str(row["entity_type"]) != entity_type
        or actual_mission != mission_id
        or str(row["actor_id"]) != actor_id
        or str(row["run_id"]) != run_id
    ):
        raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
    return _parse_audit_details(str(row["details_json"]))


def _require_event_details(actual: dict[str, object], expected: dict[str, object]) -> None:
    if not _details_match(actual, expected):
        raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")


def _verify_material_audit_links(connection: sqlite3.Connection) -> int:
    expected_counts = {
        "research.run.started": 0,
        "research.mission.created": 0,
        "research.question.created": 0,
        "research.claim.created": 0,
        "research.claim.status_changed": 0,
        "source.snapshot.imported": 0,
        "evidence.card.created": 0,
        "evidence.card.withdrawn": 0,
        "research.finding.created": 0,
        "research.finding.retracted": 0,
        "synthesis.brief.exported": 0,
    }
    reconciled = 0

    for row in connection.execute("SELECT id, actor_id, purpose FROM research_runs ORDER BY id"):
        details = _one_event_details(
            connection,
            event_type="research.run.started",
            entity_type="research_run",
            entity_id=str(row["id"]),
            mission_id=None,
            actor_id=str(row["actor_id"]),
            run_id=str(row["id"]),
        )
        _require_event_details(details, {"purpose": str(row["purpose"])})
        expected_counts["research.run.started"] += 1
        reconciled += 1

    for row in connection.execute(
        "SELECT id, creator_id, run_id FROM research_missions ORDER BY id"
    ):
        details = _one_event_details(
            connection,
            event_type="research.mission.created",
            entity_type="research_mission",
            entity_id=str(row["id"]),
            mission_id=str(row["id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(details, {})
        expected_counts["research.mission.created"] += 1
        reconciled += 1

    for row in connection.execute(
        "SELECT id, mission_id, creator_id, run_id FROM research_questions ORDER BY id"
    ):
        details = _one_event_details(
            connection,
            event_type="research.question.created",
            entity_type="research_question",
            entity_id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(details, {})
        expected_counts["research.question.created"] += 1
        reconciled += 1

    for row in connection.execute(
        "SELECT id, mission_id, creator_id, run_id FROM claims ORDER BY id"
    ):
        details = _one_event_details(
            connection,
            event_type="research.claim.created",
            entity_type="claim",
            entity_id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(details, {"initial_status": "open"})
        expected_counts["research.claim.created"] += 1
        reconciled += 1

    status_audit: dict[tuple[str, int], sqlite3.Row] = {}
    for event in connection.execute(
        """
        SELECT entity_type, entity_id, mission_id, actor_id, run_id, details_json
        FROM audit_events
        WHERE event_type = 'research.claim.status_changed'
        ORDER BY sequence
        """
    ):
        details = _parse_audit_details(str(event["details_json"]))
        version = details.get("version")
        if type(version) is not int or version < 2:
            raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
        key = (str(event["entity_id"]), version)
        if key in status_audit:
            raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
        status_audit[key] = event

    for row in connection.execute(
        """
        SELECT claim_id, mission_id, version, status, creator_id, run_id,
               LAG(version) OVER (PARTITION BY claim_id ORDER BY version) AS previous_version,
               LAG(status) OVER (PARTITION BY claim_id ORDER BY version) AS previous_status
        FROM claim_status_events
        ORDER BY claim_id, version
        """
    ):
        version = int(row["version"])
        previous_version = (
            int(row["previous_version"]) if row["previous_version"] is not None else None
        )
        previous_status = (
            str(row["previous_status"]) if row["previous_status"] is not None else None
        )
        if version == 1:
            if str(row["status"]) != "open" or previous_version is not None:
                raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
        else:
            if previous_version != version - 1 or previous_status is None:
                raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
            key = (str(row["claim_id"]), version)
            event = status_audit.pop(key, None)
            if event is None or not _event_metadata_matches(
                event,
                entity_type="claim",
                mission_id=str(row["mission_id"]),
                actor_id=str(row["creator_id"]),
                run_id=str(row["run_id"]),
            ):
                raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
            details = _parse_audit_details(str(event["details_json"]))
            _require_event_details(
                details,
                {"from": previous_status, "to": str(row["status"]), "version": version},
            )
            expected_counts["research.claim.status_changed"] += 1
        reconciled += 1
    if status_audit:
        raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")

    for source in connection.execute(
        "SELECT id, mission_id, creator_id, run_id FROM sources ORDER BY id"
    ):
        snapshots = list(
            connection.execute(
                """
                SELECT id, source_id, mission_id, content, sha256, byte_length,
                       encoding, media_type, creator_id, run_id
                FROM source_snapshots WHERE source_id = ? ORDER BY id
                """,
                (str(source["id"]),),
            )
        )
        if len(snapshots) != 1:
            raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
        snapshot = snapshots[0]
        if (
            str(snapshot["mission_id"]) != str(source["mission_id"])
            or str(snapshot["creator_id"]) != str(source["creator_id"])
            or str(snapshot["run_id"]) != str(source["run_id"])
        ):
            raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
        verify_snapshot_integrity(connection, snapshot)
        expected_counts["source.snapshot.imported"] += 1
        reconciled += 2

    for row in connection.execute(
        """
        SELECT id, mission_id, claim_id, snapshot_id, snapshot_sha256,
               start_byte, end_byte, stance, supersedes_evidence_id, creator_id, run_id
        FROM evidence_cards ORDER BY id
        """
    ):
        details = _one_event_details(
            connection,
            event_type="evidence.card.created",
            entity_type="evidence_card",
            entity_id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(
            details,
            {
                "claim_id": str(row["claim_id"]),
                "end_byte": int(row["end_byte"]),
                "snapshot_id": str(row["snapshot_id"]),
                "snapshot_sha256": str(row["snapshot_sha256"]),
                "stance": str(row["stance"]),
                "start_byte": int(row["start_byte"]),
                "supersedes": (
                    str(row["supersedes_evidence_id"])
                    if row["supersedes_evidence_id"] is not None
                    else None
                ),
            },
        )
        expected_counts["evidence.card.created"] += 1
        reconciled += 1

    for row in connection.execute(
        """
        SELECT id, mission_id, evidence_id, creator_id, run_id
        FROM evidence_withdrawals ORDER BY id
        """
    ):
        details = _one_event_details(
            connection,
            event_type="evidence.card.withdrawn",
            entity_type="evidence_card",
            entity_id=str(row["evidence_id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(details, {"withdrawal_id": str(row["id"])})
        expected_counts["evidence.card.withdrawn"] += 1
        reconciled += 1

    for row in connection.execute(
        """
        SELECT id, mission_id, statement_kind, status, creator_id, run_id
        FROM findings ORDER BY id
        """
    ):
        citation_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM finding_citations WHERE finding_id = ?",
                (str(row["id"]),),
            ).fetchone()[0]
        )
        details = _one_event_details(
            connection,
            event_type="research.finding.created",
            entity_type="finding",
            entity_id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(
            details,
            {
                "citation_count": citation_count,
                "statement_kind": str(row["statement_kind"]),
                "status": str(row["status"]),
            },
        )
        expected_counts["research.finding.created"] += 1
        reconciled += 1

    # Retraction reconciles exactly as withdrawal does. Without it a deleted
    # retraction row leaves its audit event dangling and unnoticed, and the
    # finding silently returns to synthesis as an asserted statement.
    for row in connection.execute(
        """
        SELECT id, mission_id, finding_id, creator_id, run_id
        FROM finding_retractions ORDER BY id
        """
    ):
        details = _one_event_details(
            connection,
            event_type="research.finding.retracted",
            entity_type="finding",
            entity_id=str(row["finding_id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(details, {"retraction_id": str(row["id"])})
        expected_counts["research.finding.retracted"] += 1
        reconciled += 1

    for row in connection.execute(
        """
        SELECT id, mission_id, schema_version, export_digest,
               markdown_sha256, json_sha256, creator_id, run_id
        FROM brief_exports ORDER BY id
        """
    ):
        details = _one_event_details(
            connection,
            event_type="synthesis.brief.exported",
            entity_type="research_brief",
            entity_id=str(row["id"]),
            mission_id=str(row["mission_id"]),
            actor_id=str(row["creator_id"]),
            run_id=str(row["run_id"]),
        )
        _require_event_details(
            details,
            {
                "export_digest": str(row["export_digest"]),
                "json_sha256": str(row["json_sha256"]),
                "markdown_sha256": str(row["markdown_sha256"]),
                "schema_version": str(row["schema_version"]),
            },
        )
        expected_counts["synthesis.brief.exported"] += 1
        reconciled += 1

    for event_type, expected in expected_counts.items():
        actual = int(
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE event_type = ?",
                (event_type,),
            ).fetchone()[0]
        )
        if actual != expected:
            raise IntegrityError("audit_link_invalid", "Stored audit history is inconsistent.")
    return reconciled


def _event_metadata_matches(
    row: sqlite3.Row,
    *,
    entity_type: str,
    mission_id: str | None,
    actor_id: str,
    run_id: str,
) -> bool:
    actual_mission = str(row["mission_id"]) if row["mission_id"] is not None else None
    return (
        str(row["entity_type"]) == entity_type
        and actual_mission == mission_id
        and str(row["actor_id"]) == actor_id
        and str(row["run_id"]) == run_id
    )


_TRIGGER_PATTERN = re.compile(
    r"(?P<sql>CREATE\s+TRIGGER\s+(?P<name>[A-Za-z0-9_]+)\b.*?\bEND\s*;)",
    flags=re.IGNORECASE | re.DOTALL,
)


def _packaged_trigger_fingerprints() -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    migration_root = resources.files("minerva.core.migrations")
    for migration in sorted(migration_root.iterdir(), key=lambda item: item.name):
        if not migration.name.endswith(".sql"):
            continue
        sql = migration.read_text(encoding="utf-8")
        for match in _TRIGGER_PATTERN.finditer(sql):
            name = match.group("name")
            fingerprints[name] = _sql_fingerprint(match.group("sql"))
    if not set(fingerprints) >= _REQUIRED_TRIGGERS:
        raise IntegrityError(
            "trigger_definition_missing",
            "Packaged append-only trigger definitions are incomplete.",
        )
    return fingerprints


def _sql_fingerprint(sql: str) -> str:
    normalized = " ".join(sql.strip().rstrip(";").split())
    return sha256(normalized.encode("utf-8")).hexdigest()


def _staging_remnant_notice(database: Database) -> DoctorNotice:
    """Count private staging files left beside the database by an interrupted write.

    Restore and fresh initialization stage into `.{name}.minerva-*.tmp` before
    publishing. A crash between the staged commit and publication leaves one
    behind, and each is a full copy of a database, so an operator needs to know
    it is there. Names are never reported: they would disclose the database path.
    """

    try:
        remnants = [
            entry
            for entry in database.path.parent.glob(f".{database.path.name}.minerva-*.tmp")
            if entry.is_file() and not entry.is_symlink()
        ]
    except OSError:
        return DoctorNotice(
            "staging_remnants",
            0,
            "the database directory could not be inspected for staging remnants",
        )
    if not remnants:
        return DoctorNotice("staging_remnants", 0, "no staging remnants beside the database")
    return DoctorNotice(
        "staging_remnants",
        len(remnants),
        "private staging copies remain beside the database; review and remove them yourself",
    )


def _unfinished_assistance_notice(connection: sqlite3.Connection) -> DoctorNotice:
    """Count assistance invocations recorded as requested with no terminal event.

    The requested event commits before egress and the terminal event after, so
    process death between them leaves an unmatched pair. The provider may still
    have processed and charged for that request; Minerva cannot know.
    """

    unfinished = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT entity_id
                FROM audit_events
                WHERE entity_type = 'assistance_invocation'
                GROUP BY entity_id
                HAVING SUM(CASE WHEN event_type = ? THEN 1 ELSE 0 END) > 0
                   AND SUM(CASE WHEN event_type <> ? THEN 1 ELSE 0 END) = 0
            )
            """,
            (_ASSISTANCE_REQUESTED_EVENT, _ASSISTANCE_REQUESTED_EVENT),
        ).fetchone()[0]
    )
    if not unfinished:
        return DoctorNotice(
            "unfinished_assistance",
            0,
            "every recorded assistance invocation has a terminal outcome",
        )
    return DoctorNotice(
        "unfinished_assistance",
        unfinished,
        "assistance invocations have no terminal outcome; the provider may still "
        "have processed those requests",
    )
