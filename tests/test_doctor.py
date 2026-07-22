from __future__ import annotations

import os
import sqlite3
from hashlib import sha256
from pathlib import Path

import pytest

from conftest import Lab
from minerva.core.db import Database
from minerva.core.doctor import DoctorCheck, DoctorReport, run_doctor
from minerva.evidence.models import EvidenceStance
from minerva.research.models import FindingStatus, StatementKind


def _checks_by_name(report: DoctorReport) -> dict[str, DoctorCheck]:
    return {check.name: check for check in report.checks}


def _domain_counts(connection: sqlite3.Connection) -> tuple[int, ...]:
    return (
        connection.execute("SELECT COUNT(*) FROM research_runs").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM research_missions").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM research_questions").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM claims").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM claim_status_events").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM source_snapshots").fetchone()[0],
        connection.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0],
    )


def test_doctor_reports_missing_database_without_creating_it(tmp_path: Path) -> None:
    database = Database(tmp_path / "missing.db")

    report = run_doctor(database, deep=True)

    assert not report.ok
    assert len(report.checks) == 1
    assert report.checks[0].name == "database"
    assert not report.checks[0].ok
    assert not database.path.exists()


def test_fresh_database_passes_shallow_and_deep_doctor_checks(lab: Lab) -> None:
    lab.seed_claim()

    shallow = run_doctor(lab.database)
    deep = run_doctor(lab.database, deep=True)

    assert shallow.ok
    assert deep.ok
    assert all(check.ok for check in shallow.checks)
    assert all(check.ok for check in deep.checks)
    deep_names = {check.name for check in deep.checks}
    assert {
        "permissions",
        "schema",
        "sqlite_integrity",
        "wal",
        "foreign_keys",
        "append_only_triggers",
        "snapshot_integrity",
        "citation_integrity",
        "finding_integrity",
        "audit_integrity",
        "material_audit_integrity",
    } <= deep_names


def test_doctor_detects_overbroad_database_permissions(lab: Lab) -> None:
    os.chmod(lab.database.path, 0o644)

    report = run_doctor(lab.database)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["permissions"].ok
    assert "group or other" in checks["permissions"].message


def test_doctor_detects_schema_version_mismatch(lab: Lab) -> None:
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER schema_migrations_no_delete")
        connection.execute("DELETE FROM schema_migrations WHERE version = 2")

    report = run_doctor(lab.database)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["schema"].ok


def test_doctor_detects_missing_append_only_trigger(lab: Lab) -> None:
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")

    report = run_doctor(lab.database)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["append_only_triggers"].ok


def test_deep_doctor_detects_snapshot_tamper_after_trigger_drop(lab: Lab) -> None:
    seed = lab.seed_claim()
    changed = b"X" + seed.content[1:]
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (changed, seed.snapshot.snapshot_id),
        )

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["snapshot_integrity"].ok


def test_deep_doctor_detects_citation_tamper_after_trigger_drop(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER evidence_no_update")
        connection.execute(
            "UPDATE evidence_cards SET quote = ? WHERE id = ?",
            ("forged quote", evidence.id),
        )

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["citation_integrity"].ok


def test_deep_doctor_detects_uncited_material_finding_after_trigger_drop(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A material finding must retain its citation.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER finding_citations_no_delete")
        connection.execute(
            "DELETE FROM finding_citations WHERE finding_id = ?",
            (finding.id,),
        )

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["finding_integrity"].ok


def test_deep_doctor_detects_malformed_audit_details_after_trigger_drop(lab: Lab) -> None:
    lab.seed_claim()
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute("UPDATE audit_events SET details_json = 'not-json' WHERE sequence = 1")

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["audit_integrity"].ok


def test_doctor_is_read_only(lab: Lab) -> None:
    lab.seed_claim()
    with lab.database.read() as connection:
        before = _domain_counts(connection)

    run_doctor(lab.database, deep=True)

    with lab.database.read() as connection:
        after = _domain_counts(connection)
    assert after == before


def test_schema_migration_history_is_append_only(lab: Lab) -> None:
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("0" * 64,),
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute("DELETE FROM schema_migrations WHERE version = 1")


def test_doctor_rejects_same_named_noop_trigger(lab: Lab) -> None:
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            """
            CREATE TRIGGER snapshots_no_update BEFORE UPDATE ON source_snapshots
            BEGIN SELECT 1; END
            """
        )

    report = run_doctor(lab.database)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["append_only_triggers"].ok


def test_deep_doctor_rejects_coordinated_snapshot_row_rewrite_with_original_audit(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    changed = b"Z" + seed.content[1:]
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            """
            UPDATE source_snapshots
            SET content = ?, sha256 = ?, byte_length = ?
            WHERE id = ?
            """,
            (
                changed,
                sha256(changed).hexdigest(),
                len(changed),
                seed.snapshot.snapshot_id,
            ),
        )

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert not checks["snapshot_integrity"].ok


def test_deep_doctor_reconciles_material_rows_to_creation_events(lab: Lab) -> None:
    seed = lab.seed_claim()
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_delete")
        connection.execute(
            """
            DELETE FROM audit_events
            WHERE event_type = 'research.mission.created' AND entity_id = ?
            """,
            (seed.mission.id,),
        )

    report = run_doctor(lab.database, deep=True)
    checks = _checks_by_name(report)

    assert not report.ok
    assert checks["audit_integrity"].ok
    assert not checks["material_audit_integrity"].ok


def test_all_migrated_entity_ids_require_full_lowercase_hex_suffix(lab: Lab) -> None:
    table_names = {
        "audit_events",
        "brief_exports",
        "claim_status_events",
        "claims",
        "evidence_cards",
        "evidence_withdrawals",
        "findings",
        "research_missions",
        "research_questions",
        "research_runs",
        "source_snapshots",
        "sources",
    }
    with lab.database.read() as connection:
        definitions = {
            str(row["name"]): str(row["sql"])
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_schema WHERE type = 'table'"
            )
            if str(row["name"]) in table_names
        }

    assert set(definitions) == table_names
    assert all(
        "substr(id, 5) NOT GLOB '*[^0-9a-f]*'" in definition for definition in definitions.values()
    )
