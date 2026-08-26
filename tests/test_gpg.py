"""Tests for repo_utilities.gpg.

GPG key creation/signing is fully mocked: no real gpg binary, keyring, or
subprocess call is exercised (the environment this suite runs in has no
`/bin/gpg`, and `gnupg.GPG()` itself requires a real gpg binary to
construct, so `GPG2`/`TempGPG` are stubbed at the seams instead of
constructed for real).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from gnupg._parsers import Sign
from typing_extensions import override

from repo_utilities.gpg import (
    GPG2,
    KeyCreationError,
    TempGPG,
    _orig_handle_status,
    create_priv_key,
    patched_handle_status,
    sign_repo,
)


class FakeTempGPG:
    """Stand-in for TempGPG that hands back a pre-built fake gpg object."""

    instances: ClassVar[list[FakeTempGPG]] = []

    def __init__(self, dir: Path | None = None) -> None:  # noqa: A002
        """Record this instance and prepare its fake gpg object."""
        self.dir = dir
        self.gpg: MagicMock = MagicMock()
        FakeTempGPG.instances.append(self)

    def __enter__(self) -> MagicMock:
        return self.gpg

    def __exit__(self, *args: object) -> None:
        return None


@pytest.fixture(autouse=True)
def _reset_fake_instances() -> None:
    FakeTempGPG.instances = []


def test_patched_handle_status_normalizes_warning_key() -> None:
    fake_self = MagicMock()
    fake_self.status = None

    patched_handle_status(fake_self, "WARNING", "some value")

    assert fake_self.status == "warning"


def test_patched_handle_status_delegates_other_keys_to_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_orig = MagicMock()
    monkeypatch.setattr("repo_utilities.gpg._orig_handle_status", mock_orig)

    fake_self = MagicMock()
    patched_handle_status(fake_self, "NEWSIG", "value")

    mock_orig.assert_called_once_with(fake_self, "NEWSIG", "value")


def test_sign_is_patched_with_our_handler() -> None:
    # The module patches Sign._handle_status at import time; verify it is
    # indeed our function and not the pristine gnupg implementation.
    assert Sign._handle_status is patched_handle_status  # noqa: SLF001
    assert _orig_handle_status is not patched_handle_status


def make_gpg2(homedir: Path) -> GPG2:
    """Build a GPG2 instance without invoking gnupg.GPG.__init__.

    Constructing a real gnupg.GPG requires a local gpg binary discoverable
    by gnupg's own binary search, which this environment does not
    guarantee; the methods under test here only use `self.homedir`.
    """
    instance = GPG2.__new__(GPG2)
    instance.ignore_homedir_permissions = True
    instance.homedir = str(homedir)
    return instance


def test_gpg2_import_priv_key_invokes_gpg_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)
    homedir = tmp_path / "home"
    homedir.mkdir()
    key_file = tmp_path / "key.asc"
    key_file.write_text("key-data", "utf-8")

    gpg = make_gpg2(homedir)
    gpg.import_priv_key(key_file)

    args, kwargs = mock_check_call.call_args
    cmd = args[0]
    assert cmd[:2] == ["/bin/gpg", "--import"]
    assert Path(cmd[2]) == key_file.expanduser().resolve()
    assert kwargs["env"]["GNUPGHOME"] == str(homedir)


@pytest.mark.parametrize(
    ("secret", "armor", "expected_flag", "expect_armor"),
    [
        (False, True, "--export", True),
        (True, True, "--export-secret-keys", True),
        (False, False, "--export", False),
    ],
)
def test_gpg2_export_key_builds_expected_command(  # noqa: PLR0913, PLR0917
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    secret: bool,
    armor: bool,
    expected_flag: str,
    expect_armor: bool,
) -> None:
    mock_check_output = MagicMock(return_value=b"exported-bytes")
    monkeypatch.setattr(subprocess, "check_output", mock_check_output)
    homedir = tmp_path / "home"
    homedir.mkdir()
    output = tmp_path / "out.key"

    gpg = make_gpg2(homedir)
    gpg.export_key(output, secret=secret, armor=armor)

    args, kwargs = mock_check_output.call_args
    cmd = args[0]
    assert cmd[0] == "/bin/gpg"
    assert expected_flag in cmd
    assert ("--armor" in cmd) is expect_armor
    assert kwargs["env"]["GNUPGHOME"] == str(homedir)
    assert output.read_bytes() == b"exported-bytes"


def test_gpg2_sign_file_writes_signed_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    src = tmp_path / "src.txt"
    src.write_text("payload", "utf-8")
    output = tmp_path / "out.sig"

    mock_sign_file: MagicMock = MagicMock()
    fake_result = MagicMock()
    fake_result.data = b"signed-bytes"
    mock_sign_file.return_value = fake_result
    monkeypatch.setattr("gnupg._meta.GPGBase._sign_file", mock_sign_file)

    gpg = make_gpg2(tmp_path / "home")
    gpg.sign_file(src, output, clearsign=False, detach=True, binary=False)

    assert output.read_bytes() == b"signed-bytes"
    _, kwargs = mock_sign_file.call_args
    assert kwargs == {"clearsign": False, "detach": True, "binary": False}


def test_temp_gpg_enter_creates_homedir_with_restricted_perms(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_gpg2 = MagicMock()
    monkeypatch.setattr("repo_utilities.gpg.GPG2", mock_gpg2)

    temp_gpg = TempGPG(dir=tmp_path)
    with temp_gpg:
        assert temp_gpg._tmp is not None  # noqa: SLF001
        pgp_dir = temp_gpg._tmp.path / "pgpkeys-AAAAAA"  # noqa: SLF001
        assert pgp_dir.is_dir()
        assert oct(pgp_dir.stat().st_mode)[-3:] == "700"
        mock_gpg2.assert_called_once_with(homedir=pgp_dir)

    # cleanup() removes the whole temp dir (TMPDIR_DEBUG unset by default).
    assert not pgp_dir.exists()


def test_temp_gpg_exit_without_enter_is_a_no_op(tmp_path: Path) -> None:
    # Calling __exit__ on a TempGPG that was never entered (self._tmp is
    # still None) must not raise, e.g. if a caller builds one but never
    # uses it as a context manager.
    TempGPG(dir=tmp_path).__exit__()


def test_create_priv_key_raises_if_file_already_exists(tmp_path: Path) -> None:
    priv_file = tmp_path / "priv.key"
    priv_file.write_text("existing", "utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        create_priv_key(priv_file)


def test_create_priv_key_export_key_side_effect_is_used(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeTempGPGWithExport(FakeTempGPG):
        @override
        def __enter__(self) -> MagicMock:
            gpg = super().__enter__()

            def fake_export_key(output: Any, secret: bool, armor: bool) -> None:  # noqa: ARG001
                Path(output).write_bytes(b"a-real-looking-key")

            gpg.export_key.side_effect = fake_export_key
            gpg.gen_key.return_value = "fingerprint123"
            return gpg

    monkeypatch.setattr("repo_utilities.gpg.TempGPG", FakeTempGPGWithExport)
    priv_file = tmp_path / "priv.key"

    create_priv_key(priv_file, tmp=tmp_path)

    assert priv_file.read_bytes() == b"a-real-looking-key"
    fake_gpg = FakeTempGPGWithExport.instances[0].gpg
    fake_gpg.gen_key_input.assert_called_once()
    fake_gpg.export_key.assert_called_once_with(output=priv_file, secret=True, armor=False)


def test_create_priv_key_raises_if_gen_key_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeTempGPGNoneKey(FakeTempGPG):
        @override
        def __enter__(self) -> MagicMock:
            gpg = super().__enter__()
            gpg.gen_key.return_value = None
            return gpg

    monkeypatch.setattr("repo_utilities.gpg.TempGPG", FakeTempGPGNoneKey)
    priv_file = tmp_path / "priv.key"

    with pytest.raises(KeyCreationError, match="GPG returned None"):
        create_priv_key(priv_file, tmp=tmp_path)


def test_create_priv_key_raises_if_export_creates_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("repo_utilities.gpg.TempGPG", FakeTempGPG)
    priv_file = tmp_path / "priv.key"

    with pytest.raises(KeyCreationError, match="No file at"):
        create_priv_key(priv_file, tmp=tmp_path)


def test_create_priv_key_raises_and_removes_file_if_export_is_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class FakeTempGPGEmptyExport(FakeTempGPG):
        @override
        def __enter__(self) -> MagicMock:
            gpg = super().__enter__()

            def fake_export_key(output: Any, secret: bool, armor: bool) -> None:  # noqa: ARG001
                Path(output).touch()

            gpg.export_key.side_effect = fake_export_key
            return gpg

    monkeypatch.setattr("repo_utilities.gpg.TempGPG", FakeTempGPGEmptyExport)
    priv_file = tmp_path / "priv.key"

    with pytest.raises(KeyCreationError, match="is empty"):
        create_priv_key(priv_file, tmp=tmp_path)

    assert not priv_file.exists()


def test_sign_repo_signs_release_and_exports_public_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("repo_utilities.gpg.TempGPG", FakeTempGPG)
    root = tmp_path / "repo"
    (root / "dists" / "stable").mkdir(parents=True)
    release = root / "dists" / "stable" / "Release"
    release.write_text("release-content", "utf-8")

    pub_file = tmp_path / "pub.gpg"
    priv_file = tmp_path / "priv.key"

    sign_repo(root, pub_file, priv_file, tmp=tmp_path)

    fake_gpg = FakeTempGPG.instances[0].gpg
    fake_gpg.import_priv_key.assert_called_once_with(priv_file)
    assert fake_gpg.sign_file.call_count == 2

    first_call = fake_gpg.sign_file.call_args_list[0]
    assert first_call.args == (release, release.with_suffix(".gpg"))
    assert first_call.kwargs == {"detach": True, "clearsign": False, "binary": False}

    second_call = fake_gpg.sign_file.call_args_list[1]
    assert second_call.args == (release, release.parent / "InRelease")
    assert second_call.kwargs == {"detach": False, "clearsign": True}

    fake_gpg.export_key.assert_called_once_with(pub_file, secret=False, armor=False)
