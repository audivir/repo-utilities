"""Tests for repo_utilities.utils."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from repo_utilities.utils import (
    EMPTY_HASH,
    change_cwd,
    checksum,
    find_common_parent,
    short_checksum,
    symlinker,
)


def test_change_cwd_restores_previous_dir(tmp_path: Path) -> None:
    original = Path.cwd()
    with change_cwd(tmp_path):
        assert Path.cwd() == tmp_path.resolve()
    assert Path.cwd() == original


def test_change_cwd_restores_on_exception(tmp_path: Path) -> None:
    original = Path.cwd()
    with pytest.raises(ValueError, match="boom"), change_cwd(tmp_path):
        raise ValueError("boom")
    assert Path.cwd() == original


def test_checksum_matches_hashlib_for_small_file(tmp_path: Path) -> None:
    file = tmp_path / "small.txt"
    content = b"hello world"
    file.write_bytes(content)

    full_hash, short_hash = checksum(file)

    expected = hashlib.sha256(content).hexdigest()
    assert full_hash == expected
    # A file smaller than FOUR_MB is fully read in a single chunk, so the
    # short (first-4MB) hash equals the full hash.
    assert short_hash == expected


def test_checksum_short_hash_differs_from_full_for_large_file(tmp_path: Path) -> None:
    file = tmp_path / "large.bin"
    # Build a file spanning two read chunks so the short hash (first chunk
    # only) is genuinely different from the full hash.
    from repo_utilities.utils import FOUR_MB

    first_chunk = b"a" * FOUR_MB
    second_chunk = b"b" * 10
    file.write_bytes(first_chunk + second_chunk)

    full_hash, short_hash = checksum(file)

    assert short_hash == hashlib.sha256(first_chunk).hexdigest()
    assert full_hash == hashlib.sha256(first_chunk + second_chunk).hexdigest()
    assert full_hash != short_hash


def test_checksum_empty_file_returns_empty_hash_constant(tmp_path: Path) -> None:
    file = tmp_path / "empty.txt"
    file.write_bytes(b"")

    full_hash, short_hash = checksum(file)

    assert full_hash == hashlib.sha256(b"").hexdigest()
    # The loop body never runs for an empty file, so short_hash keeps its
    # EMPTY_HASH initializer instead of being computed.
    assert short_hash == EMPTY_HASH


def test_short_checksum_only_returns_short_hash(tmp_path: Path) -> None:
    file = tmp_path / "small.txt"
    content = b"hello"
    file.write_bytes(content)

    result = short_checksum(file)

    assert result == hashlib.sha256(content).hexdigest()


def test_checksum_short_only_skips_full_hash_computation(tmp_path: Path) -> None:
    file = tmp_path / "small.txt"
    file.write_bytes(b"hello")

    full_hash, _ = checksum(file, short_only=True)

    assert full_hash == ""


def test_find_common_parent_of_sibling_paths(tmp_path: Path) -> None:
    a = tmp_path / "a" / "x.txt"
    b = tmp_path / "b" / "y.txt"

    result = find_common_parent(a, b)

    assert result == tmp_path


def test_find_common_parent_no_overlap_returns_root() -> None:
    # Both are absolute, so "/" is still a shared leading part even though
    # nothing below it matches.
    result = find_common_parent(Path("/a/b/c"), Path("/x/y/z"))

    assert result == Path("/")


def test_find_common_parent_single_path_is_itself(tmp_path: Path) -> None:
    result = find_common_parent(tmp_path)

    assert result == tmp_path


def test_symlinker_creates_relative_symlink(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    target_dir = tmp_path / "deep" / "nested"
    src_dir.mkdir()
    target_dir.mkdir(parents=True)

    src_file = src_dir / "file.txt"
    src_file.write_text("content", "utf-8")
    target_file = target_dir / "link.txt"

    symlinker(src_file, target_file)

    assert target_file.is_symlink()
    # It must be relative (not an absolute path baked into the symlink),
    # so the repo remains relocatable.
    assert not Path(target_file.readlink()).is_absolute()
    assert target_file.read_text("utf-8") == "content"


def test_symlinker_relative_path_uses_parent_depth(tmp_path: Path) -> None:
    src_file = tmp_path / "src.txt"
    src_file.write_text("data", "utf-8")
    target_dir = tmp_path / "a" / "b" / "c"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "link.txt"

    symlinker(src_file, target_file)

    link = target_file.readlink()
    assert str(link) == "../../../src.txt"
