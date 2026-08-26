"""Tests for repo_utilities.extract."""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from repo_utilities.extract import DecompressionError, _get_compression_mode, extract, is_safe_path


@pytest.mark.parametrize(
    ("name", "mode"),
    [
        ("archive.tar", "r"),
        ("archive.tar.gz", "r:gz"),
        ("archive.tar.bz2", "r:bz2"),
        # ".tar" must literally appear as one of the suffixes, so the short
        # forms only resolve to "r:gz"/"r:bz2" via the unusual combined
        # ".tar.tgz"/".tar.tbz2" suffix chain, not the bare ".tgz"/".tbz2".
        ("archive.tar.tgz", "r:gz"),
        ("archive.tar.tbz2", "r:bz2"),
    ],
)
def test_get_compression_mode(name: str, mode: str) -> None:
    assert _get_compression_mode(name) == mode


def test_get_compression_mode_raises_for_non_tarball() -> None:
    with pytest.raises(DecompressionError, match="Not a tarball"):
        _get_compression_mode("archive.zip")


def test_get_compression_mode_raises_for_unsupported_tar_compression() -> None:
    # ".zst" is an allowed extension and combines with ".tar", but no
    # compression mode for it is implemented (tarfile has no "r:zst").
    with pytest.raises(DecompressionError, match="Unknown compression mode"):
        _get_compression_mode("archive.tar.zst")


@pytest.mark.parametrize("name", ["archive.tgz", "archive.tbz2"])
def test_get_compression_mode_rejects_bare_short_suffix(name: str) -> None:
    # Despite the docstring's claim that ".tgz"/".tbz2" are supported, the
    # implementation requires ".tar" to appear among the suffixes, so a
    # filename ending only in the short form is rejected as "not a tarball".
    with pytest.raises(DecompressionError, match="Not a tarball"):
        _get_compression_mode(name)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("relative/path.txt", True),
        ("file.txt", True),
        ("/absolute/path.txt", False),
        ("../escape.txt", False),
        ("nested/../../escape.txt", False),
    ],
)
def test_is_safe_path(path: str, expected: bool) -> None:
    assert is_safe_path(path) is expected


def make_tarball(tmp_path: Path, name: str = "archive.tar.gz") -> Path:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "a.txt").write_text("a", "utf-8")
    (src_dir / "b.txt").write_text("b", "utf-8")
    sub = src_dir / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c", "utf-8")

    tarball = tmp_path / name
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(src_dir, arcname=".")
    return tarball


def test_extract_extracts_all_members_to_target(tmp_path: Path) -> None:
    tarball = make_tarball(tmp_path)
    target = tmp_path / "out"
    target.mkdir()

    extracted = extract(tarball, target)

    names = {p.relative_to(target) for p in extracted}
    assert Path("a.txt") in names
    assert Path("b.txt") in names
    assert Path("sub/c.txt") in names
    assert (target / "a.txt").read_text("utf-8") == "a"


def test_extract_defaults_target_to_parent_of_src(tmp_path: Path) -> None:
    tarball = make_tarball(tmp_path)

    extract(tarball)

    assert (tmp_path / "a.txt").exists()
    assert (tmp_path / "sub" / "c.txt").exists()


def test_extract_filters_by_glob(tmp_path: Path) -> None:
    tarball = make_tarball(tmp_path)
    target = tmp_path / "out"
    target.mkdir()

    extracted = extract(tarball, target, glob="*.txt")

    names = {p.name for p in extracted}
    assert names == {"a.txt", "b.txt", "c.txt"}


def test_extract_skips_unsafe_members(tmp_path: Path) -> None:
    tarball = tmp_path / "malicious.tar"
    with tarfile.open(tarball, "w") as tar:
        info = tarfile.TarInfo(name="../evil.txt")
        data = b"evil"
        info.size = len(data)
        import io

        tar.addfile(info, io.BytesIO(data))

        safe_info = tarfile.TarInfo(name="safe.txt")
        safe_data = b"safe"
        safe_info.size = len(safe_data)
        tar.addfile(safe_info, io.BytesIO(safe_data))

    target = tmp_path / "out"
    target.mkdir()

    extracted = extract(tarball, target)

    assert len(extracted) == 1
    assert extracted[0].name == "safe.txt"
    assert not (tmp_path / "evil.txt").exists()
