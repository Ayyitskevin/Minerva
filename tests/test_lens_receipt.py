from __future__ import annotations

import base64
import json
import socket
from collections.abc import Callable
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from typing import NoReturn, cast

import pytest

import minerva.core.db as db_module
import minerva.integrations.ai as ai_integrations
import minerva.lens.service as lens_service_module
from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.db import Database, latest_schema_version
from minerva.core.errors import IntegrityError
from minerva.core.operations import OperationsService
from minerva.core.types import ActorKind, IdentityContext
from minerva.integrations.lens_receipt import LensReceiptShapeError, parse_lens_receipt
from minerva.lens import (
    LensBounds,
    LensService,
    lens_receipt_verification_result,
    verify_lens_receipt,
)
from minerva.lens.models import LensCorpusFilter, LensSearchResult
from minerva.research.service import ResearchService
from minerva.sources.service import SourceService


def _envelope_bytes(receipt: LensSearchResult) -> bytes:
    return json.dumps(
        {"lens": asdict(receipt)},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _database_dump(database: Database) -> tuple[str, ...]:
    with database.read() as connection:
        return tuple(connection.iterdump())


def _recompute_receipt(receipt: LensSearchResult) -> LensSearchResult:
    provisional = replace(receipt, retrieval_receipt_sha256="")
    return replace(
        provisional,
        retrieval_receipt_sha256=lens_service_module._receipt_digest(provisional),
    )


def _self_consistent_label_edit(receipt: LensSearchResult) -> LensSearchResult:
    original = receipt.searched_snapshots[0]
    edited_label = "locally-edited-label.txt"
    edited_snapshot = replace(original, original_label=edited_label)
    snapshots = (edited_snapshot, *receipt.searched_snapshots[1:])
    candidates = tuple(
        replace(candidate, source_label=edited_label)
        if candidate.snapshot_id == original.snapshot_id
        else candidate
        for candidate in receipt.candidates
    )
    edited = replace(
        receipt,
        searched_snapshots=snapshots,
        candidates=candidates,
        snapshot_set_sha256=lens_service_module._snapshot_set_digest(
            receipt.mission_id,
            snapshots,
        ),
    )
    return _recompute_receipt(edited)


def test_parser_accepts_only_the_exact_cli_envelope(lab: Lab) -> None:
    seed = lab.seed_claim(content="Café 東京 is exact.\n".encode())
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="CAFÉ 東京",
    )

    assert parse_lens_receipt(_envelope_bytes(receipt)) == receipt
    assert parse_lens_receipt(_envelope_bytes(receipt).decode()) == receipt

    bare = json.dumps(asdict(receipt), ensure_ascii=False, separators=(",", ":"))
    with pytest.raises(LensReceiptShapeError):
        parse_lens_receipt(bare)

    envelope_with_extra = json.loads(_envelope_bytes(receipt))
    envelope_with_extra["unexpected"] = False
    with pytest.raises(LensReceiptShapeError):
        parse_lens_receipt(json.dumps(envelope_with_extra))

    receipt_with_extra = json.loads(_envelope_bytes(receipt))
    receipt_with_extra["lens"]["unexpected"] = False
    with pytest.raises(LensReceiptShapeError):
        parse_lens_receipt(json.dumps(receipt_with_extra))

    nested_extra = json.loads(_envelope_bytes(receipt))
    nested_extra["lens"]["candidates"][0]["score"]["unexpected"] = 1
    with pytest.raises(LensReceiptShapeError):
        parse_lens_receipt(json.dumps(nested_extra))

    for path in (
        ("bounds", "max_results"),
        ("semantic_boundary", "candidate_context_only"),
        ("candidates", 0, "score", "exact_phrase_match"),
    ):
        incomplete = json.loads(_envelope_bytes(receipt))
        target: object = incomplete["lens"]
        for component in path[:-1]:
            assert isinstance(target, dict | list)
            target = target[component]
        assert isinstance(target, dict)
        del target[path[-1]]
        with pytest.raises(LensReceiptShapeError):
            parse_lens_receipt(json.dumps(incomplete))


def test_compatibility_and_digest_failures_are_classified_after_self_digest(
    lab: Lab,
) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )

    stale = replace(receipt, algorithm_version="future")
    with pytest.raises(IntegrityError) as stale_failure:
        verify_lens_receipt(stale)
    assert stale_failure.value.code == "lens_receipt_digest_mismatch"

    cases = (
        (
            replace(receipt, schema_version="minerva.lens-search.future"),
            "lens_receipt_schema_unsupported",
        ),
        (
            replace(receipt, algorithm_version="future"),
            "lens_receipt_algorithm_unsupported",
        ),
        (
            replace(receipt, unicode_database_version="future"),
            "lens_receipt_runtime_incompatible",
        ),
    )
    for changed, expected_code in cases:
        with pytest.raises(IntegrityError) as caught:
            verify_lens_receipt(_recompute_receipt(changed))
        assert caught.value.code == expected_code

    with pytest.raises(IntegrityError) as malformed_digest:
        verify_lens_receipt(replace(receipt, retrieval_receipt_sha256="not-a-digest"))
    assert malformed_digest.value.code == "lens_receipt_invalid"


def test_self_consistent_receipt_semantic_mutations_fail_closed(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    candidate = receipt.candidates[0]
    snapshot = receipt.searched_snapshots[0]

    mutations: tuple[Callable[[LensSearchResult], LensSearchResult], ...] = (
        lambda item: replace(item, kind="not_candidate_context_search"),
        lambda item: replace(item, bounds=replace(item.bounds, max_results=0)),
        lambda item: replace(item, query_sha256="0" * 64),
        lambda item: replace(item, snapshot_set_sha256="0" * 64),
        lambda item: replace(
            item,
            corpus_filter=LensCorpusFilter(
                source_ids=(snapshot.source_id, snapshot.source_id),
                snapshot_ids=item.corpus_filter.snapshot_ids,
            ),
        ),
        lambda item: replace(
            item,
            searched_snapshots=(replace(snapshot, source_id="src_" + "f" * 32),),
        ),
        lambda item: replace(item, searched_corpus_bytes=item.searched_corpus_bytes + 1),
        lambda item: replace(
            item,
            omissions=replace(item.omissions, eligible_snapshot_count=-1),
        ),
        lambda item: replace(
            item,
            omissions=replace(
                item.omissions,
                snapshots_excluded_by_corpus_filter=1,
            ),
        ),
        lambda item: replace(item, result_count=item.result_count + 1),
        lambda item: replace(
            item,
            candidates=(replace(candidate, snapshot_id="snp_" + "f" * 32),),
        ),
        lambda item: replace(
            item,
            candidates=(replace(candidate, source_id="src_" + "f" * 32),),
        ),
        lambda item: replace(
            item,
            candidates=(replace(candidate, quote_utf8_base64="!!!!"),),
        ),
        lambda item: replace(
            item,
            candidates=(
                replace(
                    candidate,
                    score=replace(
                        candidate.score,
                        density_ppm=candidate.score.density_ppm + 1,
                    ),
                ),
            ),
        ),
    )

    for mutate in mutations:
        changed = _recompute_receipt(mutate(receipt))
        with pytest.raises(IntegrityError) as caught:
            verify_lens_receipt(changed)
        assert caught.value.code == "lens_receipt_invalid"


def test_producer_impossible_omission_arithmetic_fails_closed(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    service = LensService(lab.database)
    receipt = service.search(mission_id=seed.mission.id, query="matching")

    no_passages = _recompute_receipt(
        replace(
            receipt,
            matching_candidate_count=0,
            result_count=0,
            candidates=(),
            omissions=replace(
                receipt.omissions,
                empty_passages_excluded=0,
                nonmatching_passages_excluded=0,
                oversized_passages_omitted=0,
                oversized_passage_bytes_omitted=0,
                matching_candidates_omitted_by_result_limit=0,
            ),
        )
    )
    oversized_bytes_without_passage = _recompute_receipt(
        replace(
            receipt,
            omissions=replace(
                receipt.omissions,
                oversized_passage_bytes_omitted=1,
            ),
        )
    )
    empty_filter = service.search(
        mission_id=seed.mission.id,
        query="matching",
        source_ids=(),
        snapshot_ids=(),
    )
    bytes_without_eligible_snapshot = _recompute_receipt(
        replace(
            empty_filter,
            omissions=replace(
                empty_filter.omissions,
                eligible_corpus_bytes=1,
                omitted_corpus_bytes=1,
            ),
        )
    )
    bounded_seed = lab.seed_claim(content=b"matching\n" + b"x" * 40 + b"\n")
    bounded = service.search(
        mission_id=bounded_seed.mission.id,
        query="matching",
        bounds=LensBounds(max_quote_bytes=32),
    )
    assert bounded.omissions.oversized_passages_omitted == 1
    impossible_passage_bytes = _recompute_receipt(
        replace(
            bounded,
            omissions=replace(
                bounded.omissions,
                oversized_passage_bytes_omitted=bounded.searched_corpus_bytes,
            ),
        )
    )
    impossible_empty_filter = _recompute_receipt(
        replace(
            empty_filter,
            truncated=True,
            omissions=replace(
                empty_filter.omissions,
                snapshots_excluded_by_corpus_filter=0,
                eligible_snapshot_count=1,
                eligible_corpus_bytes=1,
                omitted_snapshot_count=1,
                omitted_corpus_bytes=1,
                corpus_byte_limit_reached=True,
            ),
        )
    )

    filter_seed = lab.seed_claim(content=b"matching one\n")
    lab.sources.import_bytes(
        mission_id=filter_seed.mission.id,
        content=b"matching two\n",
        original_label="second-filter-source.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    snapshot_filtered = service.search(
        mission_id=filter_seed.mission.id,
        query="matching",
        snapshot_ids=(filter_seed.snapshot.snapshot_id,),
        bounds=LensBounds(max_corpus_bytes=len(filter_seed.content)),
    )
    impossible_snapshot_filter_count = _recompute_receipt(
        replace(
            snapshot_filtered,
            truncated=True,
            omissions=replace(
                snapshot_filtered.omissions,
                snapshots_excluded_by_corpus_filter=0,
                eligible_snapshot_count=2,
                eligible_corpus_bytes=snapshot_filtered.searched_corpus_bytes + 1,
                omitted_snapshot_count=1,
                omitted_corpus_bytes=1,
                corpus_byte_limit_reached=True,
            ),
        )
    )

    corpus_seed = lab.seed_claim(content=b"matching\n")
    lab.sources.import_bytes(
        mission_id=corpus_seed.mission.id,
        content=b"x" * 100,
        original_label="oversized-next-source.txt",
        media_type="text/plain",
        identity=lab.identity,
    )
    corpus_limited = service.search(
        mission_id=corpus_seed.mission.id,
        query="matching",
        bounds=LensBounds(max_corpus_bytes=20),
    )
    assert corpus_limited.omissions.corpus_byte_limit_reached is True
    false_corpus_limit = _recompute_receipt(
        replace(
            corpus_limited,
            omissions=replace(
                corpus_limited.omissions,
                eligible_corpus_bytes=corpus_limited.searched_corpus_bytes + 1,
                omitted_corpus_bytes=1,
            ),
        )
    )

    full_span_seed = lab.seed_claim(content=b"a " * 16)
    full_span = service.search(
        mission_id=full_span_seed.mission.id,
        query="a",
    )
    assert full_span.candidates[0].start_byte == 0
    assert full_span.candidates[0].end_byte == full_span.searched_corpus_bytes
    impossible_omitted_match = _recompute_receipt(
        replace(
            full_span,
            matching_candidate_count=2,
            truncated=True,
            omissions=replace(
                full_span.omissions,
                matching_candidates_omitted_by_result_limit=1,
            ),
        )
    )

    for invalid in (
        no_passages,
        oversized_bytes_without_passage,
        bytes_without_eligible_snapshot,
        impossible_passage_bytes,
        impossible_empty_filter,
        impossible_snapshot_filter_count,
        false_corpus_limit,
        impossible_omitted_match,
    ):
        with pytest.raises(IntegrityError) as caught:
            verify_lens_receipt(invalid)
        assert caught.value.code == "lens_receipt_invalid"


def test_overlapping_candidate_spans_fail_closed(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"matching line\nmatching line\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    first, second = receipt.candidates
    assert first.snapshot_id == second.snapshot_id
    assert first.end_byte < second.start_byte
    quote_length = second.end_byte - second.start_byte
    overlapping_second = replace(
        second,
        start_byte=first.start_byte + 1,
        end_byte=first.start_byte + 1 + quote_length,
    )
    invalid = _recompute_receipt(replace(receipt, candidates=(first, overlapping_second)))

    with pytest.raises(IntegrityError) as caught:
        verify_lens_receipt(invalid)
    assert caught.value.code == "lens_receipt_invalid"


def test_candidate_nul_bytes_fail_closed(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    candidate = receipt.candidates[0]
    quote_bytes = b"\x00" + candidate.quote.encode("utf-8")[1:]
    changed_candidate = replace(
        candidate,
        quote=quote_bytes.decode("utf-8"),
        quote_utf8_base64=base64.b64encode(quote_bytes).decode("ascii"),
        quote_sha256=sha256(quote_bytes).hexdigest(),
    )
    invalid = _recompute_receipt(replace(receipt, candidates=(changed_candidate,)))

    with pytest.raises(IntegrityError) as caught:
        verify_lens_receipt(invalid)
    assert caught.value.code == "lens_receipt_invalid"


def test_python_boolean_integer_aliases_fail_strict_verification(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    receipt = LensService(lab.database).search(
        mission_id=seed.mission.id,
        query="matching",
    )
    candidate = receipt.candidates[0]
    cases = (
        replace(receipt, searched_snapshot_count=cast(int, True)),
        replace(
            receipt,
            candidates=(replace(candidate, rank=cast(int, True)),),
        ),
        replace(
            receipt,
            candidates=(
                replace(
                    candidate,
                    score=replace(
                        candidate.score,
                        matched_distinct_terms=cast(int, True),
                    ),
                ),
            ),
        ),
        replace(
            receipt,
            omissions=replace(
                receipt.omissions,
                snapshot_limit_reached=cast(bool, 0),
            ),
        ),
        replace(
            receipt,
            semantic_boundary=replace(
                receipt.semantic_boundary,
                candidate_context_only=cast(bool, 1),
            ),
        ),
    )

    for changed in cases:
        with pytest.raises(IntegrityError) as caught:
            verify_lens_receipt(_recompute_receipt(changed))
        assert caught.value.code == "lens_receipt_invalid"


def test_verify_and_replay_are_deterministic_read_only_and_provider_free(
    lab: Lab,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = lab.seed_claim(content="Préface.\nCafé 東京 evidence is exact.\n".encode())
    service = LensService(lab.database)
    receipt = service.search(mission_id=seed.mission.id, query="CAFÉ 東京")
    parsed = parse_lens_receipt(_envelope_bytes(receipt))
    before = _database_dump(lab.database)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("Lens receipt checks crossed a provider or network boundary")

    monkeypatch.setattr(ai_integrations, "candidate_provider", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    first_verification = lens_receipt_verification_result(parsed)
    second_verification = lens_receipt_verification_result(parsed)
    first_replay = service.replay_receipt(parsed)
    second_replay = service.replay_receipt(parsed)

    assert first_verification == second_verification
    assert first_verification.status == "verified"
    assert first_verification.searched_snapshot_content_verified is False
    assert first_verification.semantic_boundary.reads_research_database is False
    assert first_replay == second_replay
    assert first_replay.status == "reproduced"
    assert first_replay.exact_receipt_match is True
    assert first_replay.current_database_snapshot_matched is True
    assert first_replay.historical_corpus_replay is False
    assert first_replay.searched_snapshot_content_verified is True
    assert first_replay.semantic_boundary.reads_research_database is True
    assert first_replay.semantic_boundary.creates_evidence_or_inference is False
    assert _database_dump(lab.database) == before


def test_search_records_an_idempotent_unicode_normalization_fixed_point(lab: Lab) -> None:
    # U+00DF followed by U+0301 needs two changing NFKC/casefold applications:
    # "ß́" -> "sś" -> "sś". Lens v2 records only the stable representation.
    original_query = "ß́"
    seed = lab.seed_claim(content=f"{original_query} observation.\n".encode())
    service = LensService(lab.database)

    receipt = service.search(mission_id=seed.mission.id, query=original_query)

    assert receipt.algorithm_version == "2"
    assert receipt.normalized_query == "sś"
    assert lens_service_module._normalize_text(receipt.normalized_query) == receipt.normalized_query
    assert (
        service.search(
            mission_id=seed.mission.id,
            query=receipt.normalized_query,
        )
        == receipt
    )
    assert service.replay_receipt(parse_lens_receipt(_envelope_bytes(receipt))).status == (
        "reproduced"
    )


def test_receipt_refuses_a_producer_impossible_normalized_query(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"a context\n")
    service = LensService(lab.database)
    receipt = service.search(mission_id=seed.mission.id, query="a 2")
    impossible_query = "a ²"
    forged = _recompute_receipt(
        replace(
            receipt,
            normalized_query=impossible_query,
            query_terms=("a", "²"),
            query_sha256=sha256(impossible_query.encode()).hexdigest(),
        )
    )

    assert lens_service_module._normalize_text(impossible_query) == "a 2"
    with pytest.raises(IntegrityError) as caught:
        verify_lens_receipt(forged)
    assert caught.value.code == "lens_receipt_invalid"


def test_explicit_empty_filters_replay_without_expanding_the_corpus(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"private matching observation\n")
    service = LensService(lab.database)

    receipt = service.search(
        mission_id=seed.mission.id,
        query="matching",
        source_ids=(),
        snapshot_ids=(),
    )
    parsed = parse_lens_receipt(_envelope_bytes(receipt))

    assert parsed.corpus_filter.source_ids == ()
    assert parsed.corpus_filter.snapshot_ids == ()
    assert parsed.searched_snapshot_count == 0
    assert parsed.result_count == 0
    assert parsed.omissions.eligible_snapshot_count == 0
    assert service.replay_receipt(parsed).status == "reproduced"


def test_self_consistent_offline_edit_verifies_but_current_database_replay_refuses(
    lab: Lab,
) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    service = LensService(lab.database)
    receipt = service.search(mission_id=seed.mission.id, query="matching")
    edited = _self_consistent_label_edit(receipt)

    assert verify_lens_receipt(edited) == edited
    assert parse_lens_receipt(_envelope_bytes(edited)) == edited

    with pytest.raises(IntegrityError) as caught:
        service.replay_receipt(edited)

    assert caught.value.code == "lens_replay_mismatch"


def test_same_mission_appends_invalidate_exact_replay_even_when_filtered(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"first matching observation\n")
    service = LensService(lab.database)
    unfiltered = service.search(mission_id=seed.mission.id, query="matching")
    filtered = service.search(
        mission_id=seed.mission.id,
        query="matching",
        source_ids=(seed.snapshot.source_id,),
        snapshot_ids=(seed.snapshot.snapshot_id,),
    )

    lab.sources.import_bytes(
        mission_id=seed.mission.id,
        content=b"second matching observation\n",
        original_label="second.txt",
        media_type="text/plain",
        identity=lab.identity,
    )

    for receipt in (unfiltered, filtered):
        assert verify_lens_receipt(receipt) == receipt
        with pytest.raises(IntegrityError) as caught:
            service.replay_receipt(receipt)
        assert caught.value.code == "lens_replay_mismatch"


def test_foreign_mission_changes_do_not_invalidate_filtered_replay(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"mission scoped matching observation\n")
    service = LensService(lab.database)
    receipt = service.search(
        mission_id=seed.mission.id,
        query="matching",
        source_ids=(seed.snapshot.source_id,),
        snapshot_ids=(seed.snapshot.snapshot_id,),
    )

    foreign = lab.seed_claim(content=b"foreign matching observation\n")
    assert foreign.mission.id != seed.mission.id

    assert service.replay_receipt(receipt).status == "reproduced"


def test_snapshot_tamper_fails_replay_without_additional_mutation(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"exact matching observation\n")
    service = LensService(lab.database)
    receipt = service.search(mission_id=seed.mission.id, query="matching")
    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute(
            "UPDATE source_snapshots SET content = ? WHERE id = ?",
            (b"Z" * len(seed.content), seed.snapshot.snapshot_id),
        )
    tampered_state = _database_dump(lab.database)

    with pytest.raises(IntegrityError) as caught:
        service.replay_receipt(receipt)

    assert caught.value.code == "snapshot_tampered"
    assert _database_dump(lab.database) == tampered_state


def test_replay_requires_explicit_legacy_database_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert latest_schema_version() == 5
    migrations = db_module._migration_files()
    legacy = Database(tmp_path / "legacy-lens-replay-v4.db")
    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations[:-1])
    assert legacy.initialize() == 4

    ids = SequenceIds()
    identity = IdentityContext(
        actor_id="os-user:legacy-lens-replay",
        actor_kind=ActorKind.OS_USER,
        run_id=ids("run"),
        purpose="verify explicit migration before Lens receipt replay",
    )
    research = ResearchService(legacy, clock=fixed_clock, id_factory=ids)
    mission = research.create_mission(
        title="Legacy Lens replay mission",
        objective="Reproduce a receipt only against a current database contract.",
        identity=identity,
    )
    SourceService(legacy, clock=fixed_clock, id_factory=ids).import_bytes(
        mission_id=mission.id,
        content=b"legacy matching observation\n",
        original_label="legacy.txt",
        media_type="text/plain",
        identity=identity,
    )
    receipt = LensService(legacy).search(mission_id=mission.id, query="matching")

    monkeypatch.setattr(db_module, "_migration_files", lambda: migrations)
    with pytest.raises(IntegrityError) as required:
        LensService(legacy).replay_receipt(receipt)
    assert required.value.code == "database_migration_required"

    assert (
        OperationsService(legacy, clock=fixed_clock, id_factory=ids).initialize(
            identity=identity,
            refuse_existing=False,
        )
        == 5
    )
    assert LensService(legacy).replay_receipt(receipt).status == "reproduced"
