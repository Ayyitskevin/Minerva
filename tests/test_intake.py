from __future__ import annotations

import sqlite3
from typing import Any, Literal, cast

import pytest

from conftest import Lab, fixed_clock
from minerva.core.errors import MinervaError
from minerva.evidence import EvidenceStance
from minerva.intake import EvidenceIntakeService


def _service(lab: Lab, *, audit: object | None = None) -> EvidenceIntakeService:
    return EvidenceIntakeService(
        lab.database,
        audit=cast(Any, audit),
        clock=fixed_clock,
        id_factory=lab.ids,
    )


def _file(
    lab: Lab,
    preview,
    *,
    rank: int = 1,
    stance: EvidenceStance = EvidenceStance.SUPPORTS,
    service: EvidenceIntakeService | None = None,
):
    return (service or _service(lab)).file_evidence(
        mission_id=preview.mission_id,
        claim_id=preview.claim_id,
        snapshot_id=preview.snapshot_id,
        quote=preview.quote,
        candidate_rank=rank,
        expected_intake_preview_sha256=preview.intake_preview_sha256,
        expected_snapshot_sha256=preview.snapshot_sha256,
        expected_mission_audit_sequence=preview.mission_audit_sequence,
        stance=stance,
        identity=lab.identity,
    )


def _count(lab: Lab, table: Literal["audit_events", "evidence_cards"]) -> int:
    queries = {
        "audit_events": "SELECT COUNT(*) FROM audit_events",
        "evidence_cards": "SELECT COUNT(*) FROM evidence_cards",
    }
    with lab.database.read() as connection:
        return int(connection.execute(queries[table]).fetchone()[0])


def test_preview_locates_exact_multibyte_quote_without_writing(lab: Lab) -> None:
    content = "Préface.\nCafé 東京 evidence is byte exact.\n".encode()
    seed = lab.seed_claim(content=content)
    before_audit = _count(lab, "audit_events")

    preview = _service(lab).preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="Café 東京 evidence",
    )

    expected = "Café 東京 evidence".encode()
    start = content.index(expected)
    assert preview.schema_version == "minerva.evidence-intake-preview.v1"
    assert preview.kind == "exact_quote_candidates"
    assert preview.quote == "Café 東京 evidence"
    assert preview.quote_sha256
    assert preview.snapshot_sha256 == seed.snapshot.sha256
    assert preview.candidate_count == 1
    candidate = preview.candidates[0]
    assert candidate.rank == 1
    assert (candidate.start_byte, candidate.end_byte) == (start, start + len(expected))
    assert content[candidate.context_start_byte : candidate.context_end_byte].decode() == (
        candidate.context
    )
    assert candidate.context_start_byte <= candidate.start_byte
    assert candidate.context_end_byte >= candidate.end_byte
    assert len(preview.intake_preview_sha256) == 64
    assert _count(lab, "audit_events") == before_audit
    assert _count(lab, "evidence_cards") == 0


def test_preview_returns_every_overlapping_occurrence_in_byte_order(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"aaaa")

    preview = _service(lab).preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="aa",
    )

    assert [(item.rank, item.start_byte, item.end_byte) for item in preview.candidates] == [
        (1, 0, 2),
        (2, 1, 3),
        (3, 2, 4),
    ]


def test_utf8_candidate_boundaries_are_canonical_and_not_operator_supplied(lab: Lab) -> None:
    seed = lab.seed_claim(content="éé".encode())
    preview = _service(lab).preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="é",
    )

    assert [(item.start_byte, item.end_byte) for item in preview.candidates] == [(0, 2), (2, 4)]
    result = _file(lab, preview, rank=2)
    assert (result.evidence.start_byte, result.evidence.end_byte) == (2, 4)


@pytest.mark.parametrize(
    ("quote", "expected_code"),
    [
        ("absent", "intake_quote_not_found"),
        ("", "evidence_quote_invalid"),
    ],
)
def test_preview_refuses_unusable_quotes(lab: Lab, quote: str, expected_code: str) -> None:
    seed = lab.seed_claim(content=b"one precise observation")

    with pytest.raises(MinervaError) as caught:
        _service(lab).preview(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            quote=quote,
        )

    assert caught.value.code == expected_code


def test_preview_refuses_ambiguous_work_above_fixed_candidate_bound(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"a" * 101)

    with pytest.raises(MinervaError) as caught:
        _service(lab).preview(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            quote="a",
        )

    assert caught.value.code == "intake_candidate_limit"


def test_file_creates_one_evidence_card_and_exact_audit_atomically(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"first fact; second fact; second fact")
    service = _service(lab)
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="second fact",
    )

    result = _file(
        lab,
        preview,
        rank=2,
        stance=EvidenceStance.CONTEXT,
        service=service,
    )

    candidate = preview.candidates[1]
    assert result.schema_version == "minerva.evidence-intake.v1"
    assert result.status == "filed"
    assert result.candidate_rank == 2
    assert result.intake_preview_sha256 == preview.intake_preview_sha256
    assert result.evidence.start_byte == candidate.start_byte
    assert result.evidence.end_byte == candidate.end_byte
    assert result.evidence.quote == preview.quote
    assert result.evidence.stance is EvidenceStance.CONTEXT
    assert result.semantic_boundary.operator_supplied_stance
    assert not result.semantic_boundary.determines_truth_or_confidence
    with lab.database.read() as connection:
        events = list(
            connection.execute(
                "SELECT event_type, details_json FROM audit_events WHERE entity_id = ?",
                (result.evidence.id,),
            )
        )
    assert [(str(row["event_type"])) for row in events] == ["evidence.card.created"]
    assert preview.quote not in str(events[0]["details_json"])


def test_replay_and_stale_preview_fail_closed_without_duplicate(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    service = _service(lab)
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )
    _file(lab, preview, service=service)

    with pytest.raises(MinervaError) as replayed:
        _file(lab, preview, service=service)
    assert replayed.value.code == "mission_version_conflict"
    assert _count(lab, "evidence_cards") == 1

    current = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )
    with pytest.raises(MinervaError) as duplicate:
        _file(lab, current, service=service)
    assert duplicate.value.code == "intake_evidence_already_exists"
    assert _count(lab, "evidence_cards") == 1


def test_withdrawn_exact_duplicate_still_refuses_append_only_replay(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    service = _service(lab)
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )
    filed = _file(lab, preview, service=service)
    lab.evidence.withdraw_evidence(
        evidence_id=filed.evidence.id,
        reason="The operator withdrew this evaluation without erasing history.",
        identity=lab.identity,
    )
    current = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )

    with pytest.raises(MinervaError) as caught:
        _file(lab, current, service=service)

    assert caught.value.code == "intake_evidence_already_exists"
    assert _count(lab, "evidence_cards") == 1


def test_unrelated_mission_change_invalidates_preview_before_write(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    service = _service(lab)
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )
    lab.research.add_question(
        mission_id=seed.mission.id,
        text="What changed after review?",
        identity=lab.identity,
    )

    with pytest.raises(MinervaError) as caught:
        _file(lab, preview, service=service)

    assert caught.value.code == "mission_version_conflict"
    assert _count(lab, "evidence_cards") == 0


@pytest.mark.parametrize(
    ("override", "expected_code"),
    [
        ({"candidate_rank": 0}, "intake_confirmation_invalid"),
        ({"expected_intake_preview_sha256": "f" * 64}, "intake_preview_mismatch"),
        ({"expected_snapshot_sha256": "f" * 64}, "intake_confirmation_mismatch"),
        ({"expected_mission_audit_sequence": 0}, "mission_version_invalid"),
    ],
)
def test_invalid_confirmation_refuses_without_writing(
    lab: Lab,
    override: dict[str, object],
    expected_code: str,
) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    service = _service(lab)
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )
    arguments: dict[str, object] = {
        "mission_id": preview.mission_id,
        "claim_id": preview.claim_id,
        "snapshot_id": preview.snapshot_id,
        "quote": preview.quote,
        "candidate_rank": 1,
        "expected_intake_preview_sha256": preview.intake_preview_sha256,
        "expected_snapshot_sha256": preview.snapshot_sha256,
        "expected_mission_audit_sequence": preview.mission_audit_sequence,
        "stance": EvidenceStance.SUPPORTS,
        "identity": lab.identity,
    }
    arguments.update(override)

    with pytest.raises(MinervaError) as caught:
        service.file_evidence(**cast(Any, arguments))

    assert caught.value.code == expected_code
    assert _count(lab, "evidence_cards") == 0


def test_foreign_claim_and_snapshot_are_not_cross_scoped(lab: Lab) -> None:
    first = lab.seed_claim(content=b"first observation")
    second = lab.seed_claim(content=b"second observation")

    with pytest.raises(MinervaError) as claim_error:
        _service(lab).preview(
            mission_id=first.mission.id,
            claim_id=second.claim.id,
            snapshot_id=first.snapshot.snapshot_id,
            quote="first",
        )
    assert claim_error.value.code == "claim_not_found"

    with pytest.raises(MinervaError) as snapshot_error:
        _service(lab).preview(
            mission_id=first.mission.id,
            claim_id=first.claim.id,
            snapshot_id=second.snapshot.snapshot_id,
            quote="second",
        )
    assert snapshot_error.value.code == "snapshot_not_found"


@pytest.mark.parametrize(
    ("field", "expected_code"),
    (("claim", "claim_not_found"), ("snapshot", "snapshot_not_found")),
)
def test_unavailable_objects_fail_closed(
    lab: Lab,
    field: str,
    expected_code: str,
) -> None:
    seed = lab.seed_claim(content=b"one observation")
    claim_id = "clm_" + "f" * 32 if field == "claim" else seed.claim.id
    snapshot_id = "snp_" + "f" * 32 if field == "snapshot" else seed.snapshot.snapshot_id

    with pytest.raises(MinervaError) as caught:
        _service(lab).preview(
            mission_id=seed.mission.id,
            claim_id=claim_id,
            snapshot_id=snapshot_id,
            quote="observation",
        )

    assert caught.value.code == expected_code


class _SilentAudit:
    def ensure_run(self, _connection: sqlite3.Connection, _identity: object) -> None:
        return None

    def record(self, _connection: sqlite3.Connection, **_kwargs: object) -> str:
        return "aud_" + "f" * 32


def test_missing_audit_postcondition_rolls_back_evidence(lab: Lab) -> None:
    seed = lab.seed_claim(content=b"one exact observation")
    service = _service(lab, audit=_SilentAudit())
    preview = service.preview(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        snapshot_id=seed.snapshot.snapshot_id,
        quote="exact observation",
    )

    with pytest.raises(MinervaError) as caught:
        _file(lab, preview, service=service)

    assert caught.value.code == "intake_audit_invalid"
    assert _count(lab, "evidence_cards") == 0
