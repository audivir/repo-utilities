"""Git utilities for the custom repository.

Implements:
- `init`: Initialize a git repository.
- `clone`: Clone a repository.
- `update_server_info`: Update the server info for the tap repository.
- `commit_everything`: Add all files, commit and push.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path
from subprocess import DEVNULL, CalledProcessError
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import StrPath


def exec_cmd(args: Sequence[str], cwd: StrPath) -> None:
    """Execute a command."""
    subprocess.check_call(args, stdout=DEVNULL, stderr=DEVNULL, cwd=cwd)  # noqa: S603


def init(repo: StrPath, bare: bool = False) -> None:
    """Initialize a git repository."""
    repo = Path(repo)
    if not repo.parent.is_dir():
        raise ValueError("Parent directory does not exist.")

    args = ["git", "init", repo.name]
    if bare:
        args.append("--bare")

    exec_cmd(args, cwd=repo.parent)


def clone(repo: StrPath, dest: StrPath, allow_same_name: bool = False) -> None:
    """Clone a repository."""
    repo = str(repo)
    dest = Path(dest)
    if not allow_same_name and dest.name == repo.rsplit("/", maxsplit=1)[-1]:
        raise ValueError("Repository name and destination folder name are the same.")

    exec_cmd(["git", "clone", repo], cwd=dest)


def update_server_info(bare_repo: StrPath) -> None:
    """Update the server info for the tap repository."""
    exec_cmd(["git", "update-server-info"], cwd=bare_repo)


def commit_everything(
    repo: StrPath, bare_repo: StrPath | None = None, message: str = "Commited."
) -> None:
    """Add all files, commit and push."""
    exec_cmd(["git", "add", "."], cwd=repo)
    with contextlib.suppress(CalledProcessError):
        exec_cmd(["git", "commit", "-m", message], cwd=repo)
    exec_cmd(["git", "push"], cwd=repo)

    if bare_repo:
        update_server_info(bare_repo)
