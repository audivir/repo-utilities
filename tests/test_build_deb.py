# %%
"""Test for build-deb."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import repo_utilities.apt.build_deb  # noqa: F401  (registers it in sys.modules)
from repo_utilities.apt.build_deb import BuildConf, extract_homepage_desc

# `from repo_utilities.apt import build_deb` would resolve to the
# `build_deb` *function* re-exported by repo_utilities/apt/__init__.py,
# which shadows the submodule attribute of the same name on the `apt`
# package (see tests/test_build_repo.py for the same situation). Pull the
# actual module out of sys.modules instead.
build_deb = sys.modules["repo_utilities.apt.build_deb"]


@pytest.mark.parametrize(
    ("cask_or_formula", "desc", "homepage"),
    [
        (
            "go",
            "Open source programming language to build simple/reliable/efficient software",
            "https://go.dev/",
        ),
        (
            "ollama",
            "Create, run, and share large language models (LLMs)",
            "https://ollama.com/",
        ),
    ],
)
def test_extract_homepage_desc(cask_or_formula: str, desc: str, homepage: str) -> None:
    """Test the extract_homepage_desc function."""
    extracted_desc, extracted_homepage = extract_homepage_desc(cask_or_formula)
    assert extracted_desc == desc
    assert extracted_homepage == homepage


def make_response(status_code: int, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    return response


def test_extract_homepage_desc_returns_none_when_not_found_anywhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_deb.requests, "get", MagicMock(return_value=make_response(404)))

    desc, homepage = extract_homepage_desc("doesnotexist")

    assert desc is None
    assert homepage is None


def test_extract_homepage_desc_raises_for_unexpected_status_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(build_deb.requests, "get", MagicMock(return_value=make_response(500)))

    with pytest.raises(ValueError, match="Unexpected status code: 500"):
        extract_homepage_desc("something")


def test_extract_homepage_desc_raises_when_desc_or_homepage_missing_from_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 200 response but the file body lacks the desc/homepage patterns.
    monkeypatch.setattr(
        build_deb.requests, "get", MagicMock(return_value=make_response(200, "no fields here"))
    )

    with pytest.raises(ValueError, match="Description or homepage not found"):
        extract_homepage_desc("something")


def test_set_xz_env_sets_expected_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XZ_OPT", raising=False)
    monkeypatch.delenv("XZ_DEFAULTS", raising=False)

    build_deb.set_xz_env(compression=6, jobs=4)

    assert os.environ["XZ_OPT"] == "-6 -T4"
    assert os.environ["XZ_DEFAULTS"] == "-6 -T4"


def test_non_debian_files_excludes_debian_dir(tmp_path: Path) -> None:
    # Note: "debian" and "DEBIAN" are excluded by the same {"debian",
    # "DEBIAN"} name check; both aren't exercised together here since
    # macOS's default (case-insensitive) filesystem can't hold both as
    # distinct directories.
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "debian" / "control").write_text("x", "utf-8")
    (source / "bin").mkdir()
    (source / "bin" / "app").write_text("bin", "utf-8")
    (source / "toplevel.txt").write_text("top", "utf-8")

    found = set(build_deb.non_debian_files(source))

    assert source / "toplevel.txt" in found
    assert source / "bin" / "app" in found
    # the top-level subdir itself ("bin") is never yielded, only its rglob("*") contents
    assert source / "bin" not in found
    assert not any(p.parts[len(source.parts)] == "debian" for p in found)


def test_find_install_files_skips_desktop_files_and_icons_dir(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "debian").mkdir()
    (source / "myapp.desktop").write_text("desktop", "utf-8")
    (source / "icons").mkdir()
    (source / "icons" / "icon.png").write_bytes(b"icon")
    (source / "bin").mkdir()
    (source / "bin" / "app").write_text("bin", "utf-8")

    found = build_deb.find_install_files(source)

    assert source / "bin" / "app" in found
    assert source / "myapp.desktop" not in found
    assert source / "icons" / "icon.png" not in found


def test_copy_additional_files_merges_into_debian_dir(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "debian" / "control").write_text("existing", "utf-8")

    additional = tmp_path / "extra"
    additional.mkdir()
    (additional / "postinst").write_text("#!/bin/sh\n", "utf-8")

    build_deb.copy_additional_files(source, additional)

    assert (source / "debian" / "postinst").read_text("utf-8") == "#!/bin/sh\n"
    assert (source / "debian" / "control").read_text("utf-8") == "existing"


def test_write_install_file_groups_by_directory(tmp_path: Path) -> None:
    # write_install_file's `install` file lists whole *directories* (an
    # entire dir gets installed recursively, keeping its basename), not
    # individual files -- so two files sharing a parent collapse to one
    # line naming that parent directory, with its *grandparent* as the
    # destination (since the basename "bin" is preserved on install).
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "bin").mkdir()
    file1 = source / "bin" / "app"
    file1.write_text("x", "utf-8")
    file2 = source / "bin" / "helper"
    file2.write_text("y", "utf-8")

    allowed_dirs = build_deb.write_install_file([file1, file2], source)

    install_content = (source / "debian" / "install").read_text("utf-8")
    lines = install_content.splitlines()
    assert len(lines) == 1  # both files share the same parent dir
    assert lines[0] == "bin "  # destination is "/" (root), stripped to ""
    assert Path("/") / "bin" in allowed_dirs


def test_write_install_file_ignores_non_file_entries(tmp_path: Path) -> None:
    # `non_debian_files` (the usual source of `files`) can yield directory
    # paths too, since its rglob("*") walk includes them; those must be
    # filtered out rather than treated as installable files.
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "bin").mkdir()
    file = source / "bin" / "app"
    file.write_text("x", "utf-8")
    stray_dir = source / "bin" / "subdir"
    stray_dir.mkdir()

    allowed_dirs = build_deb.write_install_file([file, stray_dir], source)

    install_content = (source / "debian" / "install").read_text("utf-8")
    lines = install_content.splitlines()
    assert len(lines) == 1
    assert Path("/") / "bin" in allowed_dirs


def test_write_install_file_skips_ignored_dirs(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "__pycache__").mkdir()
    pyc = source / "__pycache__" / "mod.pyc"
    pyc.write_text("x", "utf-8")
    (source / "bin").mkdir()
    app = source / "bin" / "app"
    app.write_text("x", "utf-8")

    build_deb.write_install_file([pyc, app], source)

    install_content = (source / "debian" / "install").read_text("utf-8")
    assert "__pycache__" not in install_content
    assert "bin " in install_content


def test_write_install_file_collapses_nested_dirs_to_top_ancestor(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "share" / "doc" / "nested").mkdir(parents=True)
    top_file = source / "share" / "topfile.txt"
    top_file.write_text("x", "utf-8")
    nested_file = source / "share" / "doc" / "nested" / "deep.txt"
    nested_file.write_text("y", "utf-8")

    allowed_dirs = build_deb.write_install_file([top_file, nested_file], source)

    install_content = (source / "debian" / "install").read_text("utf-8")
    # "share/doc/nested" is nested under "share", which is also in the
    # fixed_files set, so _is_parent_in_set prunes the nested entry
    # entirely: only the top ancestor "share" is written (it gets
    # installed recursively, carrying the nested file along with it).
    assert install_content.splitlines() == ["share "]
    # allowed_dirs, however, is computed from the *un-collapsed*
    # file_hierarchy, so both directories are still considered valid
    # locations for executables/desktop files.
    assert Path("/") / "share" in allowed_dirs
    assert Path("/") / "share" / "doc" / "nested" in allowed_dirs


def test_write_install_file_uses_custom_install_dir(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    (source / "bin").mkdir()
    app = source / "bin" / "app"
    app.write_text("x", "utf-8")

    allowed_dirs = build_deb.write_install_file([app], source, install_dir=Path("/opt/myapp"))

    install_content = (source / "debian" / "install").read_text("utf-8")
    assert install_content.splitlines() == ["bin opt/myapp"]
    assert Path("/opt/myapp/bin") in allowed_dirs


def test_dh_make_skips_when_debian_dir_already_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)

    build_deb.dh_make(source, name="Tim", email="tim@example.com")

    mock_check_call.assert_not_called()


def test_dh_make_raises_without_name_and_email(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "check_call", MagicMock())
    source = tmp_path / "src"
    source.mkdir()

    with pytest.raises(ValueError, match="Name and email must be provided"):
        build_deb.dh_make(source, name=None, email=None)


@pytest.mark.parametrize(
    ("arch", "expected_flag"),
    [("all", "-i"), ("amd64", "-s")],
)
def test_dh_make_builds_expected_args_and_cleans_up_ex_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arch: str, expected_flag: str
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    def fake_check_call(args: list[str], **kwargs: object) -> int:  # noqa: ARG001
        # Simulate what a real dh_make invocation would scaffold.
        debian_dir = source / "debian"
        debian_dir.mkdir()
        (debian_dir / "rules.ex").write_text("x", "utf-8")
        (debian_dir / "README.source").write_text("x", "utf-8")
        (debian_dir / "changelog.docs").write_text("x", "utf-8")
        (debian_dir / "control").write_text("keep me", "utf-8")
        return 0

    mock_check_call = MagicMock(side_effect=fake_check_call)
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)

    build_deb.dh_make(
        source,
        name="Tim",
        email="tim@example.com",
        license="mit",
        arch=arch,
    )

    args = mock_check_call.call_args.args[0]
    assert expected_flag in args
    assert "-c" in args
    assert "mit" in args
    debian_dir = source / "debian"
    assert not (debian_dir / "rules.ex").exists()
    assert not (debian_dir / "README.source").exists()
    assert not (debian_dir / "changelog.docs").exists()
    assert (debian_dir / "control").exists()
    assert os.environ["DEBEMAIL"] == "tim@example.com"
    assert os.environ["DEBFULLNAME"] == "Tim"


def test_dh_make_omits_license_flag_when_not_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    source.mkdir()

    def fake_check_call(args: list[str], **kwargs: object) -> int:  # noqa: ARG001
        (source / "debian").mkdir()
        return 0

    mock_check_call = MagicMock(side_effect=fake_check_call)
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)

    build_deb.dh_make(source, name="Tim", email="tim@example.com")

    args = mock_check_call.call_args.args[0]
    assert "-c" not in args


def test_dh_make_defaults_email_and_name_but_still_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "check_call", MagicMock())
    source = tmp_path / "src"
    source.mkdir()

    # Even though DEBEMAIL/DEBFULLNAME get filled with fallback values
    # first, the explicit email/name check still raises afterwards.
    with pytest.raises(ValueError, match="Name and email must be provided"):
        build_deb.dh_make(source, name=None, email=None)

    assert os.environ["DEBEMAIL"].startswith("unknown@")
    assert os.environ["DEBFULLNAME"]  # getpass.getuser() result, non-empty


def make_control_file(source: Path) -> Path:
    debian_dir = source / "debian"
    debian_dir.mkdir(parents=True)
    control = debian_dir / "control"
    control.write_text(
        "Source: mypkg\n"
        "Architecture: any\n"
        "Depends: ${shlibs:Depends}, ${misc:Depends}\n"
        "Homepage: <insert the upstream URL, if relevant>\n"
        "Description: short desc\n"
        " long desc line\n",
        "utf-8",
    )
    return control


def test_update_control_replaces_arch_depends_homepage_desc(tmp_path: Path) -> None:
    source = tmp_path / "src"
    control = make_control_file(source)

    build_deb.update_control(
        source,
        "mypkg",
        depends="libfoo",
        homepage="https://example.com",
        desc="New desc",
        arch="amd64",
    )

    content = control.read_text("utf-8")
    assert "Architecture: amd64" in content
    assert "Depends: libfoo, ${shlibs:Depends}, ${misc:Depends}" in content
    assert "Homepage: https://example.com" in content
    assert "Description: New desc" in content


def test_update_control_extracts_from_homebrew_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    control = make_control_file(source)

    monkeypatch.setattr(
        build_deb, "extract_homepage_desc", MagicMock(return_value=("brew desc", "https://brew.sh"))
    )

    build_deb.update_control(source, "mypkg", depends=None, homepage=None, desc=None, arch="all")

    content = control.read_text("utf-8")
    assert "Homepage: https://brew.sh" in content
    assert "Description: brew desc" in content


def test_update_control_raises_if_still_missing_after_extraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "src"
    make_control_file(source)

    monkeypatch.setattr(build_deb, "extract_homepage_desc", MagicMock(return_value=(None, None)))

    with pytest.raises(ValueError, match="Homepage and Description are required"):
        build_deb.update_control(
            source, "mypkg", depends=None, homepage=None, desc=None, arch="all"
        )


def test_cleanup_removes_matching_build_artifacts_and_source_dir(tmp_path: Path) -> None:
    # The glob is f"{package}_{version}*" -- an underscore between package
    # and version, matching dpkg-buildpackage's actual naming convention
    # (mypkg_1.0.0_amd64.deb etc), not the source dir's own "pkg-version"
    # naming (mypkg-1.0.0/).
    parent = tmp_path
    source = parent / "mypkg-1.0.0"
    source.mkdir()
    (parent / "mypkg_1.0.0_amd64.buildinfo").write_text("x", "utf-8")
    (parent / "mypkg_1.0.0.orig.tar.gz").write_text("x", "utf-8")
    (parent / "mypkg_1.0.0_amd64.changes").write_text("x", "utf-8")
    (parent / "mypkg_1.0.0_amd64.unrelated").write_text("x", "utf-8")

    build_deb.cleanup(source, "mypkg", "1.0.0")

    assert not (parent / "mypkg_1.0.0_amd64.buildinfo").exists()
    assert not (parent / "mypkg_1.0.0.orig.tar.gz").exists()
    assert not (parent / "mypkg_1.0.0_amd64.changes").exists()
    assert (parent / "mypkg_1.0.0_amd64.unrelated").exists()  # not a recognized suffix
    assert not source.exists()


def test_cleanup_keeps_source_dir_when_debug_enabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build_deb, "DEBUG", True)
    source = tmp_path / "mypkg-1.0.0"
    source.mkdir()

    build_deb.cleanup(source, "mypkg", "1.0.0")

    assert source.exists()


def test_dpkg_buildpackage_unsigned(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)
    source = tmp_path / "src"
    source.mkdir()

    build_deb.dpkg_buildpackage(source, compression=3, jobs=2, arch="all")

    args = mock_check_call.call_args.args[0]
    assert args[0] == "dpkg-buildpackage"
    assert "-j2" in args
    assert "-uc" in args
    assert "-us" in args
    assert not any(a.startswith("-a") for a in args)


def test_dpkg_buildpackage_non_all_arch_adds_arch_flag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "check_call", MagicMock())
    source = tmp_path / "src"
    source.mkdir()

    build_deb.dpkg_buildpackage(source, arch="amd64")

    args_list = subprocess.check_call.call_args.args[0]  # type: ignore[attr-defined]
    assert "-aamd64" in args_list


def test_dpkg_buildpackage_signed_uses_gpg_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)
    source = tmp_path / "src"
    source.mkdir()
    priv_file = tmp_path / "priv.key"
    priv_file.write_text("key", "utf-8")

    fake_gpg = MagicMock()
    fake_gpg.list_keys.return_value = [{"fingerprint": "ABCD1234"}]

    class FakeTempGPG:
        def __init__(self, dir: Path) -> None:  # noqa: A002
            self.dir = dir

        def __enter__(self) -> MagicMock:
            return fake_gpg

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(build_deb, "TempGPG", FakeTempGPG)

    build_deb.dpkg_buildpackage(source, priv_file=priv_file)

    fake_gpg.import_priv_key.assert_called_once_with(priv_file)
    args = mock_check_call.call_args.args[0]
    assert "-k=ABCD1234" in args


def test_disable_debhelper_scripts_appends_override_targets(tmp_path: Path) -> None:
    debian_dir = tmp_path / "debian"
    debian_dir.mkdir()
    rules = debian_dir / "rules"
    rules.write_text("#!/usr/bin/make -f\n", "utf-8")

    build_deb.disable_debhelper_scripts(debian_dir, ["strip", "shlibdeps"])

    content = rules.read_text("utf-8")
    assert "override_dh_strip:\n\ttrue\n" in content
    assert "override_dh_shlibdeps:\n\ttrue\n" in content


def test_disable_debhelper_scripts_noop_for_empty_list(tmp_path: Path) -> None:
    debian_dir = tmp_path / "debian"
    debian_dir.mkdir()
    rules = debian_dir / "rules"
    rules.write_text("original\n", "utf-8")

    build_deb.disable_debhelper_scripts(debian_dir, [])

    assert rules.read_text("utf-8") == "original\n"


def test_add_desktop_file_renders_template_and_updates_install(tmp_path: Path) -> None:
    source = tmp_path / "src"
    (source / "debian").mkdir(parents=True)
    install_file = source / "debian" / "install"
    install_file.write_text("bin/app bin\n", "utf-8")

    template = tmp_path / "template.desktop"
    template.write_text(
        "[Desktop Entry]\nName={{ name }}\nExec={{ exec }}\n"
        "Version={{ version }}\nIcon={{ icon }}\n",
        "utf-8",
    )
    icon = tmp_path / "icon.svg"
    icon.write_text("<svg/>", "utf-8")

    build_deb.add_desktop_file(source, "mypkg", "1.0.0", template, "/usr/bin/mypkg", icon)

    desktop_file = source / "mypkg.desktop"
    content = desktop_file.read_text("utf-8")
    assert "Name=mypkg" in content
    assert "Exec=/usr/bin/mypkg" in content
    assert "Version=1.0.0" in content
    assert "Icon=mypkg" in content

    icon_copy = source / "icons" / "mypkg.svg"
    assert icon_copy.exists()

    install_content = install_file.read_text("utf-8")
    assert "mypkg.desktop /usr/share/applications" in install_content
    assert "icons/mypkg.svg /usr/share/icons/hicolor/scalable/apps" in install_content


def test_unpack_source_executable_copies_binary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "check_output", MagicMock(return_value="application/x-executable\n")
    )
    monkeypatch.setattr(subprocess, "check_call", MagicMock())

    source = tmp_path / "myapp"
    source.write_bytes(b"\x7fELF")
    output = tmp_path / "out"

    build_deb.unpack_source(source, output)

    assert (output / "bin" / "myapp").read_bytes() == b"\x7fELF"


def test_unpack_source_executable_uses_custom_binary_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        subprocess, "check_output", MagicMock(return_value="application/x-executable\n")
    )
    monkeypatch.setattr(subprocess, "check_call", MagicMock())

    source = tmp_path / "myapp"
    source.write_bytes(b"\x7fELF")
    output = tmp_path / "out"

    build_deb.unpack_source(source, output, binary="renamed")

    assert (output / "bin" / "renamed").exists()


@pytest.mark.parametrize(
    ("mime_subtype", "expected_flag"),
    [
        ("gzip", "pigz"),
        ("bzip2", "pbzip2"),
        ("zstd", "zstd"),
        ("tar", None),
    ],
)
def test_unpack_source_archive_types_invoke_tar_with_expected_filter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mime_subtype: str, expected_flag: str | None
) -> None:
    monkeypatch.setattr(
        subprocess,
        "check_output",
        MagicMock(return_value=f"application/x-{mime_subtype}\n"),
    )
    mock_check_call = MagicMock()
    monkeypatch.setattr(subprocess, "check_call", mock_check_call)

    source = tmp_path / "archive"
    source.write_bytes(b"data")
    output = tmp_path / "out"

    build_deb.unpack_source(source, output, exclude=["*.md"])

    args = mock_check_call.call_args.args[0]
    assert args[0] == "tar"
    assert "--exclude" in args
    assert "*.md" in args
    if expected_flag:
        assert expected_flag in args
    assert output.is_dir()


def test_unpack_source_raises_for_unknown_mime_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(subprocess, "check_output", MagicMock(return_value="text/plain\n"))
    source = tmp_path / "file.txt"
    source.write_bytes(b"data")
    output = tmp_path / "out"

    with pytest.raises(ValueError, match="Unknown mime type"):
        build_deb.unpack_source(source, output)


def make_build_conf(tmp_path: Path, **overrides: object) -> BuildConf:
    defaults: dict[str, object] = {
        "source": tmp_path / "source",
        "package": "mypkg",
        "version": "1.0.0",
        "output": tmp_path / "out",
    }
    defaults.update(overrides)
    return BuildConf(**defaults)  # type: ignore[arg-type]


def patch_build_deb_internals(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    mocks = {
        "unpack_source": MagicMock(),
        "dh_make": MagicMock(),
        "update_control": MagicMock(),
        "find_install_files": MagicMock(return_value=[]),
        "copy_additional_files": MagicMock(),
        "add_desktop_file": MagicMock(),
        "disable_debhelper_scripts": MagicMock(),
        "dpkg_buildpackage": MagicMock(),
        "cleanup": MagicMock(),
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(build_deb, name, mock)
    return mocks


def test_build_deb_skips_unpack_when_output_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    mocks["write_install_file"] = MagicMock(return_value=set())
    monkeypatch.setattr(build_deb, "write_install_file", mocks["write_install_file"])

    conf = make_build_conf(tmp_path)
    output_dir = Path(conf.output).resolve() / f"{conf.package}-{conf.version}"
    output_dir.mkdir(parents=True)

    build_deb.build_deb(conf)

    mocks["unpack_source"].assert_not_called()
    mocks["dpkg_buildpackage"].assert_called_once()
    mocks["cleanup"].assert_called_once()


def test_build_deb_calls_unpack_when_output_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value=set()))

    conf = make_build_conf(tmp_path)

    build_deb.build_deb(conf)

    mocks["unpack_source"].assert_called_once()


def test_build_deb_copies_additional_dir_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value=set()))

    additional = tmp_path / "extra"
    conf = make_build_conf(tmp_path, additional_dir=additional)

    build_deb.build_deb(conf)

    mocks["copy_additional_files"].assert_called_once()


def test_build_deb_skips_additional_dir_when_not_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value=set()))

    conf = make_build_conf(tmp_path)

    build_deb.build_deb(conf)

    mocks["copy_additional_files"].assert_not_called()


def test_build_deb_raises_when_executable_outside_allowed_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value={Path("/usr/bin")}))

    conf = make_build_conf(tmp_path, executable=[Path("/opt/myapp/bin/tool")])

    with pytest.raises(ValueError, match="outside of allowed directories"):
        build_deb.build_deb(conf)


def test_build_deb_writes_links_file_for_allowed_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(
        build_deb, "write_install_file", MagicMock(return_value={Path("/opt/myapp/bin")})
    )

    conf = make_build_conf(tmp_path, executable=[Path("/opt/myapp/bin/tool")])
    output_dir = Path(conf.output).resolve() / f"{conf.package}-{conf.version}"
    # dh_make is mocked, so the debian/ dir it would normally create is set up here instead
    (output_dir / "debian").mkdir(parents=True)

    build_deb.build_deb(conf)

    links_content = (output_dir / "debian" / "links").read_text("utf-8")
    assert "/opt/myapp/bin/tool /usr/bin/tool" in links_content


def test_build_deb_skips_links_file_when_no_executables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value=set()))

    conf = make_build_conf(tmp_path)

    build_deb.build_deb(conf)

    output_dir = Path(conf.output).resolve() / f"{conf.package}-{conf.version}"
    assert not (output_dir / "debian" / "links").exists()


def test_build_deb_raises_when_desktop_exec_outside_allowed_dirs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value={Path("/usr/bin")}))

    conf = make_build_conf(
        tmp_path,
        desktop=(tmp_path / "tpl.desktop", Path("/opt/other/exec"), tmp_path / "icon.svg"),
    )

    with pytest.raises(ValueError, match="Desktop executable"):
        build_deb.build_deb(conf)


def test_build_deb_calls_add_desktop_file_when_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value={Path("/usr/bin")}))

    conf = make_build_conf(
        tmp_path,
        desktop=(tmp_path / "tpl.desktop", Path("/usr/bin/myapp"), tmp_path / "icon.svg"),
    )

    build_deb.build_deb(conf)

    mocks["add_desktop_file"].assert_called_once()


def test_build_deb_skips_desktop_when_not_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mocks = patch_build_deb_internals(monkeypatch)
    monkeypatch.setattr(build_deb, "write_install_file", MagicMock(return_value=set()))

    conf = make_build_conf(tmp_path)

    build_deb.build_deb(conf)

    mocks["add_desktop_file"].assert_not_called()
