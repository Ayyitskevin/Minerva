from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

import pytest

from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import IntegrityError
from minerva.core.types import IdentityContext
from minerva.sources.service import SourceService


class FailingAuditSink:
    def __init__(self, ids: SequenceIds) -> None:
        self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

    def ensure_run(
        self,
        connection: sqlite3.Connection,
        identity: IdentityContext,
    ) -> None:
        self.delegate.ensure_run(connection, identity)

    def record(
        self,
        connection: sqlite3.Connection,
        *,
        identity: IdentityContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        mission_id: str | None,
        details: Mapping[str, object] | None = None,
    ) -> str:
        raise RuntimeError("synthetic audit failure")


def test_import_bytes_stores_sha256_and_verified_immutable_content(lab: Lab) -> None:
    seed = lab.seed_claim()

    stored = lab.sources.read_snapshot(seed.snapshot.snapshot_id)

    assert seed.snapshot.sha256 == sha256(seed.content).hexdigest()
    assert seed.snapshot.byte_length == len(seed.content)
    assert stored.content == seed.content
    assert stored.metadata == seed.snapshot


def test_import_file_snapshot_is_independent_of_original_changes(
    lab: Lab,
    tmp_path: Path,
) -> None:
    root = tmp_path / "sources"
    root.mkdir()
    original = root / "notes.txt"
    original.write_bytes(b"first observed result")
    mission = lab.research.create_mission(
        title="File import mission",
        objective="Verify immutable local source capture.",
        identity=lab.identity,
    )

    snapshot = lab.sources.import_file(
        mission_id=mission.id,
        root=root,
        relative_path="notes.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    original.write_bytes(b"later changed result")

    assert lab.sources.read_snapshot(snapshot.snapshot_id).content == b"first observed result"


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "source_empty"),
        (b"bad utf8 \xff", "source_invalid_utf8"),
        (b"nul\x00byte", "source_nul_byte"),
    ],
)
def test_invalid_source_bytes_are_rejected_without_state(
    lab: Lab,
    content: bytes,
    code: str,
) -> None:
    mission = lab.research.create_mission(
        title="Rejected source mission",
        objective="Rejected imports must be transaction-free.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label="source.txt",
            media_type="text/plain",
            identity=lab.identity,
        )

    assert caught.value.code == code
    assert lab.sources.list_snapshots(mission.id) == ()


def test_configured_source_size_limit_is_enforced(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Bounded source mission",
        objective="Reject source data over the configured limit.",
        identity=lab.identity,
    )
    bounded = SourceService(
        lab.database,
        max_source_bytes=5,
        clock=fixed_clock,
        id_factory=lab.ids,
    )

    with pytest.raises(IntegrityError) as caught:
        bounded.import_bytes(
            mission_id=mission.id,
            content=b"123456",
            original_label="source.txt",
            media_type="text/plain",
            identity=lab.identity,
        )

    assert caught.value.code == "source_too_large"


def test_duplicate_bytes_create_distinct_registrations_with_equal_digests(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Duplicate provenance mission",
        objective="Retain distinct provenance for identical bytes.",
        identity=lab.identity,
    )

    first = lab.sources.import_bytes(
        mission_id=mission.id,
        content=b"same evidence bytes",
        original_label="first.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    second = lab.sources.import_bytes(
        mission_id=mission.id,
        content=b"same evidence bytes",
        original_label="second.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    assert first.source_id != second.source_id
    assert first.snapshot_id != second.snapshot_id
    assert first.sha256 == second.sha256
    assert [item.original_label for item in lab.sources.list_snapshots(mission.id)] == [
        "first.txt",
        "second.txt",
    ]


def test_snapshot_update_and_delete_are_blocked_by_immutability_triggers(lab: Lab) -> None:
    seed = lab.seed_claim()

    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (b"changed", seed.snapshot.snapshot_id),
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "DELETE FROM source_snapshots WHERE id = ?",
            (seed.snapshot.snapshot_id,),
        )

    assert lab.sources.read_snapshot(seed.snapshot.snapshot_id).content == seed.content


def test_secret_file_error_exposes_neither_secret_nor_private_paths(
    lab: Lab,
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-client-root"
    root.mkdir()
    private_name = "client-secrets.txt"
    secret_value = "ghp_" + "Q" * 36
    (root / private_name).write_text(secret_value, encoding="utf-8")
    mission = lab.research.create_mission(
        title="Secret rejection mission",
        objective="Reject likely credentials before persistence.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.import_file(
            mission_id=mission.id,
            root=root,
            relative_path=private_name,
            media_type="text/plain",
            identity=lab.identity,
        )

    assert caught.value.code == "source_secret_detected"
    assert secret_value not in str(caught.value)
    assert str(root) not in str(caught.value)
    assert private_name not in str(caught.value)
    assert lab.sources.list_snapshots(mission.id) == ()


def test_audit_failure_rolls_back_source_and_snapshot_rows(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Atomic source mission",
        objective="A source and its audit event commit together.",
        identity=lab.identity,
    )
    failing = SourceService(
        lab.database,
        audit=FailingAuditSink(lab.ids),
        clock=fixed_clock,
        id_factory=lab.ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        failing.import_bytes(
            mission_id=mission.id,
            content=b"transactional evidence",
            original_label="atomic.txt",
            media_type="text/plain",
            identity=lab.identity,
        )

    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sources WHERE mission_id = ?",
                (mission.id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM source_snapshots WHERE mission_id = ?",
                (mission.id,),
            ).fetchone()[0]
            == 0
        )


def test_rejected_source_creates_no_success_audit_event(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="No misleading audit mission",
        objective="Rejected source mutations must not look successful.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError):
        lab.sources.import_bytes(
            mission_id=mission.id,
            content=b"bad\x00source",
            original_label="bad.txt",
            media_type="text/plain",
            identity=lab.identity,
        )

    with lab.database.read() as connection:
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM audit_events
            WHERE event_type = 'source.snapshot.imported' AND mission_id = ?
            """,
                (mission.id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "label",
    ["C:/private/source.txt", "C:private-source.txt", "D:/source.txt"],
)
def test_windows_absolute_or_drive_source_labels_are_rejected(lab: Lab, label: str) -> None:
    mission = lab.research.create_mission(
        title="Portable label mission",
        objective="Reject labels that expose Windows drive locations.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.import_bytes(
            mission_id=mission.id,
            content=b"synthetic evidence",
            original_label=label,
            media_type="text/plain",
            identity=lab.identity,
        )

    assert caught.value.code == "source_label_invalid"
    assert label not in str(caught.value)


def test_source_label_secret_scan_rejects_without_reflection(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Metadata secret mission",
        objective="Reject likely credentials from labels.",
        identity=lab.identity,
    )
    secret_label = "ghp_" + "L" * 36 + ".txt"

    with pytest.raises(IntegrityError) as caught:
        lab.sources.import_bytes(
            mission_id=mission.id,
            content=b"synthetic evidence",
            original_label=secret_label,
            media_type="text/plain",
            identity=lab.identity,
        )

    assert caught.value.code == "source_secret_detected"
    assert secret_label not in str(caught.value)


@pytest.mark.parametrize(
    "url_metadata",
    [
        "https://example.test/report?access_token=placeholder",
        "https://example.test/report?%61ccess-token=placeholder",
        "https://example.test/report?reference=" + "ghp_" + "U" * 36,
    ],
)
def test_url_metadata_rejects_sensitive_query_names_and_tokens_without_reflection(
    lab: Lab,
    url_metadata: str,
) -> None:
    mission = lab.research.create_mission(
        title="Inert URL mission",
        objective="Keep URL metadata inert and credential free.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.import_bytes(
            mission_id=mission.id,
            content=b"synthetic evidence",
            original_label="source.txt",
            media_type="text/plain",
            url_metadata=url_metadata,
            identity=lab.identity,
        )

    assert caught.value.code == "source_secret_detected"
    assert url_metadata not in str(caught.value)


def test_benign_inert_url_metadata_is_preserved(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Benign metadata mission",
        objective="Retain a bounded inert research locator.",
        identity=lab.identity,
    )
    url_metadata = "https://example.test/report?page=2&topic=evidence"

    snapshot = lab.sources.import_bytes(
        mission_id=mission.id,
        content=b"synthetic evidence",
        original_label="source.txt",
        media_type="text/plain",
        url_metadata=url_metadata,
        identity=lab.identity,
    )

    assert snapshot.url_metadata == url_metadata


def test_get_snapshot_rejects_coordinated_row_rewrite_with_original_import_audit(
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

    with pytest.raises(IntegrityError) as caught:
        lab.sources.get_snapshot(seed.snapshot.snapshot_id)

    assert caught.value.code == "snapshot_tampered"


def test_snapshot_reads_require_exactly_one_import_audit_event(lab: Lab) -> None:
    seed = lab.seed_claim()
    with lab.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO audit_events(
                id, event_type, entity_type, entity_id, mission_id,
                actor_id, run_id, occurred_at, details_json
            )
            SELECT ?, event_type, entity_type, entity_id, mission_id,
                   actor_id, run_id, occurred_at, details_json
            FROM audit_events
            WHERE event_type = 'source.snapshot.imported' AND entity_id = ?
            """,
            ("aud_" + "f" * 32, seed.snapshot.snapshot_id),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.read_snapshot(seed.snapshot.snapshot_id)

    assert caught.value.code == "snapshot_tampered"


def test_snapshot_import_audit_requires_canonical_strict_json(lab: Lab) -> None:
    seed = lab.seed_claim()
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute(
            """
            UPDATE audit_events SET details_json = ' ' || details_json
            WHERE event_type = 'source.snapshot.imported' AND entity_id = ?
            """,
            (seed.snapshot.snapshot_id,),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.sources.get_snapshot(seed.snapshot.snapshot_id)

    assert caught.value.code == "snapshot_tampered"
