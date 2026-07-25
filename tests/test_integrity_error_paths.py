"""Error-path coverage for snapshot verification and backup compensation.

Snapshot verification is the control that turns partial database tampering into
a refusal instead of a plausible-looking brief, and the backup compensation
unlink is identity-checked so it can never remove a file Minerva did not
publish. Both are fail-closed paths that no happy-path test exercises.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from conftest import Lab, fixed_clock
from minerva.core.db import Database
from minerva.core.errors import IntegrityError
from minerva.core.operations import OperationsService, _unlink_if_same
from minerva.core.types import ActorKind, IdentityContext
from minerva.sources.integrity import verify_snapshot_integrity

pytestmark = pytest.mark.security


class _Row:
    """A stand-in for one `source_snapshots` row with tamperable fields."""

    def __init__(self, **values: Any) -> None:
        self._values = values

    def __getitem__(self, key: str) -> Any:
        return self._values[key]


def _snapshot_row(**overrides: Any) -> _Row:
    content = b"Evidence supports the claim.\n"
    from hashlib import sha256

    base: dict[str, Any] = {
        "id": "snp_" + "0" * 32,
        "source_id": "src_" + "0" * 32,
        "mission_id": "mis_" + "0" * 32,
        "content": content,
        "sha256": sha256(content).hexdigest(),
        "byte_length": len(content),
        "encoding": "utf-8",
        "media_type": "text/plain",
        "original_label": "notes/source.txt",
        "creator_id": "os-user:test",
        "run_id": "run_" + "0" * 32,
    }
    base.update(overrides)
    return _Row(**base)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"content": "not bytes"}, id="content_is_not_bytes"),
        pytest.param({"byte_length": "not an integer"}, id="byte_length_is_not_an_integer"),
        pytest.param({"byte_length": 3}, id="byte_length_disagrees_with_content"),
        pytest.param({"sha256": "0" * 64}, id="digest_disagrees_with_content"),
        pytest.param({"content": b"\xff\xfe invalid"}, id="content_is_not_utf8"),
        pytest.param({"content": b"embedded\x00null\n"}, id="content_contains_a_null"),
        pytest.param({"encoding": "utf-16"}, id="encoding_is_not_utf8"),
    ],
)
def test_tampered_snapshot_fields_fail_closed(
    database: Database,
    overrides: dict[str, Any],
) -> None:
    """Each stored field is re-derived, so any disagreement is a refusal."""

    if "content" in overrides and isinstance(overrides["content"], bytes):
        from hashlib import sha256

        overrides.setdefault("sha256", sha256(overrides["content"]).hexdigest())
        overrides.setdefault("byte_length", len(overrides["content"]))

    with database.read() as connection, pytest.raises(IntegrityError) as caught:
        verify_snapshot_integrity(connection, _snapshot_row(**overrides))

    assert caught.value.code == "snapshot_tampered"


def test_snapshot_without_exactly_one_import_event_fails_closed(lab: Lab) -> None:
    """A snapshot must resolve to exactly one recorded import event."""

    seed = lab.seed_claim()
    with lab.database.read() as connection:
        row = connection.execute(
            """
            SELECT id, source_id, mission_id, content, sha256, byte_length,
                   encoding, media_type, original_label, creator_id, run_id
            FROM source_snapshots WHERE id = ?
            """,
            (seed.snapshot.snapshot_id,),
        ).fetchone()
        assert verify_snapshot_integrity(connection, row)

    with lab.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO audit_events(
                id, event_type, entity_type, entity_id, mission_id,
                actor_id, run_id, occurred_at, details_json
            ) VALUES (?, 'source.snapshot.imported', 'source_snapshot', ?, ?, ?, ?, ?, '{}')
            """,
            (
                "aud_" + "d" * 32,
                seed.snapshot.snapshot_id,
                seed.mission.id,
                lab.identity.actor_id,
                lab.identity.run_id,
                fixed_clock(),
            ),
        )

    with lab.database.read() as connection, pytest.raises(IntegrityError) as caught:
        verify_snapshot_integrity(connection, row)

    assert caught.value.code == "snapshot_tampered"


@pytest.mark.parametrize(
    "details",
    [
        pytest.param('{"source_id": "src_x"}', id="missing_required_keys"),
        pytest.param('{"a": 1, "a": 2}', id="duplicate_json_keys"),
        pytest.param("{NaN}", id="non_standard_json"),
        pytest.param(
            '{"source_id":"x","sha256":"y","byte_length":1,'
            '"encoding":"utf-8","media_type":"text/plain"} ',
            id="non_canonical_json",
        ),
        pytest.param("[]", id="not_a_json_object"),
    ],
)
def test_malformed_import_event_details_fail_closed(lab: Lab, details: str) -> None:
    """Import-event details are re-parsed canonically; drift is tampering."""

    seed = lab.seed_claim()
    with lab.database.read() as connection:
        row = connection.execute(
            """
            SELECT id, source_id, mission_id, content, sha256, byte_length,
                   encoding, media_type, original_label, creator_id, run_id
            FROM source_snapshots WHERE id = ?
            """,
            (seed.snapshot.snapshot_id,),
        ).fetchone()

    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute(
            "UPDATE audit_events SET details_json = ? WHERE entity_id = ? AND event_type = ?",
            (details, seed.snapshot.snapshot_id, "source.snapshot.imported"),
        )

    with lab.database.read() as connection, pytest.raises(IntegrityError) as caught:
        verify_snapshot_integrity(connection, row)

    assert caught.value.code == "snapshot_tampered"


def test_backup_compensation_only_removes_the_inode_it_published(tmp_path: Path) -> None:
    """The compensating unlink is identity-checked, not pathname-based."""

    target = tmp_path / "artifact.db"
    target.write_bytes(b"published")
    published = os.stat(target)

    assert _unlink_if_same(target, published.st_dev, published.st_ino) is True
    assert not target.exists()

    replacement = tmp_path / "replacement.db"
    replacement.write_bytes(b"someone else's file")
    other = os.stat(replacement)

    assert _unlink_if_same(replacement, other.st_dev, other.st_ino + 1) is False
    assert replacement.read_bytes() == b"someone else's file"
    assert _unlink_if_same(tmp_path / "absent.db", 1, 1) is False


def test_failed_backup_audit_removes_only_the_backup_it_created(
    lab: Lab,
    tmp_path: Path,
) -> None:
    """A backup whose audit record fails must not survive as an unrecorded artifact."""

    class FailingAudit:
        def ensure_run(self, connection: sqlite3.Connection, identity: IdentityContext) -> None:
            return None

        def record(self, *args: object, **kwargs: object) -> str:
            raise RuntimeError("synthetic audit failure")

    target = tmp_path / "backup.db"
    service = OperationsService(lab.database, audit=FailingAudit())
    identity = IdentityContext(
        actor_id="os-user:test",
        actor_kind=ActorKind.OS_USER,
        run_id="run_" + "e" * 32,
        purpose="backup compensation",
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        service.backup(target=target, identity=identity)

    assert not target.exists()
