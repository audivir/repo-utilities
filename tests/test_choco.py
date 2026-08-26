"""Tests for repo_utilities.choco."""

from __future__ import annotations

import json
import os
import subprocess
from subprocess import DEVNULL
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import psutil
import pytest

from repo_utilities import choco

if TYPE_CHECKING:
    from pathlib import Path


def test_choco_raises_if_conda_prefix_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with pytest.raises(ValueError, match="CONDA_PREFIX"):
        choco.choco(["list"])


def test_choco_invokes_mono_with_choco_exe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path))
    mock_check_output = MagicMock(return_value="output")
    monkeypatch.setattr(subprocess, "check_output", mock_check_output)

    result = choco.choco(["pack", "foo.nuspec"], cwd=tmp_path)

    assert result == "output"
    args, kwargs = mock_check_output.call_args
    assert args[0] == [
        f"{tmp_path}/bin/mono",
        f"{tmp_path}/opt/chocolatey/choco.exe",
        "pack",
        "foo.nuspec",
    ]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["text"] is True
    assert kwargs["stderr"] == DEVNULL


def test_build_choco_symlinks_packages_and_writes_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg_dir = tmp_path / "pkgs"
    pkg_dir.mkdir()
    pkg = pkg_dir / "mytool.1.0.0.nupkg"
    pkg.write_bytes(b"nupkg-data")

    choco.build_choco(repo, [pkg])

    linked = repo / pkg.name
    assert linked.is_symlink()
    assert linked.read_bytes() == b"nupkg-data"

    app_yaml = (repo / "app.yaml").read_text("utf-8")
    assert "runtime: nodejs22" in app_yaml

    packages_json = json.loads((repo / "packages.json").read_text("utf-8"))
    assert packages_json == choco.CHOCO_SERVER_PACKAGE_JSON


def test_build_choco_raises_for_non_nupkg(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    bad_pkg = tmp_path / "not_a_pkg.zip"
    bad_pkg.write_bytes(b"nope")

    with pytest.raises(ValueError, match="Unexpected file"):
        choco.build_choco(repo, [bad_pkg])


def test_build_choco_replaces_existing_symlink(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    pkg_dir = tmp_path / "pkgs"
    pkg_dir.mkdir()
    pkg = pkg_dir / "mytool.1.0.0.nupkg"
    pkg.write_bytes(b"v1")

    choco.build_choco(repo, [pkg])
    pkg.write_bytes(b"v2")
    choco.build_choco(repo, [pkg])

    assert (repo / pkg.name).read_bytes() == b"v2"


def test_pack_pkg_renders_templates_and_moves_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(
        choco,
        "TemporaryDirectory",
        lambda prefix: RealTemporaryDirectory(prefix=prefix, dir=tmp_path),
    )

    nuspec_dir = tmp_path / "nuspec_src"
    nuspec_dir.mkdir()
    nuspec = nuspec_dir / "pkg.nuspec"
    nuspec.write_text("<id>{{ name }}</id>", "utf-8")
    binary_file = nuspec_dir / "logo.png"
    binary_file.write_bytes(b"\xff\xd8\xff\xe0not-really-a-jpeg\x00\x01")
    # A subdirectory must be skipped by the `not file.is_file()` guard
    # instead of being (fruitlessly) treated as a template.
    (nuspec_dir / "subdir").mkdir()

    def fake_choco(args: list[str], cwd: Path) -> str:
        # Simulate `choco pack` producing a .nupkg file in the working dir.
        assert args[0] == "pack"
        (cwd / "pkg.1.0.0.nupkg").write_bytes(b"packed")
        return "ok"

    monkeypatch.setattr(choco, "choco", fake_choco)

    target = tmp_path / "final" / "pkg.nupkg"
    target.parent.mkdir()

    choco.pack_pkg(nuspec, target, vars={"name": "mypkg"})

    assert target.read_bytes() == b"packed"


def test_pack_pkg_without_vars_skips_rendering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(
        choco,
        "TemporaryDirectory",
        lambda prefix: RealTemporaryDirectory(prefix=prefix, dir=tmp_path),
    )

    nuspec_dir = tmp_path / "nuspec_src"
    nuspec_dir.mkdir()
    nuspec = nuspec_dir / "pkg.nuspec"
    original_content = "<id>{{ name }}</id>"
    nuspec.write_text(original_content, "utf-8")

    captured: dict[str, str] = {}

    def fake_choco(args: list[str], cwd: Path) -> str:  # noqa: ARG001
        captured["content"] = (cwd / "pkg.nuspec").read_text("utf-8")
        (cwd / "pkg.nupkg").write_bytes(b"packed")
        return "ok"

    monkeypatch.setattr(choco, "choco", fake_choco)

    target = tmp_path / "pkg.nupkg"
    choco.pack_pkg(nuspec, target)

    # No vars provided, so the template placeholder must remain untouched.
    assert captured["content"] == original_content


def test_restart_server_warns_when_no_node_process_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(psutil, "process_iter", MagicMock(return_value=[]))
    mock_popen = MagicMock()
    monkeypatch.setattr(subprocess, "Popen", mock_popen)
    repo = tmp_path
    (repo / "a.nupkg").write_bytes(b"x")

    choco.restart_server(repo)

    mock_popen.assert_called_once()
    args, kwargs = mock_popen.call_args
    assert args[0] == ["/usr/bin/nohup", "npx", "express-chocolatey-server", "a.nupkg"]
    assert kwargs["cwd"] == repo


def test_restart_server_kills_existing_node_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    matching_proc = MagicMock()
    matching_proc.name.return_value = "node"
    matching_proc.cmdline.return_value = ["node", "express-chocolatey-server", "a.nupkg"]
    matching_proc.pid = 1234

    other_proc = MagicMock()
    other_proc.name.return_value = "python"

    # A "node" process whose cmdline does not reference our server must be
    # left alone (only the express-chocolatey-server one gets killed).
    unrelated_node_proc = MagicMock()
    unrelated_node_proc.name.return_value = "node"
    unrelated_node_proc.cmdline.return_value = ["node", "some-other-script.js"]

    monkeypatch.setattr(
        psutil,
        "process_iter",
        MagicMock(return_value=[matching_proc, other_proc, unrelated_node_proc]),
    )
    mock_process_cls = MagicMock()
    monkeypatch.setattr(psutil, "Process", mock_process_cls)
    monkeypatch.setattr(subprocess, "Popen", MagicMock())

    choco.restart_server(tmp_path, port=8080)

    mock_process_cls.assert_called_once_with(1234)
    mock_process_cls.return_value.kill.assert_called_once()
    mock_process_cls.return_value.wait.assert_called_once()
    assert os.environ["PORT"] == "8080"


def test_restart_server_raises_for_multiple_node_processes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def make_proc(pid: int) -> MagicMock:
        proc = MagicMock()
        proc.name.return_value = "node"
        proc.cmdline.return_value = ["node", "express-chocolatey-server"]
        proc.pid = pid
        return proc

    monkeypatch.setattr(
        psutil,
        "process_iter",
        MagicMock(return_value=[make_proc(1), make_proc(2)]),
    )

    with pytest.raises(ValueError, match="More than one node process"):
        choco.restart_server(tmp_path)
