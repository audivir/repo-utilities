"""Utilities for file manipulation.

Implements:
- `extract`: Extract a tarball.
- `copy`: Copy a file or folder.
"""

from __future__ import annotations

import fnmatch
import logging
import tarfile
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from repo_utilities.ext import filter_exts

if TYPE_CHECKING:
    from _typeshed import StrPath

logger = logging.getLogger("repo_utilities")


class FileManupilationError(Exception):
    """File manipulation failed."""


class DecompressionError(FileManupilationError):
    """Decompression failed."""


def _get_compression_mode(src: StrPath) -> Literal["r", "r:gz", "r:bz2"]:
    """Return the compression mode for a given tarball.

    If suffix is .tgz or .tar.gz, return 'r:gz'.
    If suffix is .tbz2 or .tar.bz2, return 'r:bz2'.
    Otherwise, return 'r'.
    """
    exts = filter_exts(src)
    if ".tar" not in exts:
        raise DecompressionError(f"Not a tarball: {src}")

    final = exts[-1]
    if final == ".tar":
        return "r"

    if final in {".gz", ".tgz"}:
        return "r:gz"

    if final in {".bz2", ".tbz2"}:
        return "r:bz2"

    raise DecompressionError(f"Unknown compression mode for {src}")


def is_safe_path(path: StrPath) -> bool:
    """Check if the path is safe to extract."""
    path = Path(path)
    return not (path.is_absolute() or ".." in path.parts)


def extract(src: StrPath, target: StrPath | None = None, glob: str | None = None) -> list[Path]:
    """Extract the tar file at `src` to `target`.

    Use the parent directory of `src` if `target` is None.
    """
    logger.debug("Extracting %s to %s with glob %s", src, target, glob)

    src = Path(src)
    mode = _get_compression_mode(src)

    target = Path(target) if target else src.parent

    tar: tarfile.TarFile
    with tarfile.open(src, mode) as tar:

        def _match(name: str) -> bool:
            if not is_safe_path(name):
                return False

            if glob is None:
                return True

            return fnmatch.fnmatch(name, glob)

        members = [member for member in tar.getmembers() if _match(member.name)]

        for member in members:
            logger.debug("Extracting %s ...", member.name)
            tar.extract(member, target)

        return [target / member.name for member in members]


__all__ = ["extract"]
