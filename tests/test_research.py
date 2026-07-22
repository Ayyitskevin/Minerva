from __future__ import annotations

import sqlite3
from collections.abc import Mapping

import pytest

from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError
from minerva.core.types import IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.research.models import CitationStatus, ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import ResearchService


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


def test_claim_records_nonempty_falsification_criteria_and_initial_version(lab: Lab) -> None:
    seed = lab.seed_claim()

    stored = lab.research.get_claim(seed.claim.id)

    assert stored.falsification_criteria == (
        "An exact opposing observation would falsify the proposition."
    )
    assert stored.status is ClaimStatus.OPEN
    assert stored.version == 1
    assert stored.etag.endswith('-v1"')


def test_claim_without_falsification_criteria_is_rejected_without_audit(lab: Lab) -> None:
    mission = lab.research.create_mission(
        title="Falsifiability mission",
        objective="Claims must say what observation could disprove them.",
        identity=lab.identity,
    )
    question = lab.research.add_question(
        mission_id=mission.id,
        text="What would disprove the proposed claim?",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_claim(
            mission_id=mission.id,
            question_id=question.id,
            statement="An unfalsifiable statement.",
            falsification_criteria="   ",
            identity=lab.identity,
        )

    assert caught.value.code == "falsification_criteria_required"
    assert lab.research.list_claims(mission.id) == ()
    with lab.database.read() as connection:
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM audit_events
            WHERE event_type = 'research.claim.created' AND mission_id = ?
            """,
                (mission.id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "status",
    [
        ClaimStatus.PROVISIONALLY_SUPPORTED,
        ClaimStatus.CONTESTED,
        ClaimStatus.UNSUPPORTED,
    ],
)
def test_evidentiary_claim_status_requires_active_evidence(
    lab: Lab,
    status: ClaimStatus,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        lab.research.set_claim_status(
            claim_id=seed.claim.id,
            status=status,
            reason="A workflow label cannot substitute for active evidence.",
            expected_version=1,
            identity=lab.identity,
        )

    assert caught.value.code == "claim_status_evidence_required"
    current = lab.research.get_claim(seed.claim.id)
    assert current.status is ClaimStatus.OPEN
    assert current.version == 1
    with lab.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events "
                "WHERE event_type = 'research.claim.status_changed'"
            ).fetchone()[0]
            == 0
        )


def test_claim_status_changes_append_versions_and_reject_stale_or_noop_updates(
    lab: Lab,
) -> None:
    seed = lab.seed_claim()
    lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.cite(seed, "Evidence opposes the claim.", EvidenceStance.OPPOSES)

    changed = lab.research.set_claim_status(
        claim_id=seed.claim.id,
        status=ClaimStatus.CONTESTED,
        reason="Both supporting and opposing observations are recorded.",
        expected_version=1,
        identity=lab.identity,
    )

    assert changed.version == 2
    assert changed.status is ClaimStatus.CONTESTED
    assert changed.etag.endswith('-v2"')
    assert lab.research.get_claim(seed.claim.id) == changed

    with pytest.raises(ConflictError) as stale:
        lab.research.set_claim_status(
            claim_id=seed.claim.id,
            status=ClaimStatus.INCONCLUSIVE,
            reason="This request used a stale version.",
            expected_version=1,
            identity=lab.identity,
        )
    with pytest.raises(ConflictError) as unchanged:
        lab.research.set_claim_status(
            claim_id=seed.claim.id,
            status=ClaimStatus.CONTESTED,
            reason="This status is already current.",
            expected_version=2,
            identity=lab.identity,
        )

    assert stale.value.code == "claim_version_conflict"
    assert unchanged.value.code == "claim_status_unchanged"
    with lab.database.read() as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM claim_status_events WHERE claim_id = ? ORDER BY version",
                (seed.claim.id,),
            )
        ]
    assert versions == [1, 2]


def test_claim_and_status_history_are_append_only(lab: Lab) -> None:
    seed = lab.seed_claim()

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE claims SET statement = ? WHERE id = ?",
            ("rewritten", seed.claim.id),
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE claim_status_events SET reason = ? WHERE claim_id = ?",
            ("rewritten", seed.claim.id),
        )


def test_material_finding_requires_and_retains_exact_citations(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)

    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The source directly asserts support for the proposition.",
        statement_kind=StatementKind.SOURCE_ASSERTION,
        status=FindingStatus.SUPPORTED,
        uncertainty="One source may not generalize.",
        evidence_ids=(support.id, support.id),
        identity=lab.identity,
    )

    assert finding.evidence_ids == (support.id,)
    assert lab.research.list_findings(seed.mission.id) == (finding,)


@pytest.mark.parametrize(
    "kind",
    [
        StatementKind.OBSERVED_FACT,
        StatementKind.SOURCE_ASSERTION,
        StatementKind.AGENT_INFERENCE,
        StatementKind.CALCULATION,
        StatementKind.RECOMMENDATION,
    ],
)
def test_each_material_statement_class_rejects_missing_citations(
    lab: Lab,
    kind: StatementKind,
) -> None:
    seed = lab.seed_claim()

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="This material statement is not cited.",
            statement_kind=kind,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="",
            evidence_ids=(),
            identity=lab.identity,
        )

    assert caught.value.code == "finding_citation_required"


@pytest.mark.parametrize(
    "kind",
    [StatementKind.ASSUMPTION, StatementKind.UNRESOLVED_QUESTION],
)
def test_explicitly_non_evidentiary_findings_may_remain_uncited(
    lab: Lab,
    kind: StatementKind,
) -> None:
    seed = lab.seed_claim()

    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        statement="This statement is explicitly labeled as non-evidentiary.",
        statement_kind=kind,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="It remains unverified.",
        evidence_ids=(),
        identity=lab.identity,
    )

    assert finding.statement_kind is kind
    assert finding.evidence_ids == ()


def test_finding_citation_must_evaluate_its_linked_claim(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    second_question = lab.research.add_question(
        mission_id=seed.mission.id,
        text="Does a different proposition hold?",
        identity=lab.identity,
    )
    second_claim = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=second_question.id,
        statement="A different proposition is supported.",
        falsification_criteria="An opposing observation would falsify it.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=second_claim.id,
            statement="This citation evaluates the wrong claim.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="",
            evidence_ids=(support.id,),
            identity=lab.identity,
        )

    assert caught.value.code == "finding_citation_scope_invalid"


def test_withdrawn_evidence_cannot_support_a_new_finding(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="The observation was withdrawn after review.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="A withdrawn observation cannot support this finding.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.UNSUPPORTED,
            uncertainty="",
            evidence_ids=(support.id,),
            identity=lab.identity,
        )

    assert caught.value.code == "citation_withdrawn"


def test_withdrawn_citation_invalidates_finding_provenance_on_read(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="This operator-recorded finding depends on active provenance.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(support.id,),
        identity=lab.identity,
    )

    lab.evidence.withdraw_evidence(
        evidence_id=support.id,
        reason="Review invalidated the cited observation.",
        identity=lab.identity,
    )

    listed = lab.research.list_findings(seed.mission.id)
    assert listed[0].id == finding.id
    assert listed[0].status is FindingStatus.SUPPORTED
    assert listed[0].citation_status is CitationStatus.WITHDRAWN


def test_failing_finding_audit_rolls_back_finding_and_links(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    failing = ResearchService(
        lab.database,
        audit=FailingAuditSink(lab.ids),
        clock=fixed_clock,
        id_factory=lab.ids,
    )

    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        failing.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="This finding must roll back with its failed audit.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="",
            evidence_ids=(support.id,),
            identity=lab.identity,
        )

    assert lab.research.list_findings(seed.mission.id) == ()
    with lab.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM finding_citations").fetchone()[0] == 0


def test_findings_and_citation_links_are_append_only(lab: Lab) -> None:
    seed = lab.seed_claim()
    support = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="An immutable evidence-backed finding.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(support.id,),
        identity=lab.identity,
    )

    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "UPDATE findings SET statement = ? WHERE id = ?",
            ("rewritten", finding.id),
        )
    with (
        pytest.raises(sqlite3.IntegrityError, match="append-only"),
        lab.database.transaction() as connection,
    ):
        connection.execute(
            "DELETE FROM finding_citations WHERE finding_id = ?",
            (finding.id,),
        )
