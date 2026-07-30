from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from minerva.cli.main import main

_RESPONSE_SHA256 = sha256(b"a fake provider response document").hexdigest()


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


def _invoke_error(
    capsys: pytest.CaptureFixture[str],
    *arguments: str,
) -> dict[str, object]:
    assert main(arguments) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)
    assert isinstance(error, dict)
    assert set(error["error"]) == {"code", "message"}  # type: ignore[index]
    return error


def _identifier(result: dict[str, object], section: str, field: str = "id") -> str:
    value = result[section]
    assert isinstance(value, dict)
    identifier = value[field]
    assert isinstance(identifier, str)
    return identifier


def _seed_claim_with_evidence(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> tuple[Path, str, str, str]:
    database = tmp_path / "research.db"
    _invoke(capsys, "init", "--db", str(database), "--refuse-existing")
    mission = _invoke(
        capsys,
        "mission",
        "create",
        "--db",
        str(database),
        "--title",
        "Adoption review",
        "--objective",
        "Adopt one reviewed candidate without manufacturing certainty.",
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
        "Which candidates survive adoption review?",
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
        "Adopted inferences remain labeled model output.",
        "--falsification-criteria",
        "An adopted inference presented as a human finding would falsify it.",
    )
    claim_id = _identifier(claim, "claim")

    source_root = tmp_path / "sources"
    source_root.mkdir()
    source_text = "Bounded evidence supports cautious adoption."
    source_bytes = source_text.encode("utf-8")
    (source_root / "evidence.txt").write_bytes(source_bytes)
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
        "evidence.txt",
        "--media-type",
        "text/plain",
    )
    snapshot_id = _identifier(imported, "snapshot", "snapshot_id")
    evidence = _invoke(
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
        "0",
        "--end",
        str(len(source_bytes)),
        "--quote",
        source_text,
        "--stance",
        "supports",
    )
    return database, mission_id, claim_id, _identifier(evidence, "evidence")


def _adopt(
    capsys: pytest.CaptureFixture[str],
    database: Path,
    claim_id: str,
    evidence_id: str,
    *,
    statement: str = "The bounded evidence supports a cautious adopted inference.",
    uncertainty: str = "The evidence does not establish generality.",
    candidate_index: int = 0,
) -> dict[str, object]:
    result = _invoke(
        capsys,
        "assist",
        "adopt",
        "--db",
        str(database),
        "--claim",
        claim_id,
        "--provider",
        "openai",
        "--model",
        "test-model-1",
        "--candidate-index",
        str(candidate_index),
        "--response-sha256",
        _RESPONSE_SHA256,
        "--statement",
        statement,
        "--uncertainty",
        uncertainty,
        "--evidence",
        evidence_id,
    )
    inference = result["inference"]
    assert isinstance(inference, dict)
    return inference


def _retract(
    capsys: pytest.CaptureFixture[str],
    database: Path,
    inference_id: str,
    reason: str,
) -> dict[str, object]:
    return _invoke(
        capsys,
        "assist",
        "retract-inference",
        "--db",
        str(database),
        "--inference",
        inference_id,
        "--reason",
        reason,
    )


def _promote(
    capsys: pytest.CaptureFixture[str],
    database: Path,
    inference_id: str,
) -> dict[str, object]:
    result = _invoke(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--from-inference",
        inference_id,
        "--status",
        "supported",
    )
    finding = result["finding"]
    assert isinstance(finding, dict)
    return finding


def test_assist_adopt_persists_a_labeled_inference(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)

    inference = _adopt(capsys, database, claim_id, evidence_id)

    assert str(inference["id"]).startswith("inf_")
    assert inference["mission_id"] == mission_id
    assert inference["claim_id"] == claim_id
    assert inference["statement"] == "The bounded evidence supports a cautious adopted inference."
    assert inference["provider"] == "openai"
    assert inference["model"] == "test-model-1"
    assert inference["candidate_index"] == 0
    assert inference["response_sha256"] == _RESPONSE_SHA256
    assert isinstance(inference["request_sha256"], str)
    assert inference["evidence_ids"] == [evidence_id]
    assert inference["retracted"] is False
    assert inference["promoted_finding_id"] is None

    # The inference is visible wherever findings are read, under its own label.
    mission_show = _invoke(
        capsys, "mission", "show", "--db", str(database), "--mission", mission_id
    )
    mission_inferences = mission_show["agent_inferences"]
    assert isinstance(mission_inferences, list)
    assert [item["id"] for item in mission_inferences] == [inference["id"]]  # type: ignore[index]
    findings = mission_show["findings"]
    assert isinstance(findings, list)
    assert inference["id"] not in {item["id"] for item in findings}  # type: ignore[index]

    claim_show = _invoke(capsys, "claim", "show", "--db", str(database), "--claim", claim_id)
    claim_inferences = claim_show["agent_inferences"]
    assert isinstance(claim_inferences, list)
    assert [item["id"] for item in claim_inferences] == [inference["id"]]  # type: ignore[index]


def test_assist_adopt_reports_structured_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, _mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    _adopt(capsys, database, claim_id, evidence_id)

    duplicate = _invoke_error(
        capsys,
        "assist",
        "adopt",
        "--db",
        str(database),
        "--claim",
        claim_id,
        "--provider",
        "openai",
        "--model",
        "test-model-1",
        "--candidate-index",
        "0",
        "--response-sha256",
        _RESPONSE_SHA256,
        "--statement",
        "The bounded evidence supports a cautious adopted inference.",
        "--uncertainty",
        "The evidence does not establish generality.",
        "--evidence",
        evidence_id,
    )
    assert duplicate["error"]["code"] == "inference_already_adopted"  # type: ignore[index]

    # A second, still-active card keeps the preview buildable so adoption's own
    # citation revalidation is what refuses the withdrawn citation.
    mission_show = _invoke(
        capsys, "mission", "show", "--db", str(database), "--mission", _mission_id
    )
    snapshots = mission_show["source_snapshots"]
    assert isinstance(snapshots, list)
    snapshot_id = snapshots[0]["snapshot_id"]  # type: ignore[index]
    active = _invoke(
        capsys,
        "evidence",
        "add",
        "--db",
        str(database),
        "--mission",
        _mission_id,
        "--claim",
        claim_id,
        "--snapshot",
        str(snapshot_id),
        "--start",
        "0",
        "--end",
        "16",
        "--quote",
        "Bounded evidence",
        "--stance",
        "context",
    )
    assert str(active["evidence"]["id"]).startswith("evd_")  # type: ignore[index]
    _invoke(
        capsys,
        "evidence",
        "withdraw",
        "--db",
        str(database),
        "--evidence",
        evidence_id,
        "--reason",
        "The observation was measured incorrectly.",
    )
    withdrawn = _invoke_error(
        capsys,
        "assist",
        "adopt",
        "--db",
        str(database),
        "--claim",
        claim_id,
        "--provider",
        "openai",
        "--model",
        "test-model-1",
        "--candidate-index",
        "1",
        "--response-sha256",
        _RESPONSE_SHA256,
        "--statement",
        "A candidate citing withdrawn evidence.",
        "--uncertainty",
        "The citation no longer stands.",
        "--evidence",
        evidence_id,
    )
    assert withdrawn["error"]["code"] == "citation_withdrawn"  # type: ignore[index]


def test_assist_retract_inference_mirrors_finding_retract(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    inference = _adopt(capsys, database, claim_id, evidence_id)
    inference_id = str(inference["id"])

    retracted = _retract(capsys, database, inference_id, "Superseded by a corrected analysis.")

    assert retracted["status"] == "retracted"
    assert str(retracted["retraction_id"]).startswith("inr_")

    claim_show = _invoke(capsys, "claim", "show", "--db", str(database), "--claim", claim_id)
    rendered = claim_show["agent_inferences"][0]  # type: ignore[index]
    assert rendered["retracted"] is True
    assert rendered["retraction_reason"] == "Superseded by a corrected analysis."
    assert isinstance(rendered["retracted_at"], str)
    assert rendered["retracted_at"].endswith("Z")
    assert rendered["retracted_by"] == inference["creator_id"]

    mission_show = _invoke(
        capsys, "mission", "show", "--db", str(database), "--mission", mission_id
    )
    assert mission_show["agent_inferences"][0]["retracted"] is True  # type: ignore[index]

    again = _invoke_error(
        capsys,
        "assist",
        "retract-inference",
        "--db",
        str(database),
        "--inference",
        inference_id,
        "--reason",
        "A second retraction.",
    )
    assert again["error"]["code"] == "inference_already_retracted"  # type: ignore[index]

    unknown = _invoke_error(
        capsys,
        "assist",
        "retract-inference",
        "--db",
        str(database),
        "--inference",
        "inf_" + "f" * 32,
        "--reason",
        "No such inference.",
    )
    assert unknown["error"]["code"] == "inference_not_found"  # type: ignore[index]


def test_finding_add_from_inference_promotes_the_human_assertion(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    inference = _adopt(capsys, database, claim_id, evidence_id)

    finding = _promote(capsys, database, str(inference["id"]))

    assert str(finding["id"]).startswith("fnd_")
    assert finding["statement_kind"] == "agent_inference"
    assert finding["statement"] == inference["statement"]
    assert finding["uncertainty"] == inference["uncertainty"]
    assert finding["evidence_ids"] == [evidence_id]
    assert finding["claim_id"] == claim_id

    mission_show = _invoke(
        capsys, "mission", "show", "--db", str(database), "--mission", mission_id
    )
    rendered = mission_show["agent_inferences"][0]  # type: ignore[index]
    assert rendered["promoted_finding_id"] == finding["id"]
    # The promoted finding is a finding; the inference remains its provenance.
    assert [item["id"] for item in mission_show["findings"]] == [finding["id"]]  # type: ignore[index]

    audit = _invoke(capsys, "audit", "list", "--db", str(database), "--limit", "500")
    event_types = {event["event_type"] for event in audit["audit_events"]}  # type: ignore[index]
    assert "assist.inference.adopted" in event_types
    assert "assist.inference.promoted" in event_types


def test_finding_add_from_inference_refuses_invalid_retracted_and_promoted(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, _mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    inference = _adopt(capsys, database, claim_id, evidence_id)
    inference_id = str(inference["id"])

    unknown = _invoke_error(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--from-inference",
        "inf_" + "f" * 32,
        "--status",
        "supported",
    )
    assert unknown["error"]["code"] == "inference_not_found"  # type: ignore[index]

    _retract(capsys, database, inference_id, "Withdrawn from assertion.")
    retracted = _invoke_error(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--from-inference",
        inference_id,
        "--status",
        "supported",
    )
    assert retracted["error"]["code"] == "inference_retracted"  # type: ignore[index]

    live = _adopt(
        capsys,
        database,
        claim_id,
        evidence_id,
        statement="A second candidate from the same preview.",
        candidate_index=1,
    )
    _promote(capsys, database, str(live["id"]))
    twice = _invoke_error(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--from-inference",
        str(live["id"]),
        "--status",
        "supported",
    )
    assert twice["error"]["code"] == "inference_already_promoted"  # type: ignore[index]


def test_finding_add_argument_modes_are_exclusive(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, _mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    inference = _adopt(capsys, database, claim_id, evidence_id)

    mixed = _invoke_error(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--from-inference",
        str(inference["id"]),
        "--statement",
        "A statement the inference already supplies.",
        "--status",
        "supported",
    )
    assert mixed["error"]["code"] == "finding_promotion_arguments_invalid"  # type: ignore[index]

    missing = _invoke_error(
        capsys,
        "finding",
        "add",
        "--db",
        str(database),
        "--status",
        "supported",
    )
    assert missing["error"]["code"] == "finding_add_arguments_invalid"  # type: ignore[index]


def test_adopted_inferences_pass_deep_doctor_and_leave_the_v2_brief_alone(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, mission_id, claim_id, evidence_id = _seed_claim_with_evidence(capsys, tmp_path)
    before = _invoke(capsys, "brief", "preview", "--db", str(database), "--mission", mission_id)

    inference = _adopt(capsys, database, claim_id, evidence_id)
    adopted = _invoke(capsys, "brief", "preview", "--db", str(database), "--mission", mission_id)
    markdown = str(adopted["markdown"])
    assert "## Agent inferences (model-drafted, human-adopted)" in markdown
    assert str(inference["id"]) in markdown
    # Adoption never touches the canonical v2 JSON bytes.
    assert adopted["json_sha256"] == before["json_sha256"]

    # Promotion creates a real human finding, which the v2 packet always carried.
    finding = _promote(capsys, database, str(inference["id"]))
    promoted = _invoke(capsys, "brief", "preview", "--db", str(database), "--mission", mission_id)
    brief = promoted["brief"]
    assert isinstance(brief, dict)
    assert [item["id"] for item in brief["findings"]] == [finding["id"]]  # type: ignore[index]
    assert f"- Promoted to human finding: **{finding['id']}**" in str(promoted["markdown"])

    # The retracted inference then leaves the brief exactly as a retracted finding does.
    _retract(capsys, database, str(inference["id"]), "Promotion review superseded the draft.")
    retracted = _invoke(capsys, "brief", "preview", "--db", str(database), "--mission", mission_id)
    assert str(inference["id"]) not in str(retracted["markdown"])
    assert retracted["json_sha256"] == promoted["json_sha256"]

    doctor = _invoke(capsys, "doctor", "--db", str(database), "--deep")
    assert doctor["doctor"]["ok"] is True  # type: ignore[index]
