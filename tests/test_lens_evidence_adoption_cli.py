from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import pytest

import minerva.cli.main as cli_module
from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.core.db import Database
from minerva.lens import LensService
from minerva.lens.models import LensSearchResult


def _write_receipt(target: Path, receipt: LensSearchResult) -> None:
    target.write_text(
        json.dumps(
            {"lens": asdict(receipt)},
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def _arguments(
    *,
    database: Path,
    receipt_path: Path,
    receipt: LensSearchResult,
    claim_id: str,
    stance: str = "supports",
) -> tuple[str, ...]:
    candidate = receipt.candidates[0]
    return (
        "evidence",
        "add-from-lens",
        "--db",
        str(database),
        "--mission",
        receipt.mission_id,
        "--claim",
        claim_id,
        "--lens-input",
        str(receipt_path),
        "--candidate-rank",
        "1",
        "--stance",
        stance,
        "--expected-retrieval-receipt-sha256",
        receipt.retrieval_receipt_sha256,
        "--expected-snapshot-sha256",
        candidate.snapshot_sha256,
        "--expected-start-byte",
        str(candidate.start_byte),
        "--expected-end-byte",
        str(candidate.end_byte),
        "--expected-quote-sha256",
        candidate.quote_sha256,
    )


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
    assert len(captured.err) < 320
    return captured.err


def test_cli_adopts_one_confirmed_multibyte_candidate_and_emits_bounded_receipt(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(
        content="Préface.\nCafé 東京 observation is exact.\n".encode(),
        source_label="private/operator-notes.txt",
    )
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="CAFÉ 東京",
    )
    receipt_path = tmp_path / "lens-receipt.json"
    _write_receipt(receipt_path, receipt)

    payload, output = _success(
        capsys,
        _arguments(
            database=lab.database.path,
            receipt_path=receipt_path,
            receipt=receipt,
            claim_id=seed.claim.id,
            stance="context",
        ),
    )

    adoption = payload["lens_evidence_adoption"]
    assert isinstance(adoption, dict)
    candidate = receipt.candidates[0]
    evidence = adoption["evidence"]
    assert isinstance(evidence, dict)
    assert adoption["schema_version"] == "minerva.lens-evidence-adoption.v1"
    assert adoption["kind"] == "single_candidate_evidence_adoption"
    assert adoption["status"] == "adopted"
    assert adoption["mission_id"] == seed.mission.id
    assert adoption["claim_id"] == seed.claim.id
    assert adoption["retrieval_receipt_sha256"] == receipt.retrieval_receipt_sha256
    assert adoption["query_sha256"] == receipt.query_sha256
    assert adoption["snapshot_set_sha256"] == receipt.snapshot_set_sha256
    assert adoption["candidate_rank"] == 1
    assert adoption["snapshot_id"] == candidate.snapshot_id
    assert adoption["snapshot_sha256"] == candidate.snapshot_sha256
    assert adoption["start_byte"] == candidate.start_byte
    assert adoption["end_byte"] == candidate.end_byte
    assert adoption["quote_sha256"] == candidate.quote_sha256
    assert adoption["stance"] == "context"
    assert adoption["retrieval_truncated"] is False
    assert evidence["quote"] == candidate.quote
    assert evidence["stance"] == "context"
    assert str(evidence["id"]).startswith("evd_")
    assert str(adoption["adoption_audit_event_id"]).startswith("aud_")
    boundary = adoption["semantic_boundary"]
    assert isinstance(boundary, dict)
    assert boundary["single_candidate_only"] is True
    assert boundary["rank_used_as_epistemic_weight"] is False
    assert boundary["performs_bulk_or_automatic_adoption"] is False
    assert boundary["alters_claim_status"] is False
    assert boundary["persists_agent_inference"] is False
    assert boundary["invokes_model_provider_or_network"] is False
    assert receipt.normalized_query not in output
    assert seed.snapshot.original_label not in output
    assert len(output.encode("utf-8")) < 5_000
    ledger = lab.evidence.ledger_for_claim(seed.claim.id)
    assert len(ledger) == 1
    assert ledger[0].evidence.id == evidence["id"]


@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("missing", "lens_receipt_input_not_found"),
        ("directory", "lens_receipt_input_unsafe"),
        ("symlink", "lens_receipt_input_symlink"),
        ("malformed", "lens_receipt_malformed"),
    ],
)
def test_cli_safe_receipt_loader_refuses_before_database_construction(
    kind: str,
    expected_code: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "PRIVATE_ADOPTION_RECEIPT"
    target = tmp_path / f"{sentinel}.json"
    if kind == "directory":
        target.mkdir()
    elif kind == "symlink":
        actual = tmp_path / "actual.json"
        actual.write_text("{}", encoding="utf-8")
        target.symlink_to(actual)
    elif kind == "malformed":
        target.write_bytes(b'{"lens":')

    def forbidden_database(_path: Path) -> NoReturn:
        raise AssertionError("unsafe receipt reached database construction")

    monkeypatch.setattr(cli_module, "Database", forbidden_database)
    error = _failure(
        capsys,
        (
            "evidence",
            "add-from-lens",
            "--db",
            str(tmp_path / "must-not-exist.db"),
            "--mission",
            "mis_" + "a" * 32,
            "--claim",
            "clm_" + "b" * 32,
            "--lens-input",
            str(target),
            "--candidate-rank",
            "1",
            "--stance",
            "supports",
            "--expected-retrieval-receipt-sha256",
            "c" * 64,
            "--expected-snapshot-sha256",
            "d" * 64,
            "--expected-start-byte",
            "0",
            "--expected-end-byte",
            "1",
            "--expected-quote-sha256",
            "e" * 64,
        ),
        expected_code,
    )

    assert sentinel not in error
    assert str(target) not in error


def test_cli_confirmation_mismatch_refuses_before_database_open(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    receipt_path = tmp_path / "receipt.json"
    _write_receipt(receipt_path, receipt)
    unused_database = tmp_path / "must-not-exist.db"
    arguments = list(
        _arguments(
            database=unused_database,
            receipt_path=receipt_path,
            receipt=receipt,
            claim_id=seed.claim.id,
        )
    )
    arguments[-1] = "f" * 64

    def forbidden_connect(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("mismatched confirmation opened the database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)

    _failure(
        capsys,
        arguments,
        "lens_adoption_confirmation_mismatch",
    )
    assert not unused_database.exists()


def test_cli_help_and_readme_expose_the_explicit_single_candidate_boundary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli_module.main(("evidence", "--help"))

    assert stopped.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "adopt one explicitly confirmed Lens candidate as evidence" in " ".join(
        captured.out.split()
    )
    with pytest.raises(SystemExit) as leaf_stopped:
        cli_module.main(("evidence", "add-from-lens", "--help"))
    assert leaf_stopped.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    for option in (
        "--lens-input",
        "--candidate-rank",
        "--expected-retrieval-receipt-sha256",
        "--expected-snapshot-sha256",
        "--expected-start-byte",
        "--expected-end-byte",
        "--expected-quote-sha256",
        "--stance",
        "--supersedes",
    ):
        assert option in captured.out
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert (
        "| `minerva evidence add-from-lens` | "
        "adopt one explicitly confirmed Lens candidate as evidence |"
    ) in readme
