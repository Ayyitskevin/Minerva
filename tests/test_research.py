from __future__ import annotations

import sqlite3
from collections.abc import Mapping

import pytest

from conftest import Lab, SequenceIds, fixed_clock
from minerva.core.audit import AuditRecorder
from minerva.core.errors import ConflictError, IntegrityError, NotFoundError
from minerva.core.types import IdentityContext
from minerva.evidence.models import EvidenceStance
from minerva.research.models import CitationStatus, ClaimStatus, FindingStatus, StatementKind
from minerva.research.service import MAX_FINDING_CITATIONS, ResearchService

_COUNT_QUERIES = {
    "audit_events": "SELECT COUNT(*) FROM audit_events",
    "claims": "SELECT COUNT(*) FROM claims",
    "claim_status_events": "SELECT COUNT(*) FROM claim_status_events",
    "finding_citations": "SELECT COUNT(*) FROM finding_citations",
    "findings": "SELECT COUNT(*) FROM findings",
    "research_runs": "SELECT COUNT(*) FROM research_runs",
}


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


def test_claim_creation_honors_mission_audit_freshness_without_partial_state(lab: Lab) -> None:
    seed = lab.seed_claim()
    expected_sequence = lab.research.get_mission_audit_sequence(seed.mission.id)

    created = lab.research.add_claim(
        mission_id=seed.mission.id,
        question_id=seed.question.id,
        statement="A second falsifiable proposition.",
        falsification_criteria="An exact counterexample would falsify it.",
        identity=lab.identity,
        expected_mission_audit_sequence=expected_sequence,
    )

    assert created.version == 1
    assert lab.research.get_mission_audit_sequence(seed.mission.id) > expected_sequence
    with lab.database.read() as connection:
        state_before_replay = tuple(
            int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0])
            for table in ("claims", "claim_status_events", "audit_events", "research_runs")
        )

    with pytest.raises(ConflictError) as caught:
        lab.research.add_claim(
            mission_id=seed.mission.id,
            question_id=seed.question.id,
            statement="A replay must not create this proposition.",
            falsification_criteria="The stale mission version is sufficient to refuse it.",
            identity=lab.identity,
            expected_mission_audit_sequence=expected_sequence,
        )

    assert caught.value.code == "mission_version_conflict"
    with lab.database.read() as connection:
        state_after_replay = tuple(
            int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0])
            for table in ("claims", "claim_status_events", "audit_events", "research_runs")
        )
    assert state_after_replay == state_before_replay


def test_finding_creation_honors_mission_audit_freshness_without_partial_state(lab: Lab) -> None:
    seed = lab.seed_claim()
    expected_sequence = lab.research.get_mission_audit_sequence(seed.mission.id)

    created = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The benchmark conditions remain an explicit assumption.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="The source does not record benchmark conditions.",
        evidence_ids=(),
        identity=lab.identity,
        expected_mission_audit_sequence=expected_sequence,
    )

    assert created.evidence_ids == ()
    assert lab.research.get_mission_audit_sequence(seed.mission.id) > expected_sequence
    with lab.database.read() as connection:
        state_before_replay = tuple(
            int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0])
            for table in ("findings", "finding_citations", "audit_events", "research_runs")
        )

    with pytest.raises(ConflictError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="A replay must not create this finding.",
            statement_kind=StatementKind.ASSUMPTION,
            status=FindingStatus.INCONCLUSIVE,
            uncertainty="This request is stale.",
            evidence_ids=(),
            identity=lab.identity,
            expected_mission_audit_sequence=expected_sequence,
        )

    assert caught.value.code == "mission_version_conflict"
    with lab.database.read() as connection:
        state_after_replay = tuple(
            int(connection.execute(_COUNT_QUERIES[table]).fetchone()[0])
            for table in ("findings", "finding_citations", "audit_events", "research_runs")
        )
    assert state_after_replay == state_before_replay


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


def test_finding_citation_limit_is_enforced_by_the_service(lab: Lab) -> None:
    """The citation bound belongs to the service, not only the REST adapter.

    A CLI operator could otherwise create findings whose citations exceed the
    synthesis reference limit, permanently blocking the mission's brief export
    because findings are append-only.
    """

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    too_many = tuple(f"{evidence.id[:-4]}{index:04x}" for index in range(MAX_FINDING_CITATIONS + 1))
    assert len(set(too_many)) == MAX_FINDING_CITATIONS + 1

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="A finding citing more evidence than the service permits.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="",
            evidence_ids=too_many,
            identity=lab.identity,
        )

    assert caught.value.code == "finding_citation_limit"


def test_undecodable_text_is_a_domain_refusal_not_an_internal_error(lab: Lab) -> None:
    """Surrogate-escaped argv bytes must fail validation, not SQLite binding."""

    with pytest.raises(IntegrityError) as caught:
        lab.research.create_mission(
            title="Undecodable \udcff title",
            objective="A mission whose title never decoded as UTF-8.",
            identity=lab.identity,
        )

    assert caught.value.code == "title_invalid"


def test_retracting_a_finding_restores_brief_export_after_an_honest_correction(
    lab: Lab,
) -> None:
    """The documented correction workflow must not permanently disable export.

    Withdrawing evidence is how Minerva records that an observation was wrong.
    Before retraction existed, any material finding citing that evidence blocked
    `brief export` for the whole mission forever, because findings are
    append-only and withdrawal is irreversible.
    """

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The proposition holds for the measured window.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="Bounded to the measured window.",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    assert lab.synthesis.build_brief(seed.mission.id)

    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The observation was measured incorrectly.",
        identity=lab.identity,
    )
    with pytest.raises(IntegrityError) as blocked:
        lab.synthesis.build_brief(seed.mission.id)
    assert blocked.value.code == "citation_withdrawn"

    retraction_id = lab.research.retract_finding(
        finding_id=finding.id,
        reason="The cited observation was withdrawn as mismeasured.",
        identity=lab.identity,
    )

    brief = lab.synthesis.build_brief(seed.mission.id)
    assert retraction_id.startswith("ret_")
    assert [item["id"] for item in brief.payload["findings"]] == []
    assert brief.payload["uncertainties"] == []


def test_retraction_preserves_the_finding_and_its_history(lab: Lab) -> None:
    """Retraction is a separate append-only record, never an edit or a delete."""

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A statement that will be retracted.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=finding.id,
        reason="Superseded by a corrected analysis.",
        identity=lab.identity,
    )

    with lab.database.read() as connection:
        stored = connection.execute(
            "SELECT statement FROM findings WHERE id = ?", (finding.id,)
        ).fetchone()
        citations = connection.execute(
            "SELECT COUNT(*) FROM finding_citations WHERE finding_id = ?", (finding.id,)
        ).fetchone()[0]
        reason = connection.execute(
            "SELECT reason FROM finding_retractions WHERE finding_id = ?", (finding.id,)
        ).fetchone()[0]
        retracted_events = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE event_type = 'research.finding.retracted'"
        ).fetchone()[0]

    assert stored["statement"] == "A statement that will be retracted."
    assert citations == 1
    assert reason == "Superseded by a corrected analysis."
    assert retracted_events == 1


def test_retracted_findings_are_distinguishable_on_every_read_surface(lab: Lab) -> None:
    """A retracted finding must never read as an asserted one.

    Synthesis drops retracted findings, but the listing surfaces keep showing
    them, so a reviewer needs the retraction carried in the read model itself.
    Without it a retracted statement is indistinguishable from a live one, which
    is exactly the false certainty the doctrine forbids.
    """

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    kept = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A statement that stays asserted.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    retracted = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A statement that is withdrawn from assertion.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=retracted.id,
        reason="Superseded by a corrected analysis.",
        identity=lab.identity,
    )

    listed = {item.id: item for item in lab.research.list_findings(seed.mission.id)}
    page, cursor = lab.research.page_findings(seed.mission.id, limit=10)
    paged = {item.id: item for item in page}

    assert len(listed) == 2, "the left join must not drop or duplicate findings"
    assert len(paged) == 2
    assert cursor is None

    for surface in (listed, paged):
        assert surface[retracted.id].retracted is True
        assert surface[retracted.id].retraction_reason == "Superseded by a corrected analysis."
        assert surface[retracted.id].retracted_at == fixed_clock()
        assert surface[retracted.id].retracted_by == lab.identity.actor_id
        assert surface[kept.id].retracted is False
        assert surface[kept.id].retraction_reason is None
        assert surface[kept.id].retracted_at is None
        assert surface[kept.id].retracted_by is None


def test_finding_pagination_still_advances_across_the_retraction_join(lab: Lab) -> None:
    """The retraction join must not disturb cursor paging."""

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    created = [
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement=f"Statement number {index}.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="",
            evidence_ids=(evidence.id,),
            identity=lab.identity,
        )
        for index in range(3)
    ]
    lab.research.retract_finding(
        finding_id=created[1].id, reason="Retracted mid-page.", identity=lab.identity
    )

    seen: list[str] = []
    cursor: tuple[str, str] | None = None
    while True:
        page, cursor = lab.research.page_findings(seed.mission.id, limit=1, after=cursor)
        seen.extend(item.id for item in page)
        if cursor is None:
            break

    assert seen == [item.id for item in created]


def test_a_finding_cannot_be_retracted_twice(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A statement retracted once.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=finding.id, reason="First retraction.", identity=lab.identity
    )

    with pytest.raises(ConflictError) as caught:
        lab.research.retract_finding(
            finding_id=finding.id, reason="Second retraction.", identity=lab.identity
        )

    assert caught.value.code == "finding_already_retracted"


def test_retraction_records_are_append_only(lab: Lab) -> None:
    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    finding = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="A retracted statement.",
        statement_kind=StatementKind.OBSERVED_FACT,
        status=FindingStatus.SUPPORTED,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.research.retract_finding(
        finding_id=finding.id, reason="Retracted for test.", identity=lab.identity
    )

    for statement in (
        "UPDATE finding_retractions SET reason = 'rewritten'",
        "DELETE FROM finding_retractions",
    ):
        with (
            pytest.raises(sqlite3.IntegrityError, match="append-only"),
            lab.database.transaction() as connection,
        ):
            connection.execute(statement)


def test_unknown_finding_cannot_be_retracted(lab: Lab) -> None:
    with pytest.raises(NotFoundError) as caught:
        lab.research.retract_finding(
            finding_id="fnd_" + "f" * 32, reason="No such finding.", identity=lab.identity
        )

    assert caught.value.code == "finding_not_found"


def test_withdrawn_optional_citation_does_not_block_a_non_material_statement(
    lab: Lab,
) -> None:
    """Invariant 8 governs material findings; an assumption asserts no support.

    Citing evidence from an assumption is a supported workflow, so a later
    withdrawal of that evidence must not refuse the whole mission's export.
    """

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="The instrument was calibrated before the run.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="The observation was measured incorrectly.",
        identity=lab.identity,
    )

    brief = lab.synthesis.build_brief(seed.mission.id)

    assumptions = brief.payload["assumptions"]
    assert [item["statement_kind"] for item in assumptions] == ["assumption"]
    assert assumptions[0]["citation_ids"] == [evidence.id]
    citation = next(
        item for item in brief.payload["citations"] if item["citation_id"] == evidence.id
    )
    assert citation["withdrawn"] is True


def test_an_assumption_may_cite_already_withdrawn_evidence(lab: Lab) -> None:
    """Creation must not be stricter than export about withdrawn citations.

    PRD invariant 8 and ADR 0007 scope the withdrawn-citation refusal to
    material findings, and the packet carries a non-material statement's
    withdrawn citation marked `withdrawn: true`. `add_finding` nonetheless
    refused every kind, so the same end state was reachable by withdrawing
    afterwards but not by citing evidence already withdrawn.
    """

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="Withdrawn before the assumption is recorded.",
        identity=lab.identity,
    )

    assumption = lab.research.add_finding(
        mission_id=seed.mission.id,
        claim_id=seed.claim.id,
        statement="An assumption that keeps an optional citation to withdrawn evidence.",
        statement_kind=StatementKind.ASSUMPTION,
        status=FindingStatus.INCONCLUSIVE,
        uncertainty="",
        evidence_ids=(evidence.id,),
        identity=lab.identity,
    )

    assert assumption.evidence_ids == (evidence.id,)
    assert lab.synthesis.build_brief(seed.mission.id) is not None


def test_a_material_finding_still_cannot_cite_withdrawn_evidence(lab: Lab) -> None:
    """Relaxing the assumption case must not relax PRD invariant 8."""

    seed = lab.seed_claim()
    evidence = lab.cite(seed, "Evidence supports the claim.", EvidenceStance.SUPPORTS)
    lab.evidence.withdraw_evidence(
        evidence_id=evidence.id,
        reason="Withdrawn before the finding is recorded.",
        identity=lab.identity,
    )

    with pytest.raises(IntegrityError) as caught:
        lab.research.add_finding(
            mission_id=seed.mission.id,
            claim_id=seed.claim.id,
            statement="A material finding resting on withdrawn evidence.",
            statement_kind=StatementKind.OBSERVED_FACT,
            status=FindingStatus.SUPPORTED,
            uncertainty="",
            evidence_ids=(evidence.id,),
            identity=lab.identity,
        )

    assert caught.value.code == "citation_withdrawn"
