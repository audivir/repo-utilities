"""Tests for repo_utilities.brew."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from packaging.version import Version

from repo_utilities import brew, git


def test_read_version_parses_quoted_version(tmp_path: Path) -> None:
    file = tmp_path / "formula.rb"
    file.write_text('class Foo < Formula\n  version "1.2.3"\nend\n', "utf-8")

    assert brew.read_version(file) == Version("1.2.3")


def test_read_version_latest_is_treated_as_very_high_version(tmp_path: Path) -> None:
    file = tmp_path / "formula.rb"
    file.write_text('version "latest"\n', "utf-8")

    assert brew.read_version(file) == Version("9999.9.9")


def test_read_version_raises_when_missing(tmp_path: Path) -> None:
    file = tmp_path / "formula.rb"
    file.write_text("class Foo < Formula\nend\n", "utf-8")

    with pytest.raises(ValueError, match="No version found"):
        brew.read_version(file)


def make_rb(tmp_path: Path, name: str, version: str) -> Path:
    file = tmp_path / name
    file.write_text(f'version "{version}"\n', "utf-8")
    return file


def test_build_tap_inits_repo_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_init = MagicMock()
    mock_update = MagicMock()
    mock_clone = MagicMock()
    mock_commit = MagicMock()
    monkeypatch.setattr(git, "init", mock_init)
    monkeypatch.setattr(git, "update_server_info", mock_update)
    monkeypatch.setattr(git, "clone", mock_clone)
    monkeypatch.setattr(git, "commit_everything", mock_commit)

    repo = tmp_path / "tap.git"

    # `clone` is mocked, so simulate what a real clone would produce: a
    # checkout directory named after the repo inside the temp parent.
    def fake_clone(_repo: Path, dest: Path, allow_same_name: bool = False) -> None:  # noqa: ARG001
        (dest / repo.name).mkdir(parents=True)

    mock_clone.side_effect = fake_clone
    # A real `git init --bare` would create the directory; simulate that so
    # the subsequent TemporaryDirectory(dir=repo) has somewhere to live.
    mock_init.side_effect = lambda repo_path, bare=False: Path(repo_path).mkdir(  # noqa: ARG005
        parents=True
    )

    brew.build_tap(repo, casks=[], formulae=[])

    mock_init.assert_called_once_with(repo, bare=True)
    mock_update.assert_called_once_with(repo)
    mock_clone.assert_called_once()
    mock_commit.assert_called_once()


def test_build_tap_skips_init_when_repo_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_init = MagicMock()
    monkeypatch.setattr(git, "init", mock_init)
    monkeypatch.setattr(git, "update_server_info", MagicMock())
    monkeypatch.setattr(git, "commit_everything", MagicMock())

    repo = tmp_path / "tap.git"
    repo.mkdir()

    def fake_clone(_repo: Path, dest: Path, allow_same_name: bool = False) -> None:  # noqa: ARG001
        (dest / repo.name).mkdir(parents=True)

    monkeypatch.setattr(git, "clone", fake_clone)

    brew.build_tap(repo, casks=[], formulae=[])

    mock_init.assert_not_called()


def test_build_tap_writes_empty_marker_when_no_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(git, "init", MagicMock())
    monkeypatch.setattr(git, "update_server_info", MagicMock())

    repo = tmp_path / "tap.git"
    repo.mkdir()
    checkout_holder: dict[str, Path] = {}

    def fake_clone(_repo: Path, dest: Path, allow_same_name: bool = False) -> None:  # noqa: ARG001
        checkout = dest / repo.name
        checkout.mkdir(parents=True)
        checkout_holder["path"] = checkout

    monkeypatch.setattr(git, "clone", fake_clone)

    # commit_everything is called while the temp checkout still exists (it
    # is deleted right after build_tap returns), so assert on its contents
    # from inside the mock rather than after the call.
    def fake_commit(curr_tmp: Path, bare_repo: Path | None = None, message: str = "") -> None:
        assert (curr_tmp / "Casks" / ".empty").exists()
        assert (curr_tmp / "Formula" / ".empty").exists()
        assert curr_tmp == checkout_holder["path"]
        assert bare_repo == repo
        assert message == "Pushed."

    mock_commit = MagicMock(side_effect=fake_commit)
    monkeypatch.setattr(git, "commit_everything", mock_commit)

    brew.build_tap(repo, casks=[], formulae=[])

    mock_commit.assert_called_once()


def test_build_tap_copies_new_cask_and_skips_older_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(git, "init", MagicMock())
    monkeypatch.setattr(git, "update_server_info", MagicMock())

    repo = tmp_path / "tap.git"
    repo.mkdir()

    def fake_clone(_repo: Path, dest: Path, allow_same_name: bool = False) -> None:  # noqa: ARG001
        checkout = dest / repo.name
        checkout.mkdir(parents=True)
        # Pre-existing cask at version 2.0.0 in the "remote" checkout.
        (checkout / "Casks").mkdir()
        (checkout / "Casks" / "stale.rb").write_text('version "2.0.0"\n', "utf-8")

    monkeypatch.setattr(git, "clone", fake_clone)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    new_cask = make_rb(src_dir, "fresh.rb", "1.0.0")
    older_cask = make_rb(src_dir, "stale.rb", "1.0.0")  # older than existing 2.0.0

    def fake_commit(
        curr_tmp: Path,
        bare_repo: Path | None = None,  # noqa: ARG001
        message: str = "",  # noqa: ARG001
    ) -> None:
        assert (curr_tmp / "Casks" / "fresh.rb").exists()
        # The older-versioned file must not have overwritten the existing one.
        assert (curr_tmp / "Casks" / "stale.rb").read_text("utf-8") == 'version "2.0.0"\n'

    monkeypatch.setattr(git, "commit_everything", MagicMock(side_effect=fake_commit))

    brew.build_tap(repo, casks=[new_cask, older_cask], formulae=[])


def test_build_tap_raises_for_non_rb_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(git, "init", MagicMock())
    monkeypatch.setattr(git, "update_server_info", MagicMock())
    monkeypatch.setattr(git, "commit_everything", MagicMock())

    repo = tmp_path / "tap.git"
    repo.mkdir()

    def fake_clone(_repo: Path, dest: Path, allow_same_name: bool = False) -> None:  # noqa: ARG001
        (dest / repo.name).mkdir(parents=True)

    monkeypatch.setattr(git, "clone", fake_clone)

    bad_file = tmp_path / "not_ruby.txt"
    bad_file.write_text("nope", "utf-8")

    with pytest.raises(ValueError, match="Unexpected file"):
        brew.build_tap(repo, casks=[bad_file], formulae=[])


def test_build_tap_cli_parses_args_and_calls_build_tap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_build_tap = MagicMock()
    monkeypatch.setattr(brew, "build_tap", mock_build_tap)

    repo = tmp_path / "tap.git"
    cask = tmp_path / "a.rb"
    formula = tmp_path / "b.rb"
    monkeypatch.setattr(
        sys,
        "argv",
        ["prog", str(repo), "--casks", str(cask), "--formulae", str(formula)],
    )

    result = brew.build_tap_cli()

    assert result == 0
    mock_build_tap.assert_called_once_with(repo, [cask], [formula])
