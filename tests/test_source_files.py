from __future__ import annotations

import os
from pathlib import Path

import pytest

import minerva.sources.files as source_files
from minerva.sources.files import (
    SecretCategory,
    SourceFileError,
    read_local_utf8,
    scan_secret_patterns,
)


def _assert_read_error(
    root: Path,
    relative_path: str,
    max_bytes: int,
    expected_code: str,
) -> SourceFileError:
    with pytest.raises(SourceFileError) as caught:
        read_local_utf8(root, relative_path, max_bytes)
    assert caught.value.code == expected_code
    assert str(root) not in str(caught.value)
    if relative_path:
        assert relative_path not in str(caught.value)
    return caught.value


def test_read_local_utf8_accepts_exact_limit_and_preserves_relative_label(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    payload = "Café evidence.\n".encode()
    (nested / "source.txt").write_bytes(payload)

    result = read_local_utf8(tmp_path, "nested/source.txt", len(payload))

    assert result.content == payload
    assert result.original_label == "nested/source.txt"


def test_read_bytes_are_isolated_from_later_original_mutation(tmp_path: Path) -> None:
    original = tmp_path / "source.txt"
    original.write_bytes(b"first immutable snapshot")

    result = read_local_utf8(tmp_path, "source.txt", 100)
    original.write_bytes(b"later changed material")

    assert result.content == b"first immutable snapshot"


@pytest.mark.parametrize(
    "relative_path",
    [
        "",
        ".",
        "..",
        "../outside.txt",
        "nested/../outside.txt",
        "nested/./source.txt",
        "nested//source.txt",
        "/absolute.txt",
        "C:\\private\\source.txt",
        "\\\\server\\share\\source.txt",
        "nested\\source.txt",
        "source.txt\x00ignored",
    ],
)
def test_lexically_unsafe_paths_are_rejected(tmp_path: Path, relative_path: str) -> None:
    _assert_read_error(tmp_path, relative_path, 100, "invalid_path")


def test_missing_root_is_rejected_without_disclosure(tmp_path: Path) -> None:
    root = tmp_path / "private-root-name"

    error = _assert_read_error(root, "source.txt", 100, "invalid_root")

    assert "private-root-name" not in str(error)


def test_root_symlink_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "source.txt").write_text("evidence", encoding="utf-8")
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(actual, target_is_directory=True)

    _assert_read_error(linked_root, "source.txt", 100, "invalid_root")


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    _assert_read_error(tmp_path, "missing-private-name.txt", 100, "not_found")


def test_parent_symlink_is_rejected_even_when_it_points_inside_root(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    (actual / "source.txt").write_text("evidence", encoding="utf-8")
    (tmp_path / "linked").symlink_to(actual, target_is_directory=True)

    _assert_read_error(tmp_path, "linked/source.txt", 100, "symlink_not_allowed")


def test_final_symlink_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "actual.txt").write_text("evidence", encoding="utf-8")
    (tmp_path / "linked.txt").symlink_to("actual.txt")

    _assert_read_error(tmp_path, "linked.txt", 100, "symlink_not_allowed")


def test_directory_is_not_accepted_as_a_source(tmp_path: Path) -> None:
    (tmp_path / "directory").mkdir()

    _assert_read_error(tmp_path, "directory", 100, "not_regular_file")


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_bytes(b"valid prefix\xffinvalid")

    _assert_read_error(tmp_path, "source.txt", 100, "invalid_utf8")


def test_nul_byte_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_bytes(b"evidence\x00hidden")

    _assert_read_error(tmp_path, "source.txt", 100, "nul_byte")


def test_oversized_file_is_rejected_from_metadata(tmp_path: Path) -> None:
    (tmp_path / "source.txt").write_bytes(b"123456")

    _assert_read_error(tmp_path, "source.txt", 5, "source_too_large")


def test_streaming_limit_still_rejects_when_initial_size_is_underreported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    target.write_bytes(b"123456")
    original_open = source_files._open_regular_file

    def open_with_underreported_size(
        parent_fd: int,
        name: str,
    ) -> tuple[int, os.stat_result]:
        descriptor, metadata = original_open(parent_fd, name)
        values = list(metadata)
        values[6] = 0
        return descriptor, os.stat_result(values)

    monkeypatch.setattr(source_files, "_open_regular_file", open_with_underreported_size)

    _assert_read_error(tmp_path, "source.txt", 5, "source_too_large")


def test_identity_or_content_change_during_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    target.write_bytes(b"original evidence")
    initial = target.stat()
    original_read = source_files._read_bounded
    read_count = 0

    def read_then_mutate(descriptor: int, max_bytes: int) -> bytes:
        nonlocal read_count
        result = original_read(descriptor, max_bytes)
        if read_count == 0:
            replacement = b"modified evidence"
            assert len(replacement) == len(result)
            target.write_bytes(replacement)
            os.utime(target, ns=(initial.st_atime_ns, initial.st_mtime_ns))
        read_count += 1
        return result

    monkeypatch.setattr(source_files, "_read_bounded", read_then_mutate)
    monkeypatch.setattr(
        source_files,
        "_file_version",
        lambda metadata: (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            initial.st_mtime_ns,
            initial.st_ctime_ns,
        ),
    )

    _assert_read_error(tmp_path, "source.txt", 100, "source_changed")


def test_unlink_and_recreate_during_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    payload = b"original evidence"
    target.write_bytes(payload)
    initial = target.stat()
    original_read = source_files._read_bounded
    replaced = False

    def read_then_replace(descriptor: int, max_bytes: int) -> bytes:
        nonlocal replaced
        result = original_read(descriptor, max_bytes)
        if not replaced:
            opened = os.fstat(descriptor)
            target.unlink()
            target.write_bytes(payload)
            os.utime(target, ns=(initial.st_atime_ns, initial.st_mtime_ns))
            replacement = os.stat(target, follow_symlinks=False)
            assert replacement.st_size == opened.st_size
            assert (replacement.st_dev, replacement.st_ino) != (
                opened.st_dev,
                opened.st_ino,
            )
            replaced = True
        return result

    monkeypatch.setattr(source_files, "_read_bounded", read_then_replace)
    monkeypatch.setattr(
        source_files,
        "_file_version",
        lambda metadata: (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            initial.st_mtime_ns,
            initial.st_ctime_ns,
        ),
    )

    _assert_read_error(tmp_path, "source.txt", 100, "source_changed")
    assert target.read_bytes() == payload


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        (
            "-----BEGIN PRIVATE KEY-----\nsynthetic material\n-----END PRIVATE KEY-----",
            SecretCategory.PRIVATE_KEY,
        ),
        ("token=" + "ghp_" + "A" * 36, SecretCategory.COMMON_TOKEN),
        ('client_secret = "synthetic-credential-value-123"', SecretCategory.SECRET_ASSIGNMENT),
    ],
)
def test_secret_scanner_returns_category_only(
    payload: str,
    category: SecretCategory,
) -> None:
    result = scan_secret_patterns(payload)

    assert result is category
    assert payload not in repr(result)


@pytest.mark.parametrize(
    "payload",
    [
        "api_key = ${MINERVA_API_KEY}",
        "password = changeme",
        "token: Optional[str]",
        "Ordinary research prose mentioning tokens and secrets.",
    ],
)
def test_secret_scanner_avoids_common_placeholders_and_prose(payload: str) -> None:
    assert scan_secret_patterns(payload) is None


def test_secret_rejection_never_leaks_value_or_paths(tmp_path: Path) -> None:
    secret_value = "ghp_" + "Z" * 36
    private_name = "private-client-notes.txt"
    (tmp_path / private_name).write_text(secret_value, encoding="utf-8")

    error = _assert_read_error(tmp_path, private_name, 100, "secret_detected")

    assert error.category is SecretCategory.COMMON_TOKEN
    assert secret_value not in str(error)
    assert secret_value not in repr(error)
