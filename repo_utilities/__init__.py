"""Utilities usable by all repositories."""

from __future__ import annotations

from repo_utilities import download, git
from repo_utilities.ext import (
    ALLOWED_EXTENSIONS,
    COMPRESSION_EXTENSIONS,
    ExtensionError,
    filter_exts,
)
from repo_utilities.extract import extract
from repo_utilities.gpg import GPG2, TempGPG, create_priv_key, sign_repo
from repo_utilities.session import CacheSession, ConnectionKeeper
from repo_utilities.temp import TemporaryDirectory
from repo_utilities.utils import (
    ARCH,
    EMPTY_HASH,
    FOUR_MB,
    change_cwd,
    checksum,
    find_common_parent,
    short_checksum,
    symlinker,
)

__version__ = "0.0.4"

__all__ = [
    "ALLOWED_EXTENSIONS",
    "ARCH",
    "COMPRESSION_EXTENSIONS",
    "EMPTY_HASH",
    "FOUR_MB",
    "GPG2",
    "CacheSession",
    "ConnectionKeeper",
    "ExtensionError",
    "TempGPG",
    "TemporaryDirectory",
    "change_cwd",
    "checksum",
    "create_priv_key",
    "download",
    "extract",
    "filter_exts",
    "find_common_parent",
    "git",
    "short_checksum",
    "sign_repo",
    "symlinker",
]
