from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from minerva.cli.main import main
from minerva.core.db import Database


def _invoke(
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> dict[str, object]:
    assert main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    result = json.loads(captured.out)
    assert isinstance(result, dict)
    return result


def _identifier(result: dict[str, object], section: str, field: str = "id") -> str:
    value = result[section]
    assert isinstance(value, dict)
    identifier = value[field]
    assert isinstance(identifier, str)
    return identifier


def _add_evidence(
    capsys: pytest.CaptureFixture[str],
    *,
    database: Path,
    mission_id: str,
    claim_id: str,
    snapshot_id: str,
    source: bytes,
    quote: str,
    stance: str,
) -> str:
    encoded_quote = quote.encode("utf-8")
    start = source.index(encoded_quote)
    result = _invoke(
        capsys,
        "evidence",
        "add",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--claim",
        claim_id,
        "--snapshot",
        snapshot_id,
        "--start",
        str(start),
        "--end",
        str(start + len(encoded_quote)),
        "--quote",
        quote,
        "--stance",
        stance,
    )
    return _identifier(result, "evidence")


def test_cli_vertical_slice_and_lifecycle(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "research.db"
    initialized = _invoke(capsys, "init", "--db", str(database), "--refuse-existing")
    assert initialized["status"] == "initialized"

    mission = _invoke(
        capsys,
        "mission",
        "create",
        "--db",
        str(database),
        "--title",
        "Pinned and adaptive inference",
        "--objective",
        "Compare reproducibility without manufacturing certainty.",
    )
    mission_id = _identifier(mission, "mission")
    question = _invoke(
        capsys,
        "question",
        "add",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--text",
        "Which local strategy is more reproducible?",
    )
    question_id = _identifier(question, "question")
    claim = _invoke(
        capsys,
        "claim",
        "add",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--question",
        question_id,
        "--statement",
        "Pinned runtimes are more reproducible than adaptive runtimes.",
        "--falsification-criteria",
        "Adaptive repeats have equal or lower result variance.",
    )
    claim_id = _identifier(claim, "claim")

    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_text = (
        "Controlled repeats favored pinned consistency. "
        "A separate run found adaptive consistency exceeded pinned consistency."
    )
    source_bytes = source_text.encode("utf-8")
    (source_root / "comparison.txt").write_bytes(source_bytes)
    imported = _invoke(
        capsys,
        "source",
        "import",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--root",
        str(source_root),
        "--file",
        "comparison.txt",
        "--media-type",
        "text/plain",
    )
    snapshot_id = _identifier(imported, "snapshot", "snapshot_id")
    shown_source = _invoke(
        capsys,
        "source",
        "show",
        "--db",
        str(database),
        "--snapshot",
        snapshot_id,
    )
    assert shown_source["text"] == source_text

    supporting = _add_evidence(
        capsys,
        database=database,
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        source=source_bytes,
        quote="Controlled repeats favored pinned consistency.",
        stance="supports",
    )
    opposing = _add_evidence(
        capsys,
        database=database,
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        source=source_bytes,
        quote="A separate run found adaptive consistency exceeded pinned consistency.",
        stance="opposes",
    )
    context = _add_evidence(
        capsys,
        database=database,
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        source=source_bytes,
        quote=source_text,
        stance="context",
    )
    _invoke(
        capsys,
        "evidence",
        "withdraw",
        "--db",
        str(database),
        "--evidence",
        context,
        "--reason",
        "The combined span is less precise than the two exact cards.",
    )
    updated_claim = _invoke(
        capsys,
        "claim",
        "status",
        "--db",
        str(database),
        "--claim",
        claim_id,
        "--status",
        "contested",
        "--reason",
        "Supporting and opposing exact evidence coexist.",
        "--expected-version",
        "1",
    )
    assert updated_claim["claim"]["version"] == 2  # type: ignore[index]

    finding = _invoke(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--claim",
        claim_id,
        "--statement",
        "The bounded observations leave the claim contested.",
        "--kind",
        "agent_inference",
        "--status",
        "contested",
        "--uncertainty",
        "The sample does not isolate hardware effects.",
        "--evidence",
        supporting,
        "--evidence",
        opposing,
    )
    assert _identifier(finding, "finding").startswith("fnd_")

    claim_show = _invoke(capsys, "claim", "show", "--db", str(database), "--claim", claim_id)
    claim_ledger = _invoke(capsys, "claim", "ledger", "--db", str(database), "--claim", claim_id)
    assert claim_show == claim_ledger
    ledger = claim_show["evidence_ledger"]
    assert isinstance(ledger, list)
    assert {entry["evidence"]["stance"] for entry in ledger} == {  # type: ignore[index]
        "supports",
        "opposes",
        "context",
    }
    assert any(entry["withdrawn"] for entry in ledger)  # type: ignore[index]

    preview = _invoke(
        capsys,
        "brief",
        "preview",
        "--db",
        str(database),
        "--mission",
        mission_id,
    )
    assert isinstance(preview["export_digest"], str)
    assert "CONTESTED" in preview["markdown"]
    export_directory = tmp_path / "export"
    exported = _invoke(
        capsys,
        "brief",
        "export",
        "--db",
        str(database),
        "--mission",
        mission_id,
        "--output-dir",
        str(export_directory),
    )
    assert exported["export_digest"] == preview["export_digest"]
    assert (export_directory / "research-brief.md").is_file()
    assert (export_directory / "research-brief.json").is_file()

    mission_list = _invoke(capsys, "mission", "list", "--db", str(database))
    assert len(mission_list["missions"]) == 1  # type: ignore[arg-type]
    mission_show = _invoke(
        capsys,
        "mission",
        "show",
        "--db",
        str(database),
        "--mission",
        mission_id,
    )
    assert len(mission_show["source_snapshots"]) == 1  # type: ignore[arg-type]

    backup = tmp_path / "research.backup.db"
    _invoke(capsys, "backup", "--db", str(database), "--output", str(backup))
    audit = _invoke(capsys, "audit", "list", "--db", str(database), "--limit", "500")
    events = audit["audit_events"]
    assert isinstance(events, list)
    event_types = {event["event_type"] for event in events}
    assert "database.initialized" in event_types
    assert "source.snapshot.imported" in event_types
    assert "evidence.card.created" in event_types
    assert "synthesis.brief.exported" in event_types
    assert "database.backup.created" in event_types

    restored = tmp_path / "restored.db"
    _invoke(
        capsys,
        "restore",
        "--backup",
        str(backup),
        "--db",
        str(restored),
    )
    restored_audit = _invoke(capsys, "audit", "list", "--db", str(restored), "--limit", "500")
    assert any(
        event["event_type"] == "database.restored"  # type: ignore[index]
        for event in restored_audit["audit_events"]  # type: ignore[union-attr]
    )
    doctor = _invoke(capsys, "doctor", "--db", str(restored), "--deep")
    assert doctor["doctor"]["ok"] is True  # type: ignore[index]


@pytest.mark.security
def test_cli_errors_do_not_reflect_private_paths_or_submitted_content(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database = tmp_path / "private-research.db"
    _invoke(capsys, "init", "--db", str(database))
    mission = _invoke(
        capsys,
        "mission",
        "create",
        "--db",
        str(database),
        "--title",
        "Safe errors",
        "--objective",
        "Exercise a missing import.",
    )
    mission_id = _identifier(mission, "mission")
    private_root = tmp_path / "private-source-directory"
    private_root.mkdir()
    missing_name = "private-missing-source.txt"
    code = main(
        (
            "source",
            "import",
            "--db",
            str(database),
            "--mission",
            mission_id,
            "--root",
            str(private_root),
            "--file",
            missing_name,
        )
    )
    captured = capsys.readouterr()
    assert code == 3
    assert captured.out == ""
    error = json.loads(captured.err)
    assert error["error"]["code"] == "source_not_found"
    assert str(private_root) not in captured.err
    assert missing_name not in captured.err


def test_serve_rejects_non_loopback_host() -> None:
    with pytest.raises(SystemExit) as error:
        main(("serve", "--db", "unused.db", "--host", "0.0.0.0"))
    assert error.value.code == 2


def test_cli_composed_show_commands_each_use_one_read_transaction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "composition.db"
    _invoke(capsys, "init", "--db", str(database_path))
    mission = _invoke(
        capsys,
        "mission",
        "create",
        "--db",
        str(database_path),
        "--title",
        "Transaction composition",
        "--objective",
        "Read each composed view from one snapshot.",
    )
    mission_id = _identifier(mission, "mission")
    question = _invoke(
        capsys,
        "question",
        "add",
        "--db",
        str(database_path),
        "--mission",
        mission_id,
        "--text",
        "Does the CLI compose reads atomically?",
    )
    question_id = _identifier(question, "question")
    claim = _invoke(
        capsys,
        "claim",
        "add",
        "--db",
        str(database_path),
        "--mission",
        mission_id,
        "--question",
        question_id,
        "--statement",
        "The CLI uses one caller-owned read transaction.",
        "--falsification-criteria",
        "More than one Database.read call occurs.",
    )
    claim_id = _identifier(claim, "claim")

    original_read = Database.read
    read_count = 0

    @contextmanager
    def counted_read(database: Database) -> Iterator[sqlite3.Connection]:
        nonlocal read_count
        read_count += 1
        with original_read(database) as connection:
            yield connection

    monkeypatch.setattr(Database, "read", counted_read)

    _invoke(capsys, "claim", "show", "--db", str(database_path), "--claim", claim_id)
    assert read_count == 1

    read_count = 0
    _invoke(capsys, "claim", "ledger", "--db", str(database_path), "--claim", claim_id)
    assert read_count == 1

    read_count = 0
    _invoke(capsys, "mission", "show", "--db", str(database_path), "--mission", mission_id)
    assert read_count == 1
