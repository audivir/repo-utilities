"""Tests for repo_utilities.apt.build_meta."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import repo_utilities.apt.build_meta  # noqa: F401  (registers it in sys.modules)

# See tests/test_build_repo.py for why the module is pulled from
# sys.modules: repo_utilities/apt/__init__.py re-exports the `build_meta`
# function, which shadows the submodule attribute of the same name on the
# `apt` package.
build_meta = sys.modules["repo_utilities.apt.build_meta"]


def test_build_meta_raises_without_name_or_email(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Name and email"):
        build_meta.build_meta(tmp_path, "mypkg", [], name=None, email="a@b.com")

    with pytest.raises(ValueError, match="Name and email"):
        build_meta.build_meta(tmp_path, "mypkg", [], name="Tim", email=None)


def test_build_meta_builds_control_file_and_invokes_dpkg_deb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_check_call(args: list[str]) -> int:
        captured["args"] = args
        work_dir = Path(args[2])
        control = work_dir / "DEBIAN" / "control"
        captured["control"] = control.read_text("utf-8")
        return 0

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)

    build_meta.build_meta(
        tmp_path,
        "mypkg",
        ["dep1", "dep2"],
        name="Tim",
        email="tim@example.com",
        version="1.2.3",
        arch="amd64",
    )

    control = captured["control"]
    assert isinstance(control, str)
    assert "Package: mypkg" in control
    assert "Version: 1.2.3" in control
    assert "Maintainer: Tim <tim@example.com>>" in control
    assert "Depends: dep1, dep2" in control
    assert "Architecture: amd64" in control

    args = captured["args"]
    assert isinstance(args, list)
    assert args[0] == "/usr/bin/dpkg-deb"
    assert args[1] == "--build"
    assert args[3] == str(tmp_path / "mypkg_1.2.3_amd64.deb")


def test_build_meta_uses_default_description_when_not_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, str] = {}

    def fake_check_call(args: list[str]) -> int:
        work_dir = Path(args[2])
        captured["control"] = (work_dir / "DEBIAN" / "control").read_text("utf-8")
        return 0

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)

    build_meta.build_meta(tmp_path, "mypkg", [], name="Tim", email="tim@example.com")

    assert "insert up to 60 chars description" in captured["control"]


def test_build_meta_uses_custom_description(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, str] = {}

    def fake_check_call(args: list[str]) -> int:
        work_dir = Path(args[2])
        captured["control"] = (work_dir / "DEBIAN" / "control").read_text("utf-8")
        return 0

    monkeypatch.setattr(subprocess, "check_call", fake_check_call)

    build_meta.build_meta(
        tmp_path, "mypkg", [], name="Tim", email="tim@example.com", desc="My custom desc"
    )

    assert "Description: My custom desc" in captured["control"]
