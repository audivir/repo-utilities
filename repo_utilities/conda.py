"""Conda package manager."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import conda_index.api
import jinja2
import requests.exceptions as req_errors
from rattler_bindings import PLATFORM, optimized_rattler_build
from requests import Response, Session

from repo_utilities.temp import TemporaryDirectory
from repo_utilities.utils import ARCH, symlinker

if TYPE_CHECKING:
    from collections.abc import Sequence

    from _typeshed import StrPath


logger = logging.getLogger("repo_utilities")

ARCH_MAP: dict[ARCH, PLATFORM] = {"amd64": "linux-64"}  # TODO(tim25651): other arches


def build_channel(channel: StrPath, pkgs: Sequence[StrPath], arch: ARCH) -> None:
    """Build the channel for conda packages.

    Args:
       channel: The channel directory.
       pkgs: The packages to add to the channel.
       arch: Arch to build for.

    Raises:
        FileExistsError: If the public directory already exists.
        ValueError: If an unexpected file is found in the conda packages directory.
    """
    channel = Path(channel)
    channel.mkdir(exist_ok=True)

    arch_channel = channel / ARCH_MAP[arch]
    arch_channel.mkdir(exist_ok=True)

    for raw_pkg in pkgs:
        pkg = Path(raw_pkg)
        if not pkg.name.endswith((".tar.bz2", ".conda")):
            raise ValueError(f"Unexpected file in {pkgs}: {pkg}")
        target_pkg = arch_channel / pkg.name
        target_pkg.unlink(missing_ok=True)
        symlinker(pkg, target_pkg)

    conda_index.api.update_index(channel)  # type: ignore[no-untyped-call]

    for file in channel.glob("**/*.json"):
        content = json.loads(file.read_text("utf-8"))
        file.write_text(json.dumps(content, indent=4), "utf-8")


def build_pkg(  # noqa: PLR0913, PLR0917
    target_dir: StrPath,
    recipe: StrPath,
    arch: ARCH,
    channels: Sequence[str] | None = None,
    vars: dict[str, str] | None = None,  # noqa: A002
    session: Session | None = None,
    cleanup: bool = True,
) -> tuple[Path | None, list[dict[str, Any]], int]:
    """Build a conda package."""
    if channels is None:
        channels = []
    if vars is None:
        vars = {}  # noqa: A001

    orig_recipe = Path(recipe)
    with TemporaryDirectory() as tmp:
        recipe = tmp / orig_recipe.name
        shutil.copytree(orig_recipe, recipe)
        for file in recipe.iterdir():
            template = jinja2.Template(file.read_text("utf-8"))
            file.write_text(template.render(vars), "utf-8")

        # test if %domain%/conda is reachable
        checked_channels: list[str] = []
        for channel in channels:
            if session is None:
                session = Session()

            response: Response | None = None
            try:
                reponse = session.get(channel)
                reponse.raise_for_status()
                checked_channels.append(channel)
            except (req_errors.ConnectionError, req_errors.HTTPError):
                logger.exception(
                    "Error: %s is not reachable (%s). Only conda-forge will be used.",
                    channel,
                    reponse.status_code if response else None,  # type: ignore[possibly-undefined]
                )

        logger.info("Running rattler-build...")
        return optimized_rattler_build(
            recipe,
            target_dir,
            clean_bld_cache=cleanup,
            clean_src_cache=cleanup,
            run_conda_index=False,
            check=False,
            target_platform=ARCH_MAP[arch],
            channels=[*checked_channels, "conda-forge"],
            skip_existing=True,
        )


__all__ = ["build_channel", "build_pkg"]
