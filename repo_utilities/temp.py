"""Expands the `tempfile` module."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from typing_extensions import override

if TYPE_CHECKING:
    from _typeshed import StrPath

logger = logging.getLogger("repo_utilities")


class TemporaryDirectory(tempfile.TemporaryDirectory[str]):
    """A temporary directory context manager.

    With `TMPDIR_DEBUG` set, the directory won't be removed.

    Attributes:
        path (Path): The path of the temporary directory.
    """

    def __init__(
        self,
        prefix: str | None = None,
        dir: StrPath | None = None,  # noqa: A002
    ) -> None:
        """Initialize the class.

        Args:
            prefix: The prefix of the temporary directory.
            dir: The directory to create the temporary directory in.
        """
        self.debug = bool(os.getenv("TMPDIR_DEBUG"))
        super().__init__(prefix=prefix, dir=dir)
        self.path = Path(self.name)

        if self.debug:
            logger.warning("Temporary directory created and won't be removed: %s", self.name)

    @override
    def __enter__(self) -> Path:  # type: ignore[override]
        """Changed from `str` to `Path`.

        Returns:
            The path of the temporary directory.
        """
        return self.path

    @classmethod
    def _cleanup(cls, name: str, warn_message: str, ignore_errors: bool = False) -> None:
        if bool(os.getenv("TMPDIR_DEBUG")):
            logger.warning("Temporary directory %s not removed.", name)
        else:
            super()._cleanup(name, warn_message, ignore_errors)  # type: ignore[misc]

    @override
    def cleanup(self) -> None:
        """Remove the temporary directory or warn if `TMPDIR_DEBUG` is set."""
        if self.debug:
            logger.warning("Temporary directory %s not removed.", self.name)
        else:
            super().cleanup()


__all__ = ["TemporaryDirectory"]
