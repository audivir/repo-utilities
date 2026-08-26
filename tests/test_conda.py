"""Tests for repo_utilities.conda."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import conda_index.api
import pytest
import requests.exceptions as req_errors

from repo_utilities import conda

if TYPE_CHECKING:
    from pathlib import Path


def test_build_channel_symlinks_packages_and_creates_arch_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_update_index = MagicMock()
    monkeypatch.setattr(conda_index.api, "update_index", mock_update_index)

    channel = tmp_path / "channel"
    pkg_src_dir = tmp_path / "pkgs"
    pkg_src_dir.mkdir()
    pkg = pkg_src_dir / "foo-1.0-0.tar.bz2"
    pkg.write_bytes(b"fake-pkg-data")

    conda.build_channel(channel, [pkg], "amd64")

    arch_channel = channel / "linux-64"
    assert arch_channel.is_dir()
    linked = arch_channel / pkg.name
    assert linked.is_symlink()
    assert linked.read_bytes() == b"fake-pkg-data"
    mock_update_index.assert_called_once_with(channel)


def test_build_channel_raises_for_unsupported_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(conda_index.api, "update_index", MagicMock())
    channel = tmp_path / "channel"
    bad_pkg = tmp_path / "bad.zip"
    bad_pkg.write_bytes(b"nope")

    with pytest.raises(ValueError, match="Unexpected file"):
        conda.build_channel(channel, [bad_pkg], "amd64")


def test_build_channel_reformats_json_files_with_indent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    channel = tmp_path / "channel"

    def fake_update_index(target: Path) -> None:
        # Simulate conda-index writing a compact repodata.json.
        (target / "linux-64").mkdir(parents=True, exist_ok=True)
        (target / "linux-64" / "repodata.json").write_text(
            json.dumps({"a": 1, "b": [1, 2]}), "utf-8"
        )

    monkeypatch.setattr(conda_index.api, "update_index", fake_update_index)

    conda.build_channel(channel, [], "amd64")

    content = (channel / "linux-64" / "repodata.json").read_text("utf-8")
    assert content == json.dumps({"a": 1, "b": [1, 2]}, indent=4)


def test_build_channel_replaces_existing_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(conda_index.api, "update_index", MagicMock())
    channel = tmp_path / "channel"
    pkg_src_dir = tmp_path / "pkgs"
    pkg_src_dir.mkdir()
    pkg = pkg_src_dir / "foo-1.0-0.conda"
    pkg.write_bytes(b"v1")

    conda.build_channel(channel, [pkg], "amd64")
    pkg.write_bytes(b"v2")
    conda.build_channel(channel, [pkg], "amd64")

    linked = channel / "linux-64" / pkg.name
    assert linked.read_bytes() == b"v2"


def make_recipe(tmp_path: Path) -> Path:
    recipe = tmp_path / "myrecipe"
    recipe.mkdir()
    (recipe / "meta.yaml").write_text("package:\n  name: {{ name }}\n", "utf-8")
    return recipe


def test_build_pkg_renders_templates_and_calls_rattler_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recipe = make_recipe(tmp_path)
    target_dir = tmp_path / "out"

    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(conda, "TemporaryDirectory", lambda: RealTemporaryDirectory(dir=tmp_path))

    captured_recipe: dict[str, object] = {}

    def fake_rattler_build(
        recipe_path: Path,
        out_dir: Path,  # noqa: ARG001
        **kwargs: object,
    ) -> tuple[Path, list[object], int]:
        # The temp recipe dir is deleted right after build_pkg returns, so
        # read the rendered content now, while it still exists.
        captured_recipe["rendered"] = (recipe_path / "meta.yaml").read_text("utf-8")
        captured_recipe["kwargs"] = kwargs
        return (target_dir, [], 0)

    monkeypatch.setattr(conda, "optimized_rattler_build", fake_rattler_build)

    result = conda.build_pkg(target_dir, recipe, "amd64", channels=None, vars={"name": "mypkg"})

    assert result == (target_dir, [], 0)
    assert captured_recipe["rendered"] == "package:\n  name: mypkg"
    kwargs = captured_recipe["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["target_platform"] == "linux-64"
    assert kwargs["channels"] == ["conda-forge"]
    assert kwargs["clean_bld_cache"] is True
    assert kwargs["clean_src_cache"] is True
    assert kwargs["skip_existing"] is True


def test_build_pkg_creates_own_session_when_none_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recipe = make_recipe(tmp_path)
    target_dir = tmp_path / "out"

    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(conda, "TemporaryDirectory", lambda: RealTemporaryDirectory(dir=tmp_path))
    monkeypatch.setattr(
        conda,
        "optimized_rattler_build",
        lambda recipe_path, out_dir, **kwargs: (None, [], 0),  # noqa: ARG005
    )

    fake_session = MagicMock()
    fake_session.get.return_value.raise_for_status.return_value = None
    mock_session_cls = MagicMock(return_value=fake_session)
    monkeypatch.setattr(conda, "Session", mock_session_cls)

    conda.build_pkg(target_dir, recipe, "amd64", channels=["https://example.com/conda"])

    # No session was passed in, so build_pkg must construct its own.
    mock_session_cls.assert_called_once()
    fake_session.get.assert_called_once_with("https://example.com/conda")


def test_build_pkg_checks_reachable_channel_and_includes_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recipe = make_recipe(tmp_path)
    target_dir = tmp_path / "out"

    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(conda, "TemporaryDirectory", lambda: RealTemporaryDirectory(dir=tmp_path))

    captured: dict[str, object] = {}

    def fake_rattler_build(
        recipe_path: Path,  # noqa: ARG001
        out_dir: Path,  # noqa: ARG001
        **kwargs: object,
    ) -> tuple[Path | None, list[object], int]:
        captured["kwargs"] = kwargs
        return None, [], 0

    monkeypatch.setattr(conda, "optimized_rattler_build", fake_rattler_build)

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_session.get.return_value = mock_response

    conda.build_pkg(
        target_dir,
        recipe,
        "amd64",
        channels=["https://example.com/conda"],
        session=mock_session,
    )

    mock_session.get.assert_called_once_with("https://example.com/conda")
    assert captured["kwargs"]["channels"] == [  # type: ignore[index]
        "https://example.com/conda",
        "conda-forge",
    ]


@pytest.mark.parametrize(
    "make_failure",
    [
        lambda session: setattr(
            session.get.return_value.raise_for_status,
            "side_effect",
            req_errors.HTTPError(),
        ),
        lambda session: setattr(
            session, "get", MagicMock(side_effect=req_errors.ConnectionError())
        ),
    ],
)
def test_build_pkg_excludes_unreachable_channel_and_logs_none_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    make_failure: object,
) -> None:
    """The `response`/`reponse` variable-name typo means the logged status.

    is always ``None`` regardless of the actual failure, since ``response``
    (used in the log call) is never assigned -- only the similarly-named
    ``reponse`` is. This test documents that real (if surprising) behavior.
    """
    recipe = make_recipe(tmp_path)
    target_dir = tmp_path / "out"

    from repo_utilities.temp import TemporaryDirectory as RealTemporaryDirectory

    monkeypatch.setattr(conda, "TemporaryDirectory", lambda: RealTemporaryDirectory(dir=tmp_path))
    monkeypatch.setattr(
        conda,
        "optimized_rattler_build",
        lambda recipe_path, out_dir, **kwargs: (None, [], 0),  # noqa: ARG005
    )

    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 503
    mock_session.get.return_value = mock_response
    make_failure(mock_session)  # type: ignore[operator]

    caplog.set_level(logging.ERROR, logger="repo_utilities")

    conda.build_pkg(
        target_dir,
        recipe,
        "amd64",
        channels=["https://example.com/conda"],
        session=mock_session,
    )

    assert "Only conda-forge will be used" in caplog.text
    # Despite mock_response.status_code == 503, the log always reports None.
    assert "None" in caplog.text
    assert "503" not in caplog.text
