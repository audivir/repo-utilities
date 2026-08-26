#!/usr/bin/env python
"""Creates a debian package with no content and a set of dependencies.

Useful for keeping track of large numbers of installed packages
(eg. for building a piece of software) in Debian by installing a metapackage.
This allows easy cleanup using apt-get autoremove.

https://www.shackleton.io
https://gist.github.com/w-shackleton/f35be8fecd95ab2ad94b

"""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import StrPath

    from repo_utilities.utils import ARCH


@dataclass(frozen=True)
class MetaConf(argparse.Namespace):
    """Namespace for command line arguments."""

    package: str
    dependencies: list[str]
    output: StrPath = Path()
    desc: str | None = None
    name: str | None = field(default_factory=lambda: os.getenv("APTNAME"))
    email: str | None = field(default_factory=lambda: os.getenv("APTEMAIL"))
    version: str = "0.0.1"
    arch: ARCH = "all"


def build_meta(  # noqa: PLR0913, PLR0917
    output: StrPath,
    package: str,
    dependencies: list[str],
    name: str | None,
    email: str | None,
    desc: str | None = None,
    version: str = "0.0.1",
    arch: ARCH = "all",
) -> None:
    """Create a metapackage with the given name and dependencies.

    Args:
        output: Output directory.
        package: Name of the metapackage.
        dependencies: List of package names to depend on.
        name: Name of the maintainer.
        email: Email of the maintainer.
        desc: Description of the package.
        version: Version of the package. Semver.
        arch: Architecture of the package. Defaults to all.
    """
    if not name or not email:
        raise ValueError("Name and email must be provided.")
    maintainer = f"{name} <{email}>"

    if not desc:
        desc = """<insert up to 60 chars description>
 <insert long description, indented with spaces>"""

    dest_file = Path(output) / f"{package}_{version}_{arch}.deb"

    with tempfile.TemporaryDirectory() as work_dir:
        wd = Path(work_dir)
        debian = wd / "DEBIAN"
        debian.mkdir()
        control = debian / "control"
        content = f"""\
Section: misc
Priority: optional
Package: {package}
Version: {version}
Maintainer: {maintainer}>
Depends: {", ".join(dependencies)}
Architecture: {arch}
Description: {desc}
"""
        control.write_text(content, "utf-8")

        subprocess.check_call(  # work_dir is provided by tempfile, args.name is sanitized # noqa: S603,E501
            ["/usr/bin/dpkg-deb", "--build", work_dir, str(dest_file)]
        )
