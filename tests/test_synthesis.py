from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

import minerva.evidence.integrity as evidence_integrity_module
import minerva.integrations.research_packet as packet_module
import minerva.synthesis.service as synthesis_module
from conftest import ClaimSeed, Lab, SequenceIds, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import FindingCandidate, ModelProvider, ProviderSelection
from minerva.assist.service import AssistanceService
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError, OperationalError
from minerva.core.types import IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.integrations.research_packet import (
    canonical_research_payload_bytes,
    parse_research_packet,
    serialize_research_packet,
)
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.synthesis.service import SynthesisService


@dataclass(frozen=True, slots=True)
class BriefScenario:
    seed: ClaimSeed
    support: EvidenceCard
    opposition: EvidenceCard


class FailingAuditSink:
    def __init__(self, ids: SequenceIds) -> None:
        self.delegate = AuditRecorder(clock=fixed_clock, id_factory=ids)

    def ensure_run(
        self,
        connection: sqlite3.Connection,
        identity: IdentityContext,
    ) -> None:
        self.delegate.ensure_run(connection, identity)

    def record(
        self,
        connection: sqlite3.Connection,
        *,
        identity: IdentityContext,
        event_type: str,
        entity_type: str,
        entity_id: str,
        mission_id: str | None,
        details: Mapping[str, object] | None = None,
    ) -> str:
        raise RuntimeError("synthetic audit failure")


def _populate_brief(lab: Lab) -> BriefScenario:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The source contains a direct supporting observation.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.CONTESTED,
        uncertainty="The same source also contains an opposing observation.",
        evidence_ids=(support.id,),
        identity=lab.identity,
    )
    lab.research.add_finding(
        mission_id=seed.mission.id,
        statement="The local observation is representative of a wider population.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="Representativeness has not been established.",
        evidence_ids=(),
        identity=lab.identity,
    )
    lab.research.add_finding(
        mission_id=seed.mission.id,
        statement="Which independent source can resolve the contradiction?",
        statement_kind=StatementKind.UNRESOLVED_QUESTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="No independent source has been imported.",
        evidence_ids=(),
        identity=lab.identity,
    )
    return BriefScenario(seed, support, opposition)


def test_build_brief_is_byte_deterministic_and_digests_are_reproducible(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    first = lab.synthesis.build_brief(scenario.seed.mission.id)
    second = lab.synthesis.build_brief(scenario.seed.mission.id)
    document = parse_research_packet(first.json)
    canonical_payload = canonical_research_payload_bytes(document.brief)

    assert first == second
    assert first.export_digest == sha256(canonical_payload).hexdigest()
    assert document.export_digest == first.export_digest
    assert document.brief.model_dump(mode="json") == first.payload
    assert first.json_sha256 == sha256(first.json).hexdigest()
    assert first.markdown_sha256 == sha256(first.markdown).hexdigest()
    assert first.json.endswith(b"\n")
    assert b'\n  "' not in first.json
    assert first.markdown.endswith(b"\n")


def test_packet_preserves_ownership_provenance_and_audit_references(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    artifacts = lab.synthesis.build_brief(scenario.seed.mission.id)
    payload = artifacts.payload

    assert payload["ownership"] == {
        "system": "minerva",
        "researches": True,
        "executes": False,
        "approves": False,
        "orchestrates": False,
        "publishes": False,
    }
    assert payload["runs"] == [
        {
            "id": lab.identity.run_id,
            "actor_id": lab.identity.actor_id,
            "actor_kind": lab.identity.actor_kind.value,
            "purpose": lab.identity.purpose,
            "created_at": fixed_clock(),
        }
    ]
    assert {reference["event_type"] for reference in payload["audit_references"]} == {
        "research.run.started",
        "research.mission.created",
        "research.question.created",
        "research.claim.created",
        "source.snapshot.imported",
        "evidence.card.created",
        "research.finding.created",
    }
    assert all(
        item["creator_id"] == lab.identity.actor_id and item["run_id"] == lab.identity.run_id
        for collection in (
            payload["questions"],
            payload["claims"],
            payload["findings"],
            payload["assumptions"],
            payload["unresolved_questions"],
            payload["citations"],
            payload["sources"],
        )
        for item in collection
    )


def test_packet_preserves_optional_citations_on_non_material_statements(lab: Lab) -> None:
    seed = lab.seed_claim()
    context = lab.cite(
        seed,
        "Café context remains uncertain.",
        EvidenceStance.CONTEXT,
    )
    assumption = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The observed context may generalize.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="Generalizability remains untested.",
        evidence_ids=(context.id,),
        identity=lab.identity,
    )
    unresolved = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="Which observation resolves the remaining context?",
        statement_kind=StatementKind.UNRESOLVED_QUESTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="No resolving observation is recorded.",
        evidence_ids=(context.id,),
        identity=lab.identity,
    )

    payload = lab.synthesis.build_brief(seed.mission.id).payload

    assumptions = {item["id"]: item for item in payload["assumptions"]}
    unresolved_questions = {item["id"]: item for item in payload["unresolved_questions"]}
    assert assumptions[assumption.id]["citation_ids"] == [context.id]
    assert unresolved_questions[unresolved.id]["citation_ids"] == [context.id]


def test_packet_matches_the_checked_in_golden_fixture(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    artifacts = lab.synthesis.build_brief(scenario.seed.mission.id)
    golden = Path(__file__).parent / "fixtures" / "minerva.research-brief.v2.golden.json"
    golden_bytes = golden.read_bytes()
    golden_document = parse_research_packet(golden_bytes)

    assert artifacts.json == golden_bytes
    assert golden_bytes == serialize_research_packet(golden_document)
    assert (
        artifacts.export_digest
        == "80a6579008f23314463bedb5f62fbeed478537f0d3718684f42ef7d451066576"
    )
    assert golden_document.export_digest == artifacts.export_digest


def test_packet_rejects_audit_provenance_tampering(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute(
            """
            UPDATE audit_events SET actor_id = ?
            WHERE event_type = 'evidence.card.created' AND entity_id = ?
            """,
            ("os-user:forged", scenario.support.id),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "packet_integrity_invalid"


def test_packet_rejects_duplicate_run_start_audit_history(lab: Lab) -> None:
    seed = lab.seed_claim()
    with lab.database.transaction() as connection:
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
                lab.identity.run_id,
                fixed_clock(),
            ),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(seed.mission.id)

    assert caught.value.code == "packet_provenance_invalid"


def test_packet_rejects_noncontiguous_claim_status_history(lab: Lab) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="The exact observation supports a provisional status.",
        expected_version=1,
        identity=lab.identity,
    )
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER claim_status_no_delete")
        connection.execute(
            "DELETE FROM claim_status_events WHERE claim_id = ? AND version = 1",
            (seed.claim.id,),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(seed.mission.id)

    assert caught.value.code == "packet_provenance_invalid"


def test_brief_keeps_support_opposition_and_exact_citation_locations(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    payload = lab.synthesis.build_brief(scenario.seed.mission.id).payload
    claim = payload["claims"][0]
    citations = {item["citation_id"]: item for item in payload["citations"]}

    assert claim["contested"] is True
    assert claim["evidence_ledger"] == [
        {
            "citation_id": scenario.support.id,
            "stance": "supports",
            "withdrawn": False,
        },
        {
            "citation_id": scenario.opposition.id,
            "stance": "opposes",
            "withdrawn": False,
        },
    ]
    support = citations[scenario.support.id]
    assert support["snapshot_sha256"] == scenario.seed.snapshot.sha256
    assert support["quote"] == "Evidence supports the claim."
    assert support["location"] == {
        "scheme": "utf8-byte-offset-v1",
        "start_byte": scenario.support.start_byte,
        "end_byte": scenario.support.end_byte,
    }


def test_brief_separates_material_findings_assumptions_and_unknowns(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    artifacts = lab.synthesis.build_brief(scenario.seed.mission.id)
    payload = artifacts.payload
    markdown = artifacts.markdown.decode()

    assert len(payload["findings"]) == 1
    assert payload["findings"][0]["statement_kind"] == "observed_fact"
    assert len(payload["assumptions"]) == 1
    assert payload["assumptions"][0]["citation_ids"] == []
    assert len(payload["unresolved_questions"]) == 1
    assert "Assumptions (explicitly non-evidentiary)" in markdown
    assert "Unresolved questions" in markdown
    assert "SUPPORTS" in markdown
    assert "OPPOSES" in markdown
    assert "CONTESTED" in markdown


def test_unknown_mission_cannot_produce_a_plausible_brief(lab: Lab) -> None:
    with pytest.raises(NotFoundError) as caught:
        lab.synthesis.build_brief("mis_" + "0" * 32)

    assert caught.value.code == "mission_not_found"


def test_withdrawn_citation_invalidates_material_finding_export(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    lab.evidence.withdraw_evidence(
        evidence_id=scenario.support.id,
        reason="The supporting observation was withdrawn after review.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "citation_withdrawn"


def test_snapshot_tamper_is_detected_after_explicit_trigger_removal(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    changed = b"X" + scenario.seed.content[1:]
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (changed, scenario.seed.snapshot.snapshot_id),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "snapshot_tampered"


def test_citation_tamper_is_detected_after_explicit_trigger_removal(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER evidence_no_update")
        connection.execute(
            "UPDATE evidence_cards SET quote = ? WHERE id = ?",
            ("A forged quote.", scenario.support.id),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "citation_tampered"


def test_configured_export_bound_is_enforced_before_return(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    bounded = SynthesisService(
        lab.database,
        clock=fixed_clock,
        id_factory=lab.ids,
        max_export_bytes=1_024,
    )

    with pytest.raises(IntegrityError) as caught:
        bounded.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "brief_too_large"


def test_export_writes_only_fixed_contained_owner_only_files(
    lab: Lab,
    tmp_path: Path,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"

    result = lab.synthesis.export_brief(
        mission_id=scenario.seed.mission.id,
        output_dir=output_dir,
        identity=lab.identity,
    )

    assert result.markdown_path.parent == output_dir
    assert result.json_path.parent == output_dir
    assert {result.markdown_path.name, result.json_path.name} == {
        "research-brief.md",
        "research-brief.json",
    }
    assert sha256(result.markdown_path.read_bytes()).hexdigest() == result.markdown_sha256
    assert sha256(result.json_path.read_bytes()).hexdigest() == result.json_sha256
    assert stat.S_IMODE(os.stat(result.markdown_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(result.json_path).st_mode) == 0o600


def test_export_artifacts_remain_deterministic_after_export_audit(lab: Lab, tmp_path: Path) -> None:
    scenario = _populate_brief(lab)
    before = lab.synthesis.build_brief(scenario.seed.mission.id)
    result = lab.synthesis.export_brief(
        mission_id=scenario.seed.mission.id,
        output_dir=tmp_path / "export",
        identity=lab.identity,
    )
    after = lab.synthesis.build_brief(scenario.seed.mission.id)

    assert after == before
    assert result.export_digest == before.export_digest
    assert result.markdown_path.read_bytes() == before.markdown
    assert result.json_path.read_bytes() == before.json


def test_existing_second_target_causes_rollback_and_first_file_cleanup(
    lab: Lab,
    tmp_path: Path,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    existing_json = output_dir / "research-brief.json"
    existing_json.write_bytes(b"operator-owned existing file")

    with pytest.raises(ConflictError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert caught.value.code == "export_target_exists"
    assert existing_json.read_bytes() == b"operator-owned existing file"
    assert not (output_dir / "research-brief.md").exists()
    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM brief_exports WHERE mission_id = ?",
                (scenario.seed.mission.id,),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM audit_events
            WHERE event_type = 'synthesis.brief.exported' AND mission_id = ?
            """,
                (scenario.seed.mission.id,),
            ).fetchone()[0]
            == 0
        )


def test_symlinked_output_directory_is_rejected(lab: Lab, tmp_path: Path) -> None:
    scenario = _populate_brief(lab)
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=linked,
            identity=lab.identity,
        )

    assert caught.value.code == "export_symlink_rejected"
    assert list(actual.iterdir()) == []


def test_preexisting_target_symlink_is_never_followed(
    lab: Lab,
    tmp_path: Path,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"must remain unchanged")
    (output_dir / "research-brief.md").symlink_to(outside)

    with pytest.raises(ConflictError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert caught.value.code == "export_target_exists"
    assert outside.read_bytes() == b"must remain unchanged"
    assert not (output_dir / "research-brief.json").exists()


def test_export_audit_failure_removes_both_files_and_rolls_back_export_row(
    lab: Lab,
    tmp_path: Path,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    failing = SynthesisService(
        lab.database,
        audit=FailingAuditSink(lab.ids),
        clock=fixed_clock,
        id_factory=lab.ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        failing.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM brief_exports WHERE mission_id = ?",
                (scenario.seed.mission.id,),
            ).fetchone()[0]
            == 0
        )


def test_synthesis_rejects_coordinated_snapshot_row_rewrite_with_original_audit(
    lab: Lab,
) -> None:
    scenario = _populate_brief(lab)
    changed = b"Z" + scenario.seed.content[1:]
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            """
            UPDATE source_snapshots
            SET content = ?, sha256 = ?, byte_length = ?
            WHERE id = ?
            """,
            (
                changed,
                sha256(changed).hexdigest(),
                len(changed),
                scenario.seed.snapshot.snapshot_id,
            ),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "snapshot_tampered"


def test_claim_status_provenance_and_stale_evidence_warning_are_exported(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    rationale = "The exact supporting observation meets the provisional threshold."
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason=rationale,
        expected_version=1,
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="The source observation was withdrawn after review.",
        identity=lab.identity,
    )

    artifacts = lab.synthesis.build_brief(seed.mission.id)
    claim = artifacts.payload["claims"][0]
    markdown = artifacts.markdown.decode()

    assert claim["status"] == ClaimStatus.PROVISIONALLY_SUPPORTED.value
    assert claim["version"] == 2
    assert claim["status_reason"] == rationale
    assert claim["status_creator_id"] == lab.identity.actor_id
    assert claim["status_run_id"] == lab.identity.run_id
    assert claim["status_changed_at"] == fixed_clock()
    assert claim["status_evidence_valid"] is False
    assert rationale in markdown
    assert "recorded workflow status no longer has its required active evidence" in markdown
    assert "historical label is retained" in markdown


def test_synthesis_preflight_rejects_work_bound_before_snapshot_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()

    def unexpected_snapshot_verification(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        raise AssertionError("snapshot BLOB should not be materialized after failed preflight")

    monkeypatch.setattr(synthesis_module, "MAX_SYNTHESIS_SOURCE_BYTES", 1)
    monkeypatch.setattr(
        synthesis_module,
        "verify_snapshot_integrity",
        unexpected_snapshot_verification,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(seed.mission.id)

    assert caught.value.code == "brief_work_limit"


@pytest.mark.security
def test_oversized_mission_text_refuses_as_work_not_tampering(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intact mission that is merely too large must not report as tampered.

    The mission-wide preflight bounded record counts and snapshot bytes but not
    emitted text. One evidence quote may be 100,000 bytes and many cards may
    quote the same small snapshot, so a mission could hold far more packet text
    than snapshot bytes. The oversize then surfaced at serialization, where a
    blanket `except ValueError` reported it as failed integrity validation — a
    tamper alarm for a completely healthy database, and one that wedged
    mission-wide export permanently.
    """

    quote_length = 4_000
    body = ("x" * quote_length + "\n").encode("utf-8")
    seed = lab.seed_claim(content=body, source_label="notes/large.txt")
    quote = "x" * quote_length
    for _ in range(8):
        lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=0,
            end_byte=quote_length,
            quote=quote,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )
    # A cap the quote text exceeds while snapshot bytes and record counts stay
    # far inside their own limits, which is the shape the finding described.
    synthesis = SynthesisService(
        lab.database,
        clock=fixed_clock,
        id_factory=lab.ids,
        max_export_bytes=8_000,
    )

    def unexpected_snapshot_verification(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        raise AssertionError("snapshot BLOB materialized after the preflight should have refused")

    monkeypatch.setattr(
        synthesis_module,
        "verify_snapshot_integrity",
        unexpected_snapshot_verification,
    )

    with pytest.raises(IntegrityError) as caught:
        synthesis.build_brief(seed.mission.id)

    assert caught.value.code == "brief_work_limit"


@pytest.mark.security
def test_packet_size_overflow_is_a_work_limit_not_an_integrity_failure(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The serializer's size guard must be distinguishable from a validation error.

    The guard raised a bare `ValueError`, indistinguishable from a malformed
    packet, so the producer classified "too large" as "integrity validation
    failed". It now raises a `ValueError` subclass: consumers catching
    `ValueError` are unaffected, and the producer can tell the two apart.

    Lowering only the protocol cap leaves the preflight satisfied, so this
    exercises the serializer backstop rather than the preflight.
    """

    scenario = _populate_brief(lab)
    assert issubclass(packet_module.ResearchPacketTooLargeError, ValueError)
    monkeypatch.setattr(packet_module, "MAX_RESEARCH_PACKET_BYTES", 64)

    with pytest.raises(IntegrityError) as caught:
        lab.synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "brief_work_limit"


def test_claim_scoped_packet_omits_mission_level_statements_by_design(lab: Lab) -> None:
    """Pin the claim-scoped boundary, including the case that looks like a bug.

    A mission-level finding (`claim_id` NULL) may cite the target claim's own
    evidence, and `add_finding` deliberately allows that. The claim-scoped packet
    still carries the cited card while omitting the finding, its uncertainty, and
    any mission-level unresolved question, so the arrays a consumer receives are
    empty rather than partial.

    That is ADR 0002's rule — "unrelated mission entities are omitted" — and PRD
    invariant 16's statement that the packet carries no selection marker, with the
    request/result binding supplying that meaning. It is pinned here because it
    reads like a defect and must not be "fixed" without deciding the contract
    question recorded in DECISIONS.md: the verifier requires every finding's
    citations to be present in the packet, so including mission-level findings
    that cite out-of-scope cards would drag a claim-scoped packet toward
    mission-wide.
    """

    seed = lab.seed_claim()
    card = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    scoped_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A claim-scoped finding.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="Scoped uncertainty.",
        evidence_ids=(card.id,),
        identity=lab.identity,
    )
    mission_level = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement="A mission-level inference resting on the very same card.",
        statement_kind=StatementKind.AGENT_INFERENCE,
        status=FindingStatus.SUPPORTED,
        uncertainty="Mission-level uncertainty.",
        evidence_ids=(card.id,),
        identity=lab.identity,
    )
    mission_question = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement="A mission-level unresolved question.",
        statement_kind=StatementKind.UNRESOLVED_QUESTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="",
        evidence_ids=(),
        identity=lab.identity,
    )

    wide = parse_research_packet(lab.synthesis.build_research_packet_json(seed.mission.id))
    scoped = parse_research_packet(
        lab.synthesis.build_research_packet_json(seed.mission.id, claim_id=seed.claim.id)
    )

    wide_ids = {item.id for item in wide.brief.findings} | {
        item.id for item in wide.brief.unresolved_questions
    }
    assert {scoped_finding.id, mission_level.id, mission_question.id} <= wide_ids

    scoped_ids = {item.id for item in scoped.brief.findings} | {
        item.id for item in scoped.brief.unresolved_questions
    }
    assert scoped_ids == {scoped_finding.id}, "the claim-scoped boundary moved"
    assert mission_level.id not in scoped_ids
    assert mission_question.id not in scoped_ids

    # The card the omitted finding rested on IS carried, which is what makes the
    # omission look like a defect rather than a scope decision.
    assert card.id in {citation.citation_id for citation in scoped.brief.citations}
    assert [entry.finding_id for entry in scoped.brief.uncertainties] == [scoped_finding.id]


def test_claim_materialization_lower_bound_never_exceeds_canonical_json(lab: Lab) -> None:
    scenario = _populate_brief(lab)

    packet = lab.synthesis.build_research_packet_json(
        scenario.seed.mission.id,
        claim_id=scenario.seed.claim.id,
    )
    with lab.database.read() as connection:
        lower_bound = synthesis_module._preflight_claim_synthesis(
            connection,
            mission_id=scenario.seed.mission.id,
            claim_id=scenario.seed.claim.id,
            max_export_bytes=synthesis_module.MAX_EXPORT_BYTES,
        )

    assert lower_bound <= len(packet)


@pytest.mark.parametrize(
    "target",
    ("mission", "status", "citation", "source", "finding", "audit", "run"),
)
def test_claim_preflight_bounds_each_emitted_text_family_before_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    scenario = _populate_brief(lab)
    with lab.database.read() as connection:
        baseline = synthesis_module._preflight_claim_synthesis(
            connection,
            mission_id=scenario.seed.mission.id,
            claim_id=scenario.seed.claim.id,
            max_export_bytes=synthesis_module.MAX_EXPORT_BYTES,
        )

    padding = "Q\x00" + ("Z" * 256)
    with lab.database.transaction() as connection:
        if target == "mission":
            connection.execute("DROP TRIGGER missions_no_update")
            connection.execute(
                "UPDATE research_missions SET created_at = created_at || ? WHERE id = ?",
                (padding, scenario.seed.mission.id),
            )
        elif target == "status":
            connection.execute("DROP TRIGGER claim_status_no_update")
            connection.execute(
                "UPDATE claim_status_events SET created_at = created_at || ? WHERE claim_id = ?",
                (padding, scenario.seed.claim.id),
            )
        elif target == "citation":
            connection.execute("DROP TRIGGER evidence_no_update")
            connection.execute(
                "UPDATE evidence_cards SET created_at = created_at || ? WHERE id = ?",
                (padding, scenario.support.id),
            )
        elif target == "source":
            connection.execute("DROP TRIGGER sources_no_update")
            connection.execute(
                """
                UPDATE sources SET url_metadata = COALESCE(url_metadata, '') || ?
                WHERE id = (SELECT source_id FROM source_snapshots WHERE id = ?)
                """,
                (padding, scenario.seed.snapshot.snapshot_id),
            )
        elif target == "finding":
            connection.execute("DROP TRIGGER findings_no_update")
            connection.execute(
                "UPDATE findings SET created_at = created_at || ? WHERE claim_id = ?",
                (padding, scenario.seed.claim.id),
            )
        elif target == "audit":
            connection.execute("DROP TRIGGER audit_no_update")
            connection.execute(
                """
                UPDATE audit_events SET occurred_at = occurred_at || ?
                WHERE event_type = 'evidence.card.created' AND entity_id = ?
                """,
                (padding, scenario.support.id),
            )
        else:
            connection.execute("DROP TRIGGER research_runs_no_update")
            connection.execute(
                "UPDATE research_runs SET created_at = created_at || ? WHERE id = ?",
                (padding, lab.identity.run_id),
            )

    synthesis = SynthesisService(lab.database)
    monkeypatch.setattr(synthesis, "_max_export_bytes", baseline + 128)

    def unexpected_packet_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded text reached packet construction")

    monkeypatch.setattr(synthesis_module, "build_research_packet", unexpected_packet_build)
    statements: list[str] = []
    with lab.database.read() as connection:
        connection.set_trace_callback(statements.append)
        try:
            with pytest.raises(IntegrityError) as caught:
                synthesis.build_research_packet_json(
                    scenario.seed.mission.id,
                    connection=connection,
                    claim_id=scenario.seed.claim.id,
                )
        finally:
            connection.set_trace_callback(None)

    assert caught.value.code == "brief_work_limit"
    assert not any("SELECT id, title, objective" in statement for statement in statements)
    assert not any("ss.content" in statement for statement in statements)


def _adopt_inference(
    lab: Lab,
    seed: ClaimSeed,
    evidence: EvidenceCard,
    *,
    statement: str,
    uncertainty: str,
) -> str:
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "test-model-1", "test"),
        max_candidates=2,
        max_output_tokens=512,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inference = adoption.adopt_inference(
        preview=preview,
        expected_request_sha256=preview.request_sha256,
        candidate_index=0,
        candidate=FindingCandidate(
            statement=statement,
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty=uncertainty,
            evidence_ids=(evidence.id,),
        ),
        response_sha256=sha256(b"a fake provider response document").hexdigest(),
        identity=lab.identity,
    )
    return inference.id


def _claim_bound(lab: Lab, mission_id: str, claim_id: str) -> int:
    with lab.database.read() as connection:
        return synthesis_module._preflight_claim_synthesis(
            connection,
            mission_id=mission_id,
            claim_id=claim_id,
            max_export_bytes=synthesis_module.MAX_EXPORT_BYTES,
        )


def test_claim_preflight_counts_inference_text_at_exact_markdown_multiplicity(
    lab: Lab,
) -> None:
    scenario = _populate_brief(lab)
    baseline = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    statement = "Café adoption review leaves the claim contested. " + ("x" * 1_000)
    uncertainty = "The adopted draft does not establish generality."

    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement=statement,
        uncertainty=uncertainty,
    )

    with_inference = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    # Exactly the text the Markdown section renders, once each, in stored bytes.
    assert with_inference == baseline + len(statement.encode()) + len(uncertainty.encode())


def test_claim_preflight_refuses_inference_text_past_the_bound_before_assembly(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    baseline = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    statement = "x" * 2_000
    uncertainty = "y" * 1_000
    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement=statement,
        uncertainty=uncertainty,
    )
    bound = baseline + len(statement) + len(uncertainty)

    synthesis = SynthesisService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    monkeypatch.setattr(synthesis, "_max_export_bytes", bound - 1)

    def unexpected_packet_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded inference text reached packet construction")

    monkeypatch.setattr(synthesis_module, "build_research_packet", unexpected_packet_build)
    with pytest.raises(IntegrityError) as caught:
        synthesis.build_brief(scenario.seed.mission.id, claim_id=scenario.seed.claim.id)

    assert caught.value.code == "brief_work_limit"


def test_claim_preflight_admits_a_claim_just_under_the_inference_bound(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    inference_id = _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement="The bounded evidence supports a cautious adopted inference.",
        uncertainty="The evidence does not establish generality.",
    )
    bound = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    artifacts = lab.synthesis.build_brief(scenario.seed.mission.id, claim_id=scenario.seed.claim.id)
    assert inference_id in artifacts.markdown.decode("utf-8")

    # The tightest cap the artifacts genuinely fit: the preflight admits it.
    tight = max(len(artifacts.json), len(artifacts.markdown))
    assert bound <= tight
    synthesis = SynthesisService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    monkeypatch.setattr(synthesis, "_max_export_bytes", tight)

    assert synthesis.build_brief(scenario.seed.mission.id, claim_id=scenario.seed.claim.id) == (
        artifacts
    )


def test_claim_preflight_ignores_retracted_inferences_like_the_brief_does(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    baseline = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    inference_id = _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement="A model draft later withdrawn from assertion.",
        uncertainty="The withdrawal removes it from the brief and the bound.",
    )
    assert _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id) > baseline

    AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids).retract_inference(
        inference_id=inference_id,
        reason="Superseded by a corrected analysis.",
        identity=lab.identity,
    )

    assert _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id) == baseline


def test_claim_preflight_never_counts_inferences_for_json_only_builds(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON-only build emits no Markdown, so inference text cannot shrink its cap."""

    scenario = _populate_brief(lab)
    before = lab.synthesis.build_research_packet_json(
        scenario.seed.mission.id, claim_id=scenario.seed.claim.id
    )
    baseline = _claim_bound(lab, scenario.seed.mission.id, scenario.seed.claim.id)
    statement = "x" * 3_000
    uncertainty = "y" * 1_000
    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement=statement,
        uncertainty=uncertainty,
    )
    bound = baseline + len(statement) + len(uncertainty)
    # The inference-inclusive bound must clear the canonical JSON size, or this
    # test would prove nothing about the cap the Markdown build refuses.
    assert bound > len(before)

    # A cap the Markdown build refuses must leave the JSON-only build admitted,
    # and the v2 bytes provably unchanged by the adoption.
    synthesis = SynthesisService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    monkeypatch.setattr(synthesis, "_max_export_bytes", len(before))
    with pytest.raises(IntegrityError) as caught:
        synthesis.build_brief(scenario.seed.mission.id, claim_id=scenario.seed.claim.id)
    assert caught.value.code == "brief_work_limit"

    packet = synthesis.build_research_packet_json(
        scenario.seed.mission.id, claim_id=scenario.seed.claim.id
    )
    assert packet == before


def _mission_preflight_threshold(
    lab: Lab,
    mission_id: str,
    *,
    include_markdown: bool = True,
) -> int:
    """The smallest max_export_bytes the mission-wide preflight admits.

    The mission path returns nothing, so its emitted-text lower bound is read
    through the refusal boundary instead: UTF-8 storage bytes equal output
    bytes, making the smallest admitted cap the bound itself.
    """

    def admitted(cap: int) -> bool:
        with lab.database.read() as connection:
            try:
                synthesis_module._preflight_synthesis(
                    connection,
                    mission_id=mission_id,
                    claim_id=None,
                    max_export_bytes=cap,
                    include_markdown=include_markdown,
                )
            except IntegrityError as error:
                if error.code != "brief_work_limit":
                    raise
                return False
        return True

    low, high = 0, synthesis_module.MAX_EXPORT_BYTES
    assert not admitted(low)
    assert admitted(high)
    while high - low > 1:
        middle = (low + high) // 2
        if admitted(middle):
            high = middle
        else:
            low = middle
    return high


def test_mission_preflight_counts_inference_text_at_exact_markdown_multiplicity(
    lab: Lab,
) -> None:
    scenario = _populate_brief(lab)
    baseline = _mission_preflight_threshold(lab, scenario.seed.mission.id)
    statement = "Café adoption review leaves the claim contested. " + ("x" * 1_000)
    uncertainty = "The adopted draft does not establish generality."

    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement=statement,
        uncertainty=uncertainty,
    )

    with_inference = _mission_preflight_threshold(lab, scenario.seed.mission.id)
    # Exactly the text the Markdown section renders, once each, in stored bytes.
    assert with_inference == baseline + len(statement.encode()) + len(uncertainty.encode())


def test_mission_preflight_refuses_inference_text_past_the_bound_before_assembly(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement="x" * 2_000,
        uncertainty="y" * 1_000,
    )
    bound = _mission_preflight_threshold(lab, scenario.seed.mission.id)

    synthesis = SynthesisService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    monkeypatch.setattr(synthesis, "_max_export_bytes", bound - 1)

    def unexpected_packet_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("bounded inference text reached packet construction")

    monkeypatch.setattr(synthesis_module, "build_research_packet", unexpected_packet_build)
    with pytest.raises(IntegrityError) as caught:
        synthesis.build_brief(scenario.seed.mission.id)

    assert caught.value.code == "brief_work_limit"


def test_mission_preflight_admits_a_mission_just_under_the_inference_bound(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    inference_id = _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement="The bounded evidence supports a cautious adopted inference.",
        uncertainty="The evidence does not establish generality.",
    )
    bound = _mission_preflight_threshold(lab, scenario.seed.mission.id)
    artifacts = lab.synthesis.build_brief(scenario.seed.mission.id)
    assert inference_id in artifacts.markdown.decode("utf-8")

    # The tightest cap the artifacts genuinely fit: the preflight admits it.
    tight = max(len(artifacts.json), len(artifacts.markdown))
    assert bound <= tight
    synthesis = SynthesisService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    monkeypatch.setattr(synthesis, "_max_export_bytes", tight)

    assert synthesis.build_brief(scenario.seed.mission.id) == artifacts


def test_mission_preflight_ignores_retracted_inferences_like_the_brief_does(lab: Lab) -> None:
    scenario = _populate_brief(lab)
    baseline = _mission_preflight_threshold(lab, scenario.seed.mission.id)
    inference_id = _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement="A model draft later withdrawn from assertion.",
        uncertainty="The withdrawal removes it from the brief and the bound.",
    )
    assert _mission_preflight_threshold(lab, scenario.seed.mission.id) > baseline

    AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids).retract_inference(
        inference_id=inference_id,
        reason="Superseded by a corrected analysis.",
        identity=lab.identity,
    )

    assert _mission_preflight_threshold(lab, scenario.seed.mission.id) == baseline


def test_mission_preflight_never_counts_inferences_for_json_only_builds(lab: Lab) -> None:
    """A JSON-only build emits no Markdown, so inference text cannot shrink its cap."""

    scenario = _populate_brief(lab)
    before = lab.synthesis.build_research_packet_json(scenario.seed.mission.id)
    json_baseline = _mission_preflight_threshold(
        lab, scenario.seed.mission.id, include_markdown=False
    )
    markdown_baseline = _mission_preflight_threshold(lab, scenario.seed.mission.id)
    statement = "x" * 3_000
    uncertainty = "y" * 1_000
    _adopt_inference(
        lab,
        scenario.seed,
        scenario.support,
        statement=statement,
        uncertainty=uncertainty,
    )

    assert (
        _mission_preflight_threshold(lab, scenario.seed.mission.id, include_markdown=False)
        == json_baseline
    )
    assert _mission_preflight_threshold(lab, scenario.seed.mission.id) == (
        markdown_baseline + len(statement) + len(uncertainty)
    )
    # The v2 bytes are provably unchanged by the adoption.
    assert lab.synthesis.build_research_packet_json(scenario.seed.mission.id) == before


def test_synthesis_batches_citation_verification_and_caches_shared_snapshots(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    verified_batches: list[tuple[str, ...]] = []
    verified_snapshot_ids: list[str] = []
    original_verify = synthesis_module.verify_evidence_references
    original_verify_snapshot = evidence_integrity_module.verify_snapshot_integrity

    def count_verification(
        connection: sqlite3.Connection,
        *,
        evidence_ids: Sequence[str],
        mission_id: str,
        allow_withdrawn: bool,
        snapshot_cache: object | None = None,
    ) -> object:
        evidence_batch = tuple(evidence_ids)
        verified_batches.append(evidence_batch)
        return original_verify(
            connection,
            evidence_ids=evidence_batch,
            mission_id=mission_id,
            allow_withdrawn=allow_withdrawn,
            snapshot_cache=snapshot_cache,
        )

    def count_snapshot_verification(connection: sqlite3.Connection, row: sqlite3.Row) -> bytes:
        verified_snapshot_ids.append(str(row["id"]))
        return original_verify_snapshot(connection, row)

    monkeypatch.setattr(synthesis_module, "verify_evidence_references", count_verification)
    # Both call sites are counted: assembly verifies snapshots while building the
    # sources section, and the citation batch reuses that cache. A snapshot cited
    # by several cards must still be verified exactly once per assembly.
    monkeypatch.setattr(
        evidence_integrity_module,
        "verify_snapshot_integrity",
        count_snapshot_verification,
    )
    monkeypatch.setattr(
        synthesis_module,
        "verify_snapshot_integrity",
        count_snapshot_verification,
    )

    lab.synthesis.build_brief(scenario.seed.mission.id)

    assert [sorted(batch) for batch in verified_batches] == [
        [scenario.support.id, scenario.opposition.id]
    ]
    assert verified_snapshot_ids == [scenario.seed.snapshot.snapshot_id]


def test_concurrent_mutation_during_export_fails_and_cleans_files(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    original_write = synthesis_module._write_exclusive
    mutation_done = False

    def write_then_mutate(directory_fd: int, name: str, content: bytes) -> object:
        nonlocal mutation_done
        result = original_write(directory_fd, name, content)
        if not mutation_done:
            mutation_done = True
            lab.research.add_question(
                mission_id=scenario.seed.mission.id,
                text="Did research state change while the brief was written?",
                identity=lab.identity,
            )
        return result

    monkeypatch.setattr(synthesis_module, "_write_exclusive", write_then_mutate)

    with pytest.raises(ConflictError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert caught.value.code == "export_snapshot_changed"
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM brief_exports WHERE mission_id = ?",
                (scenario.seed.mission.id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.security
def test_export_persists_directory_entries_before_recording_the_export(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A durable `brief_exports` row must never outlive the files it names.

    Each artifact is fsynced, but its directory entry lives in the parent
    directory and stays in the page cache until that directory is synced. If the
    export were recorded first, a crash in between would leave an audited export
    pointing at files that no longer exist.
    """

    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    parent_metadata = os.stat(tmp_path, follow_symlinks=False)
    parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
    order: list[str] = []
    original_fsync = synthesis_module.os.fsync
    original_transaction = lab.database.transaction

    def recording_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            identity = (metadata.st_dev, metadata.st_ino)
            if identity == parent_identity:
                order.append("fsync_output_parent")
            else:
                output_metadata = os.stat(output_dir, follow_symlinks=False)
                assert identity == (output_metadata.st_dev, output_metadata.st_ino)
                order.append("fsync_output_directory")
        original_fsync(descriptor)

    def recording_transaction() -> object:
        order.append("record_export")
        return original_transaction()

    monkeypatch.setattr(synthesis_module.os, "fsync", recording_fsync)
    monkeypatch.setattr(lab.database, "transaction", recording_transaction)

    lab.synthesis.export_brief(
        mission_id=scenario.seed.mission.id,
        output_dir=output_dir,
        identity=lab.identity,
    )

    assert order[:2] == ["fsync_output_parent", "fsync_output_directory"]
    assert order.index("fsync_output_directory") < order.index("record_export"), (
        "the export was recorded before its directory entries were made durable"
    )


@pytest.mark.security
@pytest.mark.parametrize("precreate_output", [False, True])
def test_fulfillment_persists_directory_entries_before_reporting_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    precreate_output: bool,
) -> None:
    """Fulfillment reports success by its files existing, so they must be durable."""

    output_dir = tmp_path / "fulfilled"
    if precreate_output:
        output_dir.mkdir()
    parent_metadata = os.stat(tmp_path, follow_symlinks=False)
    parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
    synced_directories: list[tuple[int, int]] = []
    original_fsync = synthesis_module.os.fsync

    def counting_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode):
            synced_directories.append((metadata.st_dev, metadata.st_ino))
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", counting_fsync)

    synthesis_module.write_research_request_artifacts(
        output_dir=output_dir,
        brief_json=b'{"brief":true}\n',
        result_json=b'{"result":true}\n',
    )

    output_metadata = os.stat(output_dir, follow_symlinks=False)
    output_identity = (output_metadata.st_dev, output_metadata.st_ino)
    assert synced_directories == [parent_identity, output_identity]
    assert (output_dir / "research-brief.json").is_file()
    assert (output_dir / "research-result.json").is_file()


@pytest.mark.security
@pytest.mark.parametrize("precreate_output", [False, True])
def test_output_parent_sync_failure_reports_unknown_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    precreate_output: bool,
) -> None:
    output_dir = tmp_path / "fulfilled"
    if precreate_output:
        output_dir.mkdir()
    parent_metadata = os.stat(tmp_path, follow_symlinks=False)
    parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
    original_fsync = synthesis_module.os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if (
            stat.S_ISDIR(metadata.st_mode)
            and (
                metadata.st_dev,
                metadata.st_ino,
            )
            == parent_identity
        ):
            raise OSError("synthetic parent-directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", fail_parent_fsync)

    with pytest.raises(OperationalError) as caught:
        synthesis_module.write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=b'{"brief":true}\n',
            result_json=b'{"result":true}\n',
        )

    assert caught.value.code == "output_publication_durability_unknown"
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


@pytest.mark.security
def test_export_parent_sync_failure_writes_nothing_and_records_no_audit(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    parent_metadata = os.stat(tmp_path, follow_symlinks=False)
    parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
    original_fsync = synthesis_module.os.fsync

    def fail_parent_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if stat.S_ISDIR(metadata.st_mode) and identity == parent_identity:
            raise OSError("synthetic parent-directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", fail_parent_fsync)

    with pytest.raises(OperationalError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert caught.value.code == "output_publication_durability_unknown"
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM brief_exports").fetchone()[0] == 0


@pytest.mark.security
def test_new_output_directory_parent_sync_failure_preserves_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "fulfilled"
    displaced = tmp_path / "displaced-created-directory"
    marker = output_dir / "operator-owned.txt"
    parent_metadata = os.stat(tmp_path, follow_symlinks=False)
    parent_identity = (parent_metadata.st_dev, parent_metadata.st_ino)
    original_fsync = synthesis_module.os.fsync

    def replace_then_fail(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if stat.S_ISDIR(metadata.st_mode) and identity == parent_identity:
            output_dir.rename(displaced)
            output_dir.mkdir()
            marker.write_text("must remain unchanged", encoding="utf-8")
            raise OSError("synthetic parent-directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", replace_then_fail)

    with pytest.raises(OperationalError) as caught:
        synthesis_module.write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=b'{"brief":true}\n',
            result_json=b'{"result":true}\n',
        )

    assert caught.value.code == "output_publication_durability_unknown"
    assert marker.read_text(encoding="utf-8") == "must remain unchanged"
    assert displaced.is_dir()
    assert list(displaced.iterdir()) == []


@pytest.mark.security
def test_output_directory_sync_failure_cleans_export_files_and_audit(
    lab: Lab,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = _populate_brief(lab)
    output_dir = tmp_path / "export"
    original_fsync = synthesis_module.os.fsync

    def fail_output_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode) and output_dir.exists():
            output_metadata = os.stat(output_dir, follow_symlinks=False)
            if (metadata.st_dev, metadata.st_ino) == (
                output_metadata.st_dev,
                output_metadata.st_ino,
            ):
                raise OSError("synthetic output-directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", fail_output_fsync)

    with pytest.raises(OperationalError) as caught:
        lab.synthesis.export_brief(
            mission_id=scenario.seed.mission.id,
            output_dir=output_dir,
            identity=lab.identity,
        )

    assert caught.value.code == "output_publication_durability_unknown"
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM brief_exports").fetchone()[0] == 0


@pytest.mark.security
def test_output_directory_sync_failure_cleans_fulfillment_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "fulfilled"
    original_fsync = synthesis_module.os.fsync

    def fail_output_fsync(descriptor: int) -> None:
        metadata = os.fstat(descriptor)
        if stat.S_ISDIR(metadata.st_mode) and output_dir.exists():
            output_metadata = os.stat(output_dir, follow_symlinks=False)
            if (metadata.st_dev, metadata.st_ino) == (
                output_metadata.st_dev,
                output_metadata.st_ino,
            ):
                raise OSError("synthetic output-directory fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(synthesis_module.os, "fsync", fail_output_fsync)

    with pytest.raises(OperationalError) as caught:
        synthesis_module.write_research_request_artifacts(
            output_dir=output_dir,
            brief_json=b'{"brief":true}\n',
            result_json=b'{"result":true}\n',
        )

    assert caught.value.code == "output_publication_durability_unknown"
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_failed_exclusive_write_preserves_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_dir = tmp_path / "export"
    output_dir.mkdir()
    target = output_dir / "research-brief.md"
    displaced = output_dir / "opened-original.md"
    replacement = b"replacement owned by a concurrent actor"
    original_write = synthesis_module.os.write
    substituted = False

    def replace_path_then_fail(descriptor: int, content: bytes) -> int:
        nonlocal substituted
        if not substituted:
            substituted = True
            target.rename(displaced)
            target.write_bytes(replacement)
            raise OSError("synthetic write failure after pathname substitution")
        return original_write(descriptor, content)

    directory_fd = os.open(output_dir, os.O_RDONLY | os.O_DIRECTORY)
    monkeypatch.setattr(synthesis_module.os, "write", replace_path_then_fail)
    try:
        with pytest.raises(OSError, match="synthetic write failure"):
            synthesis_module._write_exclusive(
                directory_fd,
                target.name,
                b"brief bytes",
            )
    finally:
        os.close(directory_fd)

    assert target.read_bytes() == replacement
    assert displaced.exists()
