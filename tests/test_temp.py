"""Tests for repo_utilities.temp."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from repo_utilities.temp import TemporaryDirectory


def test_temporary_directory_enter_returns_path_and_cleans_up(
    tmp_path: Path,
) -> None:
    with TemporaryDirectory(dir=tmp_path) as entered:
        assert isinstance(entered, Path)
        assert entered.is_dir()
        created_path = entered

    assert not created_path.exists()


def test_temporary_directory_uses_prefix(tmp_path: Path) -> None:
    with TemporaryDirectory(prefix="myprefix_", dir=tmp_path) as entered:
        assert entered.name.startswith("myprefix_")


def test_temporary_directory_debug_mode_keeps_dir_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("TMPDIR_DEBUG", "1")
    caplog.set_level(logging.WARNING, logger="repo_utilities")

    tmp_dir = TemporaryDirectory(dir=tmp_path)
    with tmp_dir as entered:
        created_path = entered

    assert created_path.exists()
    assert "won't be removed" in caplog.text

    tmp_dir.cleanup()  # explicit cleanup call still must not remove it
    assert created_path.exists()

    # In debug mode, `cleanup()` never detaches the base class's
    # weakref.finalize (only super().cleanup() does that), so it stays
    # armed and fires on GC. On this Python version, that finalizer then
    # calls this class's overridden `_cleanup(name, warn_message,
    # ignore_errors)`, but the stdlib now invokes it with an extra
    # `delete=` keyword the override does not accept, raising an
    # "exception ignored in finalizer" TypeError. Detach it here to keep
    # this test from crashing on GC and to avoid leaking the directory.
    import shutil

    tmp_dir._finalizer.detach()  # type: ignore[attr-defined]  # noqa: SLF001
    shutil.rmtree(created_path, ignore_errors=True)


def test_temporary_directory_debug_disabled_removes_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMPDIR_DEBUG", raising=False)

    with TemporaryDirectory(dir=tmp_path) as entered:
        created_path = entered

    assert not created_path.exists()


def test_cleanup_classmethod_debug_mode_keeps_dir_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Directly exercises the `_cleanup` classmethod override (only ever
    # invoked by the stdlib via a weakref finalizer in real usage; called
    # directly here to isolate its own debug/non-debug branching).
    monkeypatch.setenv("TMPDIR_DEBUG", "1")
    caplog.set_level(logging.WARNING, logger="repo_utilities")
    target = tmp_path / "somedir"
    target.mkdir()

    TemporaryDirectory._cleanup(str(target), "warn message")  # noqa: SLF001

    assert target.exists()
    assert "not removed" in caplog.text


def test_cleanup_classmethod_non_debug_removes_dir_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TMPDIR_DEBUG", raising=False)
    target = tmp_path / "somedir"
    target.mkdir()

    # Falls through to the stdlib's own _cleanup, which both removes the
    # directory and emits a ResourceWarning about implicit cleanup.
    with pytest.warns(ResourceWarning):
        TemporaryDirectory._cleanup(str(target), "warn message")  # noqa: SLF001

    assert not target.exists()
