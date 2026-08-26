"""Commands for the apt package manager."""

from __future__ import annotations

import gzip
import hashlib
import logging
from datetime import datetime, timezone
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from dpkg_scanpackages import DpkgScanPackages

from repo_utilities import change_cwd, gpg
from repo_utilities.utils import ARCH, symlinker

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from _typeshed import StrPath

logger = logging.getLogger("repo_utilities")


def build_repo(
    repo: StrPath,
    pkgs: Sequence[StrPath],
    key: StrPath,
    suite: str = "stable",
    arches: Sequence[ARCH] = ("all", "amd64", "arm64"),
) -> None:
    """Build the repository for apt packages.

    Args:
        repo: The repository directory.
        pkgs: Locations of deb packages to be linked to the repository.
        key: The private key file for signing the repository.
        suite: The release suite of the packages. Defaults to stable.
        arches: The architecture of the packages. Defaults to amd64.

    Raises:
        FileExistsError: If the public directory already exists.
        ValueError: If an unexpected file is found in the apt packages directory.
    """
    repo = Path(repo)

    for arch in arches:
        binary_dir = f"binary-{arch}"
        binary_path = repo / "dists" / suite / "main" / binary_dir
        binary_path.mkdir(parents=True, exist_ok=True)

    main = repo / "pool" / "main"
    main.mkdir(parents=True, exist_ok=True)
    for raw_pkg in pkgs:
        pkg = Path(raw_pkg).resolve()
        if pkg.suffix != ".deb":
            if pkg.suffix == ".tar" or pkg.suffixes[-2:] == [".tar", ".gz"]:
                continue
            raise ValueError(f"Unexpected file in {pkgs}: {pkg}")
        target_pkg = main / pkg.name
        target_pkg.unlink(missing_ok=True)
        symlinker(pkg, target_pkg)
        logger.debug("Linking %s to %s", pkg, target_pkg)

    create_repo(repo, suite, arches)

    gpg.sign_repo(repo, repo / "pub.gpg", key, repo)


def get_packages_hashes(
    packages: Sequence[tuple[Path, str]], packages_gz: Sequence[tuple[Path, bytes]]
) -> list[str]:
    """Get the hashes for the Packages and Packages.gz files."""
    lines: list[str] = []

    def _hash_func(s: str | bytes, hash_type: Literal["md5", "sha1", "sha256"]) -> str:
        if isinstance(s, str):  # pragma: no cover
            s = s.encode("utf-8")  # callers below already normalize to bytes first
        if hash_type == "md5":
            return hashlib.md5(s).hexdigest()  # noqa: S324
        if hash_type == "sha1":
            return hashlib.sha1(s).hexdigest()  # noqa: S324
        if hash_type == "sha256":
            return hashlib.sha256(s).hexdigest()
        raise ValueError(f"Unknown hash type: {hash_type}")  # pragma: no cover

    header_hashes: list[tuple[str, Callable[[str | bytes], str]]] = [
        ("MD5Sum", lambda x: _hash_func(x, "md5")),
        ("SHA1", lambda x: _hash_func(x, "sha1")),
        ("SHA256", lambda x: _hash_func(x, "sha256")),
    ]
    all_packages = list(zip(packages, packages_gz, strict=True))
    for header, hash_func in header_hashes:
        lines.append(f"{header}:")
        for elem in all_packages:
            for path, raw_content in elem:
                rel_path = path.relative_to(path.parent.parent.parent)
                content = (
                    raw_content.encode("utf-8") if isinstance(raw_content, str) else raw_content
                )
                char_count = len(content)
                hash_str = hash_func(content)
                lines.append(f" {hash_str} {char_count} {rel_path}")

    return lines


def create_release_file(
    data: dict[ARCH, tuple[tuple[Path, str], tuple[Path, bytes]]], suite: str
) -> str:
    """Create the Release file for the apt repository."""
    origin = "Custom Repository"
    label = "Custom"
    codename = suite
    version = "1.0"
    components = "main"
    desc = "A set of packages not available in the official repositories."
    date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    lines = [
        f"Origin: {origin}",
        f"Label: {label}",
        f"Suite: {suite}",
        f"Codename: {codename}",
        f"Version: {version}",
        f"Architectures: {' '.join(data)}",
        f"Components: {components}",
        f"Description: {desc}",
        f"Date: {date}",
    ]
    packages, packages_gz = zip(*data.values(), strict=False)
    lines += get_packages_hashes(packages, packages_gz)
    return "\n".join(lines) + "\n"


def create_packages(
    repo: StrPath,
    previous: StrPath | Sequence[StrPath] | None,
    suite: str,
    arch: ARCH,
    pbar: bool = True,
) -> tuple[Path, str]:
    """Create the Packages file for the apt repository."""
    binary_dir = f"binary-{arch}/"
    packages_file = Path(repo) / "dists" / suite / "main" / binary_dir / "Packages"

    if previous is not None:
        if isinstance(previous, str | PathLike):
            previous = (previous,)
        previous = tuple(str(Path(p).resolve()) for p in previous if Path(p).is_file())
        if not previous:  # tuple != None but evals as false
            previous = None

    with change_cwd(repo):
        DpkgScanPackages(
            binary_path="pool/",
            multiversion=True,
            arch=arch,
            package_type="deb",
            output=str(packages_file.relative_to(repo)),
            previous=previous,
            pbar=pbar,
        ).scan()

    packages = packages_file.read_text("utf-8")
    return packages_file, packages


def create_packages_gz(
    packages_file: StrPath, packages: str, skip_update: bool = False
) -> tuple[Path, bytes]:
    """Create the Packages.gz file for the apt repository."""
    packages_file = Path(packages_file)
    packages_gz_file = packages_file.with_suffix(".gz")

    if skip_update:
        return packages_gz_file, packages_gz_file.read_bytes()

    packages_gz_io = BytesIO()
    with gzip.GzipFile(fileobj=packages_gz_io, mode="wb") as f:
        f.write(packages.encode("utf-8"))
    packages_gz = packages_gz_io.getvalue()
    packages_gz_io.close()
    packages_file.with_suffix(".gz").write_bytes(packages_gz)

    return packages_gz_file, packages_gz


def create_repo(repo: StrPath, suite: str, arches: Sequence[ARCH]) -> None:
    """Create the apt repository at `repo`/debs."""
    release_file = Path(repo) / "dists" / suite / "Release"
    inrelease_file = release_file.with_name("InRelease")
    release_gpg = release_file.with_suffix(".gpg")

    release_file.unlink(missing_ok=True)
    inrelease_file.unlink(missing_ok=True)
    release_gpg.unlink(missing_ok=True)

    data: dict[ARCH, tuple[tuple[Path, str], tuple[Path, bytes]]] = {}

    old_packages_files: list[Path] = []
    for arch in arches:
        binary_dir = f"binary-{arch}"
        old_packages_file = Path(repo) / "dists" / suite / "main" / binary_dir / "Packages"
        old_packages_files.append(old_packages_file)

    for arch in arches:
        try:
            packages_file, packages = create_packages(repo, old_packages_files, suite, arch)
        except ValueError:
            continue  # no packages
        packages_gz_file, packages_gz = create_packages_gz(packages_file, packages)
        data[arch] = ((packages_file, packages), (packages_gz_file, packages_gz))

    # Create the Release file
    # no shell injection here, as the script is hardcoded
    release = create_release_file(data, suite)
    release_file.write_text(release, "utf-8")
