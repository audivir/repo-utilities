"""Tests for repo_utilities.apt.cli."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from repo_utilities.apt import cli
from repo_utilities.apt.build_deb import BuildConf

if TYPE_CHECKING:
    from pathlib import Path


def test_parse_build_deb_args_always_raises_due_to_type_field_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`parse_build_deb_args` is currently unconditionally broken.

    The `-t`/`--type` CLI flag has a non-None default ("i"), so it always
    survives the `if v is not None` filter and gets passed through as a
    `type=...` keyword to `BuildConf(...)` -- but `BuildConf` has no
    `type` field. This means `parse_build_deb_args()` (and therefore
    `build_deb_cli()`) raises `TypeError` for *every* invocation,
    regardless of which other arguments are given. This test documents
    that real, unconditional failure rather than a hypothetical one.

    A second, related bug is masked by this one: `-m`/`--mail` populates
    `args.mail`, but `BuildConf`'s matching field is named `email`, so
    even if the `--type` bug were fixed, passing `--mail` would still
    raise `TypeError: unexpected keyword argument 'mail'`.
    """
    monkeypatch.delenv("APTMAIL", raising=False)
    monkeypatch.delenv("APTNAME", raising=False)
    source = tmp_path / "src"
    monkeypatch.setattr(sys, "argv", ["prog", str(source), "mypkg", "1.0.0"])

    with pytest.raises(TypeError, match="unexpected keyword argument 'type'"):
        cli.parse_build_deb_args()


def test_build_deb_cli_calls_build_deb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_conf = BuildConf(source=tmp_path, package="mypkg", version="1.0.0")
    monkeypatch.setattr(cli, "parse_build_deb_args", MagicMock(return_value=fake_conf))
    mock_build_deb = MagicMock()
    monkeypatch.setattr(cli, "build_deb", mock_build_deb)

    result = cli.build_deb_cli()

    assert result == 0
    mock_build_deb.assert_called_once_with(fake_conf)


def test_build_repo_cli_parses_args_and_calls_build_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_build_repo = MagicMock()
    monkeypatch.setattr(cli, "build_repo", mock_build_repo)

    repo = tmp_path / "repo"
    pkg = tmp_path / "foo.deb"
    key = tmp_path / "priv.key"
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", str(repo), str(pkg), "--key", str(key), "--suite", "testing", "-a", "amd64"],
    )

    result = cli.build_repo_cli()

    assert result == 0
    mock_build_repo.assert_called_once_with(
        repo=repo, pkgs=[pkg], key=key, suite="testing", arches=["amd64"]
    )


def test_build_repo_cli_uses_default_arches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_build_repo = MagicMock()
    monkeypatch.setattr(cli, "build_repo", mock_build_repo)

    repo = tmp_path / "repo"
    pkg = tmp_path / "foo.deb"
    key = tmp_path / "priv.key"
    monkeypatch.setattr(sys, "argv", ["prog", str(repo), str(pkg), "--key", str(key)])

    cli.build_repo_cli()

    _, kwargs = mock_build_repo.call_args
    assert kwargs["arches"] == ("amd64", "arm64", "all")
    assert kwargs["suite"] == "stable"


def test_parse_build_meta_args_raises_type_error_on_required_positional() -> None:
    """`argparse` rejects `required=True` on a positional argument.

    `parse_build_meta_args` passes `required=True` to
    `add_argument("dependencies", ..., nargs="+", required=True, ...)`, but
    argparse raises TypeError for `required` on any positional argument --
    unconditionally, regardless of what `sys.argv` contains, since the
    error is raised by `add_argument` itself before any parsing happens.
    This means `parse_build_meta_args` (and therefore `build_meta_cli`) is
    currently unusable; this test documents that real, surprising
    behavior rather than a hypothetical one.
    """
    with pytest.raises(TypeError, match=r"required.*invalid argument for positionals"):
        cli.parse_build_meta_args()


def test_build_meta_cli_also_raises_due_to_broken_arg_parsing() -> None:
    with pytest.raises(TypeError, match=r"required.*invalid argument for positionals"):
        cli.build_meta_cli()
