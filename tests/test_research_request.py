from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path
from typing import NoReturn

import pytest
from pydantic import ValidationError

import minerva.integrations.research_request_file as request_file_module
import minerva.integrations.safe_artifact_file as safe_file_module
from minerva.core.errors import IntegrityError
from minerva.integrations.research_request import (
    MAX_EXPECTED_ACTIVE_CITATION_IDS,
    MAX_RESEARCH_REQUEST_BYTES,
    build_research_request,
    canonical_research_request_bytes,
    parse_research_request,
    research_request_digest,
    serialize_research_request,
    serialize_research_result,
)
from minerva.integrations.research_request_file import (
    load_research_request,
    request_verification_report,
)

_GOLDEN = Path(__file__).parent / "fixtures" / "minerva.research-request.v1.golden.json"
_MISSION_ID = "mis_00000000000000000000000000000001"
_CLAIM_ID = "clm_00000000000000000000000000000002"
_EVIDENCE_IDS = (
    "evd_00000000000000000000000000000003",
    "evd_00000000000000000000000000000004",
)
_DIGEST = "d1ea1f37c6c42f0c39db49463cb6420c21b7bef227e55e77b9e88a4de6c5b32f"


def _golden_document() -> dict[str, object]:
    document = json.loads(_GOLDEN.read_bytes())
    assert isinstance(document, dict)
    return document


def _write_document(tmp_path: Path, document: object, *, name: str = "request.json") -> Path:
    target = tmp_path / name
    target.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return target


def _request_mapping(document: dict[str, object]) -> dict[str, object]:
    request = document["request"]
    assert isinstance(request, dict)
    return request


def _selection_mapping(document: dict[str, object]) -> dict[str, object]:
    selection = _request_mapping(document)["evidence_selection"]
    assert isinstance(selection, dict)
    return selection


def _load_failure(path: Path, expected_code: str) -> IntegrityError:
    with pytest.raises(IntegrityError) as caught:
        load_research_request(path)
    assert caught.value.code == expected_code
    assert len(str(caught.value)) < 200
    return caught.value


def _reverse_objects(value: object) -> object:
    if isinstance(value, dict):
        return {key: _reverse_objects(child) for key, child in reversed(tuple(value.items()))}
    if isinstance(value, list):
        return [_reverse_objects(child) for child in value]
    return value


def test_checked_in_request_is_exact_canonical_golden_and_digest() -> None:
    golden_bytes = _GOLDEN.read_bytes()
    document = parse_research_request(golden_bytes)
    built = build_research_request(
        mission_id=_MISSION_ID,
        claim_id=_CLAIM_ID,
        expected_active_citation_ids=_EVIDENCE_IDS,
    )
    canonical_payload = canonical_research_request_bytes(document.request)

    assert document == built
    assert serialize_research_request(document) == golden_bytes
    assert golden_bytes.endswith(b"\n")
    assert b'\n  "' not in golden_bytes
    assert canonical_payload == (
        b'{"claim_id":"clm_00000000000000000000000000000002",'
        b'"evidence_selection":{"expected_active_citation_ids":'
        b'["evd_00000000000000000000000000000003",'
        b'"evd_00000000000000000000000000000004"],'
        b'"policy":"complete_claim_ledger"},'
        b'"mission_id":"mis_00000000000000000000000000000001",'
        b'"requested_output_schema":"minerva.research-brief.v2",'
        b'"schema_version":"minerva.research-request.v1"}'
    )
    assert research_request_digest(document.request) == _DIGEST
    assert sha256(canonical_payload).hexdigest() == _DIGEST


def test_reordered_json_keys_parse_to_the_same_canonical_bytes() -> None:
    reordered = json.dumps(
        _reverse_objects(_golden_document()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()

    document = parse_research_request(reordered)

    assert serialize_research_request(document) == _GOLDEN.read_bytes()


def test_verification_report_is_bounded_identifier_free_and_authority_neutral() -> None:
    report = request_verification_report(load_research_request(_GOLDEN))
    encoded = json.dumps(report, separators=(",", ":"), sort_keys=True)

    assert report == {
        "status": "verified",
        "schema_version": "minerva.research-request.v1",
        "request_digest": _DIGEST,
        "requested_output_schema": "minerva.research-brief.v2",
        "evidence_selection": {
            "policy": "complete_claim_ledger",
            "expected_active_citation_count": 2,
        },
        "integrity": {
            "digest_verified": True,
            "authenticity": "not_established",
            "authorization": "not_established",
        },
    }
    assert _MISSION_ID not in encoded
    assert _CLAIM_ID not in encoded
    assert all(evidence_id not in encoded for evidence_id in _EVIDENCE_IDS)


def test_result_manifest_is_exact_minimal_and_path_free() -> None:
    result = serialize_research_result(
        request_digest="a" * 64,
        output_artifact_sha256="b" * 64,
    )

    assert result == (
        b'{"output_artifact":{"schema_version":"minerva.research-brief.v2",'
        b'"sha256":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},'
        b'"request_digest":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"schema_version":"minerva.research-result.v1","status":"fulfilled"}\n'
    )
    assert not {
        "path",
        "url",
        "actor",
        "authority",
        "approval",
        "run_id",
        "timestamp",
    }.intersection(json.loads(result))


@pytest.mark.parametrize(
    ("location", "value"),
    [
        (("schema_version",), 1),
        (("request_digest",), True),
        (("request",), []),
        (("request", "mission_id"), 1),
        (("request", "claim_id"), False),
        (("request", "requested_output_schema"), 2),
        (("request", "evidence_selection"), []),
        (("request", "evidence_selection", "policy"), 3),
        (("request", "evidence_selection", "expected_active_citation_ids"), _EVIDENCE_IDS[0]),
        (
            ("request", "evidence_selection", "expected_active_citation_ids"),
            [_EVIDENCE_IDS[0], 4],
        ),
    ],
)
def test_request_models_reject_type_coercion_at_every_nesting(
    location: tuple[str, ...],
    value: object,
) -> None:
    document = _golden_document()
    cursor: dict[str, object] = document
    for key in location[:-1]:
        child = cursor[key]
        assert isinstance(child, dict)
        cursor = child
    cursor[location[-1]] = value

    with pytest.raises(ValidationError):
        parse_research_request(json.dumps(document, separators=(",", ":")))


@pytest.mark.parametrize(
    "location",
    [
        (),
        ("request",),
        ("request", "evidence_selection"),
    ],
)
def test_request_models_forbid_unknown_fields_at_every_object_nesting(
    location: tuple[str, ...],
) -> None:
    document = _golden_document()
    cursor = document
    for key in location:
        child = cursor[key]
        assert isinstance(child, dict)
        cursor = child
    cursor["unexpected_authority"] = "operator"

    with pytest.raises(ValidationError):
        parse_research_request(json.dumps(document, separators=(",", ":")))


def test_nested_duplicate_field_is_rejected_before_model_validation(tmp_path: Path) -> None:
    duplicate = _GOLDEN.read_bytes().replace(
        b'"policy":"complete_claim_ledger"',
        b'"policy":"complete_claim_ledger","policy":"complete_claim_ledger"',
        1,
    )
    target = tmp_path / "duplicate.json"
    target.write_bytes(duplicate)

    _load_failure(target, "request_duplicate_field")


@pytest.mark.parametrize("token", [b"NaN", b"Infinity", b"-Infinity"])
def test_nonstandard_json_numbers_are_rejected(token: bytes, tmp_path: Path) -> None:
    target = tmp_path / "nonstandard.json"
    target.write_bytes(b'{"request":' + token + b"}")

    _load_failure(target, "request_nonstandard_number")


@pytest.mark.parametrize("payload", [b"\xff\xfe", b'{"unterminated":'])
def test_malformed_json_and_utf8_are_bounded_and_non_reflective(
    payload: bytes,
    tmp_path: Path,
) -> None:
    sentinel = "PRIVATE_SENTINEL_DO_NOT_REFLECT"
    target = tmp_path / f"{sentinel}.json"
    target.write_bytes(payload)

    error = _load_failure(target, "request_malformed")

    assert sentinel not in str(error)
    assert str(target) not in str(error)


@pytest.mark.parametrize("shape", ["wide_object", "deep_array"])
def test_excessive_json_depth_and_width_are_rejected_before_validation(
    shape: str,
    tmp_path: Path,
) -> None:
    if shape == "wide_object":
        value: object = {f"field_{index}": None for index in range(65)}
    else:
        value = None
        for _index in range(66):
            value = [value]
    target = _write_document(tmp_path, value)

    _load_failure(target, "request_too_complex")


def test_oversized_file_is_rejected_before_parser_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "oversized.json"
    with target.open("wb") as stream:
        stream.truncate(MAX_RESEARCH_REQUEST_BYTES + 1)

    def forbidden_parse(_data: bytes) -> NoReturn:
        raise AssertionError("oversized request reached JSON decoding")

    monkeypatch.setattr(request_file_module, "parse_research_request", forbidden_parse)

    _load_failure(target, "request_too_large")


@pytest.mark.parametrize(
    "citation_ids",
    [
        (_EVIDENCE_IDS[1], _EVIDENCE_IDS[0]),
        (_EVIDENCE_IDS[0], _EVIDENCE_IDS[0]),
        tuple(f"evd_{index:032x}" for index in range(MAX_EXPECTED_ACTIVE_CITATION_IDS + 1)),
    ],
)
def test_selection_requires_sorted_unique_bounded_citation_ids(
    citation_ids: tuple[str, ...],
    tmp_path: Path,
) -> None:
    document = _golden_document()
    _selection_mapping(document)["expected_active_citation_ids"] = citation_ids
    target = _write_document(tmp_path, document)

    _load_failure(target, "request_invalid")


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            lambda document: document.__setitem__("schema_version", "minerva.research-request.v2"),
            "request_schema_unsupported",
        ),
        (
            lambda document: _request_mapping(document).__setitem__(
                "schema_version", "minerva.research-request.v2"
            ),
            "request_schema_unsupported",
        ),
        (
            lambda document: _request_mapping(document).__setitem__(
                "requested_output_schema", "minerva.research-brief.v3"
            ),
            "request_output_schema_unsupported",
        ),
        (
            lambda document: _selection_mapping(document).__setitem__(
                "policy", "selected_evidence_only"
            ),
            "request_selection_policy_unsupported",
        ),
        (
            lambda document: _request_mapping(document).__setitem__(
                "mission_id", "mis_ffffffffffffffffffffffffffffffff"
            ),
            "request_digest_mismatch",
        ),
    ],
)
def test_loader_distinguishes_protocol_version_policy_and_digest_failures(
    mutation: object,
    expected_code: str,
    tmp_path: Path,
) -> None:
    document = _golden_document()
    assert callable(mutation)
    mutation(document)
    target = _write_document(tmp_path, document)

    _load_failure(target, expected_code)


@pytest.mark.security
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mission_id", "/tmp/private-mission"),
        ("mission_id", "https://coordinator.invalid/mission"),
        ("mission_id", "sk-proj-PRIVATE_CREDENTIAL"),
        ("claim_id", "../../private-claim"),
        ("claim_id", "https://coordinator.invalid/claim"),
        ("claim_id", "ghp_PRIVATE_CREDENTIAL"),
    ],
)
def test_path_url_and_credential_shaped_identifiers_are_rejected_without_reflection(
    field: str,
    value: str,
    tmp_path: Path,
) -> None:
    document = _golden_document()
    _request_mapping(document)[field] = value
    target = _write_document(tmp_path, document, name="PRIVATE_PATH.json")

    error = _load_failure(target, "request_invalid")

    assert value not in str(error)
    assert str(target) not in str(error)


@pytest.mark.security
@pytest.mark.parametrize(
    "authority_field",
    ["actor_id", "authorized", "approval", "run_id", "callback_url", "credential"],
)
def test_request_rejects_authority_and_coordination_fields(
    authority_field: str,
    tmp_path: Path,
) -> None:
    document = _golden_document()
    _request_mapping(document)[authority_field] = "PRIVATE_AUTHORITY_SENTINEL"
    target = _write_document(tmp_path, document)

    error = _load_failure(target, "request_invalid")

    assert "PRIVATE_AUTHORITY_SENTINEL" not in str(error)


@pytest.mark.security
def test_request_rejects_path_url_and_credential_shaped_citation_id(tmp_path: Path) -> None:
    for index, value in enumerate(
        ("/tmp/evidence", "https://coordinator.invalid/evidence", "sk-private-evidence")
    ):
        document = _golden_document()
        _selection_mapping(document)["expected_active_citation_ids"] = [value]
        target = _write_document(tmp_path, document, name=f"invalid-{index}.json")

        error = _load_failure(target, "request_invalid")

        assert value not in str(error)


@pytest.mark.security
def test_request_reader_rejects_final_and_parent_symlinks(tmp_path: Path) -> None:
    final_link = tmp_path / "request-link.json"
    final_link.symlink_to(_GOLDEN)
    _load_failure(final_link, "request_input_symlink")

    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "request.json").write_bytes(_GOLDEN.read_bytes())
    parent_link = tmp_path / "linked"
    parent_link.symlink_to(actual, target_is_directory=True)
    _load_failure(parent_link / "request.json", "request_input_symlink")


@pytest.mark.security
def test_request_reader_rejects_parent_segments_before_normalization(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "request.json").write_bytes(_GOLDEN.read_bytes())
    elsewhere = tmp_path / "elsewhere"
    nested = elsewhere / "nested"
    nested.mkdir(parents=True)
    (elsewhere / "request.json").write_text("not selected", encoding="utf-8")
    (root / "linked").symlink_to(nested, target_is_directory=True)

    ambiguous = root / "linked" / ".." / "request.json"

    _load_failure(ambiguous, "request_input_unsafe")


@pytest.mark.security
@pytest.mark.parametrize(
    ("kind", "expected_code"),
    [
        ("missing", "request_input_not_found"),
        ("directory", "request_input_unsafe"),
        ("fifo", "request_input_unsafe"),
    ],
)
def test_request_reader_rejects_missing_and_nonregular_files_without_blocking(
    kind: str,
    expected_code: str,
    tmp_path: Path,
) -> None:
    target = tmp_path / "request-input"
    if kind == "directory":
        target.mkdir()
    elif kind == "fifo":
        os.mkfifo(target)

    _load_failure(target, expected_code)


@pytest.mark.security
@pytest.mark.skipif(not hasattr(os, "O_PATH"), reason="Linux O_PATH boundary")
def test_request_reader_classifies_device_without_reading_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_open = os.open
    device_open_flags: list[int] = []
    opened_paths: list[str] = []

    def recording_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened_paths.append(os.fsdecode(path))
        if os.fsdecode(path) == "null":
            device_open_flags.append(flags)
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_file_module.os, "open", recording_open)

    _load_failure(Path(os.devnull), "request_input_unsafe")

    assert len(device_open_flags) == 1
    assert device_open_flags[0] & os.O_PATH
    assert not any(path.startswith("/proc/self/fd/") for path in opened_paths)


@pytest.mark.security
def test_request_reader_rejects_content_change_between_pinned_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def changed(_descriptor: int, *, max_bytes: int) -> bytes:
        assert max_bytes == MAX_RESEARCH_REQUEST_BYTES
        return b"changed"

    monkeypatch.setattr(safe_file_module, "_reread_bounded", changed)

    _load_failure(_GOLDEN, "request_input_changed")
