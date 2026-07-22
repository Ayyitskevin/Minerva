from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from minerva.cli.demo import main
from minerva.core.audit import list_audit_events
from minerva.core.db import Database
from minerva.synthesis.service import SynthesisService


@pytest.mark.security
def test_demo_is_offline_complete_and_deterministic(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_connections: list[object] = []

    def deny_connect(instance: socket.socket, address: object) -> None:
        del instance
        attempted_connections.append(address)
        raise AssertionError("outbound socket connection attempted")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    canary = socket.socket()
    with canary, pytest.raises(AssertionError, match="outbound socket"):
        canary.connect(("127.0.0.1", 9))
    assert attempted_connections
    attempted_connections.clear()

    database_path = tmp_path / "demo.db"
    export_directory = tmp_path / "demo-export"
    assert (
        main(
            (
                "--db",
                str(database_path),
                "--export-dir",
                str(export_directory),
            )
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    output = json.loads(captured.out)
    assert output["status"] == "demo_created"
    assert output["review_url"] == "http://127.0.0.1:8765/"
    assert "127.0.0.1" in output["review_url"]
    assert str(database_path) not in output["next_step"]
    assert attempted_connections == []
    assert database_path.is_file()
    assert (export_directory / "research-brief.md").is_file()
    assert (export_directory / "research-brief.json").is_file()

    database = Database(database_path)
    brief_one = SynthesisService(database).build_brief(output["mission_id"])
    brief_two = SynthesisService(database).build_brief(output["mission_id"])
    assert brief_one.export_digest == brief_two.export_digest == output["export_digest"]
    assert brief_one.markdown == brief_two.markdown
    assert brief_one.json == brief_two.json

    payload = brief_one.payload
    assert len(payload["claims"]) == 2
    assert {claim["statement"] for claim in payload["claims"]} == {
        "Pinned local inference runtimes produce more reproducible results than adaptive runtimes.",
        "Adaptive local inference runtimes are at least as reproducible as pinned runtimes.",
    }
    assert len(payload["sources"]) == 4
    assert len(payload["citations"]) == 4
    assert all(claim["contested"] for claim in payload["claims"])
    assert {citation["stance"] for citation in payload["citations"]} == {
        "supports",
        "opposes",
    }
    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["status"] == "inconclusive"
    assert payload["findings"][0]["citation_ids"]
    assert len(payload["assumptions"]) == 1
    assert len(payload["unresolved_questions"]) == 1

    source_digests = {source["snapshot_id"]: source["sha256"] for source in payload["sources"]}
    for citation in payload["citations"]:
        assert source_digests[citation["snapshot_id"]] == citation["snapshot_sha256"]
        assert citation["quote"]

    with database.read() as connection:
        events = list_audit_events(connection, limit=500)
    event_types = {event["event_type"] for event in events}
    assert "database.initialized" in event_types
    assert "research.mission.created" in event_types
    assert sum(event["event_type"] == "source.snapshot.imported" for event in events) == 4
    assert sum(event["event_type"] == "evidence.card.created" for event in events) == 4
    assert "synthesis.brief.exported" in event_types

    assert main(("--db", str(database_path), "--export-dir", str(export_directory))) == 3
    refusal = capsys.readouterr()
    error = json.loads(refusal.err)
    assert error["error"]["code"] == "database_exists"
    assert str(database_path) not in refusal.err


def test_demo_refuses_preexisting_export_target_before_creating_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "new-demo.db"
    export_directory = tmp_path / "occupied-export"
    export_directory.mkdir()
    existing = export_directory / "research-brief.json"
    existing.write_text("operator-owned", encoding="utf-8")

    assert main(("--db", str(database_path), "--export-dir", str(export_directory))) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "export_target_exists"
    assert not database_path.exists()
    assert existing.read_text(encoding="utf-8") == "operator-owned"


@pytest.mark.security
def test_demo_refuses_database_symlink(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "database-target.db"
    database_link = tmp_path / "database-link.db"
    database_link.symlink_to(target)

    assert main(("--db", str(database_link), "--export-dir", str(tmp_path / "export"))) == 3
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert error["error"]["code"] == "database_exists"
    assert database_link.is_symlink()
    assert not target.exists()


@pytest.mark.security
def test_demo_refuses_export_directory_symlink_before_creating_database(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database_path = tmp_path / "new-demo.db"
    real_export = tmp_path / "real-export"
    real_export.mkdir()
    export_link = tmp_path / "export-link"
    export_link.symlink_to(real_export, target_is_directory=True)

    assert main(("--db", str(database_path), "--export-dir", str(export_link))) == 3
    captured = capsys.readouterr()
    error = json.loads(captured.err)
    assert error["error"]["code"] == "export_path_invalid"
    assert not database_path.exists()
    assert list(real_export.iterdir()) == []
