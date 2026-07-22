"""Descriptor-relative, bounded reads for local UTF-8 source files."""

from __future__ import annotations

import contextlib
import errno
import os
import re
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Never

__all__ = [
    "LocalUtf8File",
    "SecretCategory",
    "SourceFileError",
    "SourceFileErrorCode",
    "read_local_utf8",
    "scan_secret_patterns",
]

_READ_CHUNK_BYTES = 64 * 1024


class SecretCategory(StrEnum):
    """High-confidence secret categories recognized during source import."""

    PRIVATE_KEY = "private_key"
    COMMON_TOKEN = "common_token"
    SECRET_ASSIGNMENT = "secret_assignment"


class SourceFileErrorCode(StrEnum):
    """Stable, presentation-safe failure codes for local source reads."""

    INVALID_ROOT = "invalid_root"
    INVALID_PATH = "invalid_path"
    NOT_FOUND = "not_found"
    SYMLINK_NOT_ALLOWED = "symlink_not_allowed"
    NOT_REGULAR_FILE = "not_regular_file"
    SOURCE_TOO_LARGE = "source_too_large"
    SOURCE_READ_FAILED = "source_read_failed"
    SOURCE_CHANGED = "source_changed"
    INVALID_UTF8 = "invalid_utf8"
    NUL_BYTE = "nul_byte"
    SECRET_DETECTED = "secret_detected"


_ERROR_MESSAGES: dict[SourceFileErrorCode, str] = {
    SourceFileErrorCode.INVALID_ROOT: "the selected import root is unavailable",
    SourceFileErrorCode.INVALID_PATH: "the submitted relative path is invalid",
    SourceFileErrorCode.NOT_FOUND: "the selected source file does not exist",
    SourceFileErrorCode.SYMLINK_NOT_ALLOWED: "symbolic links are not accepted for import",
    SourceFileErrorCode.NOT_REGULAR_FILE: "only regular files can be imported",
    SourceFileErrorCode.SOURCE_TOO_LARGE: "the selected source exceeds the import limit",
    SourceFileErrorCode.SOURCE_READ_FAILED: "the selected source could not be read safely",
    SourceFileErrorCode.SOURCE_CHANGED: "the selected source changed during import",
    SourceFileErrorCode.INVALID_UTF8: "the selected source is not valid UTF-8",
    SourceFileErrorCode.NUL_BYTE: "the selected source contains a NUL byte",
    SourceFileErrorCode.SECRET_DETECTED: "the selected source matches a blocked secret pattern",
}


class SourceFileError(Exception):
    """A path- and content-free domain error suitable for API presentation."""

    code: str
    category: SecretCategory | None

    def __init__(
        self,
        code: SourceFileErrorCode,
        *,
        category: SecretCategory | None = None,
    ) -> None:
        self.code = code.value
        self.category = category
        super().__init__(_ERROR_MESSAGES[code])


@dataclass(frozen=True, slots=True)
class LocalUtf8File:
    """An immutable source read plus its validated root-relative label."""

    content: bytes
    original_label: str


_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z0-9][A-Z0-9 -]* )?PRIVATE KEY-----",
    re.IGNORECASE,
)

_COMMON_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{30,255}(?![A-Za-z0-9_])"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{40,255}(?![A-Za-z0-9_])"),
    re.compile(r"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{10,255}(?![A-Za-z0-9-])"),
    re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9_-])sk_(?:live|test)_[A-Za-z0-9]{16,255}(?![A-Za-z0-9_-])"),
    re.compile(
        r"(?<![A-Za-z0-9_-])sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,255}"
        r"(?![A-Za-z0-9_-])"
    ),
    re.compile(
        r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
        r"[A-Za-z0-9_-]{10,}(?![A-Za-z0-9_-])"
    ),
)

_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?:^|[,{][ \t]*)
    (?:export[ \t]+)?
    ["']?
    (?:
        api[_-]?key
        | auth[_-]?token
        | access[_-]?token
        | refresh[_-]?token
        | private[_-]?token
        | client[_-]?secret
        | secret[_-]?access[_-]?key
        | password
        | passwd
        | secret
        | token
    )
    ["']?
    [ \t]*(?:=|:)[ \t]*
    (?P<value>
        "(?:[^"\\\r\n]|\\.)*"
        | '(?:[^'\\\r\n]|\\.)*'
        | [^,\s#}\r\n][^,#}\r\n]*
    )
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)

_PLACEHOLDER_VALUES = frozenset(
    {
        "changeme",
        "change-me",
        "dummy",
        "example",
        "example-value",
        "none",
        "not-a-secret",
        "null",
        "password",
        "placeholder",
        "redacted",
        "replace-me",
        "secret",
        "test",
        "token",
        "unused",
        "your-secret-here",
        "your-token-here",
    }
)
_PLACEHOLDER_MARKERS = (
    "changeme",
    "dummy",
    "example",
    "not-a-secret",
    "placeholder",
    "redacted",
    "replace-me",
    "your-secret",
    "your-token",
)
_REFERENCE_PREFIXES = (
    "${",
    "$(",
    "<",
    "{{",
    "annotated[",
    "env(",
    "field(",
    "getenv(",
    "optional[",
    "os.environ",
    "os.getenv",
    "settings.",
)


def scan_secret_patterns(data: bytes | str) -> SecretCategory | None:
    """Return only a secret category, never the matching material.

    This is intentionally a conservative defense-in-depth scan. Invalid byte input is
    outside this helper's UTF-8 contract and yields no classification; the source reader
    performs strict UTF-8 validation before calling it.
    """

    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    else:
        text = data

    if _PRIVATE_KEY_PATTERN.search(text) is not None:
        return SecretCategory.PRIVATE_KEY
    if any(pattern.search(text) is not None for pattern in _COMMON_TOKEN_PATTERNS):
        return SecretCategory.COMMON_TOKEN
    if any(
        not _is_placeholder_assignment(match.group("value"))
        for match in _SECRET_ASSIGNMENT_PATTERN.finditer(text)
    ):
        return SecretCategory.SECRET_ASSIGNMENT
    return None


def read_local_utf8(root: Path, relative_path: str, max_bytes: int) -> LocalUtf8File:
    """Safely snapshot one regular UTF-8 file beneath an explicit directory root.

    Every submitted path component is opened relative to a directory descriptor with
    symlink following disabled. The returned bytes are independent of later mutations
    to the original file.
    """

    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)

    components, original_label = _validate_relative_path(relative_path)
    directory_fd: int | None = None
    file_fd: int | None = None

    try:
        directory_fd = _open_root(root)
        for component in components[:-1]:
            next_fd = _open_child_directory(directory_fd, component)
            _safe_close(directory_fd)
            directory_fd = next_fd

        file_fd, before = _open_regular_file(directory_fd, components[-1])
        if before.st_size > max_bytes:
            raise SourceFileError(SourceFileErrorCode.SOURCE_TOO_LARGE)

        content = _read_bounded(file_fd, max_bytes)
        _verify_unchanged(directory_fd, components[-1], file_fd, before)
    finally:
        _safe_close(file_fd)
        _safe_close(directory_fd)

    if b"\0" in content:
        raise SourceFileError(SourceFileErrorCode.NUL_BYTE)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise SourceFileError(SourceFileErrorCode.INVALID_UTF8) from None

    category = scan_secret_patterns(text)
    if category is not None:
        raise SourceFileError(SourceFileErrorCode.SECRET_DETECTED, category=category)
    return LocalUtf8File(content=content, original_label=original_label)


def _validate_relative_path(relative_path: str) -> tuple[tuple[str, ...], str]:
    if not isinstance(relative_path, str) or not relative_path or "\0" in relative_path:
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)
    if "\\" in relative_path:
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)

    posix_path = PurePosixPath(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if posix_path.is_absolute() or windows_path.is_absolute() or windows_path.drive:
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)

    components = tuple(relative_path.split("/"))
    if not components or any(component in {"", ".", ".."} for component in components):
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)
    try:
        relative_path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH) from None
    return components, "/".join(components)


def _open_root(root: Path) -> int:
    try:
        before = os.stat(root, follow_symlinks=False)
    except OSError:
        raise SourceFileError(SourceFileErrorCode.INVALID_ROOT) from None
    if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise SourceFileError(SourceFileErrorCode.INVALID_ROOT)

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(root, flags)
    except OSError:
        raise SourceFileError(SourceFileErrorCode.INVALID_ROOT) from None
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise SourceFileError(SourceFileErrorCode.INVALID_ROOT)
        if not _same_identity(before, opened):
            raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)
    except BaseException:
        _safe_close(descriptor)
        raise
    return descriptor


def _open_child_directory(parent_fd: int, component: str) -> int:
    before = _stat_entry(parent_fd, component)
    if stat.S_ISLNK(before.st_mode):
        raise SourceFileError(SourceFileErrorCode.SYMLINK_NOT_ALLOWED)
    if not stat.S_ISDIR(before.st_mode):
        raise SourceFileError(SourceFileErrorCode.INVALID_PATH)

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        descriptor = os.open(component, flags, dir_fd=parent_fd)
    except OSError as error:
        _raise_entry_os_error(error)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
            raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)
    except BaseException:
        _safe_close(descriptor)
        raise
    return descriptor


def _open_regular_file(parent_fd: int, name: str) -> tuple[int, os.stat_result]:
    before = _stat_entry(parent_fd, name)
    if stat.S_ISLNK(before.st_mode):
        raise SourceFileError(SourceFileErrorCode.SYMLINK_NOT_ALLOWED)
    if not stat.S_ISREG(before.st_mode):
        raise SourceFileError(SourceFileErrorCode.NOT_REGULAR_FILE)

    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    if hasattr(os, "O_NOCTTY"):
        flags |= os.O_NOCTTY
    try:
        descriptor = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        _raise_entry_os_error(error)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise SourceFileError(SourceFileErrorCode.NOT_REGULAR_FILE)
        if not _same_identity(before, opened):
            raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)
    except BaseException:
        _safe_close(descriptor)
        raise
    return descriptor, opened


def _stat_entry(parent_fd: int, name: str) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError as error:
        _raise_entry_os_error(error)


def _raise_entry_os_error(error: OSError) -> Never:
    if error.errno == errno.ENOENT:
        code = SourceFileErrorCode.NOT_FOUND
    elif error.errno == errno.ELOOP:
        code = SourceFileErrorCode.SYMLINK_NOT_ALLOWED
    elif error.errno == errno.ESTALE:
        code = SourceFileErrorCode.SOURCE_CHANGED
    elif error.errno == errno.ENOTDIR:
        code = SourceFileErrorCode.INVALID_PATH
    else:
        code = SourceFileErrorCode.SOURCE_READ_FAILED
    raise SourceFileError(code) from None


def _read_bounded(descriptor: int, max_bytes: int) -> bytes:
    content = bytearray()
    while True:
        allowance = max_bytes + 1 - len(content)
        if allowance <= 0:
            raise SourceFileError(SourceFileErrorCode.SOURCE_TOO_LARGE)
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, allowance))
        except OSError:
            raise SourceFileError(SourceFileErrorCode.SOURCE_READ_FAILED) from None
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > max_bytes:
            raise SourceFileError(SourceFileErrorCode.SOURCE_TOO_LARGE)


def _verify_unchanged(
    parent_fd: int,
    name: str,
    descriptor: int,
    before: os.stat_result,
) -> None:
    try:
        after = os.fstat(descriptor)
    except OSError:
        raise SourceFileError(SourceFileErrorCode.SOURCE_READ_FAILED) from None
    if _file_version(before) != _file_version(after):
        raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)

    try:
        current_entry = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED) from None
    if not stat.S_ISREG(current_entry.st_mode):
        raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)
    if _file_version(before) != _file_version(current_entry):
        raise SourceFileError(SourceFileErrorCode.SOURCE_CHANGED)


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


def _is_placeholder_assignment(value: str) -> bool:
    candidate = value.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {'"', "'"}:
        candidate = candidate[1:-1].strip()
    lowered = candidate.casefold()
    normalized = re.sub(r"[\s_.]+", "-", lowered)
    if len(candidate) < 8:
        return True
    if normalized in _PLACEHOLDER_VALUES:
        return True
    if any(marker in normalized for marker in _PLACEHOLDER_MARKERS):
        return True
    return lowered.startswith(_REFERENCE_PREFIXES)


def _safe_close(descriptor: int | None) -> None:
    if descriptor is None:
        return
    with contextlib.suppress(OSError):
        os.close(descriptor)
