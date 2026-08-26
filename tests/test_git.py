"""Tests for repo_utilities.git."""

from __future__ import annotations

import subprocess
from subprocess import DEVNULL, CalledProcessError
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from repo_utilities import git

if TYPE_CHECKING:
    from pathlib import Path


def test_exec_cmd_calls_check_call_with_devnull_and_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)

    git.exec_cmd(["git", "status"], cwd=tmp_path)

    mock_check_call.assert_called_once_with(
        ["git", "status"], stdout=DEVNULL, stderr=DEVNULL, cwd=tmp_path
    )


def test_init_raises_if_parent_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "missing" / "repo"

    with pytest.raises(ValueError, match="Parent directory does not exist"):
        git.init(missing)


def test_init_calls_git_init_with_repo_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_exec_cmd = MagicMock()
    monkeypatch.setattr(git, "exec_cmd", mock_exec_cmd)
    repo = tmp_path / "myrepo"

    git.init(repo)

    mock_exec_cmd.assert_called_once_with(["git", "init", "myrepo"], cwd=tmp_path)


def test_init_bare_appends_bare_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_exec_cmd = MagicMock()
    monkeypatch.setattr(git, "exec_cmd", mock_exec_cmd)
    repo = tmp_path / "myrepo"

    git.init(repo, bare=True)

    mock_exec_cmd.assert_called_once_with(["git", "init", "myrepo", "--bare"], cwd=tmp_path)


def test_clone_raises_if_dest_name_matches_repo_name(tmp_path: Path) -> None:
    dest = tmp_path / "myrepo"

    with pytest.raises(ValueError, match="same"):
        git.clone("https://example.com/myrepo", dest)


def test_clone_allows_same_name_when_flagged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_exec_cmd = MagicMock()
    monkeypatch.setattr(git, "exec_cmd", mock_exec_cmd)
    dest = tmp_path / "myrepo"

    git.clone("https://example.com/myrepo", dest, allow_same_name=True)

    mock_exec_cmd.assert_called_once_with(["git", "clone", "https://example.com/myrepo"], cwd=dest)


def test_clone_calls_git_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_exec_cmd = MagicMock()
    monkeypatch.setattr(git, "exec_cmd", mock_exec_cmd)
    dest = tmp_path / "somewhere_else"

    git.clone("https://example.com/myrepo", dest)

    mock_exec_cmd.assert_called_once_with(["git", "clone", "https://example.com/myrepo"], cwd=dest)


def test_update_server_info_calls_exec_cmd(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_exec_cmd = MagicMock()
    monkeypatch.setattr(git, "exec_cmd", mock_exec_cmd)

    git.update_server_info(tmp_path)

    mock_exec_cmd.assert_called_once_with(["git", "update-server-info"], cwd=tmp_path)


def test_commit_everything_adds_commits_and_pushes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_exec_cmd(args: list[str], cwd: Path) -> None:  # noqa: ARG001
        calls.append(args)

    monkeypatch.setattr(git, "exec_cmd", fake_exec_cmd)

    git.commit_everything(tmp_path)

    assert calls == [
        ["git", "add", "."],
        ["git", "commit", "-m", "Commited."],
        ["git", "push"],
    ]


def test_commit_everything_suppresses_commit_failure_eg_nothing_to_commit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_exec_cmd(args: list[str], cwd: Path) -> None:  # noqa: ARG001
        calls.append(args)
        if args[:2] == ["git", "commit"]:
            raise CalledProcessError(1, args)

    monkeypatch.setattr(git, "exec_cmd", fake_exec_cmd)

    # Must not raise even though "commit" fails (e.g. nothing to commit);
    # push still runs afterwards.
    git.commit_everything(tmp_path)

    assert calls[-1] == ["git", "push"]


def test_commit_everything_updates_server_info_for_bare_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(git, "exec_cmd", lambda args, cwd: calls.append(args))  # noqa: ARG005
    mock_update = MagicMock()
    monkeypatch.setattr(git, "update_server_info", mock_update)

    bare_repo = tmp_path / "bare"
    git.commit_everything(tmp_path, bare_repo=bare_repo)

    mock_update.assert_called_once_with(bare_repo)


def test_commit_everything_skips_server_info_without_bare_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(git, "exec_cmd", lambda args, cwd: None)  # noqa: ARG005
    mock_update = MagicMock()
    monkeypatch.setattr(git, "update_server_info", mock_update)

    git.commit_everything(tmp_path)

    mock_update.assert_not_called()
