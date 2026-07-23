from __future__ import annotations

import json
import os
import socket
import sqlite3
from pathlib import Path
from typing import NoReturn

import pytest

import minerva.cli.main as cli_module
import minerva.integrations.research_packet_file as packet_file_module
import minerva.integrations.safe_artifact_file as artifact_file_module
from minerva.cli._common import EXIT_DOMAIN
from minerva.integrations.research_packet import MAX_RESEARCH_PACKET_BYTES

_GOLDEN = Path(__file__).parent / "fixtures" / "minerva.research-brief.v2.golden.json"


def _success(
    capsys: pytest.CaptureFixture[str],
    command: str,
    path: Path,
) -> tuple[dict[str, object], str]:
    assert cli_module.main(("packet", command, "--input", str(path))) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload, captured.out


def _failure(
    capsys: pytest.CaptureFixture[str],
    command: str,
    path: Path,
    expected_code: str,
) -> str:
    assert cli_module.main(("packet", command, "--input", str(path))) == EXIT_DOMAIN
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"]["code"] == expected_code
    assert len(captured.err) < 300
    return captured.err


def _write_document(tmp_path: Path, mutation: object) -> Path:
    document = json.loads(_GOLDEN.read_bytes())
    assert isinstance(document, dict)
    mutation(document)
    target = tmp_path / "research-brief.json"
    target.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    return target


def test_packet_verify_and_inspect_checked_in_golden_are_bounded(
    capsys: pytest.CaptureFixture[str],
) -> None:
    verified, verify_output = _success(capsys, "verify", _GOLDEN)
    inspected, inspect_output = _success(capsys, "inspect", _GOLDEN)

    assert verified == {
        "status": "verified",
        "schema_version": "minerva.research-brief.v2",
        "export_digest": "80a6579008f23314463bedb5f62fbeed478537f0d3718684f42ef7d451066576",
        "integrity": {"digest_verified": True, "authenticity": "not_established"},
        "ownership": {
            "system": "minerva",
            "researches": True,
            "executes": False,
            "approves": False,
            "orchestrates": False,
            "publishes": False,
        },
    }
    assert inspected["counts"] == {
        "missions": 1,
        "questions": 1,
        "claims": 1,
        "citations": 2,
        "active_citations": 2,
        "withdrawn_citations": 0,
        "evidence_stances": {
            "supports": 1,
            "opposes": 1,
            "context": 0,
            "inconclusive": 0,
        },
        "findings": 1,
        "assumptions": 1,
        "unresolved_questions": 1,
        "uncertainties": 3,
        "sources": 1,
    }
    assert inspected["provenance"] == {
        "verified": True,
        "runs": 1,
        "creator_run_records": 9,
        "claim_status_records": 1,
        "withdrawal_records": 0,
    }
    assert inspected["audit"] == {"verified": True, "references": 10}
    assert inspected["counts_are_not_confidence"] is True

    golden = json.loads(_GOLDEN.read_bytes())
    private_values = (
        golden["brief"]["mission"]["title"],
        golden["brief"]["claims"][0]["statement"],
        golden["brief"]["citations"][0]["quote"],
        golden["brief"]["sources"][0]["original_label"],
        golden["brief"]["runs"][0]["actor_id"],
    )
    assert all(value not in verify_output for value in private_values)
    assert all(value not in inspect_output for value in private_values)
    assert len(inspect_output) < 2_000


@pytest.mark.parametrize("command", ["verify", "inspect"])
def test_packet_commands_do_not_use_sqlite_network_or_provider_credentials(
    command: str,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("offline packet command crossed a forbidden boundary")

    monkeypatch.setattr(cli_module, "Database", forbidden)
    monkeypatch.setattr(cli_module, "load_provider_credential", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    result, _output = _success(capsys, command, _GOLDEN)

    assert result["status"] == "verified"


@pytest.mark.parametrize("command", ["verify", "inspect"])
def test_packet_commands_reject_final_and_parent_symlinks(
    command: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    final_link = tmp_path / "packet-link.json"
    final_link.symlink_to(_GOLDEN)
    _failure(capsys, command, final_link, "packet_input_symlink")

    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "research-brief.json").write_bytes(_GOLDEN.read_bytes())
    parent_link = tmp_path / "linked"
    parent_link.symlink_to(actual, target_is_directory=True)
    _failure(
        capsys,
        command,
        parent_link / "research-brief.json",
        "packet_input_symlink",
    )


@pytest.mark.parametrize("command", ["verify", "inspect"])
def test_packet_commands_reject_parent_segments_before_path_normalization(
    command: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "research-brief.json").write_bytes(_GOLDEN.read_bytes())
    elsewhere = tmp_path / "elsewhere"
    nested = elsewhere / "nested"
    nested.mkdir(parents=True)
    (elsewhere / "research-brief.json").write_text("not the selected packet", encoding="utf-8")
    (root / "linked").symlink_to(nested, target_is_directory=True)

    ambiguous = root / "linked" / ".." / "research-brief.json"

    _failure(capsys, command, ambiguous, "packet_input_unsafe")


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("missing", "packet_input_not_found"),
        ("directory", "packet_input_unsafe"),
        ("fifo", "packet_input_unsafe"),
    ],
)
def test_packet_commands_reject_missing_and_non_regular_inputs_without_blocking(
    kind: str,
    expected_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "packet-input"
    if kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)

    _failure(capsys, "verify", target, expected_code)


@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="Linux O_PATH boundary")
def test_packet_reader_classifies_device_through_path_only_descriptor(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open
    device_open_flags: list[int] = []
    opened_paths: list[str] = []

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened_paths.append(os.fsdecode(path))
        if os.fsdecode(path) == "null":
            device_open_flags.append(flags)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(artifact_file_module.os, "open", recording_open)

    _failure(capsys, "verify", Path(os.devnull), "packet_input_unsafe")

    assert len(device_open_flags) == 1
    assert device_open_flags[0] & os.O_PATH
    assert not any(path.startswith("/proc/self/fd/") for path in opened_paths)


def test_packet_file_size_is_rejected_before_parser_invocation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_RESEARCH_PACKET_BYTES + 1)

    def forbidden_parse(_data: bytes) -> NoReturn:
        raise AssertionError("oversized input reached JSON decoding")

    monkeypatch.setattr(packet_file_module, "parse_research_packet", forbidden_parse)

    _failure(capsys, "verify", oversized, "packet_too_large")


def test_packet_reader_rejects_content_change_between_pinned_reads(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        artifact_file_module,
        "_reread_bounded",
        lambda _descriptor, *, max_bytes: b"changed",
    )

    _failure(capsys, "verify", _GOLDEN, "packet_input_changed")


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_packet_command_rejects_each_nonstandard_json_number(
    token: bytes,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "nonstandard.json"
    target.write_bytes(b'{"value":' + token + b"}")

    _failure(capsys, "verify", target, "packet_nonstandard_number")


def test_packet_command_rejects_nested_duplicate_fields(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw = _GOLDEN.read_bytes()
    duplicate = raw.replace(
        b'"ownership":{"approves":false',
        b'"ownership":{"approves":false,"approves":false',
        1,
    )
    target = tmp_path / "duplicate.json"
    target.write_bytes(duplicate)

    _failure(capsys, "verify", target, "packet_duplicate_field")


def test_packet_command_distinguishes_unsupported_schema_digest_and_semantics(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    schema = _write_document(
        tmp_path,
        lambda document: (
            document.__setitem__("schema_version", "minerva.research-brief.v1"),
            document["brief"].__setitem__("schema_version", "minerva.research-brief.v1"),
        ),
    )
    _failure(capsys, "verify", schema, "packet_schema_unsupported")

    digest = _write_document(
        tmp_path,
        lambda document: document["brief"]["mission"].__setitem__("title", "tampered"),
    )
    _failure(capsys, "verify", digest, "packet_digest_mismatch")

    semantics = _write_document(
        tmp_path,
        lambda document: document["brief"]["citations"].clear(),
    )
    _failure(capsys, "verify", semantics, "packet_invalid")


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfe",
        b'{"unterminated":',
        b"[" * 2_000 + b"0" + b"]" * 2_000,
    ],
)
def test_packet_command_returns_bounded_non_reflective_errors_for_hostile_input(
    payload: bytes,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "PRIVATE_SENTINEL_DO_NOT_REFLECT"
    target = tmp_path / f"{sentinel}.json"
    target.write_bytes(payload + sentinel.encode() * 100)

    error = _failure(capsys, "verify", target, "packet_malformed")

    assert sentinel not in error
    assert str(target) not in error


def test_packet_command_bounds_wide_validation_error_fanout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = json.loads(_GOLDEN.read_bytes())
    document["brief"]["questions"] = [None] * 100_000
    target = tmp_path / "wide-invalid.json"
    target.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")

    _failure(capsys, "verify", target, "packet_invalid")


def test_packet_command_caps_validation_error_classification(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document = json.loads(_GOLDEN.read_bytes())
    document.update({f"unexpected_{index}": None for index in range(40)})
    target = tmp_path / "many-unknown-fields.json"
    target.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")

    _failure(capsys, "verify", target, "packet_invalid")


@pytest.mark.parametrize("shape", ["wide_object", "deep_array"])
def test_packet_command_rejects_excessive_json_shape_before_model_validation(
    shape: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    if shape == "wide_object":
        value: object = {f"field_{index}": None for index in range(65)}
    else:
        value = None
        for _index in range(66):
            value = [value]
    target = tmp_path / "complex.json"
    target.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")

    _failure(capsys, "verify", target, "packet_too_complex")
