"""Strict, deterministic, storage-independent research request contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, FailFast, Field, StringConstraints, model_validator

from minerva.integrations.canonical_json import (
    canonical_json_bytes,
    require_bounded_json_shape,
    strict_json_loads,
)

RESEARCH_REQUEST_SCHEMA_VERSION: Literal["minerva.research-request.v1"] = (
    "minerva.research-request.v1"
)
RESEARCH_RESULT_SCHEMA_VERSION: Literal["minerva.research-result.v1"] = "minerva.research-result.v1"
REQUESTED_OUTPUT_SCHEMA_VERSION: Literal["minerva.research-brief.v2"] = "minerva.research-brief.v2"
EVIDENCE_SELECTION_POLICY: Literal["complete_claim_ledger"] = "complete_claim_ledger"
MAX_RESEARCH_REQUEST_BYTES = 65_536

REQUEST_DIGEST_MISMATCH_MESSAGE = "request digest does not match the canonical request"
"""The one message the file reader may classify as a digest mismatch.

Named so the reader can match it exactly and anchored to the envelope root,
mirroring the packet reader. A substring test would let a file whose fields
happen to contain this sentence choose its own error code; today every request
field is pattern-constrained so nothing can, but the packet side already learned
that lesson (F-SEC-1) and the two readers should not differ on it.
"""
MAX_EXPECTED_ACTIVE_CITATION_IDS = 200

_MISSION_ID_PATTERN = r"^mis_[0-9a-f]{32}$"
_CLAIM_ID_PATTERN = r"^clm_[0-9a-f]{32}$"
_EVIDENCE_ID_PATTERN = r"^evd_[0-9a-f]{32}$"
_SHA256_PATTERN = r"^[0-9a-f]{64}$"

_MissionId = Annotated[str, StringConstraints(pattern=_MISSION_ID_PATTERN)]
_ClaimId = Annotated[str, StringConstraints(pattern=_CLAIM_ID_PATTERN)]
_EvidenceId = Annotated[str, StringConstraints(pattern=_EVIDENCE_ID_PATTERN)]
_Sha256 = Annotated[str, StringConstraints(pattern=_SHA256_PATTERN)]
type _FailFastTuple[ItemT] = Annotated[tuple[ItemT, ...], FailFast()]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceSelection(_StrictFrozenModel):
    policy: Literal["complete_claim_ledger"]
    expected_active_citation_ids: _FailFastTuple[_EvidenceId] = Field(
        max_length=MAX_EXPECTED_ACTIVE_CITATION_IDS
    )

    @model_validator(mode="after")
    def _citation_ids_are_canonical(self) -> Self:
        if any(left >= right for left, right in pairwise(self.expected_active_citation_ids)):
            raise ValueError(
                "expected active citation identifiers must be unique and strictly ordered"
            )
        return self


class ResearchRequest(_StrictFrozenModel):
    schema_version: Literal["minerva.research-request.v1"]
    mission_id: _MissionId
    claim_id: _ClaimId
    evidence_selection: EvidenceSelection
    requested_output_schema: Literal["minerva.research-brief.v2"]


class ResearchRequestDocument(_StrictFrozenModel):
    schema_version: Literal["minerva.research-request.v1"]
    request_digest: _Sha256
    request: ResearchRequest

    @model_validator(mode="after")
    def _validate_envelope(self) -> Self:
        if self.schema_version != self.request.schema_version:
            raise ValueError("request envelope and payload schema versions differ")
        if self.request_digest != research_request_digest(self.request):
            raise ValueError(REQUEST_DIGEST_MISMATCH_MESSAGE)
        return self


class ResearchResultArtifact(_StrictFrozenModel):
    schema_version: Literal["minerva.research-brief.v2"]
    sha256: _Sha256


class ResearchResultDocument(_StrictFrozenModel):
    schema_version: Literal["minerva.research-result.v1"]
    status: Literal["fulfilled"]
    request_digest: _Sha256
    output_artifact: ResearchResultArtifact


def canonical_research_request_bytes(
    request: ResearchRequest | Mapping[str, object],
) -> bytes:
    """Return compact canonical UTF-8 JSON bytes for the inner request."""

    validated = request if isinstance(request, ResearchRequest) else _validate_request(request)
    return canonical_json_bytes(validated.model_dump(mode="json"))


def research_request_digest(request: ResearchRequest | Mapping[str, object]) -> str:
    """Return the lowercase SHA-256 digest of the canonical inner request."""

    return sha256(canonical_research_request_bytes(request)).hexdigest()


def build_research_request(
    *,
    mission_id: str,
    claim_id: str,
    expected_active_citation_ids: Sequence[str],
) -> ResearchRequestDocument:
    """Validate request fields and wrap them in a deterministic digest envelope."""

    request = ResearchRequest(
        schema_version=RESEARCH_REQUEST_SCHEMA_VERSION,
        mission_id=mission_id,
        claim_id=claim_id,
        evidence_selection=EvidenceSelection(
            policy=EVIDENCE_SELECTION_POLICY,
            expected_active_citation_ids=tuple(expected_active_citation_ids),
        ),
        requested_output_schema=REQUESTED_OUTPUT_SCHEMA_VERSION,
    )
    return ResearchRequestDocument(
        schema_version=RESEARCH_REQUEST_SCHEMA_VERSION,
        request_digest=research_request_digest(request),
        request=request,
    )


def serialize_research_request(document: ResearchRequestDocument) -> bytes:
    """Serialize a validated request as canonical JSON with one final newline."""

    # Revalidation protects callers that bypassed normal construction with model_construct().
    encoded = canonical_json_bytes(document.model_dump(mode="json"))
    _require_request_size(encoded)
    validated = ResearchRequestDocument.model_validate_json(encoded, strict=True)
    serialized = canonical_json_bytes(validated.model_dump(mode="json")) + b"\n"
    _require_request_size(serialized)
    return serialized


def parse_research_request(data: bytes | str) -> ResearchRequestDocument:
    """Strictly parse and verify an untrusted research request."""

    encoded = data if isinstance(data, bytes) else data.encode("utf-8")
    _require_request_size(encoded)
    text = encoded.decode("utf-8")
    parsed = strict_json_loads(text)
    require_bounded_json_shape(parsed, subject="research request")
    return ResearchRequestDocument.model_validate_json(text, strict=True)


def serialize_research_result(
    *,
    request_digest: str,
    output_artifact_sha256: str,
) -> bytes:
    """Serialize the minimal deterministic manifest for a fulfilled request."""

    document = ResearchResultDocument(
        schema_version=RESEARCH_RESULT_SCHEMA_VERSION,
        status="fulfilled",
        request_digest=request_digest,
        output_artifact=ResearchResultArtifact(
            schema_version=REQUESTED_OUTPUT_SCHEMA_VERSION,
            sha256=output_artifact_sha256,
        ),
    )
    return canonical_json_bytes(document.model_dump(mode="json")) + b"\n"


def _validate_request(request: Mapping[str, object]) -> ResearchRequest:
    encoded = canonical_json_bytes(dict(request))
    _require_request_size(encoded)
    return ResearchRequest.model_validate_json(encoded, strict=True)


def _require_request_size(data: bytes) -> None:
    if len(data) > MAX_RESEARCH_REQUEST_BYTES:
        raise ValueError("research request exceeds the protocol size limit")
