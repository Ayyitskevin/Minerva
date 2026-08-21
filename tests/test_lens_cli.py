from __future__ import annotations

import base64
import json

import pytest

from conftest import Lab
from minerva.cli._common import EXIT_DOMAIN
from minerva.cli.main import main


def test_lens_cli_emits_byte_identical_machine_readable_receipts(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim(content="Préface.\nCafé 東京 evidence is exact.\n".encode())
    arguments = (
        "lens",
        "search",
        "--db",
        str(lab.database.path),
        "--mission",
        seed.mission.id,
        "--query",
        "CAFÉ 東京",
        "--limit",
        "5",
    )

    assert main(arguments) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.err == ""
    assert first.out == second.out

    payload = json.loads(first.out)
    receipt = payload["lens"]
    assert receipt["schema_version"] == "minerva.lens-search.v1"
    assert receipt["kind"] == "candidate_context_search"
    assert receipt["result_count"] == 1
    candidate = receipt["candidates"][0]
    assert candidate["kind"] == "candidate_context"
    assert candidate["rank"] == 1
    assert base64.b64decode(candidate["quote_utf8_base64"]).decode() == candidate["quote"]
    assert receipt["semantic_boundary"]["creates_evidence"] is False
    assert receipt["retrieval_receipt_sha256"]


def test_lens_cli_rejects_invalid_bounds_with_stable_domain_error(
    lab: Lab,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()

    assert (
        main(
            (
                "lens",
                "search",
                "--db",
                str(lab.database.path),
                "--mission",
                seed.mission.id,
                "--query",
                "evidence",
                "--limit",
                "0",
            )
        )
        == EXIT_DOMAIN
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {
            "code": "lens_bounds_invalid",
            "message": "Lens search bounds are invalid.",
        }
    }
