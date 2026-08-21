from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from conftest import ClaimSeed, Lab, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import (
    AgentInference,
    FindingCandidate,
    ModelProvider,
    ProviderSelection,
)
from minerva.assist.service import AssistanceService
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.lineage import ClaimLineageService
from minerva.lineage.models import (
    AgentInferenceLineageData,
    ClaimLineageNodeKind,
    ClaimLineageRelation,
    EvidenceLineageData,
    FindingLineageData,
    SnapshotLineageData,
)
from minerva.research.models import ClaimStatus, Finding, FindingStatus, StatementKind


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _adopt(
    lab: Lab,
    seed: ClaimSeed,
    *,
    candidates: tuple[tuple[str, str, EvidenceCard], ...],
) -> tuple[AdoptionService, tuple[AgentInference, ...]]:
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "lineage-test-model", "test"),
        max_candidates=len(candidates),
        max_output_tokens=512,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inferences = tuple(
        adoption.adopt_inference(
            preview=preview,
            expected_request_sha256=preview.request_sha256,
            candidate_index=index,
            candidate=FindingCandidate(
                statement=statement,
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty=uncertainty,
                evidence_ids=(evidence.id,),
            ),
            response_sha256=sha256(f"lineage response {index}".encode()).hexdigest(),
            identity=lab.identity,
        )
        for index, (statement, uncertainty, evidence) in enumerate(candidates)
    )
    return adoption, inferences


@dataclass(frozen=True, slots=True)
class _LineageScenario:
    seed: ClaimSeed
    evidence: tuple[EvidenceCard, ...]
    withdrawal_id: str
    findings: tuple[Finding, ...]
    finding_retraction_id: str
    inferences: tuple[AgentInference, ...]
    inference_retraction_id: str
    promotion_id: str
    claim_status_event_ids: tuple[str, ...]
    excluded_ids: tuple[str, ...]
    excluded_text: tuple[str, ...]


def _lineage_scenario(lab: Lab) -> _LineageScenario:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    replacement = lab.cite(
        seed,
        "Café context remains uncertain.",
        EvidenceStance.CONTEXT,
        supersedes_evidence_id=support.id,
    )
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.CONTESTED,
        reason="The active ledger records both support and opposition.",
        expected_version=1,
        identity=lab.identity,
    )

    active_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="An active finding remains in the complete claim-owned graph.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.CONTESTED,
        uncertainty="The observation remains bounded by exact evidence.",
        evidence_ids=(opposition.id,),
        identity=lab.identity,
    )
    retracted_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A retracted finding remains visible as correction history.",
        statement_kind=StatementKind.SOURCE_ASSERTION,
        status=FindingStatus.SUPPORTED,
        uncertainty="The original source assertion was later withdrawn.",
        evidence_ids=(support.id,),
        identity=lab.identity,
    )
    finding_retraction_id = lab.research.retract_finding(
        finding_id=retracted_finding.id,
        reason="The source assertion is no longer independently asserted.",
        identity=lab.identity,
    )

    adoption, inferences = _adopt(
        lab,
        seed,
        candidates=(
            (
                "A promoted inference retains its model and adoption provenance.",
                "Its human promotion remains a separate assertion.",
                support,
            ),
            (
                "An active inference is represented independently of findings.",
                "It remains explicitly model-authored.",
                replacement,
            ),
        ),
    )
    promoted_finding = adoption.promote_inference_to_finding(
        inference_id=inferences[0].id,
        status=FindingStatus.SUPPORTED,
        identity=lab.identity,
    )
    inference_retraction_id = adoption.retract_inference(
        inference_id=inferences[0].id,
        reason="Retraction does not transitively retract the promoted finding.",
        identity=lab.identity,
    )
    withdrawal_id = lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="The original supporting observation was corrected.",
        identity=lab.identity,
    )

    claimless_text = "CLAIMLESS-FINDING-MUST-NOT-ENTER-CLAIM-LINEAGE"
    claimless = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement=claimless_text,
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="This mission-level assumption is outside claim-owned closure.",
        evidence_ids=(support.id,),
        identity=lab.identity,
    )
    sibling = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        statement="SIBLING-CLAIM-MUST-NOT-ENTER-CLAIM-LINEAGE",
        falsification_criteria="Any inclusion in the target graph violates claim scope.",
        identity=lab.identity,
    )
    sibling_evidence = lab.evidence.add_evidence(
        mission_id=seed.mission.id,
        claim_id=sibling.id,
        snapshot_id=seed.snapshot.snapshot_id,
        start_byte=opposition.start_byte,
        end_byte=opposition.end_byte,
        quote=opposition.quote,
        stance=EvidenceStance.OPPOSES,
        identity=lab.identity,
    )
    unused_snapshot = lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"UNUSED-SNAPSHOT-MUST-NOT-ENTER-CLAIM-LINEAGE\n",
        original_label="unused-lineage-source.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    foreign = lab.seed_claim(content=b"FOREIGN-MISSION-MUST-NOT-LEAK\n")

    with lab.database.read() as connection:
        promotion_id = str(
            connection.execute(
                "SELECT id FROM agent_inference_promotions WHERE inference_id = ?",
                (inferences[0].id,),
            ).fetchone()["id"]
        )
        status_ids = tuple(
            str(row["id"])
            for row in connection.execute(
                """
                SELECT id FROM claim_status_events
                WHERE claim_id = ? ORDER BY version ASC
                """,
                (seed.claim.id,),
            )
        )

    return _LineageScenario(
        seed=seed,
        evidence=(support, opposition, replacement),
        withdrawal_id=withdrawal_id,
        findings=(active_finding, retracted_finding, promoted_finding),
        finding_retraction_id=finding_retraction_id,
        inferences=inferences,
        inference_retraction_id=inference_retraction_id,
        promotion_id=promotion_id,
        claim_status_event_ids=status_ids,
        excluded_ids=(
            claimless.id,
            sibling.id,
            sibling_evidence.id,
            unused_snapshot.snapshot_id,
            foreign.mission.id,
            foreign.question.id,
            foreign.claim.id,
            foreign.snapshot.snapshot_id,
        ),
        excluded_text=(
            claimless_text,
            sibling.statement,
            "UNUSED-SNAPSHOT-MUST-NOT-ENTER-CLAIM-LINEAGE",
            "FOREIGN-MISSION-MUST-NOT-LEAK",
        ),
    )


def test_complete_claim_lineage_has_exact_nodes_edges_and_receipts(lab: Lab) -> None:
    scenario = _lineage_scenario(lab)
    service = ClaimLineageService(lab.database)

    first = service.build_graph(
        mission_id=scenario.seed.mission.id,
        claim_id=scenario.seed.claim.id,
    )
    second = service.build_graph(
        mission_id=scenario.seed.mission.id,
        claim_id=scenario.seed.claim.id,
    )

    assert first == second
    assert _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second))
    assert first.schema_version == "minerva.claim-lineage.v1"
    assert first.kind == "claim_lineage_graph"
    assert first.algorithm == "structural-ledger-lineage"
    assert first.algorithm_version == "1"
    assert first.scope == "claim_owned_closure_v1"
    assert first.completion_policy == "complete_or_refuse"
    assert first.complete is True
    assert first.truncated is False
    assert first.mission_id == scenario.seed.mission.id
    assert first.claim_id == scenario.seed.claim.id
    assert first.question_id == scenario.seed.question.id
    assert first.root_node_id == scenario.seed.claim.id

    receipt_payload = asdict(first)
    receipt_digest = receipt_payload.pop("lineage_receipt_sha256")
    assert receipt_digest == sha256(_canonical_bytes(receipt_payload)).hexdigest()

    node_set_frame = {
        "schema_version": "minerva.claim-lineage-nodes.v1",
        "mission_id": scenario.seed.mission.id,
        "claim_id": scenario.seed.claim.id,
        "nodes": [asdict(node) for node in first.nodes],
    }
    assert first.node_set_sha256 == sha256(_canonical_bytes(node_set_frame)).hexdigest()

    edge_set_frame = {
        "schema_version": "minerva.claim-lineage-edges.v1",
        "mission_id": scenario.seed.mission.id,
        "claim_id": scenario.seed.claim.id,
        "edges": [asdict(edge) for edge in first.edges],
    }
    assert first.edge_set_sha256 == sha256(_canonical_bytes(edge_set_frame)).hexdigest()

    framed_snapshot_node = next(
        node
        for node in first.nodes
        if node.kind is ClaimLineageNodeKind.SNAPSHOT
        and node.node_id == scenario.seed.snapshot.snapshot_id
    )
    assert isinstance(framed_snapshot_node.payload, SnapshotLineageData)
    snapshot_set_frame = {
        "schema_version": "minerva.claim-lineage-snapshots.v1",
        "mission_id": scenario.seed.mission.id,
        "claim_id": scenario.seed.claim.id,
        "snapshots": [
            {
                "source_id": framed_snapshot_node.payload.source_id,
                "snapshot_id": framed_snapshot_node.node_id,
                "snapshot_sha256": framed_snapshot_node.payload.snapshot_sha256,
                "byte_length": framed_snapshot_node.payload.byte_length,
                "encoding": framed_snapshot_node.payload.encoding,
                "media_type": framed_snapshot_node.payload.media_type,
                "original_label": framed_snapshot_node.payload.snapshot_original_label,
                "imported_at": framed_snapshot_node.payload.provenance.recorded_at,
            }
        ],
    }
    assert first.snapshot_set_sha256 == sha256(_canonical_bytes(snapshot_set_frame)).hexdigest()

    for digest in (
        first.node_set_sha256,
        first.edge_set_sha256,
        first.snapshot_set_sha256,
        first.lineage_receipt_sha256,
    ):
        assert len(digest) == 64
        int(digest, 16)

    expected_node_ids = {
        scenario.seed.question.id,
        scenario.seed.claim.id,
        scenario.seed.snapshot.snapshot_id,
        *scenario.claim_status_event_ids,
        *(item.id for item in scenario.evidence),
        scenario.withdrawal_id,
        *(item.id for item in scenario.findings),
        scenario.finding_retraction_id,
        *(item.id for item in scenario.inferences),
        scenario.inference_retraction_id,
        scenario.promotion_id,
    }
    nodes_by_id = {node.node_id: node for node in first.nodes}
    assert set(nodes_by_id) == expected_node_ids
    assert len(nodes_by_id) == len(first.nodes) == 17

    support, opposition, replacement = scenario.evidence
    active_finding, retracted_finding, promoted_finding = scenario.findings
    promoted_inference, active_inference = scenario.inferences
    status_one, status_two = scenario.claim_status_event_ids
    expected_edges = {
        (
            ClaimLineageRelation.QUESTION_HAS_CLAIM,
            scenario.seed.question.id,
            scenario.seed.claim.id,
        ),
        (ClaimLineageRelation.CLAIM_HAS_STATUS_EVENT, scenario.seed.claim.id, status_one),
        (ClaimLineageRelation.CLAIM_HAS_STATUS_EVENT, scenario.seed.claim.id, status_two),
        (ClaimLineageRelation.STATUS_EVENT_PRECEDES, status_one, status_two),
        *(
            (ClaimLineageRelation.CLAIM_HAS_EVIDENCE, scenario.seed.claim.id, item.id)
            for item in scenario.evidence
        ),
        *(
            (
                ClaimLineageRelation.EVIDENCE_CITES_SNAPSHOT,
                item.id,
                scenario.seed.snapshot.snapshot_id,
            )
            for item in scenario.evidence
        ),
        (ClaimLineageRelation.EVIDENCE_SUPERSEDES_EVIDENCE, replacement.id, support.id),
        (ClaimLineageRelation.EVIDENCE_HAS_WITHDRAWAL, support.id, scenario.withdrawal_id),
        *(
            (ClaimLineageRelation.CLAIM_HAS_FINDING, scenario.seed.claim.id, item.id)
            for item in scenario.findings
        ),
        (ClaimLineageRelation.FINDING_CITES_EVIDENCE, active_finding.id, opposition.id),
        (ClaimLineageRelation.FINDING_CITES_EVIDENCE, retracted_finding.id, support.id),
        (ClaimLineageRelation.FINDING_CITES_EVIDENCE, promoted_finding.id, support.id),
        (
            ClaimLineageRelation.FINDING_HAS_RETRACTION,
            retracted_finding.id,
            scenario.finding_retraction_id,
        ),
        *(
            (ClaimLineageRelation.CLAIM_HAS_AGENT_INFERENCE, scenario.seed.claim.id, item.id)
            for item in scenario.inferences
        ),
        (
            ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE,
            promoted_inference.id,
            support.id,
        ),
        (
            ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE,
            active_inference.id,
            replacement.id,
        ),
        (
            ClaimLineageRelation.AGENT_INFERENCE_HAS_RETRACTION,
            promoted_inference.id,
            scenario.inference_retraction_id,
        ),
        (
            ClaimLineageRelation.AGENT_INFERENCE_HAS_PROMOTION,
            promoted_inference.id,
            scenario.promotion_id,
        ),
        (
            ClaimLineageRelation.PROMOTION_CREATED_FINDING,
            scenario.promotion_id,
            promoted_finding.id,
        ),
    }
    actual_edges = {
        (edge.relation, edge.source_node_id, edge.target_node_id) for edge in first.edges
    }
    assert actual_edges == expected_edges
    assert len(first.edges) == 26
    assert all(
        edge.source_node_id in nodes_by_id and edge.target_node_id in nodes_by_id
        for edge in first.edges
    )

    assert first.work.node_count == len(first.nodes) == 17
    assert first.work.edge_count == len(first.edges) == 26
    assert first.work.status_event_count == 2
    assert first.work.evidence_count == 3
    assert first.work.finding_count == 3
    assert first.work.inference_count == 2
    assert first.work.correction_count == 3
    assert first.work.promotion_count == 1
    assert first.work.citation_edge_count == 5
    assert first.work.citation_bytes == sum(
        item.end_byte - item.start_byte for item in scenario.evidence
    )
    assert first.work.distinct_snapshot_count == 1
    assert first.work.distinct_snapshot_bytes == len(scenario.seed.content)
    assert 0 < first.work.graph_payload_bytes <= first.bounds.max_output_bytes

    assert {item.kind: item.count for item in first.node_kind_counts} == {
        ClaimLineageNodeKind.QUESTION.value: 1,
        ClaimLineageNodeKind.CLAIM.value: 1,
        ClaimLineageNodeKind.CLAIM_STATUS_EVENT.value: 2,
        ClaimLineageNodeKind.SNAPSHOT.value: 1,
        ClaimLineageNodeKind.EVIDENCE.value: 3,
        ClaimLineageNodeKind.EVIDENCE_WITHDRAWAL.value: 1,
        ClaimLineageNodeKind.FINDING.value: 3,
        ClaimLineageNodeKind.FINDING_RETRACTION.value: 1,
        ClaimLineageNodeKind.AGENT_INFERENCE.value: 2,
        ClaimLineageNodeKind.AGENT_INFERENCE_RETRACTION.value: 1,
        ClaimLineageNodeKind.AGENT_INFERENCE_PROMOTION.value: 1,
    }
    assert {item.kind: item.count for item in first.edge_kind_counts} == {
        relation.value: sum(edge.relation is relation for edge in first.edges)
        for relation in ClaimLineageRelation
    }

    assert nodes_by_id[support.id].state == "withdrawn"
    assert nodes_by_id[retracted_finding.id].state == "retracted"
    assert nodes_by_id[promoted_finding.id].state == "active"
    assert nodes_by_id[promoted_inference.id].state == "retracted"
    assert nodes_by_id[active_inference.id].state == "active"
    assert nodes_by_id[status_one].state == "historical"
    assert nodes_by_id[status_two].state == "current"

    assert first.semantic_boundary.read_only is True
    assert first.semantic_boundary.structural_topology_only is True
    assert first.semantic_boundary.complete_claim_owned_scope is True
    assert first.semantic_boundary.includes_corrected_history is True
    assert first.semantic_boundary.mission_wide is False
    assert first.semantic_boundary.includes_claimless_dependents is False
    assert first.semantic_boundary.determines_truth is False
    assert first.semantic_boundary.calculates_confidence is False
    assert first.semantic_boundary.creates_or_changes_research_state is False
    assert first.semantic_boundary.creates_research_queue is False
    assert first.semantic_boundary.invokes_model_provider is False
    assert first.semantic_boundary.invokes_network is False

    encoded = _canonical_bytes(asdict(first)).decode("utf-8")
    for excluded in (*scenario.excluded_ids, *scenario.excluded_text):
        assert excluded not in encoded


def test_lineage_exact_citations_round_trip_multibyte_utf8(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Café context remains uncertain.", EvidenceStance.CONTEXT)

    graph = ClaimLineageService(lab.database).build_graph(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    evidence_node = next(node for node in graph.nodes if node.node_id == evidence.id)
    assert isinstance(evidence_node.payload, EvidenceLineageData)
    raw_quote = base64.b64decode(evidence_node.payload.quote_utf8_base64, validate=True)
    assert raw_quote == evidence.quote.encode("utf-8")
    assert raw_quote == seed.content[evidence.start_byte : evidence.end_byte]
    assert evidence_node.payload.start_byte == evidence.start_byte
    assert evidence_node.payload.end_byte == evidence.end_byte
    assert evidence_node.payload.quote == evidence.quote
    assert evidence_node.payload.quote_byte_length == len(raw_quote)
    assert evidence_node.payload.quote_sha256 == sha256(raw_quote).hexdigest()

    snapshot_node = next(node for node in graph.nodes if node.node_id == seed.snapshot.snapshot_id)
    assert isinstance(snapshot_node.payload, SnapshotLineageData)
    assert snapshot_node.payload.source_id == seed.snapshot.source_id
    assert snapshot_node.payload.snapshot_sha256 == seed.snapshot.sha256
    assert snapshot_node.payload.byte_length == len(seed.content)
    assert snapshot_node.payload.snapshot_original_label == "notes/source.txt"


def test_lineage_order_is_total_and_supersession_does_not_deactivate(lab: Lab) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    replacement = lab.cite(
        seed,
        "Evidence supports the claim.",
        EvidenceStance.SUPPORTS,
        supersedes_evidence_id=original.id,
    )

    graph = ClaimLineageService(lab.database).build_graph(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )

    node_order = {kind: index for index, kind in enumerate(ClaimLineageNodeKind)}
    node_keys = tuple((node_order[node.kind], node.node_id) for node in graph.nodes)
    assert node_keys == tuple(sorted(node_keys))
    edge_order = {relation: index for index, relation in enumerate(ClaimLineageRelation)}
    edge_keys = tuple(
        (edge_order[edge.relation], edge.source_node_id, edge.target_node_id)
        for edge in graph.edges
    )
    assert edge_keys == tuple(sorted(edge_keys))

    nodes = {node.node_id: node for node in graph.nodes}
    assert nodes[original.id].state == "active"
    assert nodes[replacement.id].state == "active"
    assert any(
        edge.relation is ClaimLineageRelation.EVIDENCE_SUPERSEDES_EVIDENCE
        and edge.source_node_id == replacement.id
        and edge.target_node_id == original.id
        for edge in graph.edges
    )
    assert isinstance(nodes[original.id].payload, EvidenceLineageData)
    assert isinstance(nodes[replacement.id].payload, EvidenceLineageData)


def test_lineage_includes_unaffected_claim_owned_records(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="An unaffected active finding still belongs in the full lineage graph.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="No correction selects this record.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    _, (inference,) = _adopt(
        lab,
        seed,
        candidates=(
            (
                "An unaffected active inference still belongs in the graph.",
                "It remains labeled model output.",
                evidence,
            ),
        ),
    )

    graph = ClaimLineageService(lab.database).build_graph(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
    )
    nodes = {node.node_id: node for node in graph.nodes}

    assert isinstance(nodes[finding.id].payload, FindingLineageData)
    assert isinstance(nodes[inference.id].payload, AgentInferenceLineageData)
    assert nodes[finding.id].state == "active"
    assert nodes[inference.id].state == "active"
