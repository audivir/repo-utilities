"""Tests for repo_utilities.apt.build_repo."""

from __future__ import annotations

import gzip
import hashlib
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import repo_utilities.apt.build_repo  # noqa: F401  (registers it in sys.modules)

# `from repo_utilities.apt import build_repo` (and even
# `import repo_utilities.apt.build_repo as build_repo`, which resolves via
# attribute access along the dotted path) would both resolve to the
# `build_repo` *function* re-exported by repo_utilities/apt/__init__.py,
# which shadows the submodule attribute of the same name on the `apt`
# package. Pull the actual module out of sys.modules to get the module
# instead of the function.
build_repo = sys.modules["repo_utilities.apt.build_repo"]


def test_get_packages_hashes_computes_expected_digests(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    packages_file = root / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
    packages_file.parent.mkdir(parents=True)
    packages_content = "Package: foo\n"
    packages_gz_content = gzip.compress(packages_content.encode("utf-8"))

    lines = build_repo.get_packages_hashes(
        [(packages_file, packages_content)],
        [(packages_file.with_suffix(".gz"), packages_gz_content)],
    )

    assert lines[0] == "MD5Sum:"
    md5_line = lines[1]
    expected_md5 = hashlib.md5(packages_content.encode("utf-8")).hexdigest()  # noqa: S324
    assert expected_md5 in md5_line
    assert str(len(packages_content.encode("utf-8"))) in md5_line
    # rel_path is relative to path.parent.parent.parent, i.e. relative to
    # the suite dir ("dists/stable"), not to the repo root.
    assert "main/binary-amd64/Packages" in md5_line

    sha256_header_ix = lines.index("SHA256:")
    sha256_line = lines[sha256_header_ix + 1]
    expected_sha256 = hashlib.sha256(packages_content.encode("utf-8")).hexdigest()
    assert expected_sha256 in sha256_line


def test_get_packages_hashes_covers_both_packages_and_packages_gz(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    packages_file = root / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
    packages_file.parent.mkdir(parents=True)
    packages_gz_file = packages_file.with_suffix(".gz")

    lines = build_repo.get_packages_hashes(
        [(packages_file, "content")], [(packages_gz_file, b"gz-content")]
    )

    joined = "\n".join(lines)
    assert "Packages\n" in joined or "Packages" in joined
    assert "Packages.gz" in joined


def test_create_release_file_contains_expected_headers(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    packages_file = root / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
    packages_file.parent.mkdir(parents=True)
    packages_gz_file = packages_file.with_suffix(".gz")

    data = {
        "amd64": (
            (packages_file, "Package: foo\n"),
            (packages_gz_file, gzip.compress(b"Package: foo\n")),
        )
    }

    release = build_repo.create_release_file(data, "stable")

    assert "Origin: Custom Repository" in release
    assert "Suite: stable" in release
    assert "Codename: stable" in release
    assert "Architectures: amd64" in release
    assert "Components: main" in release
    assert re.search(r"Date: \w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} \+0000", release)
    assert release.endswith("\n")


def test_create_packages_calls_dpkg_scan_packages_and_returns_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    (repo / "dists" / "stable" / "main" / "binary-amd64").mkdir(parents=True)
    (repo / "pool").mkdir()

    class FakeScanner:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        def scan(self) -> None:
            out = Path(str(self.kwargs["output"]))
            out.write_text("Package: mypkg\n", "utf-8")

    monkeypatch.setattr(build_repo, "DpkgScanPackages", FakeScanner)

    packages_file, packages = build_repo.create_packages(repo, None, "stable", "amd64")

    assert packages == "Package: mypkg\n"
    assert packages_file == repo / "dists" / "stable" / "main" / "binary-amd64" / "Packages"


def test_create_packages_filters_out_missing_previous_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    (repo / "dists" / "stable" / "main" / "binary-amd64").mkdir(parents=True)

    captured: dict[str, object] = {}

    class FakeScanner:
        def __init__(self, **kwargs: object) -> None:
            captured["previous"] = kwargs["previous"]

        def scan(self) -> None:
            out = repo / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
            out.write_text("", "utf-8")

    monkeypatch.setattr(build_repo, "DpkgScanPackages", FakeScanner)

    missing_prev = repo / "does_not_exist"
    build_repo.create_packages(repo, missing_prev, "stable", "amd64")

    # A non-existent previous file must be filtered out, collapsing to None.
    assert captured["previous"] is None


def test_create_packages_accepts_sequence_of_previous_and_keeps_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    (repo / "dists" / "stable" / "main" / "binary-amd64").mkdir(parents=True)
    existing_prev = repo / "old_packages"
    existing_prev.write_text("Package: old\n", "utf-8")
    missing_prev = repo / "does_not_exist"

    captured: dict[str, object] = {}

    class FakeScanner:
        def __init__(self, **kwargs: object) -> None:
            captured["previous"] = kwargs["previous"]

        def scan(self) -> None:
            out = repo / "dists" / "stable" / "main" / "binary-amd64" / "Packages"
            out.write_text("", "utf-8")

    monkeypatch.setattr(build_repo, "DpkgScanPackages", FakeScanner)

    # Passed as a plain list (not a single str/PathLike), so the
    # single-item-wrapping branch must be skipped; the missing file must
    # still be filtered out while the existing one is kept.
    build_repo.create_packages(repo, [existing_prev, missing_prev], "stable", "amd64")

    assert captured["previous"] == (str(existing_prev.resolve()),)


def test_create_packages_gz_compresses_content(tmp_path: Path) -> None:
    packages_file = tmp_path / "Packages"
    packages_file.write_text("Package: foo\n", "utf-8")

    packages_gz_file, packages_gz = build_repo.create_packages_gz(packages_file, "Package: foo\n")

    assert packages_gz_file == packages_file.with_suffix(".gz")
    assert gzip.decompress(packages_gz) == b"Package: foo\n"
    assert gzip.decompress(packages_gz_file.read_bytes()) == b"Package: foo\n"


def test_create_packages_gz_skip_update_reads_existing_file(tmp_path: Path) -> None:
    packages_file = tmp_path / "Packages"
    packages_gz_file = packages_file.with_suffix(".gz")
    packages_gz_file.write_bytes(b"already-compressed")

    result_file, result_bytes = build_repo.create_packages_gz(
        packages_file, "unused", skip_update=True
    )

    assert result_file == packages_gz_file
    assert result_bytes == b"already-compressed"


def test_create_repo_writes_release_file_and_removes_stale_signatures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    dists = repo / "dists" / "stable"
    dists.mkdir(parents=True)
    (dists / "Release").write_text("stale", "utf-8")
    (dists / "InRelease").write_text("stale", "utf-8")
    (dists / "Release.gpg").write_text("stale", "utf-8")

    def fake_create_packages(
        repo_arg: Path,  # noqa: ARG001
        previous: object,  # noqa: ARG001
        suite: str,  # noqa: ARG001
        arch: str,
    ) -> tuple[Path, str]:
        packages_file = dists / "main" / f"binary-{arch}" / "Packages"
        packages_file.parent.mkdir(parents=True, exist_ok=True)
        packages_file.write_text(f"Package: {arch}\n", "utf-8")
        return packages_file, f"Package: {arch}\n"

    monkeypatch.setattr(build_repo, "create_packages", fake_create_packages)
    monkeypatch.setattr(
        build_repo,
        "create_packages_gz",
        lambda pf, packages, skip_update=False: (  # noqa: ARG005
            Path(pf).with_suffix(".gz"),
            gzip.compress(packages.encode("utf-8")),
        ),
    )

    build_repo.create_repo(repo, "stable", ["amd64"])

    release_content = (dists / "Release").read_text("utf-8")
    assert "Architectures: amd64" in release_content
    assert "MD5Sum:" in release_content


def test_create_repo_skips_arch_with_no_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "repo"
    (repo / "dists" / "stable").mkdir(parents=True)

    def fake_create_packages(
        repo_arg: Path,  # noqa: ARG001
        previous: object,  # noqa: ARG001
        suite: str,
        arch: str,
    ) -> tuple[Path, str]:
        if arch == "arm64":
            raise ValueError("no packages")
        packages_file = repo / "dists" / suite / "main" / f"binary-{arch}" / "Packages"
        packages_file.parent.mkdir(parents=True, exist_ok=True)
        packages_file.write_text("Package: x\n", "utf-8")
        return packages_file, "Package: x\n"

    monkeypatch.setattr(build_repo, "create_packages", fake_create_packages)
    monkeypatch.setattr(
        build_repo,
        "create_packages_gz",
        lambda pf, packages, skip_update=False: (  # noqa: ARG005
            Path(pf).with_suffix(".gz"),
            gzip.compress(packages.encode("utf-8")),
        ),
    )

    build_repo.create_repo(repo, "stable", ["amd64", "arm64"])

    release_content = (repo / "dists" / "stable" / "Release").read_text("utf-8")
    assert "Architectures: amd64" in release_content
    assert "arm64" not in release_content.split("\n")[5]  # Architectures line


def test_build_repo_symlinks_debs_skips_tarballs_and_signs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_create_repo = MagicMock()
    mock_sign_repo = MagicMock()
    monkeypatch.setattr(build_repo, "create_repo", mock_create_repo)
    monkeypatch.setattr(build_repo.gpg, "sign_repo", mock_sign_repo)

    repo = tmp_path / "repo"
    pkg_dir = tmp_path / "pkgs"
    pkg_dir.mkdir()
    deb = pkg_dir / "foo.deb"
    deb.write_bytes(b"deb-data")
    tarball = pkg_dir / "extra.tar.gz"
    tarball.write_bytes(b"tar-data")

    key = tmp_path / "priv.key"

    build_repo.build_repo(repo, [deb, tarball], key)

    linked = repo / "pool" / "main" / "foo.deb"
    assert linked.is_symlink()
    assert not (repo / "pool" / "main" / "extra.tar.gz").exists()

    for arch in ("all", "amd64", "arm64"):
        assert (repo / "dists" / "stable" / "main" / f"binary-{arch}").is_dir()

    mock_create_repo.assert_called_once_with(repo, "stable", ("all", "amd64", "arm64"))
    mock_sign_repo.assert_called_once_with(repo, repo / "pub.gpg", key, repo)


def test_build_repo_raises_for_unexpected_extension(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bad_pkg = tmp_path / "bad.rpm"
    bad_pkg.write_bytes(b"nope")

    with pytest.raises(ValueError, match="Unexpected file"):
        build_repo.build_repo(repo, [bad_pkg], tmp_path / "key")


def test_build_repo_skips_bare_tar_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(build_repo, "create_repo", MagicMock())
    monkeypatch.setattr(build_repo.gpg, "sign_repo", MagicMock())

    repo = tmp_path / "repo"
    tar_pkg = tmp_path / "extra.tar"
    tar_pkg.write_bytes(b"data")

    build_repo.build_repo(repo, [tar_pkg], tmp_path / "key")

    assert not (repo / "pool" / "main" / "extra.tar").exists()
