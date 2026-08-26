"""Module to handle file extensions.

Implements:
- `COMPRESSION_EXTENSIONS`: A set with the supported compression file extensions.
- `ALLOWED_EXTENSIONS`: A set with the supported file extensions.
- `filter_exts`: Filter the file extensions.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import StrPath


class ExtensionError(Exception):
    """File extension not supported."""


COMPRESSION_EXTENSIONS = {
    ".tgz",
    ".tar.gz",
    ".tar.zst",
    ".tar.bz2",
    ".tbz2",
    ".bz2",
    ".tar",
    ".gz",
    ".xz",
    ".zip",
    ".7z",
    ".zst",
}

ALLOWED_EXTENSIONS = COMPRESSION_EXTENSIONS | {
    ".deb",
    ".rpm",
    ".exe",
    ".msi",
    ".rb",
    ".nupkg",
    ".nuspec",
    ".ps1",
    ".xml",
    ".dmg",
}


def filter_exts(path_or_suffixes: StrPath | list[str]) -> list[str]:
    """Filter the file extensions.

    Args:
        path_or_suffixes: The path or the suffixes to filter.

    Returns:
        The filtered file extensions.

    Raises:
        ExtensionError: If an allowed extension preceeds a disallowed one.
    """
    if not isinstance(path_or_suffixes, list):
        suffixes = Path(path_or_suffixes).suffixes
    else:
        suffixes = path_or_suffixes

    filtered: list[str] = []
    for suffix in reversed(suffixes):
        if suffix in ALLOWED_EXTENSIONS:
            filtered.append(suffix)
        else:
            break
    filtered.reverse()

    remaining = suffixes[: len(suffixes) - len(filtered)]
    if set(remaining) & ALLOWED_EXTENSIONS:
        raise ExtensionError(f"An allowed extensions preceeds a disallowed one: {path_or_suffixes}")

    return filtered


__all__ = [
    "ALLOWED_EXTENSIONS",
    "COMPRESSION_EXTENSIONS",
    "ExtensionError",
    "filter_exts",
]
