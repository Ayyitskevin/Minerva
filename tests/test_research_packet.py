from __future__ import annotations

import copy
import json
from hashlib import sha256
from typing import Any

import pytest
from pydantic import ValidationError

import minerva.integrations.research_packet as packet_module
from minerva.integrations.research_packet import (
    RESEARCH_PACKET_SCHEMA_VERSION,
    build_research_packet,
    canonical_research_payload_bytes,
    parse_research_packet,
    research_payload_digest,
    serialize_research_packet,
)

_ACTOR = "os-user:packet-test"
_RUN = "run_packet"
_MISSION = "mis_packet"
_CREATED_AT = "2026-07-22T12:00:00.000000Z"
_STATUS_AT = "2026-07-22T12:01:00.000000Z"
_AUDITED_AT = "2026-07-22T12:02:00.000000Z"
_SNAPSHOT_DIGEST = "a" * 64


def _citation(
    citation_id: str,
    claim_id: str,
    quote: str,
    stance: str,
) -> dict[str, Any]:
    return {
        "citation_id": citation_id,
        "claim_id": claim_id,
        "snapshot_id": "snp_packet",
        "snapshot_sha256": _SNAPSHOT_DIGEST,
        "source_label": "synthetic/source.txt",
        "location": {
            "scheme": "utf8-byte-offset-v1",
            "start_byte": 0,
            "end_byte": len(quote.encode("utf-8")),
        },
        "quote": quote,
        "stance": stance,
        "withdrawn": False,
        "withdrawal_reason": None,
        "withdrawal_creator_id": None,
        "withdrawal_run_id": None,
        "withdrawn_at": None,
        "supersedes_citation_id": None,
        "creator_id": _ACTOR,
        "run_id": _RUN,
        "created_at": _CREATED_AT,
    }


def _audit(
    sequence: int,
    event_type: str,
    entity_type: str,
    entity_id: str,
    mission_id: str | None,
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "id": f"aud_{sequence}",
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "mission_id": mission_id,
        "actor_id": _ACTOR,
        "run_id": _RUN,
        # AuditRecorder reads its clock independently from the entity service.
        "occurred_at": _AUDITED_AT,
    }


def _payload() -> dict[str, Any]:
    citations = [
        _citation("evd_support", "clm_contested", "direct support", "supports"),
        _citation("evd_oppose", "clm_contested", "direct opposition", "opposes"),
        _citation("evd_context", "clm_contested", "bounded context", "context"),
        _citation("evd_unclear", "clm_open", "unclear observation", "inconclusive"),
    ]
    audits = [
        _audit(1, "research.run.started", "research_run", _RUN, None),
        _audit(2, "research.mission.created", "research_mission", _MISSION, _MISSION),
        _audit(3, "research.question.created", "research_question", "que_primary", _MISSION),
        _audit(4, "research.question.created", "research_question", "que_open", _MISSION),
        _audit(5, "research.claim.created", "claim", "clm_contested", _MISSION),
        _audit(6, "research.claim.created", "claim", "clm_open", _MISSION),
        _audit(7, "source.snapshot.imported", "source_snapshot", "snp_packet", _MISSION),
    ]
    audits.extend(
        _audit(8 + index, "evidence.card.created", "evidence_card", item["citation_id"], _MISSION)
        for index, item in enumerate(citations)
    )
    audits.extend(
        [
            _audit(12, "research.claim.status_changed", "claim", "clm_contested", _MISSION),
            _audit(13, "research.finding.created", "finding", "fnd_material", _MISSION),
            _audit(14, "research.finding.created", "finding", "fnd_assumption", _MISSION),
            _audit(15, "research.finding.created", "finding", "fnd_unresolved", _MISSION),
        ]
    )
    return {
        "schema_version": RESEARCH_PACKET_SCHEMA_VERSION,
        "doctrine": "Minerva records evidence and uncertainty; it does not manufacture certainty.",
        "ownership": {
            "system": "minerva",
            "researches": True,
            "executes": False,
            "approves": False,
            "orchestrates": False,
            "publishes": False,
        },
        "mission": {
            "id": _MISSION,
            "title": "Synthetic packet mission",
            "objective": "Test a falsifiable proposition without external systems.",
            "creator_id": _ACTOR,
            "run_id": _RUN,
            "created_at": _CREATED_AT,
            "epistemic_role": "research_scope",
        },
        "questions": [
            {
                "id": "que_primary",
                "text": "Is the primary proposition supported?",
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
                "epistemic_role": "research_question",
            },
            {
                "id": "que_open",
                "text": "What remains unresolved?",
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
                "epistemic_role": "research_question",
            },
        ],
        "claims": [
            {
                "id": "clm_contested",
                "question_id": "que_primary",
                "statement": "The primary proposition holds.",
                "falsification_criteria": "Direct opposition falsifies it.",
                "status": "contested",
                "version": 2,
                "status_reason": "The record contains support and opposition.",
                "status_creator_id": _ACTOR,
                "status_run_id": _RUN,
                "status_changed_at": _STATUS_AT,
                "status_evidence_valid": True,
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
                "epistemic_role": "claim_under_evaluation",
                "contested": True,
                "evidence_ledger": [
                    {"citation_id": "evd_support", "stance": "supports", "withdrawn": False},
                    {"citation_id": "evd_oppose", "stance": "opposes", "withdrawn": False},
                    {"citation_id": "evd_context", "stance": "context", "withdrawn": False},
                ],
            },
            {
                "id": "clm_open",
                "question_id": "que_open",
                "statement": "A second proposition remains open.",
                "falsification_criteria": "A decisive observation would resolve it.",
                "status": "open",
                "version": 1,
                "status_reason": "Claim registered for evaluation.",
                "status_creator_id": _ACTOR,
                "status_run_id": _RUN,
                "status_changed_at": _CREATED_AT,
                "status_evidence_valid": True,
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
                "epistemic_role": "claim_under_evaluation",
                "contested": False,
                "evidence_ledger": [
                    {
                        "citation_id": "evd_unclear",
                        "stance": "inconclusive",
                        "withdrawn": False,
                    }
                ],
            },
        ],
        "findings": [
            {
                "id": "fnd_material",
                "claim_id": "clm_contested",
                "statement": "A direct supporting observation was recorded.",
                "statement_kind": "observed_fact",
                "status": "contested",
                "citation_ids": ["evd_support"],
                "uncertainty": "The opposing observation remains unresolved.",
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
            }
        ],
        "assumptions": [
            {
                "id": "fnd_assumption",
                "claim_id": None,
                "statement": "The synthetic sample is representative.",
                "statement_kind": "assumption",
                "status": "inconclusive",
                "citation_ids": [],
                "uncertainty": "Representativeness has not been established.",
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
            }
        ],
        "unresolved_questions": [
            {
                "id": "fnd_unresolved",
                "claim_id": None,
                "statement": "Which independent observation resolves the conflict?",
                "statement_kind": "unresolved_question",
                "status": "inconclusive",
                "citation_ids": [],
                "uncertainty": "No independent observation is present.",
                "creator_id": _ACTOR,
                "run_id": _RUN,
                "created_at": _CREATED_AT,
            }
        ],
        "uncertainties": [
            {
                "finding_id": "fnd_material",
                "text": "The opposing observation remains unresolved.",
            },
            {
                "finding_id": "fnd_assumption",
                "text": "Representativeness has not been established.",
            },
            {
                "finding_id": "fnd_unresolved",
                "text": "No independent observation is present.",
            },
        ],
        "citations": citations,
        "sources": [
            {
                "snapshot_id": "snp_packet",
                "source_id": "src_packet",
                "original_label": "synthetic/source.txt",
                "media_type": "text/plain",
                "encoding": "utf-8",
                "byte_length": 4_096,
                "sha256": _SNAPSHOT_DIGEST,
                "imported_at": _CREATED_AT,
                "url_metadata": None,
                "creator_id": _ACTOR,
                "run_id": _RUN,
            }
        ],
        "runs": [
            {
                "id": _RUN,
                "actor_id": _ACTOR,
                "actor_kind": "os_user",
                "purpose": "verify the research packet contract",
                "created_at": _CREATED_AT,
            }
        ],
        "audit_references": audits,
        "integrity": {
            "citation_scheme": "utf8-byte-offset-v1",
            "source_digest_algorithm": "sha256",
            "export_digest_algorithm": "sha256-canonical-json-v1",
            "material_statement_policy": (
                "Material statements require exact active citations; claims remain propositions."
            ),
        },
    }


def _invalid(payload: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        build_research_packet(payload)


def test_valid_packet_is_deterministic_round_trippable_and_storage_independent() -> None:
    payload = _payload()
    first = build_research_packet(payload)
    reordered = dict(reversed(list(payload.items())))
    second = build_research_packet(reordered)

    assert first == second
    assert first.export_digest == research_payload_digest(first.brief)
    assert first.export_digest == sha256(canonical_research_payload_bytes(first.brief)).hexdigest()
    assert {citation.stance for citation in first.brief.citations} == {
        "supports",
        "opposes",
        "context",
        "inconclusive",
    }
    assert first.brief.ownership.model_dump() == {
        "system": "minerva",
        "researches": True,
        "executes": False,
        "approves": False,
        "orchestrates": False,
        "publishes": False,
    }

    serialized = serialize_research_packet(first)
    assert serialized.endswith(b"\n")
    assert serialized.count(b"\n") == 1
    assert serialized == (
        json.dumps(
            json.loads(serialized),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    assert parse_research_packet(serialized) == first
    assert first.brief.audit_references[0].occurred_at != first.brief.runs[0].created_at


def test_parser_rejects_duplicate_keys_non_finite_numbers_and_unknown_fields() -> None:
    raw = serialize_research_packet(build_research_packet(_payload()))
    duplicate = raw[:-2] + (b',"schema_version":"minerva.research-brief.v2"}\n')
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        parse_research_packet(duplicate)

    non_finite = raw.replace(b'"byte_length":4096', b'"byte_length":NaN')
    with pytest.raises(ValueError, match="non-finite JSON number"):
        parse_research_packet(non_finite)

    document = json.loads(raw)
    document["unexpected"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        parse_research_packet(json.dumps(document))


def test_parser_rejects_schema_and_digest_mismatches() -> None:
    raw = serialize_research_packet(build_research_packet(_payload()))
    document = json.loads(raw)
    document["export_digest"] = "0" * 64
    with pytest.raises(ValidationError, match="export digest"):
        parse_research_packet(json.dumps(document))

    document = json.loads(raw)
    document["brief"]["schema_version"] = "minerva.research-brief.v1"
    with pytest.raises(ValidationError, match="literal_error"):
        parse_research_packet(json.dumps(document))


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("quote_length", "UTF-8 byte range"),
        ("snapshot_digest", "snapshot digests differ"),
        ("ledger_stance", "ledger and citation metadata differ"),
        ("unknown_finding_citation", "unknown citation"),
        ("cross_claim_finding", "different claim"),
    ],
)
def test_citation_and_finding_mutations_fail_closed(mutation: str, message: str) -> None:
    payload = _payload()
    if mutation == "quote_length":
        payload["citations"][0]["quote"] += "!"
    elif mutation == "snapshot_digest":
        payload["citations"][0]["snapshot_sha256"] = "b" * 64
    elif mutation == "ledger_stance":
        payload["claims"][0]["evidence_ledger"][0]["stance"] = "context"
    elif mutation == "unknown_finding_citation":
        payload["findings"][0]["citation_ids"] = ["evd_missing"]
    else:
        payload["findings"][0]["claim_id"] = "clm_open"
    _invalid(payload, message)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing_run", "unknown run"),
        ("creator_mismatch", "creator does not match"),
        ("missing_audit", "missing required audit"),
        ("audit_outside_packet", "points outside"),
    ],
)
def test_provenance_and_audit_mutations_fail_closed(mutation: str, message: str) -> None:
    payload = _payload()
    if mutation == "missing_run":
        payload["runs"] = []
    elif mutation == "creator_mismatch":
        payload["mission"]["creator_id"] = "os-user:forged"
    elif mutation == "missing_audit":
        payload["audit_references"] = payload["audit_references"][1:]
    else:
        payload["audit_references"][1]["entity_id"] = "mis_outside"
    _invalid(payload, message)


def test_optional_assumption_and_unresolved_citations_are_preserved_and_validated() -> None:
    payload = _payload()
    payload["assumptions"][0].update({"claim_id": "clm_contested", "citation_ids": ["evd_context"]})
    payload["unresolved_questions"][0].update(
        {"claim_id": "clm_open", "citation_ids": ["evd_unclear"]}
    )

    packet = build_research_packet(payload)

    assert packet.brief.assumptions[0].citation_ids == ("evd_context",)
    assert packet.brief.unresolved_questions[0].citation_ids == ("evd_unclear",)

    unknown = copy.deepcopy(payload)
    unknown["assumptions"][0]["citation_ids"] = ["evd_missing"]
    _invalid(unknown, "unknown citation")

    cross_claim = copy.deepcopy(payload)
    cross_claim["unresolved_questions"][0]["citation_ids"] = ["evd_context"]
    _invalid(cross_claim, "different claim")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate", "duplicate uncertainty"),
        ("missing", "exactly cover"),
        ("unknown", "unknown finding"),
        ("mismatch", "differs from its finding"),
    ],
)
def test_uncertainty_reference_mutations_fail_closed(mutation: str, message: str) -> None:
    payload = _payload()
    if mutation == "duplicate":
        payload["uncertainties"].append(copy.deepcopy(payload["uncertainties"][0]))
    elif mutation == "missing":
        payload["uncertainties"].pop()
    elif mutation == "unknown":
        payload["uncertainties"][0]["finding_id"] = "fnd_missing"
    else:
        payload["uncertainties"][0]["text"] = "A forged uncertainty."

    _invalid(payload, message)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("out_of_order", "strictly increasing"),
        ("inflated_version", "version does not match"),
        ("unexpected_duplicate", "unexpected audit"),
        ("unused_run", "exactly cover represented provenance"),
        ("latest_status_provenance", "latest claim status audit provenance"),
        ("run_after_content", "before its run started"),
        ("status_before_claim", "precedes claim creation"),
    ],
)
def test_audit_history_structure_fails_closed(mutation: str, message: str) -> None:
    payload = _payload()
    if mutation == "out_of_order":
        payload["audit_references"][4:6] = reversed(payload["audit_references"][4:6])
    elif mutation == "inflated_version":
        payload["claims"][0]["version"] = 999
    elif mutation == "unexpected_duplicate":
        payload["audit_references"].append(
            _audit(16, "research.mission.created", "research_mission", _MISSION, _MISSION)
        )
    elif mutation == "run_after_content":
        run_start = payload["audit_references"].pop(0)
        run_start["sequence"] = 16
        payload["audit_references"].append(run_start)
    elif mutation == "status_before_claim":
        claim_created = payload["audit_references"].pop(4)
        claim_created["sequence"] = 16
        payload["audit_references"].append(claim_created)
    else:
        second_run = {
            "id": "run_unused",
            "actor_id": "os-user:unused",
            "actor_kind": "os_user",
            "purpose": "synthetic unused provenance",
            "created_at": _CREATED_AT,
        }
        payload["runs"].append(second_run)
        run_start = _audit(16, "research.run.started", "research_run", "run_unused", None)
        run_start.update({"actor_id": "os-user:unused", "run_id": "run_unused", "id": "aud_unused"})
        payload["audit_references"].append(run_start)
        if mutation == "latest_status_provenance":
            payload["claims"][0].update(
                {
                    "status_creator_id": "os-user:unused",
                    "status_run_id": "run_unused",
                }
            )
    _invalid(payload, message)


def _move_audit_before(
    payload: dict[str, Any],
    *,
    target_event: str,
    target_entity: str,
    before_event: str,
    before_entity: str,
) -> None:
    audits = payload["audit_references"]
    target_index = next(
        index
        for index, reference in enumerate(audits)
        if reference["event_type"] == target_event and reference["entity_id"] == target_entity
    )
    target = audits.pop(target_index)
    before_index = next(
        index
        for index, reference in enumerate(audits)
        if reference["event_type"] == before_event and reference["entity_id"] == before_entity
    )
    audits.insert(before_index, target)
    for sequence, reference in enumerate(audits, start=1):
        reference["sequence"] = sequence


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("mission", "precedes mission creation"),
        ("question", "precedes its research question"),
        ("evidence", "precedes its claim or source"),
        ("status", "precedes its required evidence"),
        ("finding", "precedes its cited evidence"),
        ("supersession", "points forward"),
    ],
)
def test_audit_dependency_order_fails_closed(mutation: str, message: str) -> None:
    payload = _payload()
    if mutation == "mission":
        _move_audit_before(
            payload,
            target_event="research.question.created",
            target_entity="que_primary",
            before_event="research.mission.created",
            before_entity=_MISSION,
        )
    elif mutation == "question":
        _move_audit_before(
            payload,
            target_event="research.claim.created",
            target_entity="clm_contested",
            before_event="research.question.created",
            before_entity="que_primary",
        )
    elif mutation == "evidence":
        _move_audit_before(
            payload,
            target_event="evidence.card.created",
            target_entity="evd_support",
            before_event="source.snapshot.imported",
            before_entity="snp_packet",
        )
    elif mutation == "status":
        _move_audit_before(
            payload,
            target_event="research.claim.status_changed",
            target_entity="clm_contested",
            before_event="evidence.card.created",
            before_entity="evd_oppose",
        )
    elif mutation == "finding":
        _move_audit_before(
            payload,
            target_event="research.finding.created",
            target_entity="fnd_material",
            before_event="evidence.card.created",
            before_entity="evd_support",
        )
    else:
        payload["citations"][0]["supersedes_citation_id"] = "evd_context"

    _invalid(payload, message)


def test_unsupported_claim_requires_real_opposition_or_withdrawn_history() -> None:
    fabricated = _payload()
    claim = fabricated["claims"][1]
    claim.update(
        {
            "status": "unsupported",
            "version": 2,
            "status_reason": "A fabricated unsupported label.",
            "status_changed_at": _STATUS_AT,
            "status_evidence_valid": False,
        }
    )
    fabricated["audit_references"].append(
        _audit(16, "research.claim.status_changed", "claim", "clm_open", _MISSION)
    )
    _invalid(fabricated, "no active or withdrawn evidentiary history")

    falsely_valid = copy.deepcopy(fabricated)
    falsely_valid["claims"][1]["status_evidence_valid"] = True
    _invalid(falsely_valid, "evidence-valid flag")


def test_stale_status_is_allowed_only_with_withdrawn_evidence_history() -> None:
    payload = _payload()
    opposition = payload["citations"][1]
    opposition.update(
        {
            "withdrawn": True,
            "withdrawal_reason": "Synthetic retraction.",
            "withdrawal_creator_id": _ACTOR,
            "withdrawal_run_id": _RUN,
            "withdrawn_at": _STATUS_AT,
        }
    )
    payload["claims"][0]["evidence_ledger"][1]["withdrawn"] = True
    payload["claims"][0]["status_evidence_valid"] = False
    payload["audit_references"].append(
        _audit(16, "evidence.card.withdrawn", "evidence_card", "evd_oppose", _MISSION)
    )

    packet = build_research_packet(payload)

    assert packet.brief.claims[0].status == "contested"
    assert packet.brief.claims[0].status_evidence_valid is False


def test_withdrawn_citation_cannot_support_a_material_finding() -> None:
    payload = _payload()
    support = payload["citations"][0]
    support.update(
        {
            "withdrawn": True,
            "withdrawal_reason": "Synthetic retraction.",
            "withdrawal_creator_id": _ACTOR,
            "withdrawal_run_id": _RUN,
            "withdrawn_at": _STATUS_AT,
        }
    )
    payload["claims"][0]["evidence_ledger"][0]["withdrawn"] = True
    payload["claims"][0]["status_evidence_valid"] = False
    payload["audit_references"].append(
        _audit(16, "evidence.card.withdrawn", "evidence_card", "evd_support", _MISSION)
    )

    _invalid(payload, "withdrawn evidence cannot support")


def test_long_citation_supersession_chain_is_validated_without_recursion() -> None:
    payload = _payload()
    previous_id = "evd_unclear"
    for index in range(2_000):
        citation_id = f"evd_chain_{index:04d}"
        citation = _citation(citation_id, "clm_open", "x", "context")
        citation["supersedes_citation_id"] = previous_id
        payload["citations"].append(citation)
        payload["claims"][1]["evidence_ledger"].append(
            {"citation_id": citation_id, "stance": "context", "withdrawn": False}
        )
        payload["audit_references"].append(
            _audit(
                16 + index,
                "evidence.card.created",
                "evidence_card",
                citation_id,
                _MISSION,
            )
        )
        previous_id = citation_id

    packet = build_research_packet(payload)

    assert len(packet.brief.citations) == 2_004
    payload["citations"][3]["supersedes_citation_id"] = previous_id
    _invalid(payload, "supersession contains a cycle")


def test_parser_rejects_packets_over_the_protocol_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = serialize_research_packet(build_research_packet(_payload()))
    monkeypatch.setattr(packet_module, "MAX_RESEARCH_PACKET_BYTES", len(raw) - 1)

    with pytest.raises(ValueError, match="protocol size limit"):
        parse_research_packet(raw)


def test_contract_models_are_strict_frozen_and_forbid_extra_fields() -> None:
    payload = _payload()
    payload["ownership"]["unexpected"] = False
    _invalid(payload, "extra_forbidden")

    strict_payload = _payload()
    strict_payload["sources"][0]["byte_length"] = "4096"
    _invalid(strict_payload, "int_type")

    document = build_research_packet(_payload())
    with pytest.raises(ValidationError, match="frozen_instance"):
        document.brief.ownership.executes = True  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("system", "other"),
        ("researches", False),
        ("executes", True),
        ("approves", True),
        ("orchestrates", True),
        ("publishes", True),
    ],
)
def test_ownership_boundary_cannot_be_forged(field: str, value: object) -> None:
    payload = _payload()
    payload["ownership"][field] = value

    _invalid(payload, "literal_error")
