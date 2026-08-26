"""Utilities for the apt-repo package."""

from __future__ import annotations

import hashlib
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Generator

    from _typeshed import StrPath
logger = logging.getLogger("repo_utilities")

EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
FOUR_MB = 4 * 1024 * 1024
ARCH: TypeAlias = Literal["amd64", "arm64", "all"]


@contextmanager
def change_cwd(path: StrPath) -> Generator[None]:
    """Change the work dir to `path`."""
    cwd = Path.cwd()
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)


def short_checksum(file: StrPath) -> str:
    """Returns the SHA256 hash for the first 4 MB."""
    return checksum(file, short_only=True)[1]


def checksum(file: StrPath, short_only: bool = False) -> tuple[str, str]:
    """Returns the SHA256 hash for the full file and the first 4 MB."""
    hash_func = hashlib.sha256()
    first = True

    short_hash = EMPTY_HASH  # initialize
    with Path(file).open("rb") as f:
        for chunk in iter(lambda: f.read(FOUR_MB), b""):
            hash_func.update(chunk)
            if first:
                short_hash = hash_func.hexdigest()
                if short_only:
                    break
                first = False
    if short_only:
        return "", short_hash

    full_hash = hash_func.hexdigest()
    return full_hash, short_hash


def find_common_parent(*paths: StrPath) -> Path:
    """Find the common parent directory of the paths."""
    # Get the parts of each path as lists
    split_paths = [Path(path).resolve().parts for path in paths]
    # Transpose the lists to compare corresponding parts
    common_parts = []
    for parts in zip(*split_paths, strict=False):  # doesnt need to be same-size
        if all(part == parts[0] for part in parts):
            common_parts.append(parts[0])
        else:
            break
    return Path(*common_parts)


def symlinker(src: StrPath, target: StrPath) -> None:
    """Symlink a file relatively over a common parent."""
    src, target = Path(src).resolve(), Path(target).resolve()
    common_parent = find_common_parent(src, target)
    rel_src = src.relative_to(common_parent)
    rel_target = target.relative_to(common_parent)
    rel_symlink = Path("../" * len(rel_target.parent.parts)) / rel_src
    target.symlink_to(rel_symlink)


__all__ = [
    "ARCH",
    "EMPTY_HASH",
    "FOUR_MB",
    "change_cwd",
    "checksum",
    "find_common_parent",
    "short_checksum",
    "symlinker",
]
