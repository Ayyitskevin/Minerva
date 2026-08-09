from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

import minerva.cli.main as cli_module
from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.lens import LensSearchResult, LensService


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_lens_receipt(path: Path, receipt: LensSearchResult) -> None:
    path.write_bytes(_canonical_bytes({"lens": asdict(receipt)}) + b"\n")


def _success(
    capsys: pytest.CaptureFixture[str],
    arguments: Sequence[str],
) -> tuple[dict[str, object], str]:
    assert cli_module.main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload, captured.out


def _failure(
    capsys: pytest.CaptureFixture[str],
    arguments: Sequence[str],
    *,
    code: str,
    message: str,
) -> str:
    assert cli_module.main(arguments) == EXIT_DOMAIN
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": code,
            "message": message,
        }
    }
    assert len(captured.err) < 300
    return captured.err


def _build_arguments(
    lab: Lab,
    *,
    mission_id: str,
    claim_id: str,
    lens_input: Path,
) -> tuple[str, ...]:
    return (
        "dossier",
        "build",
        "--db",
        str(lab.database.path),
        "--mission",
        mission_id,
        "--claim",
        claim_id,
        "--lens-input",
        str(lens_input),
    )


def test_dossier_cli_emits_an_exact_repeated_envelope_with_all_explicit_bounds(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content="Préface.\nCafé evidence remains exact.\n".encode())
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="CAFÉ evidence",
    )
    lens_input = tmp_path / "captured-lens-receipt.json"
    _write_lens_receipt(lens_input, lens_receipt)
    arguments = (
        *_build_arguments(
            lab,
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_input=lens_input,
        ),
        "--queue-max-claims",
        "5",
        "--queue-max-items",
        "20",
        "--queue-max-evidence-cards",
        "10",
        "--queue-max-distinct-evidence-quote-bytes",
        "4096",
        "--queue-max-affected-records",
        "20",
        "--queue-max-relationships",
        "50",
        "--queue-max-distinct-snapshot-bytes",
        "4096",
        "--queue-max-output-bytes",
        "500000",
        "--lineage-max-nodes",
        "20",
        "--lineage-max-edges",
        "40",
        "--lineage-max-citation-bytes",
        "4096",
        "--lineage-max-snapshot-bytes",
        "4096",
        "--lineage-max-output-bytes",
        "500000",
        "--max-output-bytes",
        "500000",
        "--max-sqlite-vm-steps",
        "4000000",
    )

    first_envelope, first_output = _success(capsys, arguments)
    second_envelope, second_output = _success(capsys, arguments)

    assert first_envelope == second_envelope
    assert first_output == second_output
    assert first_output.endswith("\n")
    assert set(first_envelope) == {"review_dossier"}
    dossier = first_envelope["review_dossier"]
    assert isinstance(dossier, dict)
    assert dossier["schema_version"] == "minerva.review-dossier.v1"
    assert dossier["kind"] == "review_dossier"
    assert dossier["algorithm"] == "current-snapshot-review-composition"
    assert dossier["algorithm_version"] == "1"
    assert dossier["scope"] == "mission_claim_with_captured_lens_v1"
    assert dossier["completion_policy"] == "complete_or_refuse"
    assert dossier["complete"] is True
    assert dossier["truncated"] is False
    assert dossier["mission_id"] == seed.mission.id
    assert dossier["claim_id"] == seed.claim.id
    assert dossier["question_id"] == seed.question.id
    assert dossier["bounds"] == {
        "claim_lineage": {
            "max_citation_bytes": 4096,
            "max_edges": 40,
            "max_nodes": 20,
            "max_output_bytes": 500000,
            "max_snapshot_bytes": 4096,
            "max_sqlite_vm_steps": 4000000,
        },
        "max_output_bytes": 500000,
        "max_sqlite_vm_steps": 4000000,
        "mission_queue": {
            "max_affected_records": 20,
            "max_claims": 5,
            "max_distinct_evidence_quote_bytes": 4096,
            "max_distinct_snapshot_bytes": 4096,
            "max_evidence_cards": 10,
            "max_items": 20,
            "max_output_bytes": 500000,
            "max_relationships": 50,
            "max_sqlite_vm_steps": 4000000,
        },
    }
    assert dossier["component_order"] == [
        "mission_research_queue",
        "claim_review",
        "claim_lineage",
        "lens_search",
        "lens_replay",
    ]
    assert isinstance(dossier["component_receipts"], list)
    assert len(dossier["component_receipts"]) == 5
    assert isinstance(dossier["cross_checks"], dict)
    assert all(value is True for value in dossier["cross_checks"].values())
    assert dossier["lens_search"] == json.loads(_canonical_bytes(asdict(lens_receipt)))
    assert dossier["lens_replay"]["status"] == "reproduced"
    assert dossier["lens_replay"]["exact_receipt_match"] is True
    assert dossier["lens_replay"]["current_database_snapshot_matched"] is True
    assert dossier["lens_replay"]["historical_corpus_replay"] is False
    assert dossier["work"]["canonical_output_bytes"] == len(_canonical_bytes(dossier))
    dossier_payload = dict(dossier)
    dossier_digest = dossier_payload.pop("dossier_receipt_sha256")
    assert dossier_digest == sha256(_canonical_bytes(dossier_payload)).hexdigest()
    assert dossier["semantic_boundary"]["read_only"] is True
    assert dossier["semantic_boundary"]["lens_candidates_are_evidence"] is False
    assert dossier["semantic_boundary"]["creates_or_changes_research_state"] is False


def test_dossier_cli_help_and_readme_expose_the_same_build_description(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli_module.main(("dossier", "--help"))

    assert stopped.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "build" in captured.out
    assert "compose one atomic local review dossier" in captured.out
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "| `minerva dossier build` | compose one atomic local review dossier |" in readme


@pytest.mark.parametrize(
    ("kind", "code", "message"),
    [
        (
            "missing",
            "lens_receipt_input_not_found",
            "The Lens receipt input was not found.",
        ),
        (
            "directory",
            "lens_receipt_input_unsafe",
            "The Lens receipt input path is unsafe.",
        ),
        (
            "symlink",
            "lens_receipt_input_symlink",
            "Lens receipt paths may not use symbolic links.",
        ),
    ],
)
def test_dossier_cli_uses_the_shared_safe_lens_file_boundary(
    kind: str,
    code: str,
    message: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"matching dossier observation\n")
    sentinel = "PRIVATE-DOSSIER-LENS-PATH"
    lens_input = tmp_path / sentinel
    if kind == "directory":
        lens_input.mkdir()
    elif kind == "symlink":
        actual = tmp_path / "actual-receipt.json"
        actual.write_text("{}", encoding="utf-8")
        lens_input.symlink_to(actual)

    error = _failure(
        capsys,
        _build_arguments(
            lab,
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_input=lens_input,
        ),
        code=code,
        message=message,
    )

    assert sentinel not in error
    assert str(lens_input) not in error


def test_dossier_cli_missing_and_foreign_claims_are_non_reflective(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"target dossier observation\n")
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="dossier observation",
    )
    lens_input = tmp_path / "scope-receipt.json"
    _write_lens_receipt(lens_input, lens_receipt)
    missing_claim_id = "clm_" + "f" * 32
    foreign = lab.seed_claim(content=b"FOREIGN-DOSSIER-TEXT-MUST-NOT-LEAK\n")

    for claim_id in (missing_claim_id, foreign.claim.id):
        error = _failure(
            capsys,
            _build_arguments(
                lab,
                mission_id=seed.mission.id,
                claim_id=claim_id,
                lens_input=lens_input,
            ),
            code="review_dossier_scope_invalid",
            message="The local review dossier scope is invalid.",
        )
        assert claim_id not in error
        assert foreign.claim.statement not in error
        assert "FOREIGN-DOSSIER-TEXT-MUST-NOT-LEAK" not in error


def test_dossier_cli_refuses_a_stale_captured_lens_receipt_without_reflection(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"first dossier observation\n")
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="dossier observation",
    )
    lens_input = tmp_path / "PRIVATE-STALE-DOSSIER-RECEIPT.json"
    _write_lens_receipt(lens_input, lens_receipt)
    appended_label = "PRIVATE-APPENDED-DOSSIER-SOURCE.txt"
    appended_text = "PRIVATE-APPENDED-DOSSIER-TEXT"
    lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=f"{appended_text}\n".encode(),
        original_label=appended_label,
        media_type="text/plain",
        identity=lab.identity,
    )

    error = _failure(
        capsys,
        _build_arguments(
            lab,
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_input=lens_input,
        ),
        code="lens_replay_mismatch",
        message="The current database does not exactly reproduce the Lens receipt.",
    )

    assert str(lens_input) not in error
    assert appended_label not in error
    assert appended_text not in error
    assert seed.mission.id not in error


@pytest.mark.parametrize(
    ("flag", "value", "code", "message"),
    [
        (
            "--max-output-bytes",
            "0",
            "review_dossier_bounds_invalid",
            "Review dossier bounds are invalid.",
        ),
        (
            "--max-output-bytes",
            "1",
            "review_dossier_work_limit",
            "The complete local review dossier exceeds its configured work limits.",
        ),
    ],
)
def test_dossier_cli_bounds_and_complete_work_refusals_have_no_partial_output(
    flag: str,
    value: str,
    code: str,
    message: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"bounded dossier observation\n")
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="dossier observation",
    )
    lens_input = tmp_path / "PRIVATE-BOUNDS-DOSSIER-RECEIPT.json"
    _write_lens_receipt(lens_input, lens_receipt)

    error = _failure(
        capsys,
        (
            *_build_arguments(
                lab,
                mission_id=seed.mission.id,
                claim_id=seed.claim.id,
                lens_input=lens_input,
            ),
            flag,
            value,
        ),
        code=code,
        message=message,
    )

    assert str(lens_input) not in error
    assert seed.mission.id not in error
    assert seed.claim.id not in error
