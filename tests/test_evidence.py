from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, cast

import pytest

from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.evidence.service import EvidenceService


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


def test_exact_utf8_byte_quote_creates_resolvable_citation(lab: Lab) -> None:
    seed = lab.seed_claim()
    quote = "Café context remains uncertain."

    card = lab.cite(seed, quote, EvidenceStance.CONTEXT)
    ledger = lab.evidence.ledger_for_claim(seed.claim.id)

    assert card.snapshot_sha256 == seed.snapshot.sha256
    assert card.start_byte == seed.content.index(quote.encode("utf-8"))
    assert card.end_byte == card.start_byte + len(quote.encode("utf-8"))
    assert ledger[0].citation_id == card.id
    assert ledger[0].snapshot_sha256 == seed.snapshot.sha256
    assert ledger[0].source_label == seed.snapshot.original_label
    assert not ledger[0].withdrawn


def test_quote_must_match_exact_snapshot_bytes(lab: Lab) -> None:
    seed = lab.seed_claim()
    quote = "Evidence supports the claim."
    start = seed.content.index(quote.encode())

    with pytest.raises(IntegrityError) as caught:
        lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=start,
            end_byte=start + len(quote.encode()),
            quote="Evidence supposedly supports the claim.",
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert caught.value.code == "citation_quote_mismatch"
    assert lab.evidence.ledger_for_claim(seed.claim.id) == ()


def test_offsets_may_not_split_a_utf8_codepoint(lab: Lab) -> None:
    seed = lab.seed_claim(content="évidence".encode())

    with pytest.raises(IntegrityError) as caught:
        lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=1,
            end_byte=2,
            quote="x",
            stance=EvidenceStance.CONTEXT,
            identity=lab.identity,
        )

    assert caught.value.code == "citation_offsets_invalid"


@pytest.mark.parametrize(
    ("start", "end", "quote"),
    [
        (0, 0, ""),
        (-1, 1, "E"),
        (0, 10_000, "Evidence supports the claim."),
    ],
)
def test_empty_negative_and_out_of_range_spans_are_rejected(
    lab: Lab,
    start: int,
    end: int,
    quote: str,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=start,
            end_byte=end,
            quote=quote,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert caught.value.code in {"citation_offsets_invalid", "evidence_quote_invalid"}


def test_stance_must_be_a_domain_enum(lab: Lab) -> None:
    seed = lab.seed_claim()
    quote = "Evidence supports the claim."

    with pytest.raises(IntegrityError) as caught:
        lab.evidence.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=0,
            end_byte=len(quote.encode()),
            quote=quote,
            stance=cast(Any, "supports"),
            identity=lab.identity,
        )

    assert caught.value.code == "evidence_stance_invalid"


def test_supporting_and_opposing_evidence_remain_visible_together(lab: Lab) -> None:
    seed = lab.seed_claim()

    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    opposition = lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)
    ledger = lab.evidence.ledger_for_claim(seed.claim.id)

    assert [entry.evidence.id for entry in ledger] == [support.id, opposition.id]
    assert [entry.evidence.stance for entry in ledger] == [
        EvidenceStance.SUPPORTS,
        EvidenceStance.OPPOSES,
    ]


def test_withdrawal_is_separate_history_and_cannot_be_repeated(lab: Lab) -> None:
    seed = lab.seed_claim()
    card = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    withdrawal_id = lab.evidence.withdraw_evidence(
        evidence_id=card.id,
        reason="The observation was superseded by a corrected measurement.",
        identity=lab.identity,
    )
    entry = lab.evidence.ledger_for_claim(seed.claim.id)[0]

    assert withdrawal_id.startswith("wdr_")
    assert entry.withdrawn
    assert entry.withdrawal_reason == "The observation was superseded by a corrected measurement."
    assert entry.evidence == card
    with pytest.raises(ConflictError) as caught:
        lab.evidence.withdraw_evidence(
            evidence_id=card.id,
            reason="A second withdrawal must not rewrite history.",
            identity=lab.identity,
        )
    assert caught.value.code == "evidence_already_withdrawn"


def test_supersession_creates_a_new_card_linked_to_the_old_card(lab: Lab) -> None:
    seed = lab.seed_claim()
    original = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    replacement = lab.cite(
        seed,
        "Evidence opposes the claim.",
        EvidenceStance.OPPOSES,
        supersedes_evidence_id=original.id,
    )

    assert replacement.id != original.id
    assert replacement.supersedes_evidence_id == original.id
    assert [entry.evidence.id for entry in lab.evidence.ledger_for_claim(seed.claim.id)] == [
        original.id,
        replacement.id,
    ]


def test_supersession_cannot_cross_claim_or_mission(lab: Lab) -> None:
    first = lab.seed_claim(source_label="first.txt")
    second = lab.seed_claim(source_label="second.txt")
    original = lab.cite(first, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    with pytest.raises(IntegrityError) as caught:
        lab.cite(
            second,
            "Evidence opposes the claim.",
            EvidenceStance.OPPOSES,
            supersedes_evidence_id=original.id,
        )

    assert caught.value.code == "evidence_supersession_invalid"


def test_claim_and_snapshot_must_belong_to_submitted_mission(lab: Lab) -> None:
    first = lab.seed_claim(source_label="first.txt")
    second = lab.seed_claim(source_label="second.txt")
    quote = "Evidence supports the claim."

    with pytest.raises(NotFoundError) as wrong_snapshot:
        lab.evidence.add_evidence(
            mission_id=first.mission.id,
            claim_id=first.claim.id,
            snapshot_id=second.snapshot.snapshot_id,
            start_byte=0,
            end_byte=len(quote.encode()),
            quote=quote,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )
    with pytest.raises(NotFoundError) as wrong_claim:
        lab.evidence.add_evidence(
            mission_id=first.mission.id,
            claim_id=second.claim.id,
            snapshot_id=first.snapshot.snapshot_id,
            start_byte=0,
            end_byte=len(quote.encode()),
            quote=quote,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert wrong_snapshot.value.code == "snapshot_not_found"
    assert wrong_claim.value.code == "claim_not_found"


def test_audit_failure_rolls_back_evidence_card(lab: Lab) -> None:
    seed = lab.seed_claim()
    quote = "Evidence supports the claim."
    failing = EvidenceService(
        lab.database,
        audit=FailingAuditSink(lab.ids),
        clock=fixed_clock,
        id_factory=lab.ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        failing.add_evidence(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            snapshot_id=seed.snapshot.snapshot_id,
            start_byte=0,
            end_byte=len(quote.encode()),
            quote=quote,
            stance=EvidenceStance.SUPPORTS,
            identity=lab.identity,
        )

    assert lab.evidence.ledger_for_claim(seed.claim.id) == ()


def test_evidence_cards_are_append_only(lab: Lab) -> None:
    seed = lab.seed_claim()
    card = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE evidence_cards SET quote = ? WHERE id = ?",
            ("changed", card.id),
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute("DELETE FROM evidence_cards WHERE id = ?", (card.id,))


def test_citation_time_digest_survives_coordinated_snapshot_and_audit_rewrite(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    card = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    changed = seed.content[:-2] + b"!\n"
    changed_digest = sha256(changed).hexdigest()
    changed_audit = json.dumps(
        {
            "byte_length": len(changed),
            "encoding": "utf-8",
            "media_type": seed.snapshot.media_type,
            "sha256": changed_digest,
            "source_id": seed.snapshot.source_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    with lab.database.transaction() as connection:
        connection.execute("DROP TRIGGER snapshots_no_update")
        connection.execute("DROP TRIGGER audit_no_update")
        connection.execute(
            """
            UPDATE source_snapshots
            SET content = ?, sha256 = ?, byte_length = ?
            WHERE id = ?
            """,
            (changed, changed_digest, len(changed), seed.snapshot.snapshot_id),
        )
        connection.execute(
            """
            UPDATE audit_events SET details_json = ?
            WHERE event_type = 'source.snapshot.imported' AND entity_id = ?
            """,
            (changed_audit, seed.snapshot.snapshot_id),
        )

    with pytest.raises(IntegrityError) as caught:
        lab.evidence.ledger_for_claim(seed.claim.id)

    assert card.snapshot_sha256 == seed.snapshot.sha256
    assert caught.value.code == "citation_tampered"
