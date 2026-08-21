from __future__ import annotations

import base64
import json
from dataclasses import asdict, dataclass
from hashlib import sha256

from conftest import Lab
from minerva.dossier import ReviewDossierService
from minerva.evidence.models import EvidenceStance
from minerva.lens import LensBounds, LensSearchResult, LensService
from minerva.lineage import ClaimLineageService
from minerva.lineage.models import ClaimLineageNodeKind, EvidenceLineageData
from minerva.research.models import ClaimStatus, FindingStatus, StatementKind
from minerva.research_queue import MissionResearchQueueService
from minerva.review import ClaimReviewService


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _receipt_digest(value: object, field: str) -> str:
    payload = asdict(value)  # type: ignore[arg-type]
    payload.pop(field)
    return sha256(_canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class _DossierScenario:
    mission_id: str
    question_id: str
    claim_id: str
    snapshot_id: str
    evidence_id: str
    owned_finding_id: str
    claimless_finding_id: str
    content: bytes
    quote: str
    lens_receipt: LensSearchResult


def _dossier_scenario(lab: Lab) -> _DossierScenario:
    quote = "Café résumé supports the bounded claim."
    content = (
        b"A prelude does not match the retrieval query.\n"
        + quote.encode("utf-8")
        + b"\n"
        + "A second résumé passage preserves local context.\n".encode()
    )
    seed = lab.seed_claim(content=content, source_label="dossier/utf8-source.txt")
    evidence = lab.cite(seed, quote, EvidenceStance.SUPPORTS)
    lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.PROVISIONALLY_SUPPORTED,
        reason="The exact supporting citation was active when this status was recorded.",
        expected_version=seed.claim.version,
        identity=lab.identity,
    )
    owned_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The multibyte source passage records bounded support.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The fixture later withdraws the cited evidence.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    claimless_finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=None,
        statement="A claimless assumption retains the same corrected citation.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="It remains optional and outside claim-owned lineage.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The fixture preserves the citation while recording its withdrawal.",
        identity=lab.identity,
    )
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="résumé supports",
        bounds=LensBounds(max_results=10),
    )
    return _DossierScenario(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        evidence_id=evidence.id,
        owned_finding_id=owned_finding.id,
        claimless_finding_id=claimless_finding.id,
        content=content,
        quote=quote,
        lens_receipt=lens_receipt,
    )


def test_dossier_is_deterministic_and_binds_exact_nested_provenance(lab: Lab) -> None:
    scenario = _dossier_scenario(lab)
    service = ReviewDossierService(lab.database)

    first = service.build_dossier(
        mission_id=scenario.mission_id,
        claim_id=scenario.claim_id,
        lens_receipt=scenario.lens_receipt,
    )
    second = service.build_dossier(
        mission_id=scenario.mission_id,
        claim_id=scenario.claim_id,
        lens_receipt=scenario.lens_receipt,
    )

    assert first == second
    assert _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second))
    assert first.schema_version == "minerva.review-dossier.v1"
    assert first.kind == "review_dossier"
    assert first.algorithm == "current-snapshot-review-composition"
    assert first.algorithm_version == "1"
    assert first.scope == "mission_claim_with_captured_lens_v1"
    assert first.completion_policy == "complete_or_refuse"
    assert first.complete is True
    assert first.truncated is False
    assert first.lens_retrieval_truncated is False
    assert (first.mission_id, first.claim_id, first.question_id) == (
        scenario.mission_id,
        scenario.claim_id,
        scenario.question_id,
    )
    assert first.component_order == (
        "mission_research_queue",
        "claim_review",
        "claim_lineage",
        "lens_search",
        "lens_replay",
    )
    assert all(asdict(first.cross_checks).values())

    queue = first.mission_research_queue
    review = first.claim_review
    lineage = first.claim_lineage
    selected_summary = tuple(
        item for item in queue.reviewed_claims if item.claim_id == scenario.claim_id
    )
    assert len(selected_summary) == 1
    assert selected_summary[0].review_receipt_sha256 == review.review_receipt_sha256
    assert selected_summary[0].reason_codes == review.gap_codes + review.impact_codes
    assert tuple(
        (item.reason_code, item.record_ids, item.source_review_receipt_sha256)
        for item in queue.items
        if item.claim_id == scenario.claim_id
    ) == tuple(
        (cue.code, cue.record_ids, review.review_receipt_sha256) for cue in review.review_cues
    )

    quote_bytes = scenario.quote.encode("utf-8")
    expected_start = scenario.content.index(quote_bytes)
    evidence = next(item for item in review.evidence if item.evidence_id == scenario.evidence_id)
    assert evidence.snapshot_id == scenario.snapshot_id
    assert (evidence.start_byte, evidence.end_byte) == (
        expected_start,
        expected_start + len(quote_bytes),
    )
    assert evidence.quote_byte_length == len(quote_bytes)
    assert evidence.quote_sha256 == sha256(quote_bytes).hexdigest()
    assert evidence.withdrawal is not None
    assert scenario.content[evidence.start_byte : evidence.end_byte] == quote_bytes

    lineage_evidence = next(
        node.payload
        for node in lineage.nodes
        if node.kind is ClaimLineageNodeKind.EVIDENCE
        and node.node_id == scenario.evidence_id
        and isinstance(node.payload, EvidenceLineageData)
    )
    assert lineage_evidence.quote == scenario.quote
    assert base64.b64decode(lineage_evidence.quote_utf8_base64, validate=True) == quote_bytes
    assert (lineage_evidence.start_byte, lineage_evidence.end_byte) == (
        evidence.start_byte,
        evidence.end_byte,
    )
    assert lineage_evidence.quote_sha256 == evidence.quote_sha256
    assert scenario.owned_finding_id in {node.node_id for node in lineage.nodes}
    assert scenario.claimless_finding_id in {item.finding_id for item in review.affected_findings}
    assert scenario.claimless_finding_id not in {node.node_id for node in lineage.nodes}

    lens_candidate = next(
        candidate for candidate in first.lens_search.candidates if candidate.quote == scenario.quote
    )
    assert first.lens_search == scenario.lens_receipt
    assert base64.b64decode(lens_candidate.quote_utf8_base64, validate=True) == quote_bytes
    assert scenario.content[lens_candidate.start_byte : lens_candidate.end_byte] == quote_bytes
    assert first.lens_replay.status == "reproduced"
    assert first.lens_replay.exact_receipt_match is True
    assert first.lens_replay.current_database_snapshot_matched is True
    assert first.lens_replay.historical_corpus_replay is False
    assert (
        first.lens_replay.retrieval_receipt_sha256 == scenario.lens_receipt.retrieval_receipt_sha256
    )

    assert queue.queue_receipt_sha256 == _receipt_digest(queue, "queue_receipt_sha256")
    assert review.review_receipt_sha256 == _receipt_digest(review, "review_receipt_sha256")
    assert lineage.lineage_receipt_sha256 == _receipt_digest(
        lineage,
        "lineage_receipt_sha256",
    )
    assert first.lens_search.retrieval_receipt_sha256 == _receipt_digest(
        first.lens_search,
        "retrieval_receipt_sha256",
    )
    expected_component_digests = (
        queue.queue_receipt_sha256,
        review.review_receipt_sha256,
        lineage.lineage_receipt_sha256,
        first.lens_search.retrieval_receipt_sha256,
        sha256(_canonical_bytes(asdict(first.lens_replay))).hexdigest(),
    )
    assert tuple(item.receipt_sha256 for item in first.component_receipts) == (
        expected_component_digests
    )
    component_frame = {
        "schema_version": "minerva.review-dossier-components.v1",
        "algorithm": first.algorithm,
        "algorithm_version": first.algorithm_version,
        "scope": first.scope,
        "mission_id": first.mission_id,
        "claim_id": first.claim_id,
        "components": [asdict(item) for item in first.component_receipts],
    }
    assert first.component_set_sha256 == sha256(_canonical_bytes(component_frame)).hexdigest()
    assert first.dossier_receipt_sha256 == _receipt_digest(
        first,
        "dossier_receipt_sha256",
    )
    assert first.work.canonical_output_bytes == len(_canonical_bytes(asdict(first)))
    assert first.work.component_count == len(first.component_receipts) == 5


def test_snapshot_composition_seams_equal_the_public_child_services(lab: Lab) -> None:
    scenario = _dossier_scenario(lab)
    dossier = ReviewDossierService(lab.database).build_dossier(
        mission_id=scenario.mission_id,
        claim_id=scenario.claim_id,
        lens_receipt=scenario.lens_receipt,
    )

    assert dossier.mission_research_queue == MissionResearchQueueService(lab.database).build_queue(
        mission_id=scenario.mission_id,
        bounds=dossier.bounds.mission_queue,
    )
    assert dossier.claim_review == ClaimReviewService(lab.database).review_claim(
        mission_id=scenario.mission_id,
        claim_id=scenario.claim_id,
        bounds=dossier.mission_research_queue.claim_review_bounds,
    )
    assert dossier.claim_lineage == ClaimLineageService(lab.database).build_graph(
        mission_id=scenario.mission_id,
        claim_id=scenario.claim_id,
        bounds=dossier.bounds.claim_lineage,
    )
    assert dossier.lens_search == scenario.lens_receipt
    assert dossier.lens_replay == LensService(lab.database).replay_receipt(scenario.lens_receipt)


def test_lens_truncation_is_preserved_without_making_the_dossier_partial(lab: Lab) -> None:
    content = (
        "Café bounded lead one remains candidate context.\n"
        "Café bounded lead two remains candidate context.\n"
        "Café bounded lead three remains candidate context.\n"
    ).encode()
    seed = lab.seed_claim(content=content, source_label="dossier/truncated-lens.txt")
    lens_receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="café bounded lead",
        bounds=LensBounds(max_results=1),
    )
    assert lens_receipt.truncated is True
    assert lens_receipt.result_count == 1
    assert lens_receipt.matching_candidate_count == 3
    assert lens_receipt.omissions.matching_candidates_omitted_by_result_limit == 2

    dossier = ReviewDossierService(lab.database).build_dossier(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        lens_receipt=lens_receipt,
    )

    assert dossier.complete is True
    assert dossier.truncated is False
    assert dossier.lens_retrieval_truncated is True
    assert dossier.lens_search == lens_receipt
    assert dossier.lens_search.omissions == lens_receipt.omissions
    assert dossier.lens_replay.exact_receipt_match is True
    assert dossier.lens_replay.current_database_snapshot_matched is True
    assert dossier.cross_checks.lens_current_database_exact_match is True
    assert dossier.semantic_boundary.lens_candidates_are_evidence is False
    assert dossier.semantic_boundary.lens_candidates_assessed_against_claim is False
    assert dossier.semantic_boundary.creates_or_changes_research_state is False
