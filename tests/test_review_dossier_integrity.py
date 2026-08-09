from __future__ import annotations

import socket
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import minerva.cli.credentials as cli_credentials
import minerva.core.db as db_module
import minerva.dossier.service as dossier_service_module
import minerva.integrations.ai as ai_integrations
import minerva.lineage.service as lineage_service_module
import minerva.research_queue.service as queue_service_module
from conftest import ClaimSeed, Lab, SequenceIds, fixed_clock
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.dossier import ReviewDossierBounds, ReviewDossierService
from minerva.evidence.models import EvidenceStance
from minerva.lens import LensService
from minerva.lens.models import LensSearchResult
from minerva.lineage.models import (
    ClaimLineageNodeKind,
    ClaimStatusEventLineageData,
    EvidenceLineageData,
)
from minerva.lineage.service import ClaimLineageService
from minerva.research.service import ResearchService
from minerva.research_queue.models import MissionResearchQueueBounds
from minerva.research_queue.service import MissionResearchQueueService
from minerva.sources.service import SourceService

_SUPPORT_QUOTE = "Evidence supports the claim."
_SAFE_SCOPE_MESSAGE = "The local review dossier scope is invalid."
_SAFE_INCONSISTENT_MESSAGE = "The local review dossier components are inconsistent."


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def _seed_dossier(lab: Lab) -> tuple[ClaimSeed, LensSearchResult]:
    seed = lab.seed_claim()
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="evidence supports",
    )
    return seed, receipt


def _bounds_with_vm_steps(value: int) -> ReviewDossierBounds:
    defaults = ReviewDossierBounds()
    return replace(
        defaults,
        mission_queue=replace(defaults.mission_queue, max_sqlite_vm_steps=value),
        claim_lineage=replace(defaults.claim_lineage, max_sqlite_vm_steps=value),
        max_sqlite_vm_steps=value,
    )


@pytest.mark.parametrize(
    "bounds",
    [
        object(),
        replace(ReviewDossierBounds(), max_output_bytes=0),
        replace(ReviewDossierBounds(), max_output_bytes=134_217_729),
        replace(ReviewDossierBounds(), max_output_bytes=True),
        replace(ReviewDossierBounds(), max_sqlite_vm_steps=999),
        replace(ReviewDossierBounds(), max_sqlite_vm_steps=16_000_001),
        replace(ReviewDossierBounds(), max_sqlite_vm_steps=True),
        replace(
            ReviewDossierBounds(),
            mission_queue=MissionResearchQueueBounds(max_claims=0),
        ),
        replace(
            ReviewDossierBounds(),
            claim_lineage=replace(ReviewDossierBounds().claim_lineage, max_nodes=0),
        ),
        replace(
            ReviewDossierBounds(),
            mission_queue=replace(
                ReviewDossierBounds().mission_queue,
                max_sqlite_vm_steps=8_000_000,
            ),
        ),
        replace(
            ReviewDossierBounds(),
            claim_lineage=replace(
                ReviewDossierBounds().claim_lineage,
                max_sqlite_vm_steps=8_000_000,
            ),
        ),
    ],
)
def test_invalid_bounds_refuse_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    bounds: object,
) -> None:
    seed, receipt = _seed_dossier(lab)

    def read_must_not_run() -> object:
        raise AssertionError("dossier bounds must be validated before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
            bounds=cast(ReviewDossierBounds, bounds),
        )

    assert caught.value.code == "review_dossier_bounds_invalid"
    assert caught.value.public_message == "Review dossier bounds are invalid."


@pytest.mark.parametrize(
    ("mission_id", "claim_id", "expected_code", "expected_message"),
    [
        (
            "MIS_00000000000000000000000000000000",
            "clm_00000000000000000000000000000000",
            "mission_not_found",
            "The requested resource was not found.",
        ),
        (
            "mis_00000000000000000000000000000000",
            "CLM_00000000000000000000000000000000",
            "review_dossier_scope_invalid",
            _SAFE_SCOPE_MESSAGE,
        ),
    ],
)
def test_invalid_scope_shape_refuses_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    mission_id: str,
    claim_id: str,
    expected_code: str,
    expected_message: str,
) -> None:
    _seed, receipt = _seed_dossier(lab)

    def read_must_not_run() -> object:
        raise AssertionError("dossier scope shape must be validated before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    error_type = NotFoundError if expected_code == "mission_not_found" else IntegrityError
    with pytest.raises(error_type) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=mission_id,
            claim_id=claim_id,
            lens_receipt=receipt,
        )

    assert caught.value.code == expected_code
    assert caught.value.public_message == expected_message
    assert mission_id not in caught.value.public_message
    assert claim_id not in caught.value.public_message


def test_foreign_lens_mission_refuses_before_database_work(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    foreign = lab.seed_claim(source_label="foreign/receipt.txt")
    foreign_receipt = LensService(lab.database).search(
        mission_id=foreign.mission.id,
        query="evidence",
    )

    def read_must_not_run() -> object:
        raise AssertionError("receipt mission mismatch must refuse before database work")

    monkeypatch.setattr(lab.database, "read", read_must_not_run)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=foreign_receipt,
        )

    assert caught.value.code == "review_dossier_scope_invalid"
    assert caught.value.public_message == _SAFE_SCOPE_MESSAGE
    assert foreign.mission.id not in caught.value.public_message


def test_well_formed_foreign_claim_refuses_without_identity_disclosure(lab: Lab) -> None:
    seed = lab.seed_claim()
    foreign = lab.seed_claim(source_label="foreign/claim.txt")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="evidence",
    )

    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=foreign.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_scope_invalid"
    assert caught.value.public_message == _SAFE_SCOPE_MESSAGE
    assert foreign.mission.id not in caught.value.public_message
    assert foreign.claim.statement not in caught.value.public_message


def test_sqlite_vm_limit_refuses_and_restores_the_progress_handler(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    real_read = lab.database.read
    progress_calls: list[tuple[bool, int]] = []

    class RecordingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def set_progress_handler(self, callback: object, instructions: int) -> None:
            progress_calls.append((callback is None, instructions))
            self.connection.set_progress_handler(callback, instructions)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

    @contextmanager
    def recording_read() -> Any:
        with real_read() as connection:
            yield RecordingConnection(connection)

    monkeypatch.setattr(lab.database, "read", recording_read)
    monkeypatch.setattr(dossier_service_module, "_QUERY_PROGRESS_GRANULARITY", 1)
    monkeypatch.setattr(dossier_service_module, "_MIN_SQLITE_VM_STEPS", 1)
    monkeypatch.setattr(queue_service_module, "_MIN_SQLITE_VM_STEPS", 1)
    monkeypatch.setattr(lineage_service_module, "_MIN_SQLITE_VM_STEPS", 1)

    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
            bounds=_bounds_with_vm_steps(1),
        )

    assert caught.value.code == "review_dossier_work_limit"
    assert progress_calls[0] == (False, 1)
    assert progress_calls[-1] == (True, 0)
    assert progress_calls.count((True, 0)) == 1


def test_output_limit_refuses_the_whole_dossier(lab: Lab) -> None:
    seed, receipt = _seed_dossier(lab)

    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
            bounds=replace(ReviewDossierBounds(), max_output_bytes=1),
        )

    assert caught.value.code == "review_dossier_work_limit"
    assert caught.value.public_message == (
        "The complete local review dossier exceeds its configured work limits."
    )


def test_output_bound_succeeds_exactly_and_refuses_one_byte_below(lab: Lab) -> None:
    seed, receipt = _seed_dossier(lab)
    service = ReviewDossierService(lab.database)
    bounds = ReviewDossierBounds()

    for _ in range(5):
        result = service.build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
            bounds=bounds,
        )
        measured = result.work.canonical_output_bytes
        if bounds.max_output_bytes == measured:
            break
        bounds = replace(bounds, max_output_bytes=measured)
    else:  # pragma: no cover - protects deterministic size convergence
        raise AssertionError("dossier output-bound framing did not converge")

    assert result.work.canonical_output_bytes == bounds.max_output_bytes
    with pytest.raises(IntegrityError) as caught:
        service.build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
            bounds=replace(bounds, max_output_bytes=bounds.max_output_bytes - 1),
        )
    assert caught.value.code == "review_dossier_work_limit"


def test_dossier_uses_one_query_only_read_and_one_cumulative_handler(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    real_read = lab.database.read
    read_count = 0
    trace: list[str] = []
    progress_calls: list[tuple[bool, int]] = []

    class RecordingConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def set_progress_handler(self, callback: object, instructions: int) -> None:
            progress_calls.append((callback is None, instructions))
            self.connection.set_progress_handler(callback, instructions)  # type: ignore[arg-type]

        def __getattr__(self, name: str) -> object:
            return getattr(self.connection, name)

    @contextmanager
    def traced_read() -> Any:
        nonlocal read_count
        read_count += 1
        with real_read() as connection:
            connection.set_trace_callback(trace.append)
            yield RecordingConnection(connection)

    monkeypatch.setattr(lab.database, "read", traced_read)
    result = ReviewDossierService(lab.database).build_dossier(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        lens_receipt=receipt,
    )

    assert result.complete is True
    assert read_count == 1
    assert progress_calls == [(False, 1_000), (True, 0)]
    assert any(statement.strip().upper() == "PRAGMA QUERY_ONLY = ON" for statement in trace)


def test_dossier_has_zero_unauthorized_mutation_or_external_invocation(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    before_dump = _database_dump(lab.database)
    before_bytes = lab.database.path.read_bytes()

    def transaction_forbidden() -> object:
        raise AssertionError("Review Dossier must not open a write transaction")

    def provider_forbidden(_: object) -> object:
        raise AssertionError("Review Dossier must not construct a model provider")

    def credential_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Review Dossier must not read provider credentials")

    def network_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Review Dossier must not construct a network socket")

    monkeypatch.setattr(lab.database, "transaction", transaction_forbidden)
    monkeypatch.setattr(ai_integrations, "candidate_provider", provider_forbidden)
    monkeypatch.setattr(cli_credentials, "load_provider_credential", credential_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)

    result = ReviewDossierService(lab.database).build_dossier(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        lens_receipt=receipt,
    )

    assert result.semantic_boundary.read_only is True
    assert result.semantic_boundary.creates_or_changes_research_state is False
    assert result.semantic_boundary.writes_audit_event_or_export is False
    assert result.semantic_boundary.invokes_model_provider is False
    assert result.semantic_boundary.invokes_network is False
    assert _database_dump(lab.database) == before_dump
    assert lab.database.path.read_bytes() == before_bytes


def test_current_database_lens_mismatch_refuses_the_dossier(lab: Lab) -> None:
    seed, receipt = _seed_dossier(lab)
    lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"a later same-mission snapshot\n",
        original_label="later.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "lens_replay_mismatch"
    assert caught.value.public_message == (
        "The current database does not exactly reproduce the Lens receipt."
    )


def test_snapshot_tamper_fails_closed_without_additional_mutation(lab: Lab) -> None:
    seed, receipt = _seed_dossier(lab)
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (b"Z" * len(seed.content), seed.snapshot.snapshot_id),
        )
    tampered_dump = _database_dump(lab.database)

    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "snapshot_tampered"
    assert caught.value.public_message == "Stored source snapshot integrity failed."
    assert _database_dump(lab.database) == tampered_dump


def test_self_consistent_component_mismatch_refuses(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    real_graph = ClaimLineageService._build_graph_in_snapshot

    def mismatched_graph(self: ClaimLineageService, **kwargs: object) -> object:
        graph = real_graph(self, **kwargs)  # type: ignore[arg-type]
        provisional = replace(
            graph,
            question_id="que_" + "f" * 32,
            lineage_receipt_sha256="",
        )
        return replace(
            provisional,
            lineage_receipt_sha256=lineage_service_module._lineage_receipt_digest(provisional),
        )

    monkeypatch.setattr(ClaimLineageService, "_build_graph_in_snapshot", mismatched_graph)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_inconsistent"
    assert caught.value.public_message == _SAFE_INCONSISTENT_MESSAGE


@pytest.mark.parametrize(
    ("field_name", "forged_value"),
    [
        ("kind", "forged_lineage_kind"),
        ("scope", "forged_lineage_scope"),
        ("completion_policy", "forged_completion_policy"),
    ],
)
def test_self_consistent_component_contract_drift_refuses(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    forged_value: str,
) -> None:
    seed, receipt = _seed_dossier(lab)
    real_graph = ClaimLineageService._build_graph_in_snapshot

    def forged_graph(self: ClaimLineageService, **kwargs: object) -> object:
        graph = real_graph(self, **kwargs)  # type: ignore[arg-type]
        if field_name == "kind":
            provisional = replace(graph, kind=forged_value, lineage_receipt_sha256="")
        elif field_name == "scope":
            provisional = replace(graph, scope=forged_value, lineage_receipt_sha256="")
        else:
            provisional = replace(
                graph,
                completion_policy=forged_value,
                lineage_receipt_sha256="",
            )
        return replace(
            provisional,
            lineage_receipt_sha256=lineage_service_module._lineage_receipt_digest(provisional),
        )

    monkeypatch.setattr(ClaimLineageService, "_build_graph_in_snapshot", forged_graph)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_inconsistent"
    assert caught.value.public_message == _SAFE_INCONSISTENT_MESSAGE


def test_lens_replay_contract_drift_refuses(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    real_replay = cast(Any, dossier_service_module)._replay_lens_receipt_in_snapshot

    def forged_replay(*args: object, **kwargs: object) -> object:
        replay = real_replay(*args, **kwargs)  # type: ignore[arg-type]
        return replace(replay, kind="forged_lens_replay_kind")

    monkeypatch.setattr(
        dossier_service_module,
        "_replay_lens_receipt_in_snapshot",
        forged_replay,
    )
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_inconsistent"
    assert caught.value.public_message == _SAFE_INCONSISTENT_MESSAGE


def test_requested_claim_is_bound_to_review_lineage_root_and_claim_node(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    forged_claim_id = "clm_" + "f" * 32
    real_queue = MissionResearchQueueService._build_queue_in_snapshot
    real_graph = ClaimLineageService._build_graph_in_snapshot

    def forged_queue(
        self: MissionResearchQueueService,
        **kwargs: object,
    ) -> object:
        queue, review = real_queue(self, **kwargs)  # type: ignore[arg-type]
        assert review is not None
        review_without_digest = replace(
            review,
            claim_id=forged_claim_id,
            review_receipt_sha256="",
        )
        forged_review = replace(
            review_without_digest,
            review_receipt_sha256=queue_service_module._claim_review_receipt_digest(
                review_without_digest
            ),
        )
        reviewed_claims = tuple(
            replace(
                item,
                review_receipt_sha256=forged_review.review_receipt_sha256,
            )
            if item.claim_id == seed.claim.id
            else item
            for item in queue.reviewed_claims
        )
        items = tuple(
            replace(
                item,
                source_review_receipt_sha256=forged_review.review_receipt_sha256,
            )
            if item.claim_id == seed.claim.id
            else item
            for item in queue.items
        )
        queue_without_digest = replace(
            queue,
            reviewed_claims=reviewed_claims,
            items=items,
            claim_review_set_sha256=queue_service_module._claim_review_set_digest(
                mission_id=queue.mission_id,
                reviewed_claims=reviewed_claims,
            ),
            item_set_sha256=queue_service_module._item_set_digest(
                mission_id=queue.mission_id,
                items=items,
            ),
            queue_receipt_sha256="",
        )
        forged_queue_receipt = replace(
            queue_without_digest,
            queue_receipt_sha256=queue_service_module._queue_receipt_digest(queue_without_digest),
        )
        return forged_queue_receipt, forged_review

    def forged_graph(self: ClaimLineageService, **kwargs: object) -> object:
        graph = real_graph(self, **kwargs)  # type: ignore[arg-type]
        nodes = tuple(
            replace(node, payload=replace(node.payload, claim_id=forged_claim_id))
            if node.kind is ClaimLineageNodeKind.CLAIM_STATUS_EVENT
            and isinstance(node.payload, ClaimStatusEventLineageData)
            else node
            for node in graph.nodes
        )
        graph_without_digest = replace(
            graph,
            claim_id=forged_claim_id,
            nodes=nodes,
            node_set_sha256=lineage_service_module._node_set_digest(
                mission_id=graph.mission_id,
                claim_id=forged_claim_id,
                nodes=nodes,
            ),
            edge_set_sha256=lineage_service_module._edge_set_digest(
                mission_id=graph.mission_id,
                claim_id=forged_claim_id,
                edges=graph.edges,
            ),
            snapshot_set_sha256=lineage_service_module._snapshot_set_digest(
                mission_id=graph.mission_id,
                claim_id=forged_claim_id,
                snapshot_rows=(),
            ),
            lineage_receipt_sha256="",
        )
        return replace(
            graph_without_digest,
            lineage_receipt_sha256=lineage_service_module._lineage_receipt_digest(
                graph_without_digest
            ),
        )

    monkeypatch.setattr(
        MissionResearchQueueService,
        "_build_queue_in_snapshot",
        forged_queue,
    )
    monkeypatch.setattr(ClaimLineageService, "_build_graph_in_snapshot", forged_graph)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_inconsistent"
    assert caught.value.public_message == _SAFE_INCONSISTENT_MESSAGE
    assert forged_claim_id not in caught.value.public_message


def test_lineage_evidence_cannot_name_a_different_claim_even_with_valid_digests(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    foreign = lab.seed_claim(source_label="foreign/evidence-owner.txt")
    real_graph = ClaimLineageService._build_graph_in_snapshot

    def forged_graph(self: ClaimLineageService, **kwargs: object) -> object:
        graph = real_graph(self, **kwargs)  # type: ignore[arg-type]
        nodes = tuple(
            replace(node, payload=replace(node.payload, claim_id=foreign.claim.id))
            if node.kind is ClaimLineageNodeKind.EVIDENCE
            and isinstance(node.payload, EvidenceLineageData)
            else node
            for node in graph.nodes
        )
        provisional = replace(
            graph,
            nodes=nodes,
            node_set_sha256=lineage_service_module._node_set_digest(
                mission_id=graph.mission_id,
                claim_id=graph.claim_id,
                nodes=nodes,
            ),
            lineage_receipt_sha256="",
        )
        return replace(
            provisional,
            lineage_receipt_sha256=lineage_service_module._lineage_receipt_digest(provisional),
        )

    monkeypatch.setattr(ClaimLineageService, "_build_graph_in_snapshot", forged_graph)
    with pytest.raises(IntegrityError) as caught:
        ReviewDossierService(lab.database).build_dossier(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            lens_receipt=receipt,
        )

    assert caught.value.code == "review_dossier_inconsistent"
    assert caught.value.public_message == _SAFE_INCONSISTENT_MESSAGE
    assert foreign.claim.id not in caught.value.public_message


def test_concurrent_writer_cannot_create_a_mixed_dossier_snapshot(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, receipt = _seed_dossier(lab)
    service = ReviewDossierService(lab.database)
    baseline = service.build_dossier(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        lens_receipt=receipt,
    )
    entered = threading.Event()
    release = threading.Event()
    paused = False
    results: list[object] = []
    failures: list[BaseException] = []
    real_replay = cast(Any, dossier_service_module)._replay_lens_receipt_in_snapshot

    def pausing_replay(*args: object, **kwargs: object) -> object:
        nonlocal paused
        result = real_replay(*args, **kwargs)  # type: ignore[arg-type]
        if not paused:
            paused = True
            entered.set()
            if not release.wait(timeout=10):
                raise AssertionError("timed out waiting to resume the dossier snapshot")
        return result

    monkeypatch.setattr(
        dossier_service_module,
        "_replay_lens_receipt_in_snapshot",
        pausing_replay,
    )

    def build_in_thread() -> None:
        try:
            results.append(
                service.build_dossier(
                    mission_id=seed.mission.id,
                    claim_id=seed.claim.id,
                    lens_receipt=receipt,
                )
            )
        except BaseException as error:  # pragma: no cover - asserted below
            failures.append(error)

    thread = threading.Thread(target=build_in_thread, name="review-dossier-reader")
    thread.start()
    try:
        assert entered.wait(timeout=10), "dossier did not establish its Lens read snapshot"
        lab.cite(seed, _SUPPORT_QUOTE, EvidenceStance.SUPPORTS)
    finally:
        release.set()
    thread.join(timeout=10)

    assert not thread.is_alive()
    assert failures == []
    assert results == [baseline]

    after = service.build_dossier(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        lens_receipt=receipt,
    )
    assert after != baseline
    assert baseline.claim_review.work.evidence_card_count == 0
    assert after.claim_review.work.evidence_card_count == 1


def test_pre_v5_database_requires_explicit_migration_before_dossier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-review-dossier-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4

    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-review-dossier",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before Review Dossier",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy Review Dossier mission",
        objective="A stale database cannot compose a complete current review.",
        identity=identity,
    )
    question = research.add_question(
        mission_id=mission.id,
        text="Can a stale database compose the review views?",
        identity=identity,
    )
    claim = research.add_claim(
        mission_id=mission.id,
        question_id=question.id,
        statement="Review Dossier refuses stale migration state.",
        falsification_criteria="A successful pre-migration dossier would falsify it.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy dossier corpus\n",
        original_label="legacy-dossier.txt",
        media_type="text/plain",
        identity=identity,
    )
    receipt = LensService(legacy).search(mission_id=mission.id, query="dossier")

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as required:
        ReviewDossierService(legacy).build_dossier(
            mission_id=mission.id,
            claim_id=claim.id,
            lens_receipt=receipt,
        )
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    result = ReviewDossierService(legacy).build_dossier(
        mission_id=mission.id,
        claim_id=claim.id,
        lens_receipt=receipt,
    )
    assert result.complete is True
    assert result.work.component_count == 5
