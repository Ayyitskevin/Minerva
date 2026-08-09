"""Run the deterministic, model-free Review Dossier v1 structural evaluation."""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
from dataclasses import asdict, fields
from hashlib import sha256
from pathlib import Path

from minerva.core.db import Database
from minerva.core.types import ActorKind, IdentityContext
from minerva.dossier import ReviewDossierService
from minerva.evidence.models import EvidenceCard, EvidenceStance
from minerva.evidence.service import EvidenceService
from minerva.lens import LensBounds, LensService
from minerva.lineage.models import ClaimLineageNodeKind, EvidenceLineageData
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService

_CLOCK = "2026-08-08T12:00:00.000000Z"
_COMPONENT_ORDER = (
    "mission_research_queue",
    "claim_review",
    "claim_lineage",
    "lens_search",
    "lens_replay",
)


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


def _receipt_digest(value: object, field_name: str) -> str:
    payload = asdict(value)  # type: ignore[arg-type]
    payload.pop(field_name)
    return sha256(_canonical_bytes(payload)).hexdigest()


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
        identity=identity,
    )


def evaluate_review_dossier() -> dict[str, object]:
    """Measure structural composition, exact bytes, isolation, and nonmutation."""
    with tempfile.TemporaryDirectory(prefix="minerva-review-dossier-evaluation-") as temporary:
        database = Database(Path(temporary) / "evaluation.db")
        database.initialize()
        ids = _SequenceIds()
        identity = IdentityContext(
            actor_id="os-user:review-dossier-evaluation",
            actor_kind=ActorKind.OS_USER,
            run_id=ids("run"),
            purpose="evaluate deterministic atomic review composition",
        )
        research = ResearchService(database, clock=_fixed_clock, id_factory=ids)
        sources = SourceService(database, clock=_fixed_clock, id_factory=ids)
        evidence = EvidenceService(database, clock=_fixed_clock, id_factory=ids)

        mission = research.create_mission(
            title="Review Dossier evaluation target",
            objective="Measure exact atomic composition of local structural receipts.",
            identity=identity,
        )
        question = research.add_question(
            mission_id=mission.id,
            text="Can one read snapshot bind all review components?",
            identity=identity,
        )
        claim = research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="The fixture exposes deterministic structural composition.",
            falsification_criteria="Any inconsistent component or byte span changes the fixture.",
            identity=identity,
        )
        research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="A sibling claim remains only in the mission review index.",
            falsification_criteria="A full sibling lineage in the focal dossier changes scope.",
            identity=identity,
        )

        support_quote = "Atomic provenance Café 東京 supports the structural record."
        opposition_quote = "Atomic provenance résumé opposes the structural record."
        content = (
            "Préface calibrates multibyte offsets.\n"
            f"{support_quote}\n"
            f"{opposition_quote}\n"
            "Atomic provenance third candidate remains unassessed.\n"
        ).encode()
        snapshot = sources.import_bytes(
            mission_id=mission.id,
            content=content,
            original_label="review-dossier-evaluation.txt",
            media_type="text/plain",
            identity=identity,
        )
        support = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote=support_quote,
            stance=EvidenceStance.SUPPORTS,
            identity=identity,
        )
        opposition = _cite(
            evidence,
            mission_id=mission.id,
            claim_id=claim.id,
            snapshot_id=snapshot.snapshot_id,
            content=content,
            quote=opposition_quote,
            stance=EvidenceStance.OPPOSES,
            identity=identity,
        )

        foreign_mission = research.create_mission(
            title="FOREIGN-DOSSIER-MISSION-MUST-NOT-LEAK",
            objective="FOREIGN-DOSSIER-OBJECTIVE-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_question = research.add_question(
            mission_id=foreign_mission.id,
            text="FOREIGN-DOSSIER-QUESTION-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_claim = research.add_claim(
            mission_id=foreign_mission.id,
            question_id=foreign_question.id,
            statement="FOREIGN-DOSSIER-CLAIM-MUST-NOT-LEAK",
            falsification_criteria="FOREIGN-DOSSIER-CRITERIA-MUST-NOT-LEAK",
            identity=identity,
        )
        foreign_quote = "Atomic provenance FOREIGN-DOSSIER-TEXT-MUST-NOT-LEAK."
        foreign_content = f"{foreign_quote}\n".encode()
        foreign_snapshot = sources.import_bytes(
            mission_id=foreign_mission.id,
            content=foreign_content,
            original_label="FOREIGN-DOSSIER-SOURCE-MUST-NOT-LEAK.txt",
            media_type="text/plain",
            identity=identity,
        )
        foreign_evidence = _cite(
            evidence,
            mission_id=foreign_mission.id,
            claim_id=foreign_claim.id,
            snapshot_id=foreign_snapshot.snapshot_id,
            content=foreign_content,
            quote=foreign_quote,
            stance=EvidenceStance.CONTEXT,
            identity=identity,
        )

        lens_receipt = LensService(database).search(
            mission_id=mission.id,
            query="atomic provenance",
            bounds=LensBounds(max_results=1),
        )
        before = _state(database)
        service = ReviewDossierService(database)
        first = service.build_dossier(
            mission_id=mission.id,
            claim_id=claim.id,
            lens_receipt=lens_receipt,
        )
        second = service.build_dossier(
            mission_id=mission.id,
            claim_id=claim.id,
            lens_receipt=lens_receipt,
        )
        after = _state(database)
        first_bytes = _canonical_bytes(asdict(first))
        second_bytes = _canonical_bytes(asdict(second))

        nested_component_digests_valid = (
            first.mission_research_queue.queue_receipt_sha256
            == _receipt_digest(first.mission_research_queue, "queue_receipt_sha256")
            and first.claim_review.review_receipt_sha256
            == _receipt_digest(first.claim_review, "review_receipt_sha256")
            and first.claim_lineage.lineage_receipt_sha256
            == _receipt_digest(first.claim_lineage, "lineage_receipt_sha256")
            and first.lens_search.retrieval_receipt_sha256
            == _receipt_digest(first.lens_search, "retrieval_receipt_sha256")
        )
        expected_component_receipts = (
            first.mission_research_queue.queue_receipt_sha256,
            first.claim_review.review_receipt_sha256,
            first.claim_lineage.lineage_receipt_sha256,
            first.lens_search.retrieval_receipt_sha256,
            sha256(_canonical_bytes(asdict(first.lens_replay))).hexdigest(),
        )
        component_receipt_links_valid = (
            tuple(item.receipt_sha256 for item in first.component_receipts)
            == expected_component_receipts
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

        expected_quotes = {
            support.id: support_quote.encode("utf-8"),
            opposition.id: opposition_quote.encode("utf-8"),
        }
        review_by_id = {item.evidence_id: item for item in first.claim_review.evidence}
        lineage_by_id = {
            node.node_id: node.payload
            for node in first.claim_lineage.nodes
            if node.kind is ClaimLineageNodeKind.EVIDENCE
            and isinstance(node.payload, EvidenceLineageData)
        }
        accurate_citation_count = 0
        for evidence_id, quote_bytes in expected_quotes.items():
            review_item = review_by_id.get(evidence_id)
            lineage_item = lineage_by_id.get(evidence_id)
            if (
                review_item is not None
                and lineage_item is not None
                and review_item.snapshot_id == snapshot.snapshot_id
                and lineage_item.snapshot_id == snapshot.snapshot_id
                and content[review_item.start_byte : review_item.end_byte] == quote_bytes
                and content[lineage_item.start_byte : lineage_item.end_byte] == quote_bytes
                and review_item.quote_byte_length == len(quote_bytes)
                and lineage_item.quote_byte_length == len(quote_bytes)
                and review_item.quote_sha256 == sha256(quote_bytes).hexdigest()
                and lineage_item.quote_sha256 == sha256(quote_bytes).hexdigest()
                and lineage_item.quote.encode("utf-8") == quote_bytes
                and base64.b64decode(lineage_item.quote_utf8_base64, validate=True) == quote_bytes
            ):
                accurate_citation_count += 1

        accurate_lens_candidate_count = sum(
            candidate.snapshot_id == snapshot.snapshot_id
            and content[candidate.start_byte : candidate.end_byte]
            == candidate.quote.encode("utf-8")
            and base64.b64decode(candidate.quote_utf8_base64, validate=True)
            == candidate.quote.encode("utf-8")
            and candidate.quote_sha256 == sha256(candidate.quote.encode("utf-8")).hexdigest()
            for candidate in first.lens_search.candidates
        )
        crosscheck_count = len(fields(first.cross_checks))
        passing_crosscheck_count = sum(
            getattr(first.cross_checks, item.name) is True for item in fields(first.cross_checks)
        )
        foreign_values = (
            foreign_mission.id,
            foreign_mission.title,
            foreign_mission.objective,
            foreign_question.id,
            foreign_question.text,
            foreign_claim.id,
            foreign_claim.statement,
            foreign_claim.falsification_criteria,
            foreign_snapshot.source_id,
            foreign_snapshot.snapshot_id,
            "FOREIGN-DOSSIER-SOURCE-MUST-NOT-LEAK.txt",
            foreign_evidence.id,
            foreign_quote,
        )
        mission_isolation = first.mission_id == mission.id and not any(
            value.encode("utf-8") in first_bytes for value in foreign_values
        )
        lens_truncation_disclosed = (
            first.complete
            and not first.truncated
            and first.lens_retrieval_truncated
            and first.lens_search.truncated
            and first.lens_search.matching_candidate_count == 3
            and first.lens_search.result_count == 1
            and first.lens_search.omissions.matching_candidates_omitted_by_result_limit == 2
            and not first.semantic_boundary.lens_candidates_are_evidence
            and not first.semantic_boundary.lens_candidates_assessed_against_claim
        )
        unauthorized_mutation_count = int(before[0] != after[0]) + int(before[1] != after[1])

        return {
            "schema_version": "minerva.review-dossier-evaluation.v1",
            "algorithm": first.algorithm,
            "algorithm_version": first.algorithm_version,
            "component_order_valid": first.component_order == _COMPONENT_ORDER,
            "component_receipt_links_valid": component_receipt_links_valid,
            "nested_component_digests_valid": nested_component_digests_valid,
            "component_set_digest_valid": first.component_set_sha256
            == sha256(_canonical_bytes(component_frame)).hexdigest(),
            "dossier_receipt_digest_valid": first.dossier_receipt_sha256
            == _receipt_digest(first, "dossier_receipt_sha256"),
            "crosschecks_valid": passing_crosscheck_count == crosscheck_count,
            "citation_byte_accuracy_ppm": accurate_citation_count
            * 1_000_000
            // len(expected_quotes),
            "lens_candidate_byte_accuracy_ppm": accurate_lens_candidate_count
            * 1_000_000
            // first.lens_search.result_count,
            "determinism": first_bytes == second_bytes,
            "mission_isolation": mission_isolation,
            "lens_truncation_disclosed": lens_truncation_disclosed,
            "structural_completion_disclosed": first.complete and not first.truncated,
            "lens_candidate_boundary_preserved": (
                first.semantic_boundary.lens_association_is_operator_supplied
                and not first.semantic_boundary.lens_candidates_are_evidence
                and not first.semantic_boundary.creates_or_changes_research_state
            ),
            "unauthorized_mutation_count": unauthorized_mutation_count,
            "fixture_mission_count": 2,
            "fixture_claim_count": 3,
            "component_count": len(first.component_receipts),
            "crosscheck_count": crosscheck_count,
            "passing_crosscheck_count": passing_crosscheck_count,
            "expected_citation_count": len(expected_quotes),
            "accurate_citation_count": accurate_citation_count,
            "lens_matching_candidate_count": first.lens_search.matching_candidate_count,
            "lens_result_count": first.lens_search.result_count,
            "lens_omitted_candidate_count": (
                first.lens_search.omissions.matching_candidates_omitted_by_result_limit
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(_canonical_bytes(evaluate_review_dossier()).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
