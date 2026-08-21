"""Run the deterministic, model-free Claim Lineage Graph v1 evaluation."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from minerva.assist.adoption import AdoptionService
from minerva.assist.models import FindingCandidate, ModelProvider, ProviderSelection
from minerva.assist.service import AssistanceService
from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.lineage import ClaimLineageService
from minerva.lineage.models import (
    ClaimLineageNode,
    ClaimLineageNodeKind,
    ClaimLineageRelation,
    EvidenceLineageData,
)
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_RESPONSE_SHA256 = sha256(b"fixed synthetic claim-lineage response").hexdigest()


class _SequenceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self, prefix: str) -> str:
        self.value += 1
        return f"{prefix}_{self.value:032x}"


def _fixed_clock() -> str:
    return _CLOCK


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _state(database: Database) -> tuple[tuple[str, ...], str]:
    with database.read() as connection:
        dump = tuple(connection.iterdump())
    return dump, sha256(database.path.read_bytes()).hexdigest()


def _ppm(numerator: int, denominator: int) -> int:
    return numerator * 1_000_000 // denominator if denominator else 0


def _payload_link_signature(
    node: ClaimLineageNode,
) -> tuple[
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    payload = asdict(node.payload)
    return (
        node.node_id,
        payload.get("mission_id"),
        payload.get("question_id"),
        payload.get("claim_id"),
        payload.get("source_id"),
        payload.get("snapshot_id"),
        payload.get("target_id"),
        payload.get("inference_id"),
        payload.get("finding_id"),
    )


def _cite(
    evidence: EvidenceService,
    *,
    mission_id: str,
    claim_id: str,
    snapshot_id: str,
    content: bytes,
    quote: str,
    stance: EvidenceStance,
    identity: IdentityContext,
    supersedes_evidence_id: str | None = None,
) -> EvidenceCard:
    quote_bytes = quote.encode("utf-8")
    start_byte = content.index(quote_bytes)
    return evidence.add_evidence(
        mission_id=mission_id,
        claim_id=claim_id,
        snapshot_id=snapshot_id,
        start_byte=start_byte,
        end_byte=start_byte + len(quote_bytes),
        quote=quote,
        stance=stance,
        supersedes_evidence_id=supersedes_evidence_id,
        identity=identity,
    )


def evaluate_claim_lineage() -> dict[str, object]:
    """Measure exact topology, citation custody, isolation, and nonmutation."""
    with tempfile.TemporaryDirectory(prefix="minerva-claim-lineage-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:claim-lineage-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate deterministic claim-owned provenance topology",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        evidence = EvidenceService(database, clock=_fixed_clock, id_factory=ids)
        assistance = AssistanceService(database, clock=_fixed_clock, id_factory=ids)
        adoption = AdoptionService(database, clock=_fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Claim Lineage evaluation mission",
            objective="Measure complete claim-owned provenance topology.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Can every recorded dependency be inspected exactly?",
            identity=identity,
        )
        claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The claim-owned lineage is complete and deterministic.",
            falsification_criteria="Any missing, extra, unstable, or foreign edge refutes it.",
            identity=identity,
        )
        content = (
            "Préface establishes the UTF-8 offset.\n"
            "Café 東京 provides exact supporting bytes.\n"
            "Replacement context preserves correction history.\n"
        ).encode()
        snapshot = sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label="claim-lineage-fixture.txt",
            media_type="text/plain",
            identity=identity,
        )
        support = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Café 東京 provides exact supporting bytes.",
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )
        replacement = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote="Replacement context preserves correction history.",
            stance=EvidenceStance.CONTEXT,
            supersedes_evidence_id=support.id,
            identity=identity,
        )
        research.set_claim_status(
            claim_id=claim.id,
            status=ClaimStatus.PROVISIONALLY_SUPPORTED,
            reason="The supporting citation was active when this status was recorded.",
            expected_version=claim.version,
            identity=identity,
        )
        human_finding = research.add_finding(
            mission_id=mission.id,
            claim_id=claim.id,
            statement="A human finding retains the original exact citation.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="The cited observation may later be corrected.",
            evidence_ids=(support.id,),
            identity=identity,
        )
        finding_retraction_id = research.retract_finding(
            finding_id=human_finding.id,
            reason="The assertion is retained only as append-only history.",
            identity=identity,
        )

        preview = assistance.preview_finding_candidates(
            claim_id=claim.id,
            selection=ProviderSelection(ModelProvider.OPENAI, "lineage-eval-model", "fixture"),
            max_candidates=1,
            max_output_tokens=256,
        )
        inference = adoption.adopt_inference(
            preview=preview,
            expected_request_sha256=preview.request_sha256,
            candidate_index=0,
            candidate=FindingCandidate(
                statement="A promoted inference keeps separate model provenance.",
                statement_kind=StatementKind.AGENT_INFERENCE,
                uncertainty="Human promotion does not erase model authorship.",
                evidence_ids=(replacement.id,),
            ),
            response_sha256=_RESPONSE_SHA256,
            identity=identity,
        )
        promoted_finding = adoption.promote_inference_to_finding(
            inference_id=inference.id,
            status=FindingStatus.INCONCLUSIVE,
            identity=identity,
        )
        inference_retraction_id = adoption.retract_inference(
            inference_id=inference.id,
            reason="Retraction remains separate from the promoted finding.",
            identity=identity,
        )
        withdrawal_id = evidence.withdraw_evidence(
            evidence_id=support.id,
            reason="The original observation was corrected after recording.",
            identity=identity,
        )

        sibling = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="Sibling claim state must stay outside the target closure.",
            falsification_criteria="Any sibling identifier in the graph is a failure.",
            identity=identity,
        )
        foreign_mission = research.create_mission(
            title="Claim Lineage isolation control",
            objective="Ensure foreign records never enter the target graph.",
            identity=identity,
        )
        foreign_question = research.add_question(
            mission_id=foreign_mission.id,
            text="Can foreign topology leak?",
            identity=identity,
        )
        foreign_claim = research.add_claim(
            mission_id=foreign_mission.id,
            question_id=foreign_question.id,
            statement="Foreign lineage must remain isolated.",
            falsification_criteria="Any disclosure in the target graph is a failure.",
            identity=identity,
        )

        with database.read() as connection:
            status_ids = tuple(
                str(row["id"])
                for row in connection.execute(
                    "SELECT id FROM claim_status_events WHERE claim_id = ? ORDER BY version",
                    (claim.id,),
                )
            )
            promotion_id = str(
                connection.execute(
                    "SELECT id FROM agent_inference_promotions WHERE inference_id = ?",
                    (inference.id,),
                ).fetchone()["id"]
            )

        expected_nodes = frozenset(
            {
                (ClaimLineageNodeKind.QUESTION.value, question.id, "recorded"),
                (ClaimLineageNodeKind.CLAIM.value, claim.id, "recorded"),
                (
                    ClaimLineageNodeKind.CLAIM_STATUS_EVENT.value,
                    status_ids[0],
                    "historical",
                ),
                (ClaimLineageNodeKind.CLAIM_STATUS_EVENT.value, status_ids[1], "current"),
                (ClaimLineageNodeKind.SNAPSHOT.value, snapshot.snapshot_id, "immutable"),
                (ClaimLineageNodeKind.EVIDENCE.value, support.id, "withdrawn"),
                (ClaimLineageNodeKind.EVIDENCE.value, replacement.id, "active"),
                (ClaimLineageNodeKind.EVIDENCE_WITHDRAWAL.value, withdrawal_id, "recorded"),
                (ClaimLineageNodeKind.FINDING.value, human_finding.id, "retracted"),
                (ClaimLineageNodeKind.FINDING.value, promoted_finding.id, "active"),
                (
                    ClaimLineageNodeKind.FINDING_RETRACTION.value,
                    finding_retraction_id,
                    "recorded",
                ),
                (ClaimLineageNodeKind.AGENT_INFERENCE.value, inference.id, "retracted"),
                (
                    ClaimLineageNodeKind.AGENT_INFERENCE_RETRACTION.value,
                    inference_retraction_id,
                    "recorded",
                ),
                (
                    ClaimLineageNodeKind.AGENT_INFERENCE_PROMOTION.value,
                    promotion_id,
                    "recorded",
                ),
            }
        )
        expected_payload_links = frozenset(
            {
                (question.id, mission.id, None, None, None, None, None, None, None),
                (claim.id, mission.id, question.id, None, None, None, None, None, None),
                *(
                    (status_id, mission.id, None, claim.id, None, None, None, None, None)
                    for status_id in status_ids
                ),
                (
                    snapshot.snapshot_id,
                    mission.id,
                    None,
                    None,
                    snapshot.source_id,
                    None,
                    None,
                    None,
                    None,
                ),
                (
                    support.id,
                    mission.id,
                    None,
                    claim.id,
                    None,
                    snapshot.snapshot_id,
                    None,
                    None,
                    None,
                ),
                (
                    replacement.id,
                    mission.id,
                    None,
                    claim.id,
                    None,
                    snapshot.snapshot_id,
                    None,
                    None,
                    None,
                ),
                (
                    withdrawal_id,
                    mission.id,
                    None,
                    None,
                    None,
                    None,
                    support.id,
                    None,
                    None,
                ),
                *(
                    (finding_id, mission.id, None, claim.id, None, None, None, None, None)
                    for finding_id in (human_finding.id, promoted_finding.id)
                ),
                (
                    finding_retraction_id,
                    mission.id,
                    None,
                    None,
                    None,
                    None,
                    human_finding.id,
                    None,
                    None,
                ),
                (inference.id, mission.id, None, claim.id, None, None, None, None, None),
                (
                    inference_retraction_id,
                    mission.id,
                    None,
                    None,
                    None,
                    None,
                    inference.id,
                    None,
                    None,
                ),
                (
                    promotion_id,
                    mission.id,
                    None,
                    None,
                    None,
                    None,
                    None,
                    inference.id,
                    promoted_finding.id,
                ),
            }
        )
        expected_edges = frozenset(
            {
                (ClaimLineageRelation.QUESTION_HAS_CLAIM.value, question.id, claim.id),
                *(
                    (ClaimLineageRelation.CLAIM_HAS_STATUS_EVENT.value, claim.id, status_id)
                    for status_id in status_ids
                ),
                *(
                    (
                        ClaimLineageRelation.STATUS_EVENT_PRECEDES.value,
                        status_ids[index],
                        status_ids[index + 1],
                    )
                    for index in range(len(status_ids) - 1)
                ),
                (ClaimLineageRelation.CLAIM_HAS_EVIDENCE.value, claim.id, support.id),
                (ClaimLineageRelation.CLAIM_HAS_EVIDENCE.value, claim.id, replacement.id),
                (
                    ClaimLineageRelation.EVIDENCE_CITES_SNAPSHOT.value,
                    support.id,
                    snapshot.snapshot_id,
                ),
                (
                    ClaimLineageRelation.EVIDENCE_CITES_SNAPSHOT.value,
                    replacement.id,
                    snapshot.snapshot_id,
                ),
                (
                    ClaimLineageRelation.EVIDENCE_SUPERSEDES_EVIDENCE.value,
                    replacement.id,
                    support.id,
                ),
                (
                    ClaimLineageRelation.EVIDENCE_HAS_WITHDRAWAL.value,
                    support.id,
                    withdrawal_id,
                ),
                (ClaimLineageRelation.CLAIM_HAS_FINDING.value, claim.id, human_finding.id),
                (
                    ClaimLineageRelation.CLAIM_HAS_FINDING.value,
                    claim.id,
                    promoted_finding.id,
                ),
                (
                    ClaimLineageRelation.FINDING_CITES_EVIDENCE.value,
                    human_finding.id,
                    support.id,
                ),
                (
                    ClaimLineageRelation.FINDING_CITES_EVIDENCE.value,
                    promoted_finding.id,
                    replacement.id,
                ),
                (
                    ClaimLineageRelation.FINDING_HAS_RETRACTION.value,
                    human_finding.id,
                    finding_retraction_id,
                ),
                (
                    ClaimLineageRelation.CLAIM_HAS_AGENT_INFERENCE.value,
                    claim.id,
                    inference.id,
                ),
                (
                    ClaimLineageRelation.AGENT_INFERENCE_CITES_EVIDENCE.value,
                    inference.id,
                    replacement.id,
                ),
                (
                    ClaimLineageRelation.AGENT_INFERENCE_HAS_RETRACTION.value,
                    inference.id,
                    inference_retraction_id,
                ),
                (
                    ClaimLineageRelation.AGENT_INFERENCE_HAS_PROMOTION.value,
                    inference.id,
                    promotion_id,
                ),
                (
                    ClaimLineageRelation.PROMOTION_CREATED_FINDING.value,
                    promotion_id,
                    promoted_finding.id,
                ),
            }
        )

        service = ClaimLineageService(database)
        before = _state(database)
        first = service.build_graph(mission_id=mission.id, claim_id=claim.id)
        second = service.build_graph(mission_id=mission.id, claim_id=claim.id)
        after = _state(database)
        predicted_nodes = frozenset(
            (node.kind.value, node.node_id, node.state) for node in first.nodes
        )
        predicted_payload_links = frozenset(_payload_link_signature(node) for node in first.nodes)
        predicted_edges = frozenset(
            (edge.relation.value, edge.source_node_id, edge.target_node_id) for edge in first.edges
        )
        correct_nodes = predicted_nodes & expected_nodes
        correct_payload_links = predicted_payload_links & expected_payload_links
        correct_edges = predicted_edges & expected_edges

        expected_evidence_ids = (support.id, replacement.id)
        evidence_nodes = {
            node.node_id: node for node in first.nodes if node.kind is ClaimLineageNodeKind.EVIDENCE
        }
        accurate_citations = 0
        for evidence_id in expected_evidence_ids:
            node = evidence_nodes.get(evidence_id)
            if node is None:
                continue
            payload = node.payload
            if not isinstance(payload, EvidenceLineageData):
                continue
            quoted = base64.b64decode(payload.quote_utf8_base64, validate=True)
            if (
                content[payload.start_byte : payload.end_byte] == quoted
                and quoted.decode("utf-8") == payload.quote
                and len(quoted) == payload.quote_byte_length
                and sha256(quoted).hexdigest() == payload.quote_sha256
            ):
                accurate_citations += 1

        serialized = _canonical_bytes(asdict(first))
        excluded_identifiers = (
            sibling.id,
            foreign_mission.id,
            foreign_question.id,
            foreign_claim.id,
        )
        excluded_text = (
            sibling.statement,
            sibling.falsification_criteria,
            foreign_mission.title,
            foreign_mission.objective,
            foreign_question.text,
            foreign_claim.statement,
            foreign_claim.falsification_criteria,
        )
        isolated = (
            first.mission_id == mission.id
            and not any(identifier.encode() in serialized for identifier in excluded_identifiers)
            and not any(text.encode() in serialized for text in excluded_text)
        )
        unauthorized_mutation_count = int(before[0] != after[0]) + int(before[1] != after[1])

        return {
            "schema_version": "minerva.claim-lineage-evaluation.v1",
            "algorithm": first.algorithm,
            "algorithm_version": first.algorithm_version,
            "node_precision_ppm": _ppm(len(correct_nodes), len(predicted_nodes)),
            "node_recall_ppm": _ppm(len(correct_nodes), len(expected_nodes)),
            "payload_link_precision_ppm": _ppm(
                len(correct_payload_links), len(predicted_payload_links)
            ),
            "payload_link_recall_ppm": _ppm(
                len(correct_payload_links), len(expected_payload_links)
            ),
            "edge_precision_ppm": _ppm(len(correct_edges), len(predicted_edges)),
            "edge_recall_ppm": _ppm(len(correct_edges), len(expected_edges)),
            "citation_byte_accuracy_ppm": _ppm(accurate_citations, len(expected_evidence_ids)),
            "determinism": _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second)),
            "mission_and_claim_isolation": isolated,
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_claim_count": 3,
            "expected_node_count": len(expected_nodes),
            "result_node_count": len(predicted_nodes),
            "expected_edge_count": len(expected_edges),
            "result_edge_count": len(predicted_edges),
            "expected_citation_count": len(expected_evidence_ids),
            "result_evidence_node_count": len(evidence_nodes),
            "accurate_citation_count": accurate_citations,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_claim_lineage()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
