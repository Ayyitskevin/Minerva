"""Safe file boundary and bounded reports for standalone research packets."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import stat
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

_READ_CHUNK_BYTES = 65_536
_MAX_CLASSIFIED_VALIDATION_ERRORS = 32
_EVIDENCE_STANCES: tuple[EvidenceStance, ...] = (
    "supports",
    "opposes",
    "context",
    "inconclusive",
)


def load_research_packet(path: Path) -> ResearchPacketDocument:
    """Read and verify one regular packet file without following symbolic links."""

    data = _read_stable_packet_bytes(path)
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


def _read_stable_packet_bytes(path: Path) -> bytes:
    try:
        raw_path = os.fspath(path)
        candidate = Path(raw_path)
        if "\0" in raw_path or os.pardir in candidate.parts:
            _fail("packet_input_unsafe", "The research packet input path is unsafe.")
        absolute = candidate if candidate.is_absolute() else Path.cwd() / candidate
    except (OSError, TypeError, ValueError):
        _fail("packet_input_unsafe", "The research packet input path is unsafe.")
    components = absolute.parts[1:]
    if absolute.anchor != os.sep or not components:
        _fail("packet_input_unsafe", "The research packet input path is unsafe.")

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = _open_root()
        for component in components[:-1]:
            next_fd = _open_directory(directory_fd, component)
            _safe_close(directory_fd)
            directory_fd = next_fd

        file_fd, before = _open_regular_file(directory_fd, components[-1])
        if before.st_size > MAX_RESEARCH_PACKET_BYTES:
            _fail(
                "packet_too_large",
                "The research packet exceeds the 20 MiB protocol size limit.",
            )
        content = _read_bounded(file_fd)
        _verify_unchanged(directory_fd, components[-1], file_fd, before)
        if _reread_bounded(file_fd) != content:
            _fail(
                "packet_input_changed",
                "The research packet changed while it was being read.",
            )
        _verify_unchanged(directory_fd, components[-1], file_fd, before)
        return content
    finally:
        _safe_close(file_fd)
        _safe_close(directory_fd)


def _open_root() -> int:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
    try:
        return os.open(os.sep, flags)
    except OSError:
        _fail("packet_input_unreadable", "The research packet could not be read safely.")


def _open_directory(parent_fd: int, name: str) -> int:
    before = _stat_entry(parent_fd, name)
    if stat.S_ISLNK(before.st_mode):
        _fail("packet_input_symlink", "Research packet paths may not use symbolic links.")
    if not stat.S_ISDIR(before.st_mode):
        _fail("packet_input_unsafe", "The research packet input path is unsafe.")
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as error:
        _raise_path_os_error(error)
    try:
        opened = os.fstat(descriptor)
    except OSError:
        _safe_close(descriptor)
        _fail("packet_input_changed", "The research packet path changed while opening.")
    if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
        _safe_close(descriptor)
        _fail("packet_input_changed", "The research packet path changed while opening.")
    return descriptor


def _open_regular_file(parent_fd: int, name: str) -> tuple[int, os.stat_result]:
    path_only_flag = getattr(os, "O_PATH", None)
    if path_only_flag is None:
        _fail("packet_input_unreadable", "The research packet could not be read safely.")

    anchor_fd: int | None = None
    try:
        anchor_fd = os.open(
            name,
            path_only_flag | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
    except OSError as error:
        _raise_path_os_error(error)
    try:
        try:
            anchored = os.fstat(anchor_fd)
        except OSError:
            _fail("packet_input_changed", "The research packet changed while opening.")
        if stat.S_ISLNK(anchored.st_mode):
            _fail("packet_input_symlink", "Research packet paths may not use symbolic links.")
        if not stat.S_ISREG(anchored.st_mode):
            _fail("packet_input_unsafe", "The research packet input must be a regular file.")

        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOCTTY"):
            flags |= os.O_NOCTTY
        try:
            descriptor = os.open(f"/proc/self/fd/{anchor_fd}", flags)
        except OSError:
            _fail("packet_input_unreadable", "The research packet could not be read safely.")
        try:
            opened = os.fstat(descriptor)
        except OSError:
            _safe_close(descriptor)
            _fail("packet_input_changed", "The research packet changed while opening.")
        if not stat.S_ISREG(opened.st_mode) or not _same_identity(anchored, opened):
            _safe_close(descriptor)
            _fail("packet_input_changed", "The research packet changed while opening.")
        return descriptor, opened
    finally:
        _safe_close(anchor_fd)


def _stat_entry(parent_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        _raise_path_os_error(error)


def _raise_path_os_error(error: OSError) -> Never:
    if error.errno == errno.ENOENT:
        _fail("packet_input_not_found", "The research packet input was not found.")
    if error.errno == errno.ELOOP:
        _fail("packet_input_symlink", "Research packet paths may not use symbolic links.")
    if error.errno == errno.ESTALE:
        _fail("packet_input_changed", "The research packet path changed while opening.")
    if error.errno == errno.ENOTDIR:
        _fail("packet_input_unsafe", "The research packet input path is unsafe.")
    _fail("packet_input_unreadable", "The research packet could not be read safely.")


def _read_bounded(descriptor: int) -> bytes:
    content = bytearray()
    while True:
        allowance = MAX_RESEARCH_PACKET_BYTES + 1 - len(content)
        if allowance <= 0:
            _fail(
                "packet_too_large",
                "The research packet exceeds the 20 MiB protocol size limit.",
            )
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, allowance))
        except OSError:
            _fail("packet_input_unreadable", "The research packet could not be read safely.")
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > MAX_RESEARCH_PACKET_BYTES:
            _fail(
                "packet_too_large",
                "The research packet exceeds the 20 MiB protocol size limit.",
            )


def _reread_bounded(descriptor: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        _fail("packet_input_unreadable", "The research packet could not be read safely.")
    return _read_bounded(descriptor)


def _verify_unchanged(
    parent_fd: int,
    name: str,
    descriptor: int,
    before: os.stat_result,
) -> None:
    try:
        opened = os.fstat(descriptor)
        current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        _fail("packet_input_changed", "The research packet changed while it was being read.")
    if (
        not stat.S_ISREG(current.st_mode)
        or _file_version(before) != _file_version(opened)
        or _file_version(before) != _file_version(current)
    ):
        _fail("packet_input_changed", "The research packet changed while it was being read.")


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


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _file_version(result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        result.st_dev,
        result.st_ino,
        result.st_size,
        result.st_mtime_ns,
        result.st_ctime_ns,
    )


def _safe_close(descriptor: int | None) -> None:
    if descriptor is not None:
        with contextlib.suppress(OSError):
            os.close(descriptor)


def _fail(code: str, message: str) -> Never:
    raise IntegrityError(code, message)
