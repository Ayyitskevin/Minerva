"""Descriptor-pinned, bounded reads for untrusted local artifact files."""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from enum import StrEnum
from pathlib import Path
from typing import Never

_READ_CHUNK_BYTES = 65_536


class ArtifactReadFailureKind(StrEnum):
    """Stable, content-free reasons an artifact read can fail."""

    UNSAFE = "unsafe"
    SYMLINK = "symlink"
    NOT_FOUND = "not_found"
    UNREADABLE = "unreadable"
    CHANGED = "changed"
    TOO_LARGE = "too_large"


class ArtifactReadError(Exception):
    """A safe artifact-read failure that never reflects the selected path."""

    def __init__(self, kind: ArtifactReadFailureKind) -> None:
        super().__init__(kind.value)
        self.kind = kind


def read_stable_artifact_bytes(path: Path, *, max_bytes: int) -> bytes:
    """Read one regular file twice through a pinned descriptor.

    Symbolic links and raw parent-directory components are rejected. The
    metadata size is checked before reading, and reads are bounded to one byte
    beyond ``max_bytes`` so a stale size cannot bypass the limit.
    """

    if max_bytes < 0:
        raise ValueError("max_bytes must be non-negative")

    try:
        raw_path = os.fspath(path)
        candidate = Path(raw_path)
        if "\0" in raw_path or os.pardir in candidate.parts:
            _fail(ArtifactReadFailureKind.UNSAFE)
        absolute = candidate if candidate.is_absolute() else Path.cwd() / candidate
    except (OSError, TypeError, ValueError):
        _fail(ArtifactReadFailureKind.UNSAFE)

    components = absolute.parts[1:]
    if absolute.anchor != os.sep or not components:
        _fail(ArtifactReadFailureKind.UNSAFE)

    directory_fd: int | None = None
    file_fd: int | None = None
    try:
        directory_fd = _open_root()
        for component in components[:-1]:
            next_fd = _open_directory(directory_fd, component)
            _safe_close(directory_fd)
            directory_fd = next_fd

        file_fd, before = _open_regular_file(directory_fd, components[-1])
        if before.st_size > max_bytes:
            _fail(ArtifactReadFailureKind.TOO_LARGE)
        content = _read_bounded(file_fd, max_bytes=max_bytes)
        _verify_unchanged(directory_fd, components[-1], file_fd, before)
        if _reread_bounded(file_fd, max_bytes=max_bytes) != content:
            _fail(ArtifactReadFailureKind.CHANGED)
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
        _fail(ArtifactReadFailureKind.UNREADABLE)


def _open_directory(parent_fd: int, name: str) -> int:
    before = _stat_entry(parent_fd, name)
    if stat.S_ISLNK(before.st_mode):
        _fail(ArtifactReadFailureKind.SYMLINK)
    if not stat.S_ISDIR(before.st_mode):
        _fail(ArtifactReadFailureKind.UNSAFE)
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
        _fail(ArtifactReadFailureKind.CHANGED)
    if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
        _safe_close(descriptor)
        _fail(ArtifactReadFailureKind.CHANGED)
    return descriptor


def _open_regular_file(parent_fd: int, name: str) -> tuple[int, os.stat_result]:
    path_only_flag = getattr(os, "O_PATH", None)
    if path_only_flag is None:
        _fail(ArtifactReadFailureKind.UNREADABLE)

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
            _fail(ArtifactReadFailureKind.CHANGED)
        if stat.S_ISLNK(anchored.st_mode):
            _fail(ArtifactReadFailureKind.SYMLINK)
        if not stat.S_ISREG(anchored.st_mode):
            _fail(ArtifactReadFailureKind.UNSAFE)

        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NONBLOCK
        if hasattr(os, "O_NOCTTY"):
            flags |= os.O_NOCTTY
        try:
            descriptor = os.open(f"/proc/self/fd/{anchor_fd}", flags)
        except OSError:
            _fail(ArtifactReadFailureKind.UNREADABLE)
        try:
            opened = os.fstat(descriptor)
        except OSError:
            _safe_close(descriptor)
            _fail(ArtifactReadFailureKind.CHANGED)
        if not stat.S_ISREG(opened.st_mode) or not _same_identity(anchored, opened):
            _safe_close(descriptor)
            _fail(ArtifactReadFailureKind.CHANGED)
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
        _fail(ArtifactReadFailureKind.NOT_FOUND)
    if error.errno == errno.ELOOP:
        _fail(ArtifactReadFailureKind.SYMLINK)
    if error.errno == errno.ESTALE:
        _fail(ArtifactReadFailureKind.CHANGED)
    if error.errno == errno.ENOTDIR:
        _fail(ArtifactReadFailureKind.UNSAFE)
    _fail(ArtifactReadFailureKind.UNREADABLE)


def _read_bounded(descriptor: int, *, max_bytes: int) -> bytes:
    content = bytearray()
    while True:
        allowance = max_bytes + 1 - len(content)
        if allowance <= 0:
            _fail(ArtifactReadFailureKind.TOO_LARGE)
        try:
            chunk = os.read(descriptor, min(_READ_CHUNK_BYTES, allowance))
        except OSError:
            _fail(ArtifactReadFailureKind.UNREADABLE)
        if not chunk:
            return bytes(content)
        content.extend(chunk)
        if len(content) > max_bytes:
            _fail(ArtifactReadFailureKind.TOO_LARGE)


def _reread_bounded(descriptor: int, *, max_bytes: int) -> bytes:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        _fail(ArtifactReadFailureKind.UNREADABLE)
    return _read_bounded(descriptor, max_bytes=max_bytes)


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
        _fail(ArtifactReadFailureKind.CHANGED)
    if (
        not stat.S_ISREG(current.st_mode)
        or _file_version(before) != _file_version(opened)
        or _file_version(before) != _file_version(current)
    ):
        _fail(ArtifactReadFailureKind.CHANGED)


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


def _fail(kind: ArtifactReadFailureKind) -> Never:
    raise ArtifactReadError(kind)
