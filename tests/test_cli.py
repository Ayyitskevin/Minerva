from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import minerva.core.db as db_module
from minerva.cli._common import EXIT_OPERATIONAL
from minerva.cli.main import build_parser, main
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


@pytest.mark.security
def test_cli_reports_unknown_database_publication_durability(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "research.db"

    def fail_directory_sync(_: Path) -> None:
        raise OSError("synthetic publication-directory fsync failure")

    monkeypatch.setattr(db_module, "fsync_directory", fail_directory_sync)

    assert main(("init", "--db", str(database), "--refuse-existing")) == EXIT_OPERATIONAL
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "database_publication_durability_unknown",
            "message": (
                "The database target may have been created, but its directory entry could not "
                "be confirmed durable. Inspect the target before retrying."
            ),
        }
    }
    assert database.is_file()


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
    finding_id = _identifier(finding, "finding")
    assert finding_id.startswith("fnd_")

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
    retraction_reason = "Superseded by a corrected analysis."
    retracted = _invoke(
        capsys,
        "finding",
        "retract",
        "--db",
        str(database),
        "--finding",
        finding_id,
        "--reason",
        retraction_reason,
    )
    assert retracted["status"] == "retracted"
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
    rendered_findings = mission_show["findings"]
    assert isinstance(rendered_findings, list)
    rendered = next(item for item in rendered_findings if item["id"] == finding_id)
    assert rendered["retracted"] is True
    assert rendered["retraction_reason"] == retraction_reason
    assert isinstance(rendered["retracted_at"], str)
    assert rendered["retracted_at"].endswith("Z")
    assert rendered["retracted_by"] == finding["finding"]["creator_id"]  # type: ignore[index]

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


def _leaf_commands(
    parser: argparse.ArgumentParser,
    prefix: str = "",
) -> Iterator[tuple[str, str | None]]:
    """Yield every invocable command path and the help text argparse shows for it."""

    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        described = {choice.dest: choice.help for choice in action._choices_actions}
        for name, subparser in action.choices.items():
            path = f"{prefix} {name}".strip()
            has_children = any(
                isinstance(child, argparse._SubParsersAction) for child in subparser._actions
            )
            if not has_children:
                yield path, described.get(name)
            yield from _leaf_commands(subparser, path)


def test_readme_command_reference_covers_every_cli_verb() -> None:
    """The README must list every verb, with the same purpose `--help` gives.

    Nine verbs were absent or mentioned only in passing prose before this table
    existed. Comparing against the parser rather than a hand-written list is the
    point: a new subcommand fails here until it is documented, so the reference
    cannot quietly fall behind the CLI again.
    """

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    commands = dict(_leaf_commands(build_parser()))

    assert commands, "the parser exposes no commands, so this test would prove nothing"
    undescribed = sorted(path for path, help_text in commands.items() if not help_text)
    assert not undescribed, f"these verbs have no --help description: {undescribed}"

    missing = sorted(
        path
        for path, help_text in commands.items()
        if f"| `minerva {path}` | {help_text} |" not in readme
    )
    assert not missing, f"README command reference is missing or disagrees on: {missing}"


def test_cli_exposes_no_delete_verb() -> None:
    """The README states deletion is absent by contract; this holds it to that."""

    paths = [path for path, _ in _leaf_commands(build_parser())]

    assert not [
        path
        for path in paths
        if any(word in path.split() for word in ("delete", "remove", "purge", "destroy"))
    ]
