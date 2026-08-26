"""Key generation and signing functions.

Implements:
- `create_priv_key`: Create a PGP key.
- `sign_repo`: Sign the Release file and create the InRelease file.
"""

from __future__ import annotations

import logging
import os
import subprocess
from io import StringIO
from pathlib import Path
from subprocess import DEVNULL
from typing import TYPE_CHECKING

import gnupg
from gnupg._parsers import Sign

from repo_utilities.temp import TemporaryDirectory

if TYPE_CHECKING:
    from _typeshed import StrPath

logger = logging.getLogger("repo_utilities")


class KeyCreationError(Exception):
    """Key creation failed."""


# monkeypatch warning handler
_orig_handle_status = Sign._handle_status  # noqa: SLF001


def patched_handle_status(self: Sign, key: str, value: str) -> None:
    """Monkeypatch to handle the status of GPG operations."""
    if key == "WARNING":
        self.status = key.replace("_", " ").lower()
    else:
        _orig_handle_status(self, key, value)


Sign._handle_status = patched_handle_status  # noqa: SLF001


class GPG2(gnupg.GPG):  # type: ignore[misc]
    """GPG class with additional methods."""

    def import_priv_key(self, path: StrPath) -> None:
        """Import a GPG key from a file into the specified GPG context."""
        environ = os.environ.copy()
        environ["GNUPGHOME"] = str(self.homedir)
        subprocess.check_call(  # noqa: S603
            ["/bin/gpg", "--import", Path(path).expanduser().resolve()],
            env=environ,
            stderr=DEVNULL,
        )

    def export_key(self, output: StrPath, secret: bool = False, armor: bool = True) -> None:
        """Export a public key to a file."""
        environ = os.environ.copy()
        environ["GNUPGHOME"] = str(self.homedir)
        export_flag = "--export-secret-keys" if secret else "--export"
        cmd_args = ["/bin/gpg", export_flag]
        if armor:
            cmd_args.append("--armor")
        stdout = subprocess.check_output(  # noqa: S603
            cmd_args, env=environ
        )
        Path(output).write_bytes(stdout)

    def sign_file(
        self,
        file: StrPath,
        output: StrPath,
        clearsign: bool = True,
        detach: bool = False,
        binary: bool = False,
    ) -> None:
        """Sign a file and write the output to another file."""
        stream = StringIO(Path(file).read_text("utf-8"))
        stream.seek(0)
        content: Sign = super()._sign_file(
            stream, clearsign=clearsign, detach=detach, binary=binary
        )
        Path(output).write_bytes(content.data)


class TempGPG:
    """Create a temporary GPG home directory.

    Attributes:
        dir (Path, optional): The directory to create the temporary directory.
    """

    def __init__(
        self,
        dir: StrPath | None = None,  # noqa: A002
    ) -> None:
        """Initialize the TempGPG class.

        Args:
            dir (Path, optional): The directory to create the temporary directory.
                Defaults to None.
        """
        self._tmp: TemporaryDirectory | None = None
        self.dir = Path(dir) if dir else None

    def __enter__(self) -> GPG2:
        """Create the temporary GPG home directory.

        Returns:
            GPG2: The GPG object.
        """
        self._tmp = TemporaryDirectory(prefix="tmp_TempGPG_", dir=self.dir)
        tmp = self._tmp.path
        pgp_tmp = tmp / "pgpkeys-AAAAAA"
        pgp_tmp.mkdir(mode=0o700)

        return GPG2(homedir=pgp_tmp)

    def __exit__(self, *args: object) -> None:
        """Cleanup the temporary directory."""
        if not self._tmp:
            return

        self._tmp.cleanup()


def create_priv_key(priv_file: StrPath, tmp: StrPath | None = None) -> None:
    """Create a PGP key.

    Args:
        priv_file (Path): The path to the private key file.
        tmp (Path, optional): The temporary directory path. Defaults to None.

    Raises:
        FileExistsError: If the private key file already exists.
        KeyCreationError: If the key creation failed.
    """
    priv_file = Path(priv_file)
    if priv_file.exists():
        raise FileExistsError(f"{priv_file} already exists.")

    with TempGPG(tmp) as gpg:
        name_real = "example"
        name_email = "example@example.com"

        input_data = gpg.gen_key_input(
            Key_Type="RSA",
            Key_Length=4096,
            Name_Real=name_real,
            Name_Email=name_email,
            Expire_Date=0,
            no_protection=True,
        )
        key = gpg.gen_key(input_data)

        if key is None:
            raise KeyCreationError("GPG returned None.")

        gpg.export_key(output=priv_file, secret=True, armor=False)

        if not priv_file.exists():
            raise KeyCreationError(f"No file at {priv_file}")
        if not priv_file.stat().st_size:
            priv_file.unlink()
            raise KeyCreationError(f"File at {priv_file} is empty.")

    logger.warning("Created key file at %s", priv_file)


def sign_repo(
    root: StrPath, pub_file: StrPath, priv_file: StrPath, tmp: StrPath | None = None
) -> None:
    """Sign the Release file and create the InRelease file and exports the public key.

    Args:
        root: The root directory (subdirs: pool and dists).
        pub_file: Target public key file.
        priv_file: The private key file.
        tmp: The temporary directory path. Defaults to None.
    """
    release = Path(root) / "dists" / "stable" / "Release"

    with TempGPG(tmp) as gpg:
        # Import the private key to the temporary keyring
        gpg.import_priv_key(priv_file)
        # Sign the Release file
        # -abs: --armor --detach-sign --sign
        gpg.sign_file(
            release,
            release.with_suffix(".gpg"),
            detach=True,
            clearsign=False,
            binary=False,
        )

        # Sign the InRelease file
        # --clearsign: make a clear text signature
        gpg.sign_file(release, release.parent / "InRelease", detach=False, clearsign=True)

        gpg.export_key(pub_file, secret=False, armor=False)


__all__ = ["GPG2", "TempGPG", "create_priv_key", "sign_repo"]
