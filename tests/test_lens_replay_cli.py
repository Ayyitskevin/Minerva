from __future__ import annotations

import json
import os
import socket
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import pytest

import minerva.cli.main as cli_module
import minerva.integrations.ai as ai_integrations
import minerva.integrations.lens_receipt_file as receipt_file_module
import minerva.integrations.safe_artifact_file as artifact_file_module
from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.core.db import Database
from minerva.integrations.lens_receipt import MAX_LENS_RECEIPT_BYTES


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def _success(
    capsys: pytest.CaptureFixture[str],
    argv: Sequence[str],
) -> tuple[dict[str, object], str]:
    assert cli_module.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload, captured.out


def _failure(
    capsys: pytest.CaptureFixture[str],
    argv: Sequence[str],
    expected_code: str,
) -> str:
    assert cli_module.main(argv) == EXIT_DOMAIN
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"]["code"] == expected_code
    assert len(captured.err) < 300
    return captured.err


def _capture_search_receipt(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    *,
    mission_id: str,
    query: str,
    target: Path,
) -> dict[str, object]:
    payload, output = _success(
        capsys,
        (
            "lens",
            "search",
            "--db",
            str(lab.database.path),
            "--mission",
            mission_id,
            "--query",
            query,
        ),
    )
    target.write_bytes(output.encode("utf-8"))
    return payload


def test_cli_verify_and_replay_captured_stdout_are_deterministic_and_bounded(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content="Préface.\nCafé 東京 evidence is exact.\n".encode())
    receipt_path = tmp_path / "lens-receipt.json"
    search_payload = _capture_search_receipt(
        lab,
        capsys,
        mission_id=seed.mission.id,
        query="CAFÉ 東京",
        target=receipt_path,
    )
    receipt = search_payload["lens"]
    assert isinstance(receipt, dict)
    before = _database_dump(lab.database)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("offline Lens verification crossed a forbidden boundary")

    with monkeypatch.context() as offline:
        offline.setattr(cli_module, "Database", forbidden)
        offline.setattr(cli_module, "load_provider_credential", forbidden)
        offline.setattr(sqlite3, "connect", forbidden)
        offline.setattr(socket, "socket", forbidden)
        offline.setattr(socket, "create_connection", forbidden)
        first_verified, first_verify_output = _success(
            capsys,
            ("lens", "verify", "--input", str(receipt_path)),
        )
        second_verified, second_verify_output = _success(
            capsys,
            ("lens", "verify", "--input", str(receipt_path)),
        )

    monkeypatch.setattr(cli_module, "load_provider_credential", forbidden)
    monkeypatch.setattr(ai_integrations, "candidate_provider", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    first_replayed, first_replay_output = _success(
        capsys,
        (
            "lens",
            "replay",
            "--db",
            str(lab.database.path),
            "--input",
            str(receipt_path),
        ),
    )
    second_replayed, second_replay_output = _success(
        capsys,
        (
            "lens",
            "replay",
            "--db",
            str(lab.database.path),
            "--input",
            str(receipt_path),
        ),
    )

    assert first_verified == second_verified
    assert first_verify_output == second_verify_output
    verification = first_verified["lens_receipt_verification"]
    assert isinstance(verification, dict)
    assert verification == {
        "algorithm": "bounded-unicode-line-lexical",
        "algorithm_version": "2",
        "canonical_digest_verified": True,
        "internal_consistency_verified": True,
        "kind": "receipt_verification",
        "query_sha256": receipt["query_sha256"],
        "receipt_schema_version": "minerva.lens-search.v1",
        "result_count": 1,
        "retrieval_receipt_sha256": receipt["retrieval_receipt_sha256"],
        "runtime_compatible": True,
        "schema_version": "minerva.lens-receipt-verification.v1",
        "searched_snapshot_content_verified": False,
        "searched_snapshot_count": 1,
        "semantic_boundary": {
            "alters_claims_findings_or_confidence": False,
            "creates_evidence_or_inference": False,
            "determines_source_truth_or_quality": False,
            "deterministic_self_consistency_only": True,
            "establishes_authority_or_approval": False,
            "establishes_disclosure_permission": False,
            "establishes_lasting_freshness": False,
            "establishes_origin_or_authenticity": False,
            "exposes_external_agent_protocol": False,
            "invokes_model_provider_or_network": False,
            "mutates_research_or_audit_state": False,
            "reads_research_database": False,
            "writes_artifact_or_export": False,
        },
        "snapshot_set_sha256": receipt["snapshot_set_sha256"],
        "status": "verified",
        "truncated": False,
        "unicode_database_version": receipt["unicode_database_version"],
    }

    assert first_replayed == second_replayed
    assert first_replay_output == second_replay_output
    replay = first_replayed["lens_replay"]
    assert isinstance(replay, dict)
    assert replay["schema_version"] == "minerva.lens-replay.v1"
    assert replay["kind"] == "current_database_exact_reproduction"
    assert replay["status"] == "reproduced"
    assert replay["exact_receipt_match"] is True
    assert replay["current_database_snapshot_matched"] is True
    assert replay["historical_corpus_replay"] is False
    assert replay["searched_snapshot_content_verified"] is True
    assert replay["semantic_boundary"]["reads_research_database"] is True
    assert replay["semantic_boundary"]["mutates_research_or_audit_state"] is False
    assert _database_dump(lab.database) == before

    private_values = (
        seed.mission.id,
        seed.snapshot.original_label,
        receipt["candidates"][0]["quote"],
    )
    reports = first_verify_output + first_replay_output
    assert all(value not in reports for value in private_values)


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("missing", "lens_receipt_input_not_found"),
        ("directory", "lens_receipt_input_unsafe"),
        ("symlink", "lens_receipt_input_symlink"),
    ],
)
def test_cli_rejects_missing_and_unsafe_receipt_paths(
    kind: str,
    expected_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "receipt-input"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        actual = tmp_path / "actual.json"
        actual.write_text("{}", encoding="utf-8")
        target.symlink_to(actual)

    error = _failure(
        capsys,
        ("lens", "verify", "--input", str(target)),
        expected_code,
    )

    assert str(target) not in error


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    [
        (b"\xff\xfe", "lens_receipt_malformed"),
        (b'{"lens":', "lens_receipt_malformed"),
        (b'{"lens":{},"lens":{}}', "lens_receipt_duplicate_field"),
        (b'{"lens":NaN}', "lens_receipt_nonstandard_number"),
        (
            b'{"lens":' + b"[" * 70 + b"0" + b"]" * 70 + b"}",
            "lens_receipt_too_complex",
        ),
    ],
)
def test_cli_returns_bounded_non_reflective_errors_for_hostile_receipts(
    payload: bytes,
    expected_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel = "PRIVATE_RECEIPT_SENTINEL"
    target = tmp_path / f"{sentinel}.json"
    target.write_bytes(payload)

    error = _failure(
        capsys,
        ("lens", "verify", "--input", str(target)),
        expected_code,
    )

    assert sentinel not in error
    assert str(target) not in error


def test_cli_rejects_missing_defaulted_nested_receipt_fields(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    target = tmp_path / "incomplete-receipt.json"
    payload = _capture_search_receipt(
        lab,
        capsys,
        mission_id=seed.mission.id,
        query="matching",
        target=target,
    )
    receipt = payload["lens"]
    assert isinstance(receipt, dict)
    bounds = receipt["bounds"]
    semantic_boundary = receipt["semantic_boundary"]
    assert isinstance(bounds, dict)
    assert isinstance(semantic_boundary, dict)
    del bounds["max_results"]
    del semantic_boundary["candidate_context_only"]
    target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    _failure(
        capsys,
        ("lens", "verify", "--input", str(target)),
        "lens_receipt_invalid",
    )


def test_cli_rejects_oversized_receipt_before_json_parsing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "oversized.json"
    with target.open("wb") as stream:
        stream.truncate(MAX_LENS_RECEIPT_BYTES + 1)

    def forbidden_parse(_data: bytes) -> NoReturn:
        raise AssertionError("oversized input reached JSON parsing")

    monkeypatch.setattr(receipt_file_module, "parse_lens_receipt", forbidden_parse)

    _failure(
        capsys,
        ("lens", "verify", "--input", str(target)),
        "lens_receipt_too_large",
    )


def test_cli_rejects_receipt_change_between_pinned_reads(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    target = tmp_path / "receipt.json"
    _capture_search_receipt(
        lab,
        capsys,
        mission_id=seed.mission.id,
        query="matching",
        target=target,
    )
    monkeypatch.setattr(
        artifact_file_module,
        "_reread_bounded",
        lambda _descriptor, *, max_bytes: b"changed",
    )

    _failure(
        capsys,
        ("lens", "verify", "--input", str(target)),
        "lens_receipt_input_changed",
    )


def test_replay_refuses_invalid_receipt_before_database_construction(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    target = tmp_path / "edited-receipt.json"
    payload = _capture_search_receipt(
        lab,
        capsys,
        mission_id=seed.mission.id,
        query="matching",
        target=target,
    )
    receipt = payload["lens"]
    assert isinstance(receipt, dict)
    receipt["semantic_notice"] = "PRIVATE_EDITED_NOTICE"
    target.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    def forbidden_database(_path: Path) -> NoReturn:
        raise AssertionError("invalid receipt reached database construction")

    monkeypatch.setattr(cli_module, "Database", forbidden_database)
    unused_database = tmp_path / "must-not-exist.db"

    error = _failure(
        capsys,
        (
            "lens",
            "replay",
            "--db",
            str(unused_database),
            "--input",
            str(target),
        ),
        "lens_receipt_digest_mismatch",
    )

    assert "PRIVATE_EDITED_NOTICE" not in error
    assert not unused_database.exists()


def test_cli_replay_reports_same_mission_append_as_exact_mismatch(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"first matching observation\n")
    target = tmp_path / "receipt.json"
    _capture_search_receipt(
        lab,
        capsys,
        mission_id=seed.mission.id,
        query="matching",
        target=target,
    )
    lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"second matching observation\n",
        original_label="second.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    _failure(
        capsys,
        (
            "lens",
            "replay",
            "--db",
            str(lab.database.path),
            "--input",
            str(target),
        ),
        "lens_replay_mismatch",
    )


@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="Linux O_PATH boundary")
def test_cli_rejects_device_via_path_only_descriptor(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open
    device_flags: list[int] = []

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fsdecode(path) == "null":
            device_flags.append(flags)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(artifact_file_module.os, "open", recording_open)

    _failure(
        capsys,
        ("lens", "verify", "--input", os.devnull),
        "lens_receipt_input_unsafe",
    )

    assert len(device_flags) == 1
    assert device_flags[0] & os.O_PATH
