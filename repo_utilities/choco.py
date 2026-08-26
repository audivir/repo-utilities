"""Build Chocolatey packages."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from subprocess import DEVNULL
from typing import TYPE_CHECKING

import jinja2
import psutil
from ruamel.yaml import YAML

from repo_utilities.temp import TemporaryDirectory
from repo_utilities.utils import symlinker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import StrPath


logger = logging.getLogger("repo_utilities")

CHOCO_SERVER_APP_YAML = {
    "runtime": "nodejs22",
    "handlers": [
        {
            "url": "/.*",
            "secure": "always",
            "redirect_http_response_code": 301,
            "script": "auto",
        }
    ],
}
CHOCO_SERVER_PACKAGE_JSON = {
    "dependencies": {"express-chocolatey-server": "^1.0.0"},
    "scripts": {"start": "express-chocolatey-server *.nupkg"},
    "engines": {"node": "22.x.x"},
}


def choco(args: list[str], cwd: Path | None = None) -> str:
    """Run a Chocolatey command.

    Uses mono to run Chocolatey.
    The path to Chocolatey is determined by the environment's CONDA_PREFIX.
    Mono needs to resolvable by the system.
    """
    conda_prefix = os.getenv("CONDA_PREFIX")
    if not conda_prefix:
        raise ValueError("CONDA_PREFIX is not set.")

    return subprocess.check_output(  # noqa: S603
        [f"{conda_prefix}/bin/mono", f"{conda_prefix}/opt/chocolatey/choco.exe", *args],
        stderr=DEVNULL,
        cwd=cwd,
        text=True,
    )


def build_choco(repo: StrPath, pkgs: Sequence[StrPath]) -> None:
    """Build the Chocolatey repository.

    Args:
        repo: The repository directory.
        pkgs: The packages to link to the repo.

    Raises:
        FileExistsError: If the public directory already exists.
        ValueError: If an unexpected file is found in the Chocolatey packages directory.
    """
    repo = Path(repo)
    repo.mkdir(exist_ok=True)

    for raw_pkg in pkgs:
        pkg = Path(raw_pkg)
        if pkg.suffix != ".nupkg":
            raise ValueError(f"Unexpected file in {pkgs}: {pkg}")
        # express chocolatey server does not support | in package names

        target_pkg = repo / pkg.name
        target_pkg.unlink(missing_ok=True)
        symlinker(pkg, target_pkg)

    with (repo / "app.yaml").open("w", encoding="utf-8") as f:
        yaml = YAML(typ="rt")
        yaml.dump(CHOCO_SERVER_APP_YAML, f)
    (repo / "packages.json").write_text(json.dumps(CHOCO_SERVER_PACKAGE_JSON, indent=4), "utf-8")


def pack_pkg(
    nuspec: StrPath,
    nupkg_target: StrPath,
    vars: dict[str, str] | None = None,  # noqa:A002
) -> None:
    """Pack a Chocolatey package in temp dir and move to `target`."""
    orig_nuspec = Path(nuspec)
    with TemporaryDirectory(prefix="tmp__pack_pkg_") as tmp:
        shutil.copytree(orig_nuspec.parent, tmp / "wd")
        nuspec = tmp / "wd" / orig_nuspec.name
        if vars:
            for file in nuspec.parent.rglob("*"):
                if not file.is_file():
                    continue
                try:
                    file_content = file.read_text("utf-8")
                except UnicodeDecodeError:
                    continue  # binary files
                rendered_file = jinja2.Template(file_content).render(vars)
                file.write_text(rendered_file, "utf-8")
        choco(["pack", "--allow-unofficial", str(nuspec)], cwd=tmp / "wd")
        file = next((tmp / "wd").glob("*.nupkg"))
        file.rename(nupkg_target)


def restart_server(repo: StrPath, port: int | None = None) -> None:
    """Restart the server."""
    # get proc by name
    pids: dict[int, list[str]] = {}
    for proc in psutil.process_iter():
        if proc.name() == "node":
            cmds = proc.cmdline()
            if "express-chocolatey-server" in cmds[1]:
                pids[proc.pid] = proc.cmdline()

    if not pids:
        logger.warning("No node process found.")
    else:
        if len(pids) > 1:
            raise ValueError("More than one node process found.")
        pid = next(iter(pids))
        old_proc = psutil.Process(pid)
        old_proc.kill()
        old_proc.wait()
        logger.info("Server killed.")

    if port is not None:
        os.environ["PORT"] = str(port)

    files = [x.name for x in Path(repo).glob("*.nupkg")]
    subprocess.Popen(  # noqa: S603
        ["/usr/bin/nohup", "npx", "express-chocolatey-server", *files],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info("Server started.")


__all__ = [
    "CHOCO_SERVER_APP_YAML",
    "CHOCO_SERVER_PACKAGE_JSON",
    "build_choco",
    "choco",
    "pack_pkg",
    "restart_server",
]
