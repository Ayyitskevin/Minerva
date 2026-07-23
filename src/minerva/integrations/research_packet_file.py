"""Safe file boundary and bounded reports for standalone research packets."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from minerva.core.errors import IntegrityError
from minerva.integrations.research_packet import (
    MAX_RESEARCH_PACKET_BYTES,
    EvidenceStance,
    ResearchPacketDocument,
    parse_research_packet,
)
from minerva.integrations.safe_artifact_file import (
    ArtifactReadError,
    ArtifactReadFailureKind,
    read_stable_artifact_bytes,
)

_MAX_CLASSIFIED_VALIDATION_ERRORS = 32
_EVIDENCE_STANCES: tuple[EvidenceStance, ...] = (
    "supports",
    "opposes",
    "context",
    "inconclusive",
)


def load_research_packet(path: Path) -> ResearchPacketDocument:
    """Read and verify one regular packet file without following symbolic links."""

    try:
        data = read_stable_artifact_bytes(path, max_bytes=MAX_RESEARCH_PACKET_BYTES)
    except ArtifactReadError as error:
        _raise_read_failure(error.kind)

    try:
        return parse_research_packet(data)
    except UnicodeDecodeError:
        _fail("packet_malformed", "The research packet is not valid UTF-8 JSON.")
    except json.JSONDecodeError:
        _fail("packet_malformed", "The research packet contains malformed JSON.")
    except ValidationError as error:
        _raise_validation_failure(error)
    except RecursionError:
        _fail("packet_malformed", "The research packet JSON nesting is invalid.")
    except ValueError as error:
        message = str(error)
        if message.startswith("duplicate JSON object key:"):
            _fail(
                "packet_duplicate_field",
                "The research packet contains a duplicate JSON field.",
            )
        if message.startswith("non-finite JSON number is forbidden:"):
            _fail(
                "packet_nonstandard_number",
                "The research packet contains a non-standard JSON number.",
            )
        if message.startswith("research packet JSON "):
            _fail(
                "packet_too_complex",
                "The research packet JSON structure exceeds a safety limit.",
            )
        _fail("packet_malformed", "The research packet contains invalid JSON.")


def packet_verification_report(document: ResearchPacketDocument) -> dict[str, object]:
    """Return a bounded success record for a verified packet."""

    return {
        "status": "verified",
        "schema_version": document.schema_version,
        "export_digest": document.export_digest,
        "integrity": {
            "digest_verified": True,
            "authenticity": "not_established",
        },
        "ownership": document.brief.ownership.model_dump(mode="json"),
    }


def packet_inspection_report(document: ResearchPacketDocument) -> dict[str, object]:
    """Return bounded packet inventory without exposing research text or paths."""

    brief = document.brief
    stance_counts = Counter(citation.stance for citation in brief.citations)
    all_findings = (*brief.findings, *brief.assumptions, *brief.unresolved_questions)
    creator_run_records = (
        1
        + len(brief.questions)
        + len(brief.claims)
        + len(brief.sources)
        + len(brief.citations)
        + len(all_findings)
    )
    return {
        **packet_verification_report(document),
        "counts": {
            "missions": 1,
            "questions": len(brief.questions),
            "claims": len(brief.claims),
            "citations": len(brief.citations),
            "active_citations": sum(not citation.withdrawn for citation in brief.citations),
            "withdrawn_citations": sum(citation.withdrawn for citation in brief.citations),
            "evidence_stances": {
                stance: stance_counts.get(stance, 0) for stance in _EVIDENCE_STANCES
            },
            "findings": len(brief.findings),
            "assumptions": len(brief.assumptions),
            "unresolved_questions": len(brief.unresolved_questions),
            "uncertainties": len(brief.uncertainties),
            "sources": len(brief.sources),
        },
        "provenance": {
            "verified": True,
            "runs": len(brief.runs),
            "creator_run_records": creator_run_records,
            "claim_status_records": len(brief.claims),
            "withdrawal_records": sum(citation.withdrawn for citation in brief.citations),
        },
        "audit": {
            "verified": True,
            "references": len(brief.audit_references),
        },
        "counts_are_not_confidence": True,
    }


def _raise_read_failure(kind: ArtifactReadFailureKind) -> Never:
    if kind is ArtifactReadFailureKind.UNSAFE:
        _fail("packet_input_unsafe", "The research packet input path is unsafe.")
    if kind is ArtifactReadFailureKind.SYMLINK:
        _fail("packet_input_symlink", "Research packet paths may not use symbolic links.")
    if kind is ArtifactReadFailureKind.NOT_FOUND:
        _fail("packet_input_not_found", "The research packet input was not found.")
    if kind is ArtifactReadFailureKind.UNREADABLE:
        _fail("packet_input_unreadable", "The research packet could not be read safely.")
    if kind is ArtifactReadFailureKind.CHANGED:
        _fail(
            "packet_input_changed",
            "The research packet changed while it was being read.",
        )
    _fail(
        "packet_too_large",
        "The research packet exceeds the 20 MiB protocol size limit.",
    )


def _raise_validation_failure(error: ValidationError) -> Never:
    if error.error_count() > _MAX_CLASSIFIED_VALIDATION_ERRORS:
        _fail(
            "packet_invalid",
            "The research packet failed strict structure or semantic verification.",
        )
    details = error.errors(include_input=False, include_url=False)
    if any(
        detail["type"] == "literal_error" and tuple(detail["loc"])[-1:] == ("schema_version",)
        for detail in details
    ):
        _fail(
            "packet_schema_unsupported",
            "The research packet schema version is unsupported.",
        )
    if any(
        "packet export digest does not match the canonical brief" in detail["msg"]
        for detail in details
    ):
        _fail(
            "packet_digest_mismatch",
            "The research packet export digest does not match its canonical payload.",
        )
    _fail(
        "packet_invalid",
        "The research packet failed strict structure or semantic verification.",
    )


def _fail(code: str, message: str) -> Never:
    raise IntegrityError(code, message)
