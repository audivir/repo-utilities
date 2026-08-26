"""CLI interface for the repo_utilities.apt package."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from repo_utilities.apt.build_deb import BuildConf, build_deb
from repo_utilities.apt.build_meta import MetaConf, build_meta
from repo_utilities.apt.build_repo import build_repo

logging.basicConfig(level=logging.DEBUG)


def parse_build_deb_args() -> BuildConf:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Create a Debian package.")
    parser.add_argument("source", type=Path, help="Source directory or file path")
    parser.add_argument("package", type=str, help="Name of the package")
    parser.add_argument("version", type=str, help="Version of the package")
    parser.add_argument("-a", "--additional-dir", type=Path, help="Files to be copied to debian")
    parser.add_argument("-r", "--root-dir", type=Path, help="Root directory for relative paths")
    parser.add_argument(
        "-i", "--install-dir", type=Path, default="/", help="Installation directory"
    )
    parser.add_argument(
        "-n", "--name", type=str, help="Name of the maintainer (settable by APTNAME)"
    )
    parser.add_argument(
        "-m", "--mail", type=str, help="Email of the maintainer (settable by APTMAIL)"
    )
    parser.add_argument(
        "--homepage", type=str, help="Homepage URL (tries to extract from Homebrew)"
    )
    parser.add_argument(
        "-t",
        "--type",
        type=str,
        default="i",
        choices=("i", "s", "l", "p"),
        help="Type of package",
    )
    parser.add_argument(
        "-c",
        "--compression",
        type=int,
        metavar="LEVEL",
        default=1,
        choices=range(1, 10),
        help="Compression level for the tarball",
    )
    parser.add_argument(
        "-j", "--jobs", type=int, default=0, help="Number of jobs to run in parallel"
    )
    parser.add_argument("-o", "--output", type=Path, default=Path(), help="Output directory")
    parser.add_argument("-b", "--binary", type=str, help="Name of binary file")
    parser.add_argument(
        "-e",
        "--exclude",
        type=str,
        action="append",
        help="Globbing patterns to exclude from extraction",
    )
    parser.add_argument("--disable", type=str, action="append", help="Disable a debhelper script")
    parser.add_argument(
        "-x",
        "--executable",
        type=Path,
        action="append",
        help="Executable files (link to/usr/bin)",
    )
    parser.add_argument(
        "--desktop",
        type=Path,
        nargs=3,
        metavar=("TEMPLATE", "EXEC", "ICON"),
        help="Desktop file template, exec and path to icon",
    )
    parser.add_argument(
        "--desc",
        type=str,
        help="Description of the package (tries to extract from Homebrew)",
    )
    parser.add_argument("--depends", type=str, help="Dependencies for the package")
    parser.add_argument(
        "-l",
        "--license",
        type=str,
        metavar="LICENSE_ABBR",
        choices=(
            "apache",
            "artistic",
            "bsd",
            "gpl",
            "gpl2",
            "gpl3",
            "isc",
            "lgpl",
            "lgpl2",
            "lgpl3",
            "expat",
            "custom",
        ),
        help="License of the package",
    )
    parser.add_argument("-k", "--key", type=Path, help="Private key for signing the package")
    return BuildConf(**{k: v for k, v in vars(parser.parse_args()).items() if v is not None})


def build_deb_cli() -> int:
    """Build a Debian package from CLI arguments."""
    conf = parse_build_deb_args()
    build_deb(conf)
    return 0


def build_repo_cli() -> int:
    """Create repo."""
    parser = argparse.ArgumentParser(description="Build an APT repository")
    parser.add_argument("repo", type=Path, help="Directory of the repository")
    parser.add_argument("pkgs", nargs="+", type=Path, help="Packages to include")
    parser.add_argument(
        "-k",
        "--key",
        type=Path,
        help="Private key for signing the repository",
        required=True,
    )

    parser.add_argument("-s", "--suite", type=str, default="stable", help="Suite name")
    parser.add_argument(
        "-a",
        "--arches",
        type=str,
        nargs="+",
        choices=("amd64", "arm64", "all"),
        default=("amd64", "arm64", "all"),
        help="Architecture of the packages",
    )
    args = parser.parse_args()
    build_repo(**vars(args))

    return 0


def parse_build_meta_args() -> MetaConf:  # pragma: no cover
    """Parse command line arguments.

    Currently unusable: argparse raises TypeError for `required=True` on the
    "dependencies" positional argument below, unconditionally, before any
    parsing happens. Everything past that `add_argument` call is dead code
    until this is fixed; see tests/test_cli.py for the documented behavior.
    """
    parser = argparse.ArgumentParser(
        "Install a set of Debian packages as dependencies of a metapackage.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("package", type=str, help="Name of the metapackage")
    parser.add_argument(
        "dependencies",
        metavar="PKG",
        type=str,
        nargs="+",
        required=True,
        help="Packages to generate dependencies for",
    )
    parser.add_argument("-o", "--output", type=Path, default=Path(), help="Output directory")
    parser.add_argument("--desc", metavar="desc", type=str, help="Package description")
    parser.add_argument(
        "-n", "--name", type=str, help="Name of the maintainer (settable by APTNAME)"
    )
    parser.add_argument(
        "-m", "--mail", type=str, help="Email of the maintainer (settable by APTMAIL)"
    )
    parser.add_argument(
        "-v", "--version", type=str, default="0.0.1", help="Version of the metapackage"
    )
    parser.add_argument(
        "-a",
        "--arch",
        type=str,
        choices=("all", "amd64", "arm64"),
        default="all",
        help="Architecture",
    )
    return MetaConf(**{k: v for k, v in vars(parser.parse_args()).items() if v is not None})


def build_meta_cli() -> int:  # pragma: no cover
    """Build a metapackage."""
    conf = parse_build_meta_args()  # currently always raises, see above
    build_meta(**vars(conf))
    return 0


__all__ = [
    "build_deb_cli",
    "build_meta_cli",
    "build_repo_cli",
    "parse_build_deb_args",
    "parse_build_meta_args",
]
