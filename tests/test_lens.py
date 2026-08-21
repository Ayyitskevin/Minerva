from __future__ import annotations

import base64
import json
import socket
import sqlite3
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

import minerva.core.db as db_module
import minerva.integrations.ai as ai_integrations
from conftest import Lab, SequenceIds, fixed_clock
from minerva.assist.adoption import AdoptionService
from minerva.assist.models import FindingCandidate, ModelProvider, ProviderSelection
from minerva.assist.service import AssistanceService
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError, NotFoundError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.lens import LensBounds, LensService
from minerva.research.models import FindingStatus, StatementKind
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def test_identical_inputs_produce_identical_utf8_receipts(lab: Lab) -> None:
    content = "Préface.\nCafé 東京 preserves exact provenance.\n".encode()
    seed = lab.seed_claim(content=content)
    service = LensService(lab.database)

    first = service.search(mission_id=seed.mission.id, query="  CAFÉ\t東京  ")
    second = service.search(mission_id=seed.mission.id, query="café 東京")

    assert first == second
    assert _canonical_bytes(asdict(first)) == _canonical_bytes(asdict(second))
    assert first.normalized_query == "café 東京"
    assert first.query_sha256 == sha256("café 東京".encode()).hexdigest()
    receipt_payload = asdict(first)
    receipt_digest = receipt_payload.pop("retrieval_receipt_sha256")
    assert receipt_digest == sha256(_canonical_bytes(receipt_payload)).hexdigest()
    assert first.result_count == 1
    candidate = first.candidates[0]
    quoted = base64.b64decode(candidate.quote_utf8_base64, validate=True)
    assert quoted == candidate.quote.encode()
    assert content[candidate.start_byte : candidate.end_byte] == quoted
    assert candidate.quote == "Café 東京 preserves exact provenance."
    assert candidate.quote_sha256 == sha256(quoted).hexdigest()
    assert candidate.stance == "unassessed"
    assert candidate.evidence_status == "candidate_only"
    assert first.semantic_boundary.creates_evidence is False
    assert first.semantic_boundary.requires_separate_explicit_evidence_adoption is True


def test_scoring_and_total_tie_break_are_stable(lab: Lab) -> None:
    seed = lab.seed_claim(content=(b"alpha beta\nalpha middle beta\nalpha only\nalpha beta\n"))
    second = lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"alpha beta\n",
        original_label="second.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    result = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="alpha beta",
    )

    assert [candidate.rank for candidate in result.candidates] == [1, 2, 3, 4, 5]
    assert [candidate.score.exact_phrase_match for candidate in result.candidates[:3]] == [
        True,
        True,
        True,
    ]
    exact = [candidate for candidate in result.candidates if candidate.score.exact_phrase_match]
    assert [(candidate.snapshot_id, candidate.start_byte) for candidate in exact] == [
        (seed.snapshot.snapshot_id, 0),
        (seed.snapshot.snapshot_id, len(b"alpha beta\nalpha middle beta\nalpha only\n")),
        (second.snapshot_id, 0),
    ]
    assert result.candidates[3].quote == "alpha middle beta"
    assert result.candidates[4].quote == "alpha only"
    assert result.candidates[0].why == (
        "exact query phrase; 2/2 distinct query terms; 2 total term occurrences; "
        "density 1000000 ppm."
    )


def test_mission_and_explicit_corpus_filters_fail_closed(lab: Lab) -> None:
    first = lab.seed_claim(content=b"mission one token\n")
    same_mission_other = lab.sources.import_bytes(
        mission_id=first.mission.id,
        content=b"same mission other token\n",
        original_label="other.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    second = lab.seed_claim(content=b"mission two secret token\n")
    service = LensService(lab.database)

    scoped = service.search(mission_id=first.mission.id, query="token")

    assert {candidate.mission_id for candidate in scoped.candidates} == {first.mission.id}
    assert all("secret" not in candidate.quote for candidate in scoped.candidates)
    filtered = service.search(
        mission_id=first.mission.id,
        query="token",
        source_ids=(first.snapshot.source_id,),
        snapshot_ids=(first.snapshot.snapshot_id,),
    )
    assert filtered.result_count == 1
    assert filtered.snapshot_set_sha256 != scoped.snapshot_set_sha256
    empty_intersection = service.search(
        mission_id=first.mission.id,
        query="token",
        source_ids=(first.snapshot.source_id,),
        snapshot_ids=(same_mission_other.snapshot_id,),
    )
    assert empty_intersection.result_count == 0
    assert empty_intersection.searched_snapshot_count == 0

    failures: list[IntegrityError] = []
    for source_ids, snapshot_ids in (
        ((second.snapshot.source_id,), None),
        (("src_" + "f" * 32,), None),
        (None, (second.snapshot.snapshot_id,)),
        (None, ("snp_" + "f" * 32,)),
    ):
        with pytest.raises(IntegrityError) as caught:
            service.search(
                mission_id=first.mission.id,
                query="token",
                source_ids=source_ids,
                snapshot_ids=snapshot_ids,
            )
        failures.append(caught.value)
    assert {error.code for error in failures} == {"lens_corpus_filter_invalid"}
    assert len({error.public_message for error in failures}) == 1


def test_bounds_report_every_omission_and_truncation(lab: Lab) -> None:
    first = lab.seed_claim(content=b"match one\n" + b"match " + b"x" * 40 + b"\n")
    lab.sources.import_bytes(
        mission_id=first.mission.id,
        content=b"match two\n",
        original_label="second.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    quote_bounded = LensService(lab.database).search(
        mission_id=first.mission.id,
        query="match",
        bounds=LensBounds(
            max_results=1, max_snapshots=2, max_corpus_bytes=1_000, max_quote_bytes=32
        ),
    )

    assert quote_bounded.truncated is True
    assert quote_bounded.matching_candidate_count == 2
    assert quote_bounded.result_count == 1
    assert quote_bounded.omissions.matching_candidates_omitted_by_result_limit == 1
    assert quote_bounded.omissions.oversized_passages_omitted == 1
    assert quote_bounded.omissions.oversized_passage_bytes_omitted == len(b"match " + b"x" * 40)
    assert quote_bounded.omissions.omitted_snapshot_count == 0

    snapshot_bounded = LensService(lab.database).search(
        mission_id=first.mission.id,
        query="match",
        bounds=LensBounds(
            max_results=10, max_snapshots=1, max_corpus_bytes=1_000, max_quote_bytes=100
        ),
    )
    assert snapshot_bounded.searched_snapshot_count == 1
    assert snapshot_bounded.omissions.snapshot_limit_reached is True
    assert snapshot_bounded.omissions.omitted_snapshot_count == 1
    assert snapshot_bounded.omissions.omitted_corpus_bytes == len(b"match two\n")

    byte_bounded = LensService(lab.database).search(
        mission_id=first.mission.id,
        query="match",
        bounds=LensBounds(
            max_results=10,
            max_snapshots=2,
            max_corpus_bytes=len(first.content),
            max_quote_bytes=100,
        ),
    )
    assert byte_bounded.searched_snapshot_count == 1
    assert byte_bounded.omissions.corpus_byte_limit_reached is True
    assert byte_bounded.omissions.omitted_snapshot_count == 1


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "!!!",
        "word\x00other",
        "\ud800",
        "a" * 513,
        " ".join(f"term{index}" for index in range(33)),
    ],
)
def test_hostile_queries_are_rejected(lab: Lab, query: str) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        LensService(lab.database).search(mission_id=seed.mission.id, query=query)

    assert caught.value.code == "lens_query_invalid"


@pytest.mark.parametrize(
    "bounds",
    [
        LensBounds(max_results=0),
        LensBounds(max_results=True),
        LensBounds(max_results=101),
        LensBounds(max_snapshots=0),
        LensBounds(max_snapshots=201),
        LensBounds(max_corpus_bytes=0),
        LensBounds(max_corpus_bytes=67_108_865),
        LensBounds(max_quote_bytes=31),
        LensBounds(max_quote_bytes=4_097),
    ],
)
def test_invalid_bounds_are_rejected(lab: Lab, bounds: LensBounds) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        LensService(lab.database).search(
            mission_id=seed.mission.id,
            query="evidence",
            bounds=bounds,
        )

    assert caught.value.code == "lens_bounds_invalid"


def test_hostile_filter_and_sql_shaped_query_are_inert(lab: Lab) -> None:
    first = lab.seed_claim(content=b"safe token only\n")
    second = lab.seed_claim(content=b"foreign token should not escape\n")
    service = LensService(lab.database)

    result = service.search(
        mission_id=first.mission.id,
        query="token' OR 1=1 --",
    )
    assert result.result_count == 1
    assert result.candidates[0].mission_id == first.mission.id
    assert second.mission.id not in _canonical_bytes(asdict(result)).decode()

    too_many = tuple("src_" + f"{index:032x}" for index in range(201))
    with pytest.raises(IntegrityError) as caught:
        service.search(
            mission_id=first.mission.id,
            query="token",
            source_ids=too_many,
        )
    assert caught.value.code == "lens_corpus_filter_invalid"

    with pytest.raises(IntegrityError) as malformed:
        service.search(
            mission_id=first.mission.id,
            query="token",
            source_ids=42,  # type: ignore[arg-type]
        )
    assert malformed.value.code == "lens_corpus_filter_invalid"


def test_final_bare_carriage_return_remains_in_exact_span(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"match one\r")

    result = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="match",
    )

    assert result.candidates[0].quote == "match one\r"
    assert result.candidates[0].start_byte == 0
    assert result.candidates[0].end_byte == len(seed.content)


def test_search_is_read_only_and_invokes_no_provider(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim()
    before_dump = _database_dump(lab.database)
    before_bytes = lab.database.path.read_bytes()

    def provider_forbidden(_: ModelProvider) -> object:
        raise AssertionError("Lens must not construct a model provider")

    def network_forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Lens must not construct a network socket")

    monkeypatch.setattr(ai_integrations, "candidate_provider", provider_forbidden)
    monkeypatch.setattr(socket, "socket", network_forbidden)

    result = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="evidence claim",
    )

    assert result.result_count == 2
    assert _database_dump(lab.database) == before_dump
    assert lab.database.path.read_bytes() == before_bytes


def test_source_deletion_is_blocked_and_downstream_retractions_do_not_hide_snapshot(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The cited observation supports the bounded claim.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="The source is bounded.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    assistance = AssistanceService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    preview = assistance.preview_finding_candidates(
        claim_id=seed.claim.id,
        selection=ProviderSelection(ModelProvider.OPENAI, "test-model", "test"),
        max_candidates=1,
        max_output_tokens=256,
    )
    adoption = AdoptionService(lab.database, clock=fixed_clock, id_factory=lab.ids)
    inference = adoption.adopt_inference(
        preview=preview,
        expected_request_sha256=preview.request_sha256,
        candidate_index=0,
        candidate=FindingCandidate(
            statement="A reviewed candidate inference.",
            statement_kind=StatementKind.AGENT_INFERENCE,
            uncertainty="It remains model-authored.",
            evidence_ids=(evidence.id,),
        ),
        response_sha256=sha256(b"fake response").hexdigest(),
        identity=lab.identity,
    )
    service = LensService(lab.database)
    before = service.search(mission_id=seed.mission.id, query="evidence")

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute("DELETE FROM sources WHERE id = ?", (seed.snapshot.source_id,))
    with (
        pytest.raises(sqlite3.IntegrityError, match="immutable"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "DELETE FROM source_snapshots WHERE id = ?",
            (seed.snapshot.snapshot_id,),
        )

    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The card no longer stands; the source bytes remain.",
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=finding.id,
        reason="The finding is no longer asserted.",
        identity=lab.identity,
    )
    adoption.retract_inference(
        inference_id=inference.id,
        reason="The adopted inference is no longer asserted.",
        identity=lab.identity,
    )

    after = service.search(mission_id=seed.mission.id, query="evidence")
    assert after == before
    assert after.omissions.source_retraction_metadata == "not_modeled"


def test_tampered_snapshot_fails_integrity_verification(lab: Lab) -> None:
    seed = lab.seed_claim()
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (b"Z" * len(seed.content), seed.snapshot.snapshot_id),
        )

    with pytest.raises(IntegrityError) as caught:
        LensService(lab.database).search(
            mission_id=seed.mission.id,
            query="tampered",
        )

    assert caught.value.code == "snapshot_tampered"


def test_missing_mission_and_pre_v5_database_fail_before_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy_path = tmp_path / "legacy-v4.db"
    legacy = Database(legacy_path)
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4

    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-test",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify legacy Lens migration refusal",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy mission",
        objective="Verify explicit migration before Lens search.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy corpus text\n",
        original_label="legacy.txt",
        media_type="text/plain",
        identity=identity,
    )

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as caught:
        LensService(legacy).search(mission_id=mission.id, query="legacy")
    assert caught.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    assert LensService(legacy).search(mission_id=mission.id, query="legacy").result_count == 1

    with pytest.raises(NotFoundError) as missing:
        LensService(legacy).search(mission_id="mis_" + "f" * 32, query="legacy")
    assert missing.value.code == "mission_not_found"
