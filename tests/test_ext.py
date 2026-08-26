"""Tests for repo_utilities.ext."""

from __future__ import annotations

import pytest

from repo_utilities.ext import ExtensionError, filter_exts


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("archive.tar.gz", [".tar", ".gz"]),
        ("archive.tgz", [".tgz"]),
        ("package.deb", [".deb"]),
        ("plain.txt", []),
        ("no_extension", []),
        ("archive.zip", [".zip"]),
    ],
)
def test_filter_exts_from_path(path: str, expected: list[str]) -> None:
    assert filter_exts(path) == expected


def test_filter_exts_from_suffix_list() -> None:
    assert filter_exts([".tar", ".gz"]) == [".tar", ".gz"]


def test_filter_exts_stops_at_first_disallowed_suffix_from_the_end() -> None:
    # my.file.tar.gz -> trailing allowed run is [".tar", ".gz"]; ".file" is
    # not allowed but doesn't precede an allowed one, so it's just dropped.
    assert filter_exts("my.file.tar.gz") == [".tar", ".gz"]


def test_filter_exts_raises_when_allowed_extension_precedes_disallowed_one() -> None:
    # ".tar" (allowed) appears before ".weird" (disallowed) in suffix order,
    # which is treated as a malformed name rather than silently ignored.
    with pytest.raises(ExtensionError, match="allowed extensions preceeds"):
        filter_exts([".tar", ".weird", ".gz"])


def test_filter_exts_raises_for_path_with_allowed_before_disallowed() -> None:
    with pytest.raises(ExtensionError):
        filter_exts("archive.zip.weird")
