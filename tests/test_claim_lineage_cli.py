from __future__ import annotations

import base64
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


def test_claim_lineage_cli_emits_byte_identical_complete_receipts(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Café context remains uncertain.", EvidenceStance.CONTEXT)
    arguments = (
        "claim",
        "lineage",
        "--db",
        str(lab.database.path),
        "--mission",
        seed.mission.id,
        "--claim",
        seed.claim.id,
        "--max-nodes",
        "20",
        "--max-edges",
        "30",
        "--max-citation-bytes",
        "1000",
        "--max-snapshot-bytes",
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

    payload = json.loads(first.out)
    assert set(payload) == {"claim_lineage"}
    lineage = payload["claim_lineage"]
    assert lineage["schema_version"] == "minerva.claim-lineage.v1"
    assert lineage["kind"] == "claim_lineage_graph"
    assert lineage["algorithm"] == "structural-ledger-lineage"
    assert lineage["algorithm_version"] == "1"
    assert lineage["scope"] == "claim_owned_closure_v1"
    assert lineage["completion_policy"] == "complete_or_refuse"
    assert lineage["complete"] is True
    assert lineage["truncated"] is False
    assert lineage["mission_id"] == seed.mission.id
    assert lineage["claim_id"] == seed.claim.id
    assert lineage["root_node_id"] == seed.claim.id
    assert lineage["bounds"] == {
        "max_citation_bytes": 1000,
        "max_edges": 30,
        "max_nodes": 20,
        "max_output_bytes": 100000,
        "max_snapshot_bytes": 1000,
        "max_sqlite_vm_steps": 100000,
    }

    evidence_node = next(node for node in lineage["nodes"] if node["node_id"] == evidence.id)
    reference = evidence_node["payload"]
    quoted = seed.content[evidence.start_byte : evidence.end_byte]
    assert reference["start_byte"] == evidence.start_byte
    assert reference["end_byte"] == evidence.end_byte
    assert reference["quote"] == quoted.decode("utf-8")
    assert base64.b64decode(reference["quote_utf8_base64"], validate=True) == quoted
    assert reference["quote_byte_length"] == len(quoted)
    assert reference["quote_sha256"] == sha256(quoted).hexdigest()
    assert lineage["work"]["node_count"] == len(lineage["nodes"])
    assert lineage["work"]["edge_count"] == len(lineage["edges"])
    assert lineage["semantic_boundary"]["read_only"] is True
    assert lineage["semantic_boundary"]["structural_topology_only"] is True
    assert lineage["semantic_boundary"]["determines_truth"] is False
    assert lineage["semantic_boundary"]["calculates_confidence"] is False
    assert lineage["semantic_boundary"]["creates_or_changes_research_state"] is False
    assert lineage["semantic_boundary"]["invokes_model_provider"] is False
    assert lineage["semantic_boundary"]["invokes_network"] is False

    receipt_payload = dict(lineage)
    receipt_digest = receipt_payload.pop("lineage_receipt_sha256")
    assert receipt_digest == sha256(_canonical_bytes(receipt_payload)).hexdigest()


def test_claim_lineage_cli_rejects_invalid_bounds_with_stable_domain_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()

    assert (
        main(
            (
                "claim",
                "lineage",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--claim",
                seed.claim.id,
                "--max-nodes",
                "0",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "claim_lineage_bounds_invalid",
            "message": "Claim lineage bounds are invalid.",
        }
    }


@pytest.mark.parametrize(
    ("flag", "value"),
    [
        ("--max-nodes", "2"),
        ("--max-edges", "1"),
        ("--max-citation-bytes", "1"),
        ("--max-snapshot-bytes", "1"),
        ("--max-output-bytes", "1"),
    ],
)
def test_claim_lineage_cli_refuses_incomplete_work_without_partial_output(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    value: str,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    assert (
        main(
            (
                "claim",
                "lineage",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--claim",
                seed.claim.id,
                flag,
                value,
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "claim_lineage_work_limit",
            "message": "The complete claim lineage graph exceeds its configured work limits.",
        }
    }


def test_claim_lineage_cli_hides_foreign_claim_existence(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = lab.seed_claim()
    foreign = lab.seed_claim(content=b"FOREIGN-LINEAGE-STATE-MUST-NOT-LEAK\n")

    for claim_id in (foreign.claim.id, "clm_" + "f" * 32):
        assert (
            main(
                (
                    "claim",
                    "lineage",
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
        error = json.loads(captured.err)
        assert error == {
            "error": {
                "code": "claim_lineage_scope_invalid",
                "message": "The claim lineage scope is invalid for this mission.",
            }
        }
        assert foreign.claim.id not in captured.err
        assert "FOREIGN-LINEAGE-STATE-MUST-NOT-LEAK" not in captured.err
