"""Homebrew tap repository management."""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from packaging.version import Version

from repo_utilities import TemporaryDirectory, git

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import StrPath


logger = logging.getLogger("repo_utilities")


def read_version(path: StrPath) -> Version:
    """Read the version from a file."""
    match = re.search(r"version\s+\"([^\"]+)\"", Path(path).read_text("utf-8"))
    if match is None:
        raise ValueError(f"No version found in {path}")
    version = match.group(1)
    if version == "latest":
        return Version("9999.9.9")
    return Version(version)


def build_tap(repo: StrPath, casks: Sequence[Path], formulae: Sequence[Path]) -> None:
    """Build the tap repository.

    Args:
        repo: The repository directory.
        casks: The cask Ruby files to include.
        formulae: The formula Ruby files to include.

    Raises:
        FileExistsError: If the public directory already exists.
        ValueError: If an unexpected file is found in the temporary directory.
    """
    repo = Path(repo).resolve()

    if not repo.exists():
        git.init(repo, bare=True)
        git.update_server_info(repo)

    with TemporaryDirectory(prefix="tmp_build_tap_", dir=repo) as tmp_parent:
        git.clone(repo, tmp_parent)

        curr_tmp = tmp_parent / repo.name

        for subdir, pkgs in (("Casks", casks), ("Formula", formulae)):
            dest = curr_tmp / subdir
            dest.mkdir(exist_ok=True)

            existing_files = [x.name for x in dest.glob("*.rb")]

            if not pkgs and not existing_files:
                logger.warning("No %s files found.", subdir)
                (dest / ".empty").write_text(f"No {subdir} files found.", "utf-8")

            for file in pkgs:
                if file.suffix != ".rb":
                    raise ValueError(f"Unexpected file in {pkgs}: {file}")

                new_version = read_version(file)
                if file.name in existing_files:
                    old_version = read_version(dest / file.name)
                else:
                    old_version = Version("0.0.0")

                if old_version > new_version:
                    logger.warning(
                        "Version %s is older than the previous version %s for %s.",
                        new_version,
                        old_version,
                        file.name,
                    )
                    continue

                shutil.copy(file, dest / file.name)

        git.commit_everything(curr_tmp, repo, message="Pushed.")


def build_tap_cli() -> int:
    """Command-line interface for building a Homebrew tap."""
    parser = argparse.ArgumentParser(description="Build a Homebrew tap.")
    parser.add_argument("repo", type=Path, help="The path to the tap repository.")
    parser.add_argument(
        "--casks",
        nargs="+",
        type=Path,
        default=[],
        help="Cask formulae to include in the tap.",
    )
    parser.add_argument(
        "--formulae",
        nargs="+",
        type=Path,
        default=[],
        help="Formulae to include in the tap.",
    )
    args = parser.parse_args()
    build_tap(args.repo, args.casks, args.formulae)
    return 0


__all__ = ["build_tap", "build_tap_cli"]

if __name__ == "__main__":
    raise SystemExit(build_tap_cli())
