from __future__ import annotations

import json
from hashlib import sha256

import pytest

from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.cli.main import main
from minerva.evidence.models import EvidenceStance


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_claim_review_cli_emits_byte_identical_complete_receipts(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Café context remains uncertain.", EvidenceStance.CONTEXT)
    arguments = (
        "claim",
        "review",
        "--db",
        str(lab.database.path),
        "--mission",
        seed.mission.id,
        "--claim",
        seed.claim.id,
        "--max-evidence-cards",
        "2",
        "--max-affected-records",
        "3",
        "--max-relationships",
        "10",
        "--max-snapshot-bytes",
        "1000",
        "--max-sqlite-vm-steps",
        "100000",
    )

    assert main(arguments) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.err == ""
    assert first.out == second.out
    assert first.out.endswith("\n")

    payload = json.loads(first.out)
    review = payload["claim_review"]
    assert review["schema_version"] == "minerva.claim-review.v1"
    assert review["kind"] == "evidence_gap_and_retraction_impact"
    assert review["algorithm"] == "structural-ledger-review"
    assert review["completion_policy"] == "complete_or_refuse"
    assert review["complete"] is True
    assert review["truncated"] is False
    assert review["mission_id"] == seed.mission.id
    assert review["claim_id"] == seed.claim.id
    assert review["bounds"] == {
        "max_affected_records": 3,
        "max_evidence_cards": 2,
        "max_relationships": 10,
        "max_snapshot_bytes": 1000,
        "max_sqlite_vm_steps": 100000,
    }
    assert review["active_stance_counts"] == {
        "context": 1,
        "inconclusive": 0,
        "opposes": 0,
        "supports": 0,
        "total": 1,
    }
    assert review["gap_codes"] == ["no_active_support", "no_active_opposition"]
    assert len(review["evidence"]) == 1
    reference = review["evidence"][0]
    assert reference["evidence_id"] == evidence.id
    assert reference["snapshot_id"] == seed.snapshot.snapshot_id
    quoted = seed.content[evidence.start_byte : evidence.end_byte]
    assert reference["quote_byte_length"] == len(quoted)
    assert reference["quote_sha256"] == sha256(quoted).hexdigest()
    assert review["semantic_boundary"]["read_only"] is True
    assert review["semantic_boundary"]["determines_truth"] is False
    assert review["semantic_boundary"]["calculates_confidence"] is False
    assert review["semantic_boundary"]["recommends_claim_status"] is False
    assert review["semantic_boundary"]["writes_audit_event"] is False

    receipt_payload = dict(review)
    receipt_digest = receipt_payload.pop("review_receipt_sha256")
    assert receipt_digest == sha256(_canonical_bytes(receipt_payload)).hexdigest()


def test_claim_review_cli_rejects_invalid_bounds_with_stable_domain_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()

    assert (
        main(
            (
                "claim",
                "review",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--claim",
                seed.claim.id,
                "--max-evidence-cards",
                "0",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "claim_review_bounds_invalid",
            "message": "Claim review bounds are invalid.",
        }
    }


def test_claim_review_cli_refuses_incomplete_work_instead_of_emitting_partial_state(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)

    assert (
        main(
            (
                "claim",
                "review",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--claim",
                seed.claim.id,
                "--max-evidence-cards",
                "1",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "claim_review_work_limit",
            "message": "The complete claim review exceeds its configured work limits.",
        }
    }


def test_claim_review_cli_hides_foreign_claim_existence(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = lab.seed_claim()
    foreign = lab.seed_claim(content=b"foreign mission state\n")

    for claim_id in (foreign.claim.id, "clm_" + "f" * 32):
        assert (
            main(
                (
                    "claim",
                    "review",
                    "--db",
                    str(lab.database.path),
                    "--mission",
                    first.mission.id,
                    "--claim",
                    claim_id,
                )
            )
            == EXIT_DOMAIN
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert json.loads(captured.err) == {
            "error": {
                "code": "claim_review_scope_invalid",
                "message": "The claim review scope is invalid for this mission.",
            }
        }
