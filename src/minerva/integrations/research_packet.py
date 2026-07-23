"""Strict, deterministic, storage-independent research packet contract.

The DTOs in this module deliberately know nothing about Minerva's SQLite
schema.  Producers project their state into the contract, and consumers can
verify that projection using only the packet bytes.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from itertools import pairwise
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, FailFast, Field, StringConstraints, model_validator

RESEARCH_PACKET_SCHEMA_VERSION: Literal["minerva.research-brief.v2"] = "minerva.research-brief.v2"
CITATION_SCHEME = "utf8-byte-offset-v1"
SOURCE_DIGEST_ALGORITHM = "sha256"
EXPORT_DIGEST_ALGORITHM = "sha256-canonical-json-v1"
MAX_RESEARCH_PACKET_BYTES = 20_971_520

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_MAX_JSON_DEPTH = 64
_MAX_JSON_OBJECT_FIELDS = 64
_NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
_Sha256 = Annotated[str, StringConstraints(pattern=_SHA256_PATTERN)]
_AuditKey = tuple[str, str, str, str | None, str, str]
type _FailFastTuple[ItemT] = Annotated[tuple[ItemT, ...], FailFast()]

ClaimStatus = Literal[
    "open",
    "provisionally_supported",
    "contested",
    "unsupported",
    "inconclusive",
]
FindingStatus = Literal["supported", "contested", "unsupported", "inconclusive"]
EvidenceStance = Literal["supports", "opposes", "context", "inconclusive"]
MaterialStatementKind = Literal[
    "observed_fact",
    "source_assertion",
    "agent_inference",
    "calculation",
    "recommendation",
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Ownership(_StrictFrozenModel):
    system: Literal["minerva"]
    researches: Literal[True]
    executes: Literal[False]
    approves: Literal[False]
    orchestrates: Literal[False]
    publishes: Literal[False]


class MissionRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    title: _NonEmptyStr
    objective: _NonEmptyStr
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr
    epistemic_role: Literal["research_scope"]


class QuestionRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    text: _NonEmptyStr
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr
    epistemic_role: Literal["research_question"]


class EvidenceLedgerEntry(_StrictFrozenModel):
    citation_id: _NonEmptyStr
    stance: EvidenceStance
    withdrawn: bool


class ClaimRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    question_id: _NonEmptyStr
    statement: _NonEmptyStr
    falsification_criteria: _NonEmptyStr
    status: ClaimStatus
    version: int = Field(ge=1)
    status_reason: _NonEmptyStr
    status_creator_id: _NonEmptyStr
    status_run_id: _NonEmptyStr
    status_changed_at: _NonEmptyStr
    status_evidence_valid: bool
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr
    epistemic_role: Literal["claim_under_evaluation"]
    contested: bool
    evidence_ledger: _FailFastTuple[EvidenceLedgerEntry]

    @model_validator(mode="after")
    def _initial_status_is_open(self) -> Self:
        if self.version == 1 and self.status != "open":
            raise ValueError("a version-one claim must retain its initial open status")
        if self.version == 1 and (
            self.status_creator_id != self.creator_id
            or self.status_run_id != self.run_id
            or self.status_changed_at != self.created_at
        ):
            raise ValueError("a version-one claim status must share claim creation provenance")
        return self


class MaterialFindingRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    claim_id: _NonEmptyStr | None
    statement: _NonEmptyStr
    statement_kind: MaterialStatementKind
    status: FindingStatus
    citation_ids: _FailFastTuple[_NonEmptyStr] = Field(min_length=1)
    uncertainty: str
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr


class AssumptionRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    claim_id: _NonEmptyStr | None
    statement: _NonEmptyStr
    statement_kind: Literal["assumption"]
    status: FindingStatus
    citation_ids: _FailFastTuple[_NonEmptyStr]
    uncertainty: str
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr


class UnresolvedQuestionRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    claim_id: _NonEmptyStr | None
    statement: _NonEmptyStr
    statement_kind: Literal["unresolved_question"]
    status: FindingStatus
    citation_ids: _FailFastTuple[_NonEmptyStr]
    uncertainty: str
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr


class UncertaintyRecord(_StrictFrozenModel):
    finding_id: _NonEmptyStr
    text: _NonEmptyStr


class CitationLocation(_StrictFrozenModel):
    scheme: Literal["utf8-byte-offset-v1"]
    start_byte: int = Field(ge=0)
    end_byte: int = Field(gt=0)

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end_byte <= self.start_byte:
            raise ValueError("citation end_byte must be greater than start_byte")
        return self


class CitationRecord(_StrictFrozenModel):
    citation_id: _NonEmptyStr
    claim_id: _NonEmptyStr
    snapshot_id: _NonEmptyStr
    snapshot_sha256: _Sha256
    source_label: _NonEmptyStr
    location: CitationLocation
    quote: _NonEmptyStr
    stance: EvidenceStance
    withdrawn: bool
    withdrawal_reason: _NonEmptyStr | None
    withdrawal_creator_id: _NonEmptyStr | None
    withdrawal_run_id: _NonEmptyStr | None
    withdrawn_at: _NonEmptyStr | None
    supersedes_citation_id: _NonEmptyStr | None
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr
    created_at: _NonEmptyStr

    @model_validator(mode="after")
    def _withdrawal_provenance_is_complete(self) -> Self:
        provenance = (
            self.withdrawal_reason,
            self.withdrawal_creator_id,
            self.withdrawal_run_id,
            self.withdrawn_at,
        )
        if self.withdrawn and any(value is None for value in provenance):
            raise ValueError("withdrawn citations require complete withdrawal provenance")
        if not self.withdrawn and any(value is not None for value in provenance):
            raise ValueError("active citations cannot carry withdrawal provenance")
        return self


class SourceRecord(_StrictFrozenModel):
    snapshot_id: _NonEmptyStr
    source_id: _NonEmptyStr
    original_label: _NonEmptyStr
    media_type: _NonEmptyStr
    encoding: Literal["utf-8"]
    byte_length: int = Field(gt=0)
    sha256: _Sha256
    imported_at: _NonEmptyStr
    url_metadata: _NonEmptyStr | None
    creator_id: _NonEmptyStr
    run_id: _NonEmptyStr


class ResearchRunRecord(_StrictFrozenModel):
    id: _NonEmptyStr
    actor_id: _NonEmptyStr
    actor_kind: Literal["os_user", "system"]
    purpose: _NonEmptyStr
    created_at: _NonEmptyStr


class AuditReference(_StrictFrozenModel):
    sequence: int = Field(gt=0)
    id: _NonEmptyStr
    event_type: Literal[
        "research.run.started",
        "research.mission.created",
        "research.question.created",
        "research.claim.created",
        "research.claim.status_changed",
        "source.snapshot.imported",
        "evidence.card.created",
        "evidence.card.withdrawn",
        "research.finding.created",
    ]
    entity_type: Literal[
        "research_run",
        "research_mission",
        "research_question",
        "claim",
        "source_snapshot",
        "evidence_card",
        "finding",
    ]
    entity_id: _NonEmptyStr
    mission_id: _NonEmptyStr | None
    actor_id: _NonEmptyStr
    run_id: _NonEmptyStr
    occurred_at: _NonEmptyStr


class IntegrityPolicy(_StrictFrozenModel):
    citation_scheme: Literal["utf8-byte-offset-v1"]
    source_digest_algorithm: Literal["sha256"]
    export_digest_algorithm: Literal["sha256-canonical-json-v1"]
    material_statement_policy: _NonEmptyStr


class ResearchBriefPayload(_StrictFrozenModel):
    schema_version: Literal["minerva.research-brief.v2"]
    doctrine: _NonEmptyStr
    ownership: Ownership
    mission: MissionRecord
    questions: _FailFastTuple[QuestionRecord]
    claims: _FailFastTuple[ClaimRecord]
    findings: _FailFastTuple[MaterialFindingRecord]
    assumptions: _FailFastTuple[AssumptionRecord]
    unresolved_questions: _FailFastTuple[UnresolvedQuestionRecord]
    uncertainties: _FailFastTuple[UncertaintyRecord]
    citations: _FailFastTuple[CitationRecord]
    sources: _FailFastTuple[SourceRecord]
    runs: _FailFastTuple[ResearchRunRecord]
    audit_references: _FailFastTuple[AuditReference]
    integrity: IntegrityPolicy

    @model_validator(mode="after")
    def _validate_references_and_evidence(self) -> Self:
        _validate_payload_semantics(self)
        return self


class ResearchPacketDocument(_StrictFrozenModel):
    schema_version: Literal["minerva.research-brief.v2"]
    export_digest: _Sha256
    brief: ResearchBriefPayload

    @model_validator(mode="after")
    def _validate_envelope(self) -> Self:
        if self.schema_version != self.brief.schema_version:
            raise ValueError("packet and brief schema versions differ")
        if self.export_digest != research_payload_digest(self.brief):
            raise ValueError("packet export digest does not match the canonical brief")
        return self


def canonical_research_payload_bytes(
    payload: ResearchBriefPayload | Mapping[str, object],
) -> bytes:
    """Return compact canonical UTF-8 JSON bytes for the inner brief."""

    validated = payload if isinstance(payload, ResearchBriefPayload) else _validate_payload(payload)
    return _canonical_json_bytes(validated.model_dump(mode="json"))


def research_payload_digest(payload: ResearchBriefPayload | Mapping[str, object]) -> str:
    """Return the lowercase SHA-256 digest of the canonical inner brief."""

    return sha256(canonical_research_payload_bytes(payload)).hexdigest()


def build_research_packet(payload_mapping: Mapping[str, object]) -> ResearchPacketDocument:
    """Validate a projected brief and wrap it in its deterministic digest envelope."""

    payload = _validate_payload(payload_mapping)
    return ResearchPacketDocument(
        schema_version=RESEARCH_PACKET_SCHEMA_VERSION,
        export_digest=research_payload_digest(payload),
        brief=payload,
    )


def serialize_research_packet(document: ResearchPacketDocument) -> bytes:
    """Serialize a validated packet as compact canonical JSON with one final newline."""

    # Revalidation protects callers that bypassed normal construction with model_construct().
    encoded = _canonical_json_bytes(document.model_dump(mode="json"))
    _require_packet_size(encoded)
    validated = ResearchPacketDocument.model_validate_json(encoded, strict=True)
    serialized = _canonical_json_bytes(validated.model_dump(mode="json")) + b"\n"
    _require_packet_size(serialized)
    return serialized


def parse_research_packet(data: bytes | str) -> ResearchPacketDocument:
    """Strictly parse and semantically verify an untrusted research packet."""

    encoded = data if isinstance(data, bytes) else data.encode("utf-8")
    _require_packet_size(encoded)
    text = encoded.decode("utf-8")
    parsed = _strict_json_loads(text)
    _require_bounded_json_shape(parsed)
    return ResearchPacketDocument.model_validate_json(text, strict=True)


def _validate_payload(payload: Mapping[str, object]) -> ResearchBriefPayload:
    encoded = _canonical_json_bytes(dict(payload))
    _require_packet_size(encoded)
    return ResearchBriefPayload.model_validate_json(encoded, strict=True)


def _require_packet_size(data: bytes) -> None:
    if len(data) > MAX_RESEARCH_PACKET_BYTES:
        raise ValueError("research packet exceeds the protocol size limit")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _strict_json_loads(text: str) -> object:
    def reject_duplicate_keys(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_non_finite(token: str) -> object:
        raise ValueError(f"non-finite JSON number is forbidden: {token}")

    return cast(
        object,
        json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        ),
    )


def _require_bounded_json_shape(value: object, *, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise ValueError("research packet JSON nesting exceeds the safety limit")
    if isinstance(value, dict):
        if len(value) > _MAX_JSON_OBJECT_FIELDS:
            raise ValueError("research packet JSON object exceeds the field safety limit")
        for child in value.values():
            _require_bounded_json_shape(child, depth=depth + 1)
    elif isinstance(value, list):
        for child in value:
            _require_bounded_json_shape(child, depth=depth + 1)


def _unique_by_id[RecordT](records: Sequence[RecordT], *, field: str) -> dict[str, RecordT]:
    result: dict[str, RecordT] = {}
    for record in records:
        identifier = cast(str, getattr(record, field))
        if identifier in result:
            raise ValueError(f"duplicate identifier: {identifier}")
        result[identifier] = record
    return result


def _validate_payload_semantics(payload: ResearchBriefPayload) -> None:
    questions = _unique_by_id(payload.questions, field="id")
    claims = _unique_by_id(payload.claims, field="id")
    sources = _unique_by_id(payload.sources, field="snapshot_id")
    citations = _unique_by_id(payload.citations, field="citation_id")
    runs = _unique_by_id(payload.runs, field="id")
    all_findings: tuple[
        MaterialFindingRecord | AssumptionRecord | UnresolvedQuestionRecord, ...
    ] = (*payload.findings, *payload.assumptions, *payload.unresolved_questions)
    findings = _unique_by_id(all_findings, field="id")
    _unique_by_id(payload.audit_references, field="id")

    if len({source.source_id for source in payload.sources}) != len(payload.sources):
        raise ValueError("duplicate source identifier")
    sequences = [reference.sequence for reference in payload.audit_references]
    if len(set(sequences)) != len(sequences):
        raise ValueError("duplicate audit sequence")

    run_records = dict(runs)

    def require_provenance(creator_id: str, run_id: str, *, subject: str) -> None:
        run = run_records.get(run_id)
        if run is None:
            raise ValueError(f"{subject} references an unknown run: {run_id}")
        if run.actor_id != creator_id:
            raise ValueError(f"{subject} creator does not match its run actor")

    require_provenance(payload.mission.creator_id, payload.mission.run_id, subject="mission")
    for question in payload.questions:
        require_provenance(question.creator_id, question.run_id, subject=question.id)
    for claim in payload.claims:
        if claim.question_id not in questions:
            raise ValueError(f"claim references an unknown question: {claim.question_id}")
        require_provenance(claim.creator_id, claim.run_id, subject=claim.id)
        require_provenance(
            claim.status_creator_id,
            claim.status_run_id,
            subject=f"{claim.id} status",
        )
    for source in payload.sources:
        require_provenance(source.creator_id, source.run_id, subject=source.snapshot_id)
    for citation in payload.citations:
        require_provenance(citation.creator_id, citation.run_id, subject=citation.citation_id)
        if citation.withdrawn:
            require_provenance(
                cast(str, citation.withdrawal_creator_id),
                cast(str, citation.withdrawal_run_id),
                subject=f"{citation.citation_id} withdrawal",
            )
    for finding in all_findings:
        require_provenance(finding.creator_id, finding.run_id, subject=finding.id)

    claim_records = dict(claims)
    source_records = dict(sources)
    citation_records = dict(citations)

    _validate_citations(citation_records, claim_records, source_records)
    _validate_claim_ledgers(payload.claims, citation_records)
    _validate_findings(all_findings, claim_records, citation_records)
    _validate_uncertainties(payload, findings)
    _validate_audit_references(payload, run_records)


def _validate_citations(
    citations: Mapping[str, CitationRecord],
    claims: Mapping[str, ClaimRecord],
    sources: Mapping[str, SourceRecord],
) -> None:
    for citation in citations.values():
        if citation.claim_id not in claims:
            raise ValueError(f"citation references an unknown claim: {citation.claim_id}")
        source = sources.get(citation.snapshot_id)
        if source is None:
            raise ValueError(f"citation references an unknown snapshot: {citation.snapshot_id}")
        if citation.snapshot_sha256 != source.sha256:
            raise ValueError("citation and source snapshot digests differ")
        if citation.source_label != source.original_label:
            raise ValueError("citation and source labels differ")
        if citation.location.end_byte > source.byte_length:
            raise ValueError("citation location exceeds its source snapshot")
        byte_length = len(citation.quote.encode("utf-8"))
        if byte_length != citation.location.end_byte - citation.location.start_byte:
            raise ValueError("citation quote length does not match its UTF-8 byte range")
        if citation.supersedes_citation_id is not None:
            superseded = citations.get(citation.supersedes_citation_id)
            if superseded is None:
                raise ValueError("citation supersedes an unknown citation")
            if superseded.citation_id == citation.citation_id:
                raise ValueError("a citation cannot supersede itself")
            if superseded.claim_id != citation.claim_id:
                raise ValueError("superseded citations must evaluate the same claim")

    finished: set[str] = set()
    for citation_id in citations:
        if citation_id in finished:
            continue
        path: list[str] = []
        visiting: set[str] = set()
        cursor_id: str | None = citation_id
        while cursor_id is not None and cursor_id not in finished:
            if cursor_id in visiting:
                raise ValueError("citation supersession contains a cycle")
            visiting.add(cursor_id)
            path.append(cursor_id)
            cursor_id = citations[cursor_id].supersedes_citation_id
        finished.update(path)


def _validate_claim_ledgers(
    claims: Sequence[ClaimRecord],
    citations: Mapping[str, CitationRecord],
) -> None:
    citation_ids_by_claim: dict[str, set[str]] = {claim.id: set() for claim in claims}
    for citation in citations.values():
        citation_ids_by_claim[citation.claim_id].add(citation.citation_id)

    for claim in claims:
        ledger_ids = [item.citation_id for item in claim.evidence_ledger]
        if len(set(ledger_ids)) != len(ledger_ids):
            raise ValueError(f"claim ledger contains duplicate citations: {claim.id}")
        if set(ledger_ids) != citation_ids_by_claim[claim.id]:
            raise ValueError(f"claim ledger does not exactly cover its citations: {claim.id}")
        active_stances: set[str] = set()
        historical_stances: set[str] = set()
        for item in claim.evidence_ledger:
            citation = citations[item.citation_id]
            if item.stance != citation.stance or item.withdrawn != citation.withdrawn:
                raise ValueError("claim ledger and citation metadata differ")
            historical_stances.add(citation.stance)
            if not citation.withdrawn:
                active_stances.add(citation.stance)

        expected_contested = claim.status == "contested" or {
            "supports",
            "opposes",
        }.issubset(active_stances)
        if claim.contested != expected_contested:
            raise ValueError("claim contested flag is inconsistent with status and evidence")
        required_stances: set[str]
        if claim.status == "provisionally_supported":
            required_stances = {"supports"}
        elif claim.status == "contested":
            required_stances = {"supports", "opposes"}
        elif claim.status == "unsupported":
            required_stances = {"opposes"}
        else:
            required_stances = set()

        evidence_is_valid = required_stances.issubset(active_stances)
        if claim.status_evidence_valid != evidence_is_valid:
            raise ValueError(
                "claim status evidence-valid flag is inconsistent with active evidence"
            )
        if not evidence_is_valid and not required_stances.issubset(historical_stances):
            raise ValueError("claim status has no active or withdrawn evidentiary history")


def _validate_findings(
    all_findings: Sequence[MaterialFindingRecord | AssumptionRecord | UnresolvedQuestionRecord],
    claims: Mapping[str, ClaimRecord],
    citations: Mapping[str, CitationRecord],
) -> None:
    for finding in all_findings:
        if finding.claim_id is not None and finding.claim_id not in claims:
            raise ValueError(f"finding references an unknown claim: {finding.claim_id}")
        citation_ids = list(finding.citation_ids)
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError(f"finding contains duplicate citations: {finding.id}")
        for citation_id in citation_ids:
            citation = citations.get(citation_id)
            if citation is None:
                raise ValueError(f"finding references an unknown citation: {citation_id}")
            if citation.withdrawn:
                raise ValueError("withdrawn evidence cannot support a finding")
            if finding.claim_id is not None and citation.claim_id != finding.claim_id:
                raise ValueError("a finding citation evaluates a different claim")


def _validate_uncertainties(
    payload: ResearchBriefPayload,
    findings: Mapping[str, MaterialFindingRecord | AssumptionRecord | UnresolvedQuestionRecord],
) -> None:
    uncertainty_by_finding: dict[str, str] = {}
    for uncertainty in payload.uncertainties:
        if uncertainty.finding_id in uncertainty_by_finding:
            raise ValueError("duplicate uncertainty reference")
        finding = findings.get(uncertainty.finding_id)
        if finding is None:
            raise ValueError("uncertainty references an unknown finding")
        finding_uncertainty = finding.uncertainty
        if uncertainty.text != finding_uncertainty:
            raise ValueError("uncertainty text differs from its finding")
        uncertainty_by_finding[uncertainty.finding_id] = uncertainty.text

    expected = {identifier for identifier, finding in findings.items() if finding.uncertainty}
    if set(uncertainty_by_finding) != expected:
        raise ValueError("uncertainty references do not exactly cover recorded uncertainty")


def _validate_audit_references(
    payload: ResearchBriefPayload,
    runs: Mapping[str, ResearchRunRecord],
) -> None:
    mission_id = payload.mission.id
    all_findings: tuple[
        MaterialFindingRecord | AssumptionRecord | UnresolvedQuestionRecord, ...
    ] = (*payload.findings, *payload.assumptions, *payload.unresolved_questions)
    valid_pair = {
        "research.run.started": "research_run",
        "research.mission.created": "research_mission",
        "research.question.created": "research_question",
        "research.claim.created": "claim",
        "research.claim.status_changed": "claim",
        "source.snapshot.imported": "source_snapshot",
        "evidence.card.created": "evidence_card",
        "evidence.card.withdrawn": "evidence_card",
        "research.finding.created": "finding",
    }
    entity_ids: dict[str, set[str]] = {
        "research_run": set(runs),
        "research_mission": {mission_id},
        "research_question": {question.id for question in payload.questions},
        "claim": {claim.id for claim in payload.claims},
        "source_snapshot": {source.snapshot_id for source in payload.sources},
        "evidence_card": {citation.citation_id for citation in payload.citations},
        "finding": {finding.id for finding in all_findings},
    }
    sequences = [reference.sequence for reference in payload.audit_references]
    if any(left >= right for left, right in pairwise(sequences)):
        raise ValueError("audit references must be ordered by strictly increasing sequence")

    observed: Counter[_AuditKey] = Counter()
    status_references: dict[str, list[AuditReference]] = {claim.id: [] for claim in payload.claims}
    for reference in payload.audit_references:
        if valid_pair[reference.event_type] != reference.entity_type:
            raise ValueError("audit event and entity types are inconsistent")
        if reference.entity_id not in entity_ids[reference.entity_type]:
            raise ValueError("audit reference points outside the packet")
        run = runs.get(reference.run_id)
        if run is None:
            raise ValueError("audit reference uses an unknown run")
        if reference.actor_id != run.actor_id:
            raise ValueError("audit actor does not match its run actor")
        if reference.event_type == "research.run.started":
            if reference.mission_id is not None:
                raise ValueError("run-start audit references cannot claim mission scope")
        elif reference.mission_id != mission_id:
            raise ValueError("content audit reference has the wrong mission scope")
        if reference.event_type == "research.claim.status_changed":
            status_references[reference.entity_id].append(reference)
            continue
        observed[
            (
                reference.event_type,
                reference.entity_type,
                reference.entity_id,
                reference.mission_id,
                reference.actor_id,
                reference.run_id,
            )
        ] += 1

    expected: Counter[_AuditKey] = Counter()

    def expect(
        event_type: str,
        entity_type: str,
        entity_id: str,
        scoped_mission_id: str | None,
        actor_id: str,
        run_id: str,
    ) -> None:
        expected[
            (
                event_type,
                entity_type,
                entity_id,
                scoped_mission_id,
                actor_id,
                run_id,
            )
        ] += 1

    for run in runs.values():
        expect(
            "research.run.started",
            "research_run",
            run.id,
            None,
            run.actor_id,
            run.id,
        )
    mission = payload.mission
    expect(
        "research.mission.created",
        "research_mission",
        mission.id,
        mission.id,
        mission.creator_id,
        mission.run_id,
    )
    for question in payload.questions:
        expect(
            "research.question.created",
            "research_question",
            question.id,
            mission_id,
            question.creator_id,
            question.run_id,
        )
    for claim in payload.claims:
        expect(
            "research.claim.created",
            "claim",
            claim.id,
            mission_id,
            claim.creator_id,
            claim.run_id,
        )
    for source in payload.sources:
        expect(
            "source.snapshot.imported",
            "source_snapshot",
            source.snapshot_id,
            mission_id,
            source.creator_id,
            source.run_id,
        )
    for citation in payload.citations:
        expect(
            "evidence.card.created",
            "evidence_card",
            citation.citation_id,
            mission_id,
            citation.creator_id,
            citation.run_id,
        )
        if citation.withdrawn:
            expect(
                "evidence.card.withdrawn",
                "evidence_card",
                citation.citation_id,
                mission_id,
                cast(str, citation.withdrawal_creator_id),
                cast(str, citation.withdrawal_run_id),
            )
    for finding in all_findings:
        expect(
            "research.finding.created",
            "finding",
            finding.id,
            mission_id,
            finding.creator_id,
            finding.run_id,
        )

    missing = expected - observed
    if missing:
        raise ValueError("packet is missing required audit references")
    unexpected = observed - expected
    if unexpected:
        raise ValueError("packet contains unexpected audit references")

    run_start_sequences = {
        reference.run_id: reference.sequence
        for reference in payload.audit_references
        if reference.event_type == "research.run.started"
    }
    for reference in payload.audit_references:
        if (
            reference.event_type != "research.run.started"
            and run_start_sequences[reference.run_id] >= reference.sequence
        ):
            raise ValueError("audit provenance is recorded before its run started")

    creation_sequences = {
        (reference.event_type, reference.entity_id): reference.sequence
        for reference in payload.audit_references
        if reference.event_type != "research.claim.status_changed"
    }
    mission_creation_sequence = creation_sequences[("research.mission.created", mission_id)]
    for reference in payload.audit_references:
        if (
            reference.event_type
            not in {
                "research.run.started",
                "research.mission.created",
            }
            and reference.sequence <= mission_creation_sequence
        ):
            raise ValueError("content audit history precedes mission creation")

    question_creation_sequences = {
        question.id: creation_sequences[("research.question.created", question.id)]
        for question in payload.questions
    }
    claim_creation_sequences = {
        claim.id: creation_sequences[("research.claim.created", claim.id)]
        for claim in payload.claims
    }
    source_creation_sequences = {
        source.snapshot_id: creation_sequences[("source.snapshot.imported", source.snapshot_id)]
        for source in payload.sources
    }
    citation_creation_sequences = {
        citation.citation_id: creation_sequences[("evidence.card.created", citation.citation_id)]
        for citation in payload.citations
    }
    withdrawal_sequences = {
        reference.entity_id: reference.sequence
        for reference in payload.audit_references
        if reference.event_type == "evidence.card.withdrawn"
    }
    latest_status_sequences = {
        claim_id: references[-1].sequence
        for claim_id, references in status_references.items()
        if references
    }
    stances_at_latest_status: dict[str, set[str]] = {claim.id: set() for claim in payload.claims}
    for citation in payload.citations:
        status_sequence = latest_status_sequences.get(citation.claim_id)
        if (
            status_sequence is not None
            and citation_creation_sequences[citation.citation_id] < status_sequence
            and (
                citation.citation_id not in withdrawal_sequences
                or withdrawal_sequences[citation.citation_id] > status_sequence
            )
        ):
            stances_at_latest_status[citation.claim_id].add(citation.stance)

    for claim in payload.claims:
        if question_creation_sequences[claim.question_id] >= claim_creation_sequences[claim.id]:
            raise ValueError("claim audit history precedes its research question")
        references = status_references[claim.id]
        if len(references) != claim.version - 1:
            raise ValueError("claim version does not match status-change audit history")
        if any(
            reference.sequence <= claim_creation_sequences[claim.id] for reference in references
        ):
            raise ValueError("claim status audit history precedes claim creation")
        if references:
            latest = references[-1]
            if latest.actor_id != claim.status_creator_id or latest.run_id != claim.status_run_id:
                raise ValueError(
                    "latest claim status audit provenance differs from the current status"
                )
            required_stances: set[str]
            if claim.status == "provisionally_supported":
                required_stances = {"supports"}
            elif claim.status == "contested":
                required_stances = {"supports", "opposes"}
            elif claim.status == "unsupported":
                required_stances = {"opposes"}
            else:
                required_stances = set()
            if not required_stances.issubset(stances_at_latest_status[claim.id]):
                raise ValueError("claim status audit precedes its required evidence")

    for citation in payload.citations:
        created = citation_creation_sequences[citation.citation_id]
        if (
            claim_creation_sequences[citation.claim_id] >= created
            or source_creation_sequences[citation.snapshot_id] >= created
        ):
            raise ValueError("evidence audit history precedes its claim or source")
        if (
            citation.supersedes_citation_id is not None
            and citation_creation_sequences[citation.supersedes_citation_id] >= created
        ):
            raise ValueError("citation supersession audit history points forward")
        if citation.withdrawn and withdrawal_sequences[citation.citation_id] <= created:
            raise ValueError("citation withdrawal audit history precedes its creation")

    for finding in all_findings:
        created = creation_sequences[("research.finding.created", finding.id)]
        if finding.claim_id is not None and claim_creation_sequences[finding.claim_id] >= created:
            raise ValueError("finding audit history precedes its claim")
        if any(
            citation_creation_sequences[citation_id] >= created
            for citation_id in finding.citation_ids
        ):
            raise ValueError("finding audit history precedes its cited evidence")

    used_run_ids = {
        reference.run_id
        for reference in payload.audit_references
        if reference.event_type != "research.run.started"
    }
    if set(runs) != used_run_ids:
        raise ValueError("packet runs do not exactly cover represented provenance")
