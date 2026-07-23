from __future__ import annotations

import json
import os
import socket
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import NoReturn

import pytest

import minerva.cli.main as cli_module
import minerva.evidence.service as evidence_service_module
import minerva.synthesis.request_fulfillment as request_fulfillment_module
import minerva.synthesis.service as synthesis_module
from conftest import ClaimSeed, Lab, fixed_clock
from minerva.cli._common import EXIT_DOMAIN
from minerva.core.db import Database
from minerva.core.errors import IntegrityError
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.integrations.research_packet import (
    parse_research_packet,
    serialize_research_packet,
)
from minerva.integrations.research_request import (
    ResearchRequestDocument,
    build_research_request,
    parse_research_request,
    serialize_research_request,
)
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.synthesis.request_fulfillment import ResearchRequestFulfillmentService

_GOLDEN = Path(__file__).parent / "fixtures" / "minerva.research-request.v1.golden.json"
_GOLDEN_DIGEST = "d1ea1f37c6c42f0c39db49463cb6420c21b7bef227e55e77b9e88a4de6c5b32f"
_UNKNOWN_MISSION = "mis_ffffffffffffffffffffffffffffffff"
_UNKNOWN_CLAIM = "clm_ffffffffffffffffffffffffffffffff"
_UNKNOWN_EVIDENCE = "evd_ffffffffffffffffffffffffffffffff"


def _write_request(
    tmp_path: Path,
    *,
    mission_id: str,
    claim_id: str,
    evidence_ids: tuple[str, ...],
    name: str = "request.json",
) -> tuple[Path, ResearchRequestDocument]:
    document = build_research_request(
        mission_id=mission_id,
        claim_id=claim_id,
        expected_active_citation_ids=tuple(sorted(evidence_ids)),
    )
    target = tmp_path / name
    target.write_bytes(serialize_research_request(document))
    return target, document


def _success(
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
) -> tuple[dict[str, object], str]:
    assert cli_module.main(argv) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert isinstance(payload, dict)
    return payload, captured.out


def _failure(
    capsys: pytest.CaptureFixture[str],
    argv: tuple[str, ...],
    expected_code: str,
) -> str:
    assert cli_module.main(argv) == EXIT_DOMAIN
    captured = capsys.readouterr()
    assert captured.out == ""
    payload = json.loads(captured.err)
    assert payload["error"]["code"] == expected_code
    assert len(captured.err) < 300
    return captured.err


def _fulfill_argv(
    database: Database,
    request_path: Path,
    output_dir: Path,
) -> tuple[str, ...]:
    return (
        "request",
        "fulfill",
        "--db",
        str(database.path),
        "--input",
        str(request_path),
        "--output-dir",
        str(output_dir),
    )


def _database_dump(database: Database) -> str:
    with database.read() as connection:
        return "\n".join(connection.iterdump())


def _seed_four_stances(lab: Lab) -> tuple[ClaimSeed, tuple[EvidenceCard, ...]]:
    seed = lab.seed_claim(
        content=(
            b"Exact support observation.\n"
            b"Exact opposing observation.\n"
            b"Exact contextual observation.\n"
            b"Exact inconclusive observation.\n"
        )
    )
    cards = (
        lab.cite(seed, "Exact support observation.", EvidenceStance.SUPPORTS),
        lab.cite(seed, "Exact opposing observation.", EvidenceStance.OPPOSES),
        lab.cite(seed, "Exact contextual observation.", EvidenceStance.CONTEXT),
        lab.cite(seed, "Exact inconclusive observation.", EvidenceStance.INCONCLUSIVE),
    )
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.CONTESTED,
        reason="The complete ledger contains active support and opposition.",
        expected_version=1,
        identity=lab.identity,
    )
    return seed, cards


def _add_second_claim_in_mission(lab: Lab, seed: ClaimSeed) -> ClaimSeed:
    content = b"Other claim evidence must remain isolated.\n"
    question = lab.research.add_question(
        mission_id=seed.mission.id,
        text="Does another observation support a separate claim?",
        identity=lab.identity,
    )
    claim = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=question.id,
        statement="A separate claim is supported.",
        falsification_criteria="An opposing observation would falsify the separate claim.",
        identity=lab.identity,
    )
    snapshot = lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=content,
        original_label="notes/other-claim.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    return ClaimSeed(seed.mission, question, claim, snapshot, content)


def test_request_verify_checked_in_golden_has_exact_bounded_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload, output = _success(
        capsys,
        ("request", "verify", "--input", str(_GOLDEN)),
    )

    assert payload == {
        "status": "verified",
        "schema_version": "minerva.research-request.v1",
        "request_digest": _GOLDEN_DIGEST,
        "requested_output_schema": "minerva.research-brief.v2",
        "evidence_selection": {
            "policy": "complete_claim_ledger",
            "expected_active_citation_count": 2,
        },
        "integrity": {
            "digest_verified": True,
            "authenticity": "not_established",
            "authorization": "not_established",
        },
    }
    assert output == (
        '{"evidence_selection":{"expected_active_citation_count":2,'
        '"policy":"complete_claim_ledger"},'
        '"integrity":{"authenticity":"not_established",'
        '"authorization":"not_established","digest_verified":true},'
        f'"request_digest":"{_GOLDEN_DIGEST}",'
        '"requested_output_schema":"minerva.research-brief.v2",'
        '"schema_version":"minerva.research-request.v1","status":"verified"}\n'
    )
    golden_text = _GOLDEN.read_text(encoding="utf-8")
    assert "mis_" not in output
    assert "clm_" not in output
    assert "evd_" not in output
    assert golden_text not in output


@pytest.mark.security
def test_request_verify_uses_no_database_network_or_provider_credentials(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("offline request verification crossed a forbidden boundary")

    monkeypatch.setattr(cli_module, "Database", forbidden)
    monkeypatch.setattr(cli_module, "load_provider_credential", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    payload, _output = _success(
        capsys,
        ("request", "verify", "--input", str(_GOLDEN)),
    )

    assert payload["status"] == "verified"


@pytest.mark.security
def test_invalid_request_is_rejected_before_database_construction(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = json.loads(_GOLDEN.read_bytes())
    document["request_digest"] = "0" * 64
    request_path = tmp_path / "invalid-request.json"
    request_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    output_dir = tmp_path / "must-not-exist"

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("invalid request crossed a forbidden boundary")

    monkeypatch.setattr(cli_module, "Database", forbidden)
    monkeypatch.setattr(cli_module, "load_provider_credential", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    error = _failure(
        capsys,
        (
            "request",
            "fulfill",
            "--db",
            str(tmp_path / "private.db"),
            "--input",
            str(request_path),
            "--output-dir",
            str(output_dir),
        ),
        "request_digest_mismatch",
    )

    assert "invalid-request" not in error
    assert str(tmp_path) not in error
    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("mission_id", "claim_id", "expected_code"),
    [
        (_UNKNOWN_MISSION, _UNKNOWN_CLAIM, "mission_not_found"),
        ("existing", _UNKNOWN_CLAIM, "claim_not_found"),
        ("other", "existing", "request_claim_scope_invalid"),
    ],
)
def test_fulfillment_rejects_missing_and_cross_mission_scope(
    mission_id: str,
    claim_id: str,
    expected_code: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = lab.seed_claim(source_label="notes/first.txt")
    second = lab.seed_claim(source_label="notes/second.txt")
    selected_mission = {
        "existing": first.mission.id,
        "other": second.mission.id,
    }.get(mission_id, mission_id)
    selected_claim = first.claim.id if claim_id == "existing" else claim_id
    request_path, _document = _write_request(
        tmp_path,
        mission_id=selected_mission,
        claim_id=selected_claim,
        evidence_ids=(),
    )
    output_dir = tmp_path / "output"

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        expected_code,
    )

    assert not output_dir.exists()


@pytest.mark.security
def test_fulfillment_rejects_claim_without_status_history(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(),
    )
    output_dir = tmp_path / "output"

    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER claim_status_no_delete")
        connection.execute(
            "DELETE FROM claim_status_events WHERE claim_id = ?",
            (seed.claim.id,),
        )
    before = _database_dump(lab.database)

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "claim_not_found",
    )

    assert not output_dir.exists()
    assert _database_dump(lab.database) == before


@pytest.mark.security
@pytest.mark.parametrize("scope_case", ["unknown", "wrong_claim"])
def test_fulfillment_rejects_unknown_and_wrong_claim_evidence(
    scope_case: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    selected = lab.seed_claim(source_label="notes/selected.txt")
    if scope_case == "unknown":
        requested_evidence = _UNKNOWN_EVIDENCE
    else:
        other = _add_second_claim_in_mission(lab, selected)
        requested_evidence = lab.cite(
            other,
            "Other claim evidence must remain isolated.",
            EvidenceStance.SUPPORTS,
        ).id
    request_path, _document = _write_request(
        tmp_path,
        mission_id=selected.mission.id,
        claim_id=selected.claim.id,
        evidence_ids=(requested_evidence,),
    )

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, tmp_path / "output"),
        "request_evidence_scope_invalid",
    )


@pytest.mark.security
def test_fulfillment_rejects_explicitly_withdrawn_evidence(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    withdrawn = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=withdrawn.id,
        reason="The supporting observation was superseded.",
        identity=lab.identity,
    )
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(withdrawn.id,),
    )

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, tmp_path / "output"),
        "request_evidence_withdrawn",
    )


@pytest.mark.parametrize("change", ["omitted", "added_after_request"])
def test_fulfillment_rejects_stale_or_incomplete_active_selection(
    change: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    if change == "omitted":
        lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(support.id,),
    )
    if change == "added_after_request":
        lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, tmp_path / "output"),
        "request_evidence_selection_changed",
    )


@pytest.mark.security
def test_fulfillment_is_claim_scoped_canonical_deterministic_and_read_only(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected, cards = _seed_four_stances(lab)
    other = _add_second_claim_in_mission(lab, selected)
    other_evidence = lab.cite(
        other,
        "Other claim evidence must remain isolated.",
        EvidenceStance.SUPPORTS,
    )
    linked_finding = lab.research.add_finding(
        mission_id=selected.mission.id,
        claim_id=selected.claim.id,
        statement="The selected support is an exact recorded observation.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.CONTESTED,
        uncertainty="Opposing evidence remains active.",
        evidence_ids=(cards[0].id,),
        identity=lab.identity,
    )
    linked_assumption = lab.research.add_finding(
        mission_id=selected.mission.id,
        claim_id=selected.claim.id,
        statement="A target-claim assumption remains explicitly non-evidentiary.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="",
        evidence_ids=(),
        identity=lab.identity,
    )
    linked_question = lab.research.add_finding(
        mission_id=selected.mission.id,
        claim_id=selected.claim.id,
        statement="What additional observation would resolve the target claim?",
        statement_kind=StatementKind.UNRESOLVED_QUESTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="",
        evidence_ids=(),
        identity=lab.identity,
    )
    global_assumption = lab.research.add_finding(
        mission_id=selected.mission.id,
        statement="A mission-wide assumption must not enter a claim-scoped result.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="This assumption is outside the selected claim scope.",
        evidence_ids=(),
        identity=lab.identity,
    )
    request_path, request = _write_request(
        tmp_path,
        mission_id=selected.mission.id,
        claim_id=selected.claim.id,
        evidence_ids=tuple(card.id for card in cards),
    )
    before = _database_dump(lab.database)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("request fulfillment crossed an external boundary")

    monkeypatch.setattr(cli_module, "load_provider_credential", forbidden)
    monkeypatch.setattr(cli_module, "_identity", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(synthesis_module, "_render_markdown", forbidden)

    first_dir = tmp_path / "first-output"
    first_result, first_stdout = _success(
        capsys,
        _fulfill_argv(lab.database, request_path, first_dir),
    )
    second_dir = tmp_path / "second-output"
    second_result, second_stdout = _success(
        capsys,
        _fulfill_argv(lab.database, request_path, second_dir),
    )

    first_brief = (first_dir / "research-brief.json").read_bytes()
    first_manifest = (first_dir / "research-result.json").read_bytes()
    second_brief = (second_dir / "research-brief.json").read_bytes()
    second_manifest = (second_dir / "research-result.json").read_bytes()
    packet = parse_research_packet(first_brief)
    payload = packet.brief.model_dump(mode="json")
    manifest = json.loads(first_manifest)

    assert first_brief == second_brief
    assert first_manifest == second_manifest
    assert first_result == second_result == manifest
    assert first_stdout.encode() == first_manifest
    assert second_stdout.encode() == second_manifest
    assert serialize_research_packet(packet) == first_brief
    assert packet.schema_version == "minerva.research-brief.v2"
    assert manifest == {
        "schema_version": "minerva.research-result.v1",
        "status": "fulfilled",
        "request_digest": request.request_digest,
        "output_artifact": {
            "schema_version": "minerva.research-brief.v2",
            "sha256": sha256(first_brief).hexdigest(),
        },
    }
    assert [item["id"] for item in payload["claims"]] == [selected.claim.id]
    assert payload["claims"][0]["status"] == "contested"
    assert payload["claims"][0]["version"] == 2
    assert [item["id"] for item in payload["questions"]] == [selected.question.id]
    assert [item["snapshot_id"] for item in payload["sources"]] == [selected.snapshot.snapshot_id]
    assert {item["citation_id"] for item in payload["citations"]} == {card.id for card in cards}
    assert {item["stance"] for item in payload["citations"]} == {
        "supports",
        "opposes",
        "context",
        "inconclusive",
    }
    assert [item["id"] for item in payload["findings"]] == [linked_finding.id]
    assert [item["id"] for item in payload["assumptions"]] == [linked_assumption.id]
    assert [item["id"] for item in payload["unresolved_questions"]] == [linked_question.id]
    assert payload["uncertainties"] == [
        {"finding_id": linked_finding.id, "text": "Opposing evidence remains active."}
    ]
    assert other.claim.id not in first_brief.decode()
    assert other.question.id not in first_brief.decode()
    assert other.snapshot.snapshot_id not in first_brief.decode()
    assert other_evidence.id not in first_brief.decode()
    assert global_assumption.id not in first_brief.decode()
    assert stat.S_IMODE(first_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((first_dir / "research-brief.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((first_dir / "research-result.json").stat().st_mode) == 0o600
    assert _database_dump(lab.database) == before


@pytest.mark.security
def test_request_artifacts_enforce_0600_under_restrictive_umask(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    original_umask = os.umask(0o777)
    try:
        synthesis_module.write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=b"brief\n",
            result_json=b"result\n",
        )
    finally:
        os.umask(original_umask)

    brief = output_dir / "research-brief.json"
    result = output_dir / "research-result.json"
    assert brief.read_bytes() == b"brief\n"
    assert result.read_bytes() == b"result\n"
    assert stat.S_IMODE(brief.stat().st_mode) == 0o600
    assert stat.S_IMODE(result.stat().st_mode) == 0o600


@pytest.mark.security
def test_request_artifact_permission_failure_cleans_partial_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir(mode=0o700)
    real_fchmod = synthesis_module.os.fchmod
    chmod_calls = 0

    def fail_second_fchmod(descriptor: int, mode: int) -> None:
        nonlocal chmod_calls
        chmod_calls += 1
        if chmod_calls == 2:
            raise OSError("synthetic permission failure")
        real_fchmod(descriptor, mode)

    monkeypatch.setattr(synthesis_module.os, "fchmod", fail_second_fchmod)

    with pytest.raises(OSError, match="synthetic permission failure"):
        synthesis_module.write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=b"brief\n",
            result_json=b"result\n",
        )

    assert chmod_calls == 2
    assert list(output_dir.iterdir()) == []


def test_fulfillment_retains_withdrawn_supersession_closure(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        "Evidence opposes the claim.",
        EvidenceStance.OPPOSES,
        supersedes_evidence_id=original.id,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=original.id,
        reason="A corrected exact observation superseded the original.",
        identity=lab.identity,
    )
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(replacement.id,),
    )
    output_dir = tmp_path / "output"

    _success(capsys, _fulfill_argv(lab.database, request_path, output_dir))

    packet = parse_research_packet((output_dir / "research-brief.json").read_bytes())
    citations = {item.citation_id: item for item in packet.brief.citations}
    ledger = {item.citation_id: item for item in packet.brief.claims[0].evidence_ledger}
    assert set(citations) == {original.id, replacement.id}
    assert citations[original.id].withdrawn is True
    assert citations[original.id].withdrawal_reason == (
        "A corrected exact observation superseded the original."
    )
    assert citations[replacement.id].supersedes_citation_id == original.id
    assert ledger[original.id].withdrawn is True
    assert ledger[replacement.id].withdrawn is False


@pytest.mark.parametrize("existing_name", ["research-brief.json", "research-result.json"])
def test_fulfillment_never_overwrites_and_rolls_back_partial_publication(
    existing_name: str,
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(evidence.id,),
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    sentinel = b"PRIVATE PREEXISTING CONTENT"
    (output_dir / existing_name).write_bytes(sentinel)
    before = _database_dump(lab.database)

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "export_target_exists",
    )

    assert (output_dir / existing_name).read_bytes() == sentinel
    other_name = (
        "research-result.json" if existing_name == "research-brief.json" else "research-brief.json"
    )
    assert not (output_dir / other_name).exists()
    assert _database_dump(lab.database) == before


def test_fulfillment_uses_one_database_read_snapshot(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    _request_path, document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(evidence.id,),
    )
    original_read = lab.database.read
    read_count = 0

    @contextmanager
    def counted_read() -> Iterator[sqlite3.Connection]:
        nonlocal read_count
        read_count += 1
        with original_read() as connection:
            yield connection

    monkeypatch.setattr(lab.database, "read", counted_read)
    fulfillment = ResearchRequestFulfillmentService(lab.database)
    original_build_packet_json = fulfillment._synthesis.build_research_packet_json

    def checked_build_packet_json(
        mission_id: str,
        *,
        connection: sqlite3.Connection | None = None,
        claim_id: str | None = None,
    ) -> bytes:
        assert connection is not None
        query_only = connection.execute("PRAGMA query_only").fetchone()
        assert query_only is not None
        assert int(query_only[0]) == 1
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE request_fulfillment_must_remain_read_only(value TEXT)")
        return original_build_packet_json(
            mission_id,
            connection=connection,
            claim_id=claim_id,
        )

    monkeypatch.setattr(
        fulfillment._synthesis,
        "build_research_packet_json",
        checked_build_packet_json,
    )

    fulfillment.fulfill(
        request=parse_research_request(serialize_research_request(document)),
        output_dir=tmp_path / "output",
    )

    assert read_count == 1


@pytest.mark.security
def test_cumulative_citation_text_budget_rejects_before_materialization(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = "A" * 400
    seed = lab.seed_claim(content=(quote + "\n").encode("utf-8"))
    evidence_ids = tuple(lab.cite(seed, quote, EvidenceStance.SUPPORTS).id for _index in range(4))
    _request_path, document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=evidence_ids,
    )
    output_dir = tmp_path / "output"
    fulfillment = ResearchRequestFulfillmentService(lab.database)
    monkeypatch.setattr(
        fulfillment._synthesis,
        "_max_export_bytes",
        1_024,
    )

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("oversized citation text reached materialization")

    monkeypatch.setattr(synthesis_module, "verify_evidence_references", forbidden)
    before = _database_dump(lab.database)

    with pytest.raises(IntegrityError) as caught:
        fulfillment.fulfill(request=document, output_dir=output_dir)

    assert caught.value.code == "brief_work_limit"
    assert not output_dir.exists()
    assert _database_dump(lab.database) == before


@pytest.mark.security
def test_claim_history_overflow_is_rejected_before_synthesis(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"Repeated bounded observation.\n")
    evidence_ids = tuple(
        lab.cite(
            seed,
            "Repeated bounded observation.",
            EvidenceStance.SUPPORTS,
        ).id
        for _index in range(6)
    )
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=evidence_ids,
    )
    output_dir = tmp_path / "output"

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("oversized claim history reached synthesis")

    monkeypatch.setattr(request_fulfillment_module, "MAX_SYNTHESIS_RECORDS", 5)
    monkeypatch.setattr(
        synthesis_module.SynthesisService,
        "build_research_packet_json",
        forbidden,
    )

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "brief_work_limit",
    )

    assert not output_dir.exists()


@pytest.mark.security
def test_unrelated_mission_history_is_cut_off_by_cumulative_query_budget(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(evidence.id,),
    )
    monkeypatch.setattr(request_fulfillment_module, "MAX_REQUEST_QUERY_VM_STEPS", 50_000)
    monkeypatch.setattr(request_fulfillment_module, "_QUERY_PROGRESS_GRANULARITY", 100)

    baseline_output_dir = tmp_path / "baseline-output"
    _success(
        capsys,
        _fulfill_argv(lab.database, request_path, baseline_output_dir),
    )
    question_rows: list[tuple[object, ...]] = []
    audit_rows: list[tuple[object, ...]] = []
    for index in range(2_000):
        question_id = f"que_{100_000 + index:032x}"
        question_rows.append(
            (
                question_id,
                seed.mission.id,
                f"Unrelated mission question {index}?",
                lab.identity.actor_id,
                lab.identity.run_id,
                fixed_clock(),
            )
        )
        audit_rows.append(
            (
                f"aud_{100_000 + index:032x}",
                "research.question.created",
                "research_question",
                question_id,
                seed.mission.id,
                lab.identity.actor_id,
                lab.identity.run_id,
                fixed_clock(),
                "{}",
            )
        )
    with lab.database.transaction() as connection:
        connection.executemany(
            """
            INSERT INTO research_questions(
                id, mission_id, question_text, creator_id, run_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            question_rows,
        )
        connection.executemany(
            """
            INSERT INTO audit_events(
                id, event_type, entity_type, entity_id, mission_id,
                actor_id, run_id, occurred_at, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            audit_rows,
        )
    output_dir = tmp_path / "output"
    before = _database_dump(lab.database)

    error = _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "brief_work_limit",
    )

    assert "Unrelated mission question" not in error
    assert not output_dir.exists()
    assert _database_dump(lab.database) == before


@pytest.mark.security
def test_active_selection_overflow_is_rejected_before_synthesis(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"Repeated active observation.\n")
    evidence_ids = tuple(
        lab.cite(
            seed,
            "Repeated active observation.",
            EvidenceStance.SUPPORTS,
        ).id
        for _index in range(201)
    )
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=tuple(sorted(evidence_ids)[:200]),
    )
    output_dir = tmp_path / "output"

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("selection drift reached synthesis")

    monkeypatch.setattr(request_fulfillment_module, "MAX_SYNTHESIS_RECORDS", 2)
    monkeypatch.setattr(
        synthesis_module.SynthesisService,
        "build_research_packet_json",
        forbidden,
    )

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "request_evidence_selection_changed",
    )

    assert not output_dir.exists()


@pytest.mark.security
def test_withdrawn_history_hits_preflight_before_citation_materialization(
    lab: Lab,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content=b"Original observation.\nReplacement observation.\n")
    original = lab.cite(seed, "Original observation.", EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        "Replacement observation.",
        EvidenceStance.OPPOSES,
        supersedes_evidence_id=original.id,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=original.id,
        reason="The replacement superseded the original observation.",
        identity=lab.identity,
    )
    request_path, _document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(replacement.id,),
    )
    output_dir = tmp_path / "output"

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("bounded preflight materialized claim history")

    monkeypatch.setattr(synthesis_module, "MAX_SYNTHESIS_RECORDS", 5)
    monkeypatch.setattr(synthesis_module, "verify_evidence_references", forbidden)
    monkeypatch.setattr(synthesis_module, "verify_snapshot_integrity", forbidden)
    monkeypatch.setattr(evidence_service_module, "verify_evidence_reference", forbidden)

    _failure(
        capsys,
        _fulfill_argv(lab.database, request_path, output_dir),
        "brief_work_limit",
    )

    assert not output_dir.exists()


@pytest.mark.security
def test_claim_scoped_audit_query_does_not_materialize_unrelated_mission_rows(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    for index in range(40):
        lab.research.add_question(
            mission_id=seed.mission.id,
            text=f"Unrelated mission question {index}?",
            identity=lab.identity,
        )
    _request_path, document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(evidence.id,),
    )
    original_connect = lab.database.connect
    returned_audit_rows = 0

    def counting_connect(*, validate_schema: bool = True) -> sqlite3.Connection:
        connection = original_connect(validate_schema=validate_schema)

        def counting_factory(
            cursor: sqlite3.Cursor,
            row: tuple[object, ...],
        ) -> sqlite3.Row:
            nonlocal returned_audit_rows
            columns = tuple(item[0] for item in (cursor.description or ()))
            if columns == (
                "sequence",
                "id",
                "event_type",
                "entity_type",
                "entity_id",
                "mission_id",
                "actor_id",
                "run_id",
                "occurred_at",
            ):
                returned_audit_rows += 1
            return sqlite3.Row(cursor, row)

        connection.row_factory = counting_factory
        return connection

    monkeypatch.setattr(lab.database, "connect", counting_connect)

    ResearchRequestFulfillmentService(lab.database).fulfill(
        request=parse_research_request(serialize_research_request(document)),
        output_dir=tmp_path / "output",
    )

    assert 6 <= returned_audit_rows < 20


@pytest.mark.security
def test_claim_scoped_fulfillment_rejects_malformed_duplicate_run_start(
    lab: Lab,
    tmp_path: Path,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    _request_path, document = _write_request(
        tmp_path,
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        evidence_ids=(evidence.id,),
    )
    alternate_run_id = lab.ids("run")
    with lab.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO research_runs(id, actor_id, actor_kind, purpose, created_at)
            VALUES (?, ?, 'os_user', ?, ?)
            """,
            (
                alternate_run_id,
                "os-user:malformed-provenance",
                "exercise malformed provenance rejection",
                fixed_clock(),
            ),
        )
        connection.execute(
            """
            INSERT INTO audit_events(
                id, event_type, entity_type, entity_id, mission_id,
                actor_id, run_id, occurred_at, details_json
            ) VALUES (?, 'research.run.started', 'research_run', ?, NULL, ?, ?, ?, '{}')
            """,
            (
                lab.ids("aud"),
                lab.identity.run_id,
                lab.identity.actor_id,
                alternate_run_id,
                fixed_clock(),
            ),
        )

    output_dir = tmp_path / "output"
    with pytest.raises(IntegrityError) as caught:
        ResearchRequestFulfillmentService(lab.database).fulfill(
            request=parse_research_request(serialize_research_request(document)),
            output_dir=output_dir,
        )

    assert caught.value.code == "packet_provenance_invalid"
    assert not output_dir.exists()
