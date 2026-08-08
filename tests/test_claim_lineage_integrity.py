from __future__ import annotations

import socket
import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import pytest

import minerva.core.db as db_module
import minerva.integrations.ai as ai_integrations
import minerva.lineage.service as lineage_service_module
from conftest import ClaimSeed, Lab, SequenceIds, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.lineage import ClaimLineageBounds, ClaimLineageService
from minerva.research.models import FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_SUPPORT_QUOTE = "Evidence supports the claim."
_OPPOSITION_QUOTE = "Evidence opposes the claim."
_SAFE_INTEGRITY_MESSAGE = "Stored claim lineage state is invalid."


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def _raw_corrupt(
    database: Database,
    statements: tuple[tuple[str, tuple[object, ...]], ...],
    *,
    ignore_checks: bool = False,
) -> None:
    connection = sqlite3.connect(database.path)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        if ignore_checks:
            connection.execute("PRAGMA ignore_check_constraints = ON")
        for statement, parameters in statements:
            connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


def _adopt_inference(
    lab: Lab,
    seed: ClaimSeed,
    evidence: EvidenceCard,
    *,
    statement: str = "A model-authored statement remains inspectable but not authoritative.",
) -> tuple[AdoptionService, AgentInference]:
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "lineage-integrity-model", "test"),
        max_candidates=1,
        max_output_tokens=256,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inference = adoption.adopt_inference(
        preview=preview,
        candidate_index=0,
        candidate=FindingCandidate(
            statement=statement,
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty="This statement remains explicitly model-authored.",
            evidence_ids=(evidence.id,),
        ),
        response_sha256=sha256(statement.encode("utf-8")).hexdigest(),
        identity=lab.identity,
    )
    return adoption, inference


@pytest.mark.parametrize(
    "invalid_mission_id",
    [
        None,
        7,
        b"mis_00000000000000000000000000000000",
        "",
        " mis_00000000000000000000000000000000",
        "MIS_00000000000000000000000000000000",
        "mis_0000000000000000000000000000000g",
    ],
)
def test_invalid_mission_input_maps_to_stable_non_reflective_error(
    lab: Lab,
    invalid_mission_id: object,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(NotFoundError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=cast(str, invalid_mission_id),
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "mission_not_found"
    assert caught.value.public_message == "The requested resource was not found."
    assert caught.value.http_status == 404
    if reflected := str(invalid_mission_id):
        assert reflected not in caught.value.public_message


@pytest.mark.parametrize(
    "invalid_claim_id",
    [
        None,
        7,
        b"clm_00000000000000000000000000000000",
        "",
        " clm_00000000000000000000000000000000",
        "CLM_00000000000000000000000000000000",
        "clm_0000000000000000000000000000000g",
    ],
)
def test_invalid_claim_input_maps_to_stable_non_reflective_error(
    lab: Lab,
    invalid_claim_id: object,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=cast(str, invalid_claim_id),
        )

    assert caught.value.code == "claim_lineage_scope_invalid"
    assert caught.value.public_message == "The claim lineage scope is invalid for this mission."
    assert caught.value.http_status == 422
    if reflected := str(invalid_claim_id):
        assert reflected not in caught.value.public_message


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("max_nodes", 0),
        ("max_edges", True),
        ("max_citation_bytes", 0),
        ("max_snapshot_bytes", False),
        ("max_output_bytes", 0),
        ("max_sqlite_vm_steps", 999),
    ],
)
def test_invalid_bounds_refuse_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    invalid_value: object,
) -> None:
    seed = lab.seed_claim()
    bounds = replace(ClaimLineageBounds(), **{field: invalid_value})

    def read_must_not_run() -> object:
        raise AssertionError("bounds must be validated before opening the database")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=bounds,
        )

    assert caught.value.code == "claim_lineage_bounds_invalid"
    assert caught.value.public_message == "Claim lineage bounds are invalid."


def test_non_bounds_object_refuses_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()

    def read_must_not_run() -> object:
        raise AssertionError("bounds must be validated before opening the database")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=cast(ClaimLineageBounds, object()),
        )

    assert caught.value.code == "claim_lineage_bounds_invalid"
    assert caught.value.public_message == "Claim lineage bounds are invalid."


@pytest.mark.parametrize(
    ("field", "work_field"),
    [
        ("max_nodes", "node_count"),
        ("max_edges", "edge_count"),
        ("max_citation_bytes", "citation_bytes"),
        ("max_snapshot_bytes", "distinct_snapshot_bytes"),
    ],
)
def test_structural_bounds_succeed_at_exact_work_and_refuse_one_below(
    lab: Lab,
    field: str,
    work_field: str,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    service = ClaimLineageService(lab.database)
    baseline = service.build_graph(mission_id=seed.mission.id, claim_id=seed.claim.id)
    exact_value = cast(int, getattr(baseline.work, work_field))
    exact = replace(ClaimLineageBounds(), **{field: exact_value})

    complete = service.build_graph(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        bounds=exact,
    )
    assert complete.complete is True
    assert complete.truncated is False
    assert getattr(complete.work, work_field) == exact_value

    with pytest.raises(IntegrityError) as caught:
        service.build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=replace(exact, **{field: exact_value - 1}),
        )
    assert caught.value.code == "claim_lineage_work_limit"
    assert caught.value.public_message == (
        "The complete claim lineage graph exceeds its configured work limits."
    )


def test_output_bound_refuses_instead_of_returning_partial_graph(lab: Lab) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimLineageBounds(max_output_bytes=1),
        )

    assert caught.value.code == "claim_lineage_work_limit"
    assert caught.value.public_message == (
        "The complete claim lineage graph exceeds its configured work limits."
    )


def test_sqlite_vm_work_limit_maps_interrupt_to_domain_refusal(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    monkeypatch.setattr(lineage_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(lineage_service_module, "_MIN_SQLITE_VM_STEPS", 1)

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimLineageBounds(max_sqlite_vm_steps=1),
        )

    assert caught.value.code == "claim_lineage_work_limit"
    assert caught.value.public_message == (
        "The complete claim lineage graph exceeds its configured work limits."
    )


def test_lineage_is_query_only_and_has_zero_unauthorized_side_effects(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    before_dump = _database_dump(lab.database)
    before_bytes = lab.database.path.read_bytes()
    trace: list[str] = []
    real_read = lab.database.read

    @contextmanager
    def traced_read() -> Any:
        with real_read() as connection:
            connection.set_trace_callback(trace.append)
            yield connection

    def transaction_forbidden() -> object:
        raise AssertionError("Claim Lineage must not open a write transaction")

    def provider_forbidden(_: ModelProvider) -> object:
        raise AssertionError("Claim Lineage must not construct a model provider")

    def network_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Claim Lineage must not construct a network socket")

    monkeypatch.setattr(lab.database, "read", traced_read)
    monkeypatch.setattr(lab.database, "transaction", transaction_forbidden)
    monkeypatch.setattr(ai_integrations, "candidate_provider", provider_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)

    lineage = ClaimLineageService(lab.database).build_graph(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    assert any(statement.strip().upper() == "PRAGMA QUERY_ONLY = ON" for statement in trace)
    assert lineage.semantic_boundary.read_only is True
    assert lineage.semantic_boundary.creates_or_changes_research_state is False
    assert lineage.semantic_boundary.writes_audit_event_or_export is False
    assert lineage.semantic_boundary.modifies_source_or_snapshot_bytes is False
    assert lineage.semantic_boundary.invokes_model_provider is False
    assert lineage.semantic_boundary.invokes_network is False
    assert _database_dump(lab.database) == before_dump
    assert lab.database.path.read_bytes() == before_bytes


def test_snapshot_actual_blob_length_refuses_before_citation_materialization(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    tampered_content = b"X" * 4_096
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER snapshots_no_update", ()),
            (
                "UPDATE source_snapshots SET content = ?, byte_length = ? WHERE id = ?",
                (tampered_content, 1, seed.snapshot.snapshot_id),
            ),
        ),
        ignore_checks=True,
    )

    def verifier_must_not_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("snapshot preflight must precede citation materialization")

    monkeypatch.setattr(
        lineage_service_module,
        "verify_evidence_reference",
        verifier_must_not_run,
    )
    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            bounds=ClaimLineageBounds(max_snapshot_bytes=len(seed.content)),
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE


def test_exact_citation_tampering_fails_closed(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET quote = ? WHERE id = ?",
                ("X" * len(evidence.quote), evidence.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "citation_tampered"
    assert caught.value.public_message == "Stored citation integrity failed."


@pytest.mark.parametrize("corruption", ["self", "cycle"])
def test_self_or_cyclic_supersession_corruption_refuses(
    lab: Lab,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        _SUPPORT_QUOTE,
        EvidenceStance.SUPPORTS,
        supersedes_evidence_id=original.id,
    )
    supersedes_id = original.id if corruption == "self" else replacement.id
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER evidence_no_update", ()),
            (
                "UPDATE evidence_cards SET supersedes_evidence_id = ? WHERE id = ?",
                (supersedes_id, original.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE


@pytest.mark.parametrize("corruption", ["foreign_question", "dangling_question"])
def test_claim_question_relationship_corruption_refuses_without_text_leak(
    lab: Lab,
    corruption: str,
) -> None:
    target = lab.seed_claim()
    foreign = lab.seed_claim(content=b"FOREIGN-QUESTION-TEXT-MUST-NOT-LEAK\n")
    question_id = foreign.question.id if corruption == "foreign_question" else "que_" + "f" * 32
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER claims_no_update", ()),
            (
                "UPDATE claims SET question_id = ? WHERE id = ?",
                (question_id, target.claim.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert question_id not in caught.value.public_message
    assert foreign.question.text not in caught.value.public_message


def test_foreign_mission_status_event_refuses_without_reason_or_actor_leak(lab: Lab) -> None:
    target = lab.seed_claim()
    foreign = lab.seed_claim(content=b"foreign status source\n")
    foreign_reason = "FOREIGN-STATUS-REASON-MUST-NOT-LEAK"
    foreign_actor = "foreign-status-actor-must-not-leak"
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER claim_status_no_update", ()),
            (
                """
                UPDATE claim_status_events
                SET mission_id = ?, reason = ?, creator_id = ?
                WHERE claim_id = ?
                """,
                (foreign.mission.id, foreign_reason, foreign_actor, target.claim.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=target.mission.id,
            claim_id=target.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert foreign_reason not in caught.value.public_message
    assert foreign_actor not in caught.value.public_message


@pytest.mark.parametrize(
    ("owner_kind", "table", "trigger", "owner_column"),
    [
        ("finding", "finding_citations", "finding_citations_no_update", "finding_id"),
        (
            "inference",
            "agent_inference_citations",
            "agent_inference_citations_no_update",
            "inference_id",
        ),
    ],
)
def test_dangling_claim_owned_citation_refuses_before_receipt(
    lab: Lab,
    owner_kind: str,
    table: str,
    trigger: str,
    owner_column: str,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    if owner_kind == "finding":
        owner_id = lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="A material finding has an exact citation.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The citation is deliberately corrupted after insertion.",
            evidence_ids=(evidence.id,),
            identity=lab.identity,
        ).id
    else:
        _, inference = _adopt_inference(lab, seed, evidence)
        owner_id = inference.id
    dangling_id = "evd_" + "f" * 32
    _raw_corrupt(
        lab.database,
        (
            (f"DROP TRIGGER {trigger}", ()),
            (
                f"UPDATE {table} SET evidence_id = ? WHERE {owner_column} = ?",  # noqa: S608
                (dangling_id, owner_id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert dangling_id not in caught.value.public_message


@pytest.mark.parametrize("corruption", ["wrong_target", "citation_lineage"])
def test_promotion_copy_and_citation_lineage_corruption_refuses(
    lab: Lab,
    corruption: str,
) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, _OPPOSITION_QUOTE, EvidenceStance.OPPOSES)
    adoption, inference = _adopt_inference(lab, seed, support)
    promoted = adoption.promote_inference_to_finding(
        inference_id=inference.id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )

    if corruption == "wrong_target":
        unrelated = lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="An unrelated same-claim finding is not a valid promotion target.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="Its copied fields deliberately differ.",
            evidence_ids=(opposition.id,),
            identity=lab.identity,
        )
        statements = (
            ("DROP TRIGGER agent_inference_promotions_no_update", ()),
            (
                "UPDATE agent_inference_promotions SET finding_id = ? WHERE inference_id = ?",
                (unrelated.id, inference.id),
            ),
        )
    else:
        statements = (
            ("DROP TRIGGER finding_citations_no_update", ()),
            (
                "UPDATE finding_citations SET evidence_id = ? WHERE finding_id = ?",
                (opposition.id, promoted.id),
            ),
        )
    _raw_corrupt(lab.database, statements)

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE


def test_child_correction_mission_tampering_refuses(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="Keep correction history in the graph.",
        identity=lab.identity,
    )
    foreign = lab.seed_claim(content=b"foreign correction source\n")
    _raw_corrupt(
        lab.database,
        (
            ("DROP TRIGGER withdrawals_no_update", ()),
            (
                "UPDATE evidence_withdrawals SET mission_id = ? WHERE evidence_id = ?",
                (foreign.mission.id, evidence.id),
            ),
        ),
    )

    with pytest.raises(IntegrityError) as caught:
        ClaimLineageService(lab.database).build_graph(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
        )

    assert caught.value.code == "claim_lineage_inconsistent"
    assert caught.value.public_message == _SAFE_INTEGRITY_MESSAGE
    assert foreign.mission.id not in caught.value.public_message


def test_pre_v5_database_requires_explicit_migration_before_lineage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-lineage-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4
    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-lineage",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before claim lineage",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy lineage mission",
        objective="Verify a stale database cannot produce a partial lineage graph.",
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text="Can a stale database produce complete inference lineage?",
        identity=identity,
    )
    claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="Claim Lineage refuses stale migration state.",
        falsification_criteria="A successful pre-migration graph would falsify it.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy lineage corpus\n",
        original_label="legacy-lineage.txt",
        media_type="text/plain",
        identity=identity,
    )

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as required:
        ClaimLineageService(legacy).build_graph(
            mission_id=mission.id,
            claim_id=claim.id,
        )
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    graph = ClaimLineageService(legacy).build_graph(
        mission_id=mission.id,
        claim_id=claim.id,
    )
    assert graph.complete is True
    assert graph.work.inference_count == 0
