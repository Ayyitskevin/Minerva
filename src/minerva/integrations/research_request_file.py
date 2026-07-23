"""Safe file boundary and bounded reports for standalone research requests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Never

from pydantic import ValidationError

from minerva.core.errors import IntegrityError
from minerva.integrations.research_request import (
    MAX_RESEARCH_REQUEST_BYTES,
    ResearchRequestDocument,
    parse_research_request,
)
from minerva.integrations.safe_artifact_file import (
    ArtifactReadError,
    ArtifactReadFailureKind,
    read_stable_artifact_bytes,
)

_MAX_CLASSIFIED_VALIDATION_ERRORS = 32


def load_research_request(path: Path) -> ResearchRequestDocument:
    """Read and verify one regular request file without following symbolic links."""

    try:
        data = read_stable_artifact_bytes(path, max_bytes=MAX_RESEARCH_REQUEST_BYTES)
    except ArtifactReadError as error:
        _raise_read_failure(error.kind)

    try:
        return parse_research_request(data)
    except UnicodeDecodeError:
        _fail("request_malformed", "The research request is not valid UTF-8 JSON.")
    except json.JSONDecodeError:
        _fail("request_malformed", "The research request contains malformed JSON.")
    except ValidationError as error:
        _raise_validation_failure(error)
    except RecursionError:
        _fail("request_malformed", "The research request JSON nesting is invalid.")
    except ValueError as error:
        message = str(error)
        if message.startswith("duplicate JSON object key:"):
            _fail(
                "request_duplicate_field",
                "The research request contains a duplicate JSON field.",
            )
        if message.startswith("non-finite JSON number is forbidden:"):
            _fail(
                "request_nonstandard_number",
                "The research request contains a non-standard JSON number.",
            )
        if message.startswith("research request JSON "):
            _fail(
                "request_too_complex",
                "The research request JSON structure exceeds a safety limit.",
            )
        _fail("request_malformed", "The research request contains invalid JSON.")


def request_verification_report(document: ResearchRequestDocument) -> dict[str, object]:
    """Return a bounded, identifier-free success record for a verified request."""

    request = document.request
    selection = request.evidence_selection
    return {
        "status": "verified",
        "schema_version": document.schema_version,
        "request_digest": document.request_digest,
        "requested_output_schema": request.requested_output_schema,
        "evidence_selection": {
            "policy": selection.policy,
            "expected_active_citation_count": len(selection.expected_active_citation_ids),
        },
        "integrity": {
            "digest_verified": True,
            "authenticity": "not_established",
            "authorization": "not_established",
        },
    }


def _raise_read_failure(kind: ArtifactReadFailureKind) -> Never:
    if kind is ArtifactReadFailureKind.UNSAFE:
        _fail("request_input_unsafe", "The research request input path is unsafe.")
    if kind is ArtifactReadFailureKind.SYMLINK:
        _fail("request_input_symlink", "Research request paths may not use symbolic links.")
    if kind is ArtifactReadFailureKind.NOT_FOUND:
        _fail("request_input_not_found", "The research request input was not found.")
    if kind is ArtifactReadFailureKind.UNREADABLE:
        _fail("request_input_unreadable", "The research request could not be read safely.")
    if kind is ArtifactReadFailureKind.CHANGED:
        _fail(
            "request_input_changed",
            "The research request changed while it was being read.",
        )
    _fail(
        "request_too_large",
        "The research request exceeds the 64 KiB protocol size limit.",
    )


def _raise_validation_failure(error: ValidationError) -> Never:
    if error.error_count() > _MAX_CLASSIFIED_VALIDATION_ERRORS:
        _fail(
            "request_invalid",
            "The research request failed strict structure or semantic verification.",
        )
    details = error.errors(include_input=False, include_url=False)
    if any(
        detail["type"] == "literal_error" and tuple(detail["loc"])[-1:] == ("schema_version",)
        for detail in details
    ):
        _fail(
            "request_schema_unsupported",
            "The research request schema version is unsupported.",
        )
    if any(
        detail["type"] == "literal_error"
        and tuple(detail["loc"])[-1:] == ("requested_output_schema",)
        for detail in details
    ):
        _fail(
            "request_output_schema_unsupported",
            "The requested research output schema is unsupported.",
        )
    if any(
        detail["type"] == "literal_error" and tuple(detail["loc"])[-1:] == ("policy",)
        for detail in details
    ):
        _fail(
            "request_selection_policy_unsupported",
            "The research request evidence-selection policy is unsupported.",
        )
    if any(
        "request digest does not match the canonical request" in detail["msg"] for detail in details
    ):
        _fail(
            "request_digest_mismatch",
            "The research request digest does not match its canonical payload.",
        )
    _fail(
        "request_invalid",
        "The research request failed strict structure or semantic verification.",
    )


def _fail(code: str, message: str) -> Never:
    raise IntegrityError(code, message)
