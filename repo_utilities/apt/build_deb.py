# %%
"""Find links and binaries in a debian source tree."""

from __future__ import annotations

import getpass
import logging
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from subprocess import DEVNULL
from typing import TYPE_CHECKING, Literal, TypeAlias

import requests
from jinja2 import Template

from repo_utilities.gpg import TempGPG

if TYPE_CHECKING:
    from collections.abc import Generator, Sequence

    from _typeshed import StrPath

    from repo_utilities.utils import ARCH

logger = logging.getLogger("repo_utilities")


DEBUG = False

LICENSES: TypeAlias = Literal[
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
]
IGNORED_DIRS = {"__pycache__"}


@dataclass(frozen=True)
class BuildConf:
    """Configuration for building a Debian package."""

    source: StrPath
    package: str
    version: str
    additional_dir: StrPath | None = None
    root_dir: StrPath | None = None
    install_dir: StrPath = Path("/")
    email: str | None = field(default_factory=lambda: os.getenv("APTMAIL"))
    name: str | None = field(default_factory=lambda: os.getenv("APTNAME"))
    arch: ARCH = "all"
    compression: int = 1
    jobs: int = 0
    output: StrPath = Path()
    binary: str | None = None
    exclude: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    executable: list[StrPath] = field(default_factory=list)
    desktop: tuple[StrPath, StrPath, StrPath] | None = None
    homepage: str | None = None
    desc: str | None = None
    depends: str | None = None
    license: LICENSES | None = None
    key: StrPath | None = None


def set_xz_env(compression: int = 1, jobs: int = 0) -> None:
    """Set environment variables for xz compression."""
    os.environ["XZ_OPT"] = f"-{compression} -T{jobs}"
    os.environ["XZ_DEFAULTS"] = f"-{compression} -T{jobs}"


def extract_homepage_desc(cask_or_formula: str) -> tuple[str | None, str | None]:
    """Extract homepage and description from a cask or formula."""
    first_letter = cask_or_formula[0]
    base_url = f"https://raw.githubusercontent.com/Homebrew/homebrew-{{}}/master/{{}}/{first_letter}/{cask_or_formula}.rb"

    # Determine which file to use based on the first letter
    # re match desc "(match)" and homepage "(match)"
    for repo, subdir in (("core", "Formula"), ("cask", "Casks")):
        url = base_url.format(repo, subdir)
        response = requests.get(url, timeout=2)
        if response.status_code == 404:  # noqa: PLR2004
            continue
        if response.status_code == 200:  # noqa: PLR2004
            content = response.text
            desc_match = re.search(r'desc\s+"(.*?)"', content)
            homepage_match = re.search(r'homepage\s+"(.*?)"', content)
            if not desc_match or not homepage_match:
                raise ValueError("Description or homepage not found in the file.")
            return desc_match.group(1), homepage_match.group(1)
        raise ValueError(f"Unexpected status code: {response.status_code}")
    return None, None


def non_debian_files(source_dir: StrPath) -> Generator[Path]:
    """Find all files/folders which are not in the debian control folders."""
    source_dir = Path(source_dir).resolve()
    subdirs = [p for p in source_dir.iterdir() if p.is_dir() and p.name not in {"debian", "DEBIAN"}]
    subfiles = [p for p in source_dir.iterdir() if p.is_file()]

    yield from subfiles
    for subdir in subdirs:
        yield from subdir.rglob("*")


def find_install_files(source_dir: StrPath, root_dir: StrPath | None = None) -> list[Path]:
    """Find all files in the source_dir."""
    logger.debug("Collecting install files...")
    found_files: list[Path] = []
    source_dir = Path(source_dir)
    root_dir = root_dir or source_dir
    root_dir = Path(root_dir)
    for file in non_debian_files(root_dir):
        if file.parent == source_dir and file.suffix == ".desktop":
            continue
        if file.parent == source_dir / "icons":
            continue
        found_files.append(file)

    return found_files


def write_install_file(  # noqa: C901
    files: Sequence[StrPath],
    source_dir: StrPath,
    root_dir: StrPath | None = None,
    install_dir: StrPath = Path("/"),
) -> set[Path]:
    """Write the `install` file for Debian packaging."""
    logger.debug("Writing install file...")
    source_dir = Path(source_dir).resolve()
    root_dir = root_dir or source_dir
    root_dir = Path(root_dir).resolve()
    file_hierarchy: dict[Path, list[Path]] = {}
    for raw_file in files:
        file = Path(raw_file)
        if file.is_file():
            file_hierarchy.setdefault(file.parent, []).append(file)

    fixed_files: set[Path] = set()
    for parent, subfiles in file_hierarchy.items():
        if parent.name in IGNORED_DIRS:  # like __pycache__
            continue
        if not subfiles:  # pragma: no cover
            # setdefault(parent, []).append(file) above means every entry is non-empty.
            continue
        fixed_files.add(parent)

    def _is_parent_in_set(child: Path, _set: set[Path]) -> bool:
        if Path("/") in _set or Path() in _set:  # pragma: no cover
            # Only reachable if the source tree's resolved root is "/" or cwd.
            raise ValueError("Root directory or current directory is in set")
        if child.parent == child:  # . or /
            return False
        if child.parent in _set:
            return True
        return _is_parent_in_set(child.parent, _set)

    fixed_files = {parent for parent in fixed_files if not _is_parent_in_set(parent, fixed_files)}

    logger.debug("Filtered fixed files: %s", fixed_files)

    allowed_dirs = {install_dir / parent.relative_to(root_dir) for parent in file_hierarchy}

    install_file = source_dir / "debian" / "install"
    with install_file.open("w") as f:
        for file in sorted(fixed_files):
            target = install_dir / file.relative_to(root_dir)
            target_str = str(target.parent).removeprefix("/")
            f.write(f"{file.relative_to(source_dir)} {target_str}\n")

    logger.debug(install_file.read_text())

    return allowed_dirs


def copy_additional_files(source_dir: StrPath, additional_dir: StrPath) -> None:
    """Copy additional files to the target directory."""
    source_dir = Path(source_dir).resolve()
    debian_dir = source_dir / "debian"
    additional_dir = Path(additional_dir).resolve()

    shutil.copytree(additional_dir, debian_dir, dirs_exist_ok=True)


def dh_make(  # noqa: PLR0913, PLR0917
    source_dir: StrPath,
    name: str | None = None,
    email: str | None = None,
    license: LICENSES | None = None,  # noqa:A002
    arch: ARCH = "all",
    compression: int = 1,
    jobs: int = 0,
) -> None:
    """Create debian dir and default files."""
    logger.debug("Running dh_make...")
    source_dir = Path(source_dir).resolve()
    debian_dir = source_dir / "debian"

    if debian_dir.exists():
        logger.debug("Debian directory already exists.")
        return

    set_xz_env(compression, jobs)
    os.environ["DEBEMAIL"] = email or f"unknown@{socket.gethostname()}"
    os.environ["DEBFULLNAME"] = name or getpass.getuser()

    if not email or not name:
        raise ValueError("Name and email must be provided.")

    args: list[str] = ["dh_make", "-y", "-n"]

    if license:
        args.extend(["-c", license])

    type = "i" if arch == "all" else "s"  # noqa: A001
    args.append(f"-{type}")

    logger.debug(args)

    subprocess.check_call(args, stdout=DEVNULL, cwd=source_dir)  # noqa: S603

    # clean up .ex files, README.* files and *.docs files
    for file in debian_dir.rglob("*.ex"):
        file.unlink()
    for file in debian_dir.rglob("README.*"):
        file.unlink()
    for file in debian_dir.rglob("*.docs"):
        file.unlink()


def update_control(  # noqa: PLR0913, PLR0917
    source_dir: StrPath,
    package: str,
    depends: str | None,
    homepage: str | None,
    desc: str | None,
    arch: ARCH,
) -> None:
    """Update the control file with additional information."""
    logger.debug("Updating control file...")
    source_dir = Path(source_dir).resolve()
    debian_dir = source_dir / "debian"

    control_file = debian_dir / "control"

    content = control_file.read_text("utf-8")

    content = content.replace("Architecture: any", f"Architecture: {arch}")

    if depends:
        # Depends: {{ insert here }}, ${shlibs:Depends}, ${misc:Depends}
        content = content.replace("Depends: ", f"Depends: {depends}, ")

    if not homepage or not desc:
        brew_desc, brew_homepage = extract_homepage_desc(package)
        homepage = homepage or brew_homepage
        desc = desc or brew_desc

    if not homepage or not desc:
        raise ValueError(
            "Homepage and Description are required and could not be extracted from Homebrew."
        )

    content = content.replace(
        "Homepage: <insert the upstream URL, if relevant>", f"Homepage: {homepage}"
    )

    description_pattern = re.compile(r"Description:.*\n .*", re.DOTALL)
    content = description_pattern.sub(f"Description: {desc}", content)

    control_file.write_text(content, "utf-8")


def cleanup(source_dir: StrPath, package: str, version: str) -> None:
    """Clean up the source directory."""
    logger.debug("Cleaning up...")
    for file in Path(source_dir).parent.rglob(f"{package}_{version}*"):
        if "".join(file.suffixes).endswith(
            (
                ".buildinfo",
                ".tar.xz",
                ".debian.tar.xz",
                ".dsc",
                ".orig.tar.gz",
                ".changes",
                ".ddeb",
            )
        ):
            file.unlink()
    if not DEBUG:
        shutil.rmtree(source_dir)


def dpkg_buildpackage(
    source_dir: StrPath,
    compression: int = 1,
    jobs: int = 0,
    arch: ARCH = "all",
    priv_file: StrPath | None = None,
) -> None:
    """Build the package."""
    logger.debug("Building package...")
    source_dir = Path(source_dir).resolve()
    set_xz_env(compression, jobs)
    os.environ["DPKG_DEB_THREADS_MAX"] = str(jobs)

    cmd_args = ["dpkg-buildpackage", f"-j{jobs}"]

    if arch != "all":
        cmd_args.append(f"-a{arch}")

    if not priv_file:
        logger.debug("Building without signing...")
        cmd_args.extend(["-uc", "-us"])
        subprocess.check_call(cmd_args, cwd=source_dir)  # noqa: S603
        return

    with TempGPG(source_dir) as gpg:
        logger.debug("Building with signing using %s...", priv_file)
        gpg.import_priv_key(priv_file)
        key = gpg.list_keys(secret=True)[0]["fingerprint"]
        cmd_args.append(f"-k={key}")
        subprocess.check_call(cmd_args, cwd=source_dir)  # noqa: S603


def disable_debhelper_scripts(debian_dir: StrPath, scripts_to_disable: list[str]) -> None:
    """Disable debhelper scripts."""
    rules = Path(debian_dir) / "rules"
    with rules.open("a") as rules_file:
        for script in scripts_to_disable:
            disable_line = f"override_dh_{script}:\n\ttrue\n"
            rules_file.write(disable_line)


def add_desktop_file(  # noqa: PLR0913, PLR0917
    source_dir: StrPath,
    package: str,
    version: str,
    template: StrPath,
    desktop_exec: StrPath,
    icon: StrPath,
) -> None:
    """Add a desktop file to the package."""
    source_dir = Path(source_dir).resolve()
    debian_dir = source_dir / "debian"

    template_content = Path(template).read_text("utf-8")
    parsed_template = Template(template_content).render(
        name=package, exec=desktop_exec, version=version, icon=package
    )
    desktop = source_dir / f"{package}.desktop"
    desktop.write_text(parsed_template, "utf-8")
    install_file = debian_dir / "install"
    icons_dir = source_dir / "icons"
    Path(icons_dir).mkdir(exist_ok=True)
    icon = Path(icon)
    icon_name = f"{package}{icon.suffix}"
    shutil.copy(icon, icons_dir / icon_name)
    with install_file.open("a", encoding="utf-8") as f:
        f.write(f"{desktop.name} /usr/share/applications\n")
        f.write(f"icons/{icon_name} /usr/share/icons/hicolor/scalable/apps\n")


def unpack_source(
    source: StrPath,
    output: StrPath,
    binary: str | None = None,
    exclude: list[str] | None = None,
) -> None:
    """Unpack the source archive."""
    if exclude is None:
        exclude = []

    source = Path(source).resolve()
    output = Path(output)
    cmd_args = ["file", "-b", "--mime-type", str(source)]
    logger.debug(cmd_args)

    mime_output = subprocess.check_output(cmd_args, text=True)  # noqa: S603
    mime_type = mime_output.strip().split("/")[1].removeprefix("x-")

    if mime_type == "executable":
        output_name = binary or source.name
        binary_path = output / "bin"
        output.mkdir()
        binary_path.mkdir()
        shutil.copy(source, binary_path / output_name)
    elif mime_type in {"tar", "gzip", "bzip2", "zstd"}:
        cmd_args = ["tar"]
        if mime_type == "gzip":
            cmd_args.extend(["-I", "pigz"])
        elif mime_type == "bzip2":
            cmd_args.extend(["-I", "pbzip2"])
        elif mime_type == "zstd":
            cmd_args.extend(["-I", "zstd"])
        for pattern in exclude:
            cmd_args.extend(["--exclude", pattern])
        cmd_args.extend(["-xvf", str(source), "-C", str(output)])

        logger.debug(cmd_args)

        Path(output).mkdir()
        subprocess.check_call(cmd_args, stdout=DEVNULL, stderr=DEVNULL)  # noqa: S603
    else:
        raise ValueError(f"Unknown mime type {mime_type}")


def build_deb(args: BuildConf) -> None:
    """Main entrypoint."""
    source = Path(args.source).resolve()
    output = Path(args.output).resolve() / f"{args.package}-{args.version}"

    if not output.exists():
        unpack_source(source, output, args.binary, args.exclude)
    else:
        logger.debug("Output directory %s already exists. Skipping unpacking.", output)

    source_dir = output
    root_dir = Path(args.root_dir).resolve() if args.root_dir else None
    install_dir = args.install_dir

    dh_make(
        source_dir,
        args.name,
        args.email,
        args.license,
        args.arch,
        args.compression,
        args.jobs,
    )

    update_control(source_dir, args.package, args.depends, args.homepage, args.desc, args.arch)

    files = find_install_files(source_dir, root_dir)
    allowed_dirs = write_install_file(files, source_dir, root_dir, install_dir)

    debian_dir = source_dir / "debian"

    if args.additional_dir:
        copy_additional_files(source_dir, args.additional_dir)

    links: list[str] = []

    allowed_dirs_str = ", ".join(str(x) for x in allowed_dirs)
    for raw_file in args.executable:
        file = Path(raw_file)
        dst = Path("/usr/bin") / file.stem

        if file.parent not in allowed_dirs:
            raise ValueError(
                f"Executable {file} is outside of allowed directories: {allowed_dirs_str}"
            )
        links.append(f"{file} {dst}")

    if links:
        Path(debian_dir / "links").write_text("\n".join(links) + "\n", "utf-8")

    if args.desktop:
        template, desktop_exec, icon = args.desktop
        desktop_exec = Path(desktop_exec)
        if desktop_exec.parent not in allowed_dirs:
            raise ValueError(
                f"Desktop executable {desktop_exec} is outside of allowed directories:"
                f" {allowed_dirs_str}"
            )
        add_desktop_file(source_dir, args.package, args.version, template, desktop_exec, icon)

    disable_debhelper_scripts(debian_dir, args.disable)

    dpkg_buildpackage(source_dir, args.compression, args.jobs, args.arch, args.key)

    cleanup(source_dir, args.package, args.version)
