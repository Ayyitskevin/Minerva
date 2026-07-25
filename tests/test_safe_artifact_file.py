"""Error-path coverage for the shared no-follow artifact reader.

Every branch here is a fail-closed guard, so a regression would weaken a
documented security boundary without breaking any happy path. These tests
inject the operating-system failures that the guards exist to catch.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import minerva.integrations.safe_artifact_file as artifact_module
from minerva.integrations.safe_artifact_file import (
    ArtifactReadError,
    ArtifactReadFailureKind,
    read_stable_artifact_bytes,
)

pytestmark = pytest.mark.security


def _read(path: Path, *, max_bytes: int = 4096) -> bytes:
    return read_stable_artifact_bytes(path, max_bytes=max_bytes)


def test_negative_limit_is_a_programming_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_bytes"):
        read_stable_artifact_bytes(tmp_path / "artifact.json", max_bytes=-1)


@pytest.mark.parametrize("name", ["with\0null.json", "../escape.json"])
def test_unsafe_path_shapes_are_rejected_before_any_open(tmp_path: Path, name: str) -> None:
    with pytest.raises(ArtifactReadError) as caught:
        _read(tmp_path / name)

    assert caught.value.kind is ArtifactReadFailureKind.UNSAFE


def test_root_itself_is_rejected() -> None:
    with pytest.raises(ArtifactReadError) as caught:
        _read(Path(os.sep))

    assert caught.value.kind is ArtifactReadFailureKind.UNSAFE


def test_missing_file_is_reported_as_not_found(tmp_path: Path) -> None:
    with pytest.raises(ArtifactReadError) as caught:
        _read(tmp_path / "absent.json")

    assert caught.value.kind is ArtifactReadFailureKind.NOT_FOUND


def test_symlinked_final_target_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_bytes(b"{}")
    link = tmp_path / "link.json"
    link.symlink_to(real)

    with pytest.raises(ArtifactReadError) as caught:
        _read(link)

    assert caught.value.kind is ArtifactReadFailureKind.SYMLINK


def test_symlinked_directory_component_is_refused(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "artifact.json").write_bytes(b"{}")
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(ArtifactReadError) as caught:
        _read(linked_dir / "artifact.json")

    assert caught.value.kind is ArtifactReadFailureKind.SYMLINK


def test_directory_target_is_not_a_readable_artifact(tmp_path: Path) -> None:
    target = tmp_path / "directory"
    target.mkdir()

    with pytest.raises(ArtifactReadError) as caught:
        _read(target)

    assert caught.value.kind is ArtifactReadFailureKind.UNSAFE


def test_non_regular_target_is_refused(tmp_path: Path) -> None:
    fifo = tmp_path / "artifact.json"
    os.mkfifo(fifo)

    with pytest.raises(ArtifactReadError) as caught:
        _read(fifo)

    assert caught.value.kind is ArtifactReadFailureKind.UNSAFE


def test_file_larger_than_the_limit_is_refused_from_metadata(tmp_path: Path) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"x" * 64)

    with pytest.raises(ArtifactReadError) as caught:
        _read(target, max_bytes=16)

    assert caught.value.kind is ArtifactReadFailureKind.TOO_LARGE


def test_content_changing_between_the_two_reads_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second read is the point of the double read: differing bytes fail closed."""

    target = tmp_path / "artifact.json"
    target.write_bytes(b"original")

    def tampered_reread(descriptor: int, *, max_bytes: int) -> bytes:
        return b"tampered"

    monkeypatch.setattr(artifact_module, "_reread_bounded", tampered_reread)

    with pytest.raises(ArtifactReadError) as caught:
        _read(target)

    assert caught.value.kind is ArtifactReadFailureKind.CHANGED


def test_unreadable_reread_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "artifact.json"
    target.write_bytes(b"original")

    def failing_seek(descriptor: int, position: int, whence: int) -> int:
        raise OSError(errno.EIO, "synthetic seek failure")

    monkeypatch.setattr(artifact_module.os, "lseek", failing_seek)

    with pytest.raises(ArtifactReadError) as caught:
        _read(target)

    assert caught.value.kind is ArtifactReadFailureKind.UNREADABLE


def test_file_replaced_between_reads_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical bytes are not enough: the inode must still be the same file."""

    target = tmp_path / "artifact.json"
    target.write_bytes(b"original")
    real_reread = artifact_module._reread_bounded

    def replace_then_reread(descriptor: int, *, max_bytes: int) -> bytes:
        content = real_reread(descriptor, max_bytes=max_bytes)
        target.unlink()
        target.write_bytes(b"original")
        return content

    monkeypatch.setattr(artifact_module, "_reread_bounded", replace_then_reread)

    with pytest.raises(ArtifactReadError) as caught:
        _read(target)

    assert caught.value.kind is ArtifactReadFailureKind.CHANGED


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (errno.ENOENT, ArtifactReadFailureKind.NOT_FOUND),
        (errno.ELOOP, ArtifactReadFailureKind.SYMLINK),
        (errno.ESTALE, ArtifactReadFailureKind.CHANGED),
        (errno.ENOTDIR, ArtifactReadFailureKind.UNSAFE),
        (errno.EACCES, ArtifactReadFailureKind.UNREADABLE),
        (errno.EIO, ArtifactReadFailureKind.UNREADABLE),
    ],
)
def test_operating_system_errors_map_to_stable_kinds(
    number: int,
    expected: ArtifactReadFailureKind,
) -> None:
    with pytest.raises(ArtifactReadError) as caught:
        artifact_module._raise_path_os_error(OSError(number, os.strerror(number)))

    assert caught.value.kind is expected


def test_failure_messages_never_reflect_the_selected_path(tmp_path: Path) -> None:
    """Errors are content-free: the caller's path must not appear in them."""

    secret = tmp_path / "private-research-name.json"

    with pytest.raises(ArtifactReadError) as caught:
        _read(secret)

    rendered = f"{caught.value}{caught.value.kind}"
    assert "private-research-name" not in rendered
    assert str(tmp_path) not in rendered
