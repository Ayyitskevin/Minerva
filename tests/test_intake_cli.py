from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

import minerva.cli.main as cli_module
from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN


def _success(capsys: pytest.CaptureFixture[str], argv: Sequence[str]) -> dict[str, object]:
    assert cli_module.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload


def _preview_arguments(lab: Lab, mission: str, claim: str, snapshot: str, quote: str):
    return (
        "intake",
        "preview",
        "--db",
        str(lab.database.path),
        "--mission",
        mission,
        "--claim",
        claim,
        "--snapshot",
        snapshot,
        "--quote",
        quote,
    )


def test_cli_preview_then_file_one_selected_occurrence(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content="Café fact. Café fact.".encode())
    preview_payload = _success(
        capsys,
        _preview_arguments(
            lab,
            seed.mission.id,
            seed.claim.id,
            seed.snapshot.snapshot_id,
            "Café fact",
        ),
    )
    preview = preview_payload["evidence_intake_preview"]
    assert isinstance(preview, dict)
    assert preview["candidate_count"] == 2

    result_payload = _success(
        capsys,
        (
            "intake",
            "file",
            "--db",
            str(lab.database.path),
            "--mission",
            seed.mission.id,
            "--claim",
            seed.claim.id,
            "--snapshot",
            seed.snapshot.snapshot_id,
            "--quote",
            "Café fact",
            "--candidate-rank",
            "2",
            "--expected-intake-preview-sha256",
            str(preview["intake_preview_sha256"]),
            "--expected-snapshot-sha256",
            str(preview["snapshot_sha256"]),
            "--expected-mission-audit-sequence",
            str(preview["mission_audit_sequence"]),
            "--stance",
            "opposes",
        ),
    )

    result = result_payload["evidence_intake"]
    assert isinstance(result, dict)
    assert result["candidate_rank"] == 2
    evidence = result["evidence"]
    assert isinstance(evidence, dict)
    assert evidence["stance"] == "opposes"
    assert evidence["start_byte"] == preview["candidates"][1]["start_byte"]
    assert len(lab.evidence.ledger_for_claim(seed.claim.id)) == 1


def test_cli_stale_preview_returns_stable_domain_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    payload = _success(
        capsys,
        _preview_arguments(
            lab,
            seed.mission.id,
            seed.claim.id,
            seed.snapshot.snapshot_id,
            "exact observation",
        ),
    )
    preview = payload["evidence_intake_preview"]
    assert isinstance(preview, dict)
    lab.research.add_question(
        mission_id=seed.mission.id,
        text="What changed?",
        identity=lab.identity,
    )

    assert (
        cli_module.main(
            (
                "intake",
                "file",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--claim",
                seed.claim.id,
                "--snapshot",
                seed.snapshot.snapshot_id,
                "--quote",
                "exact observation",
                "--candidate-rank",
                "1",
                "--expected-intake-preview-sha256",
                str(preview["intake_preview_sha256"]),
                "--expected-snapshot-sha256",
                str(preview["snapshot_sha256"]),
                "--expected-mission-audit-sequence",
                str(preview["mission_audit_sequence"]),
                "--stance",
                "supports",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "mission_version_conflict"


def test_cli_preview_unavailable_snapshot_returns_stable_domain_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content=b"one exact observation")

    assert (
        cli_module.main(
            _preview_arguments(
                lab,
                seed.mission.id,
                seed.claim.id,
                "snp_" + "f" * 32,
                "exact observation",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "snapshot_not_found"


def test_cli_help_exposes_noninteractive_confirmation_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli_module.main(("intake", "file", "--help"))

    assert stopped.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    for option in (
        "--mission",
        "--claim",
        "--snapshot",
        "--quote",
        "--candidate-rank",
        "--expected-intake-preview-sha256",
        "--expected-snapshot-sha256",
        "--expected-mission-audit-sequence",
        "--stance",
        "--supersedes",
    ):
        assert option in captured.out
