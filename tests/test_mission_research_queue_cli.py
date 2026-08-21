from __future__ import annotations

import json
from hashlib import sha256

import pytest

from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.cli.main import main


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def test_mission_queue_cli_emits_byte_identical_complete_receipts(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    arguments = (
        "mission",
        "queue",
        "--db",
        str(lab.database.path),
        "--mission",
        seed.mission.id,
        "--max-claims",
        "5",
        "--max-items",
        "10",
        "--max-evidence-cards",
        "10",
        "--max-distinct-evidence-quote-bytes",
        "1000",
        "--max-affected-records",
        "10",
        "--max-relationships",
        "10",
        "--max-distinct-snapshot-bytes",
        "1000",
        "--max-output-bytes",
        "100000",
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

    envelope = json.loads(first.out)
    assert set(envelope) == {"mission_research_queue"}
    queue = envelope["mission_research_queue"]
    assert queue["schema_version"] == "minerva.mission-research-queue.v1"
    assert queue["kind"] == "mission_research_queue"
    assert queue["algorithm"] == "claim-review-cue-aggregation"
    assert queue["algorithm_version"] == "1"
    assert queue["scope"] == "mission_claim_review_cues_v1"
    assert queue["completion_policy"] == "complete_or_refuse"
    assert queue["complete"] is True
    assert queue["truncated"] is False
    assert queue["mission_id"] == seed.mission.id
    assert queue["bounds"] == {
        "max_affected_records": 10,
        "max_claims": 5,
        "max_distinct_evidence_quote_bytes": 1000,
        "max_distinct_snapshot_bytes": 1000,
        "max_evidence_cards": 10,
        "max_items": 10,
        "max_output_bytes": 100000,
        "max_relationships": 10,
        "max_sqlite_vm_steps": 100000,
    }
    assert queue["sequence_semantics"] == "deterministic_display_order_not_priority"
    assert len(queue["reviewed_claims"]) == 1
    summary = queue["reviewed_claims"][0]
    assert summary["sequence"] == 1
    assert summary["claim_id"] == seed.claim.id
    assert summary["question_id"] == seed.question.id
    assert summary["reason_codes"] == [
        "no_active_evidence",
        "no_active_support",
        "no_active_opposition",
    ]
    assert summary["item_count"] == 3
    assert [item["sequence"] for item in queue["items"]] == [1, 2, 3]
    assert [item["reason_code"] for item in queue["items"]] == summary["reason_codes"]
    assert all(item["kind"] == "structural_review_cue" for item in queue["items"])
    assert all(
        item["source_review_receipt_sha256"] == summary["review_receipt_sha256"]
        for item in queue["items"]
    )
    assert queue["work"]["reviewed_claim_count"] == 1
    assert queue["work"]["item_count"] == 3
    assert queue["work"]["canonical_output_bytes"] == len(_canonical_bytes(queue))
    assert queue["semantic_boundary"]["read_only"] is True
    assert queue["semantic_boundary"]["current_claim_review_taxonomy_guarantees_a_cue"] is True
    assert queue["semantic_boundary"]["item_presence_means_action_required"] is False
    assert queue["semantic_boundary"]["item_presence_means_open_or_unresolved"] is False
    assert queue["semantic_boundary"]["item_order_is_priority_or_severity"] is False
    assert queue["semantic_boundary"]["assigns_work"] is False
    assert queue["semantic_boundary"]["records_completion_or_deferral"] is False
    assert queue["semantic_boundary"]["creates_or_changes_research_state"] is False
    assert queue["semantic_boundary"]["invokes_claim_lineage"] is False
    assert queue["semantic_boundary"]["invokes_model_provider"] is False
    assert queue["semantic_boundary"]["invokes_network"] is False

    receipt_payload = dict(queue)
    receipt_sha256 = receipt_payload.pop("queue_receipt_sha256")
    assert receipt_sha256 == sha256(_canonical_bytes(receipt_payload)).hexdigest()


def test_mission_queue_cli_rejects_invalid_bounds_with_stable_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()

    assert (
        main(
            (
                "mission",
                "queue",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--max-claims",
                "0",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "mission_research_queue_bounds_invalid",
            "message": "Mission research queue bounds are invalid.",
        }
    }


def test_mission_queue_cli_refuses_partial_item_prefix(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()

    assert (
        main(
            (
                "mission",
                "queue",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--max-items",
                "2",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "mission_research_queue_work_limit",
            "message": ("The complete mission research queue exceeds its configured work limits."),
        }
    }


def test_mission_queue_cli_hides_missing_mission_input(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_id = "mis_" + "f" * 32

    assert (
        main(
            (
                "mission",
                "queue",
                "--db",
                str(lab.database.path),
                "--mission",
                missing_id,
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "mission_not_found",
            "message": "The requested resource was not found.",
        }
    }
    assert missing_id not in captured.err
