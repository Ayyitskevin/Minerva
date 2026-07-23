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
import minerva.synthesis.service as synthesis_module
from conftest import ClaimSeed, Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
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
    ) -> object:
        evidence_batch = tuple(evidence_ids)
        verified_batches.append(evidence_batch)
        return original_verify(
            connection,
            evidence_ids=evidence_batch,
            mission_id=mission_id,
            allow_withdrawn=allow_withdrawn,
        )

    def count_snapshot_verification(connection: sqlite3.Connection, row: sqlite3.Row) -> bytes:
        verified_snapshot_ids.append(str(row["id"]))
        return original_verify_snapshot(connection, row)

    monkeypatch.setattr(synthesis_module, "verify_evidence_references", count_verification)
    monkeypatch.setattr(
        evidence_integrity_module,
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
