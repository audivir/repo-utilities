"""Tests for repo_utilities.download.

All HTTP calls (`requests`) and playwright browser automation are mocked;
no test performs real network I/O or launches a real browser.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import requests
from playwright._impl import _errors as pw_errors
from requests import Session

from repo_utilities.download import (
    BrowserError,
    DownloadError,
    GitHubError,
    GitHubSession,
    HeaderError,
    HTTPError,
    download_direct,
    download_via_browser,
    find_asset_by_tag,
    find_recent_asset,
    get_pw_download,
    get_release_data,
    get_remote_filename,
)


def test_github_session_sets_and_clears_headers() -> None:
    session = Session()
    gh_session = GitHubSession("mytoken", session=session)

    with gh_session as entered:
        assert entered is session
        assert session.headers["Authorization"] == "Bearer mytoken"
        assert session.headers["Accept"] == "application/vnd.github+json"

    assert "Authorization" not in session.headers


def test_github_session_creates_own_session_if_none_given() -> None:
    gh_session = GitHubSession("mytoken")

    assert isinstance(gh_session.session, Session)


def make_release(tag: str, assets: list[str], prerelease: bool = False) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "prerelease": prerelease,
        "assets": [{"name": a} for a in assets],
    }


def test_get_release_data_excludes_prereleases_by_default() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = [
        make_release("v1.0.0", ["a.tar.gz"]),
        make_release("v1.1.0-beta", ["b.tar.gz"], prerelease=True),
    ]
    mock_session.get.return_value = mock_response

    data = get_release_data("owner/repo", "token", session=mock_session)

    assert data == {"v1.0.0": ["a.tar.gz"]}
    mock_response.raise_for_status.assert_called_once()


def test_get_release_data_includes_prereleases_when_requested() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.json.return_value = [
        make_release("v1.0.0", ["a.tar.gz"]),
        make_release("v1.1.0-beta", ["b.tar.gz"], prerelease=True),
    ]
    mock_session.get.return_value = mock_response

    data = get_release_data("owner/repo", "token", exclude_prereleases=False, session=mock_session)

    assert data == {"v1.0.0": ["a.tar.gz"], "v1.1.0-beta": ["b.tar.gz"]}


def test_get_release_data_uses_expected_url_and_headers() -> None:
    mock_session = MagicMock()
    mock_session.headers = {}
    mock_response = MagicMock()
    mock_response.json.return_value = []
    mock_session.get.return_value = mock_response

    get_release_data("owner/repo", "token", session=mock_session)

    mock_session.get.assert_called_once_with("https://api.github.com/repos/owner/repo/releases")


def test_find_asset_by_tag_raises_when_tag_missing() -> None:
    with pytest.raises(GitHubError, match="No assets found"):
        find_asset_by_tag({}, "*.tar.gz", "v1.0.0")


def test_find_asset_by_tag_returns_none_when_no_match() -> None:
    result = find_asset_by_tag({"v1.0.0": ["a.zip"]}, "*.tar.gz", "v1.0.0")

    assert result is None


def test_find_asset_by_tag_raises_for_multiple_matches() -> None:
    release_data = {"v1.0.0": ["a.tar.gz", "b.tar.gz"]}

    with pytest.raises(GitHubError, match="Multiple matching"):
        find_asset_by_tag(release_data, "*.tar.gz", "v1.0.0")


def test_find_asset_by_tag_returns_single_match() -> None:
    release_data = {"v1.0.0": ["a.tar.gz", "b.zip"]}

    result = find_asset_by_tag(release_data, "*.tar.gz", "v1.0.0")

    assert result == "a.tar.gz"


def test_find_recent_asset_returns_first_matching_tag() -> None:
    release_data = {"v2.0.0": ["b.zip"], "v1.0.0": ["a.tar.gz"]}

    asset, tag = find_recent_asset(release_data, "*.tar.gz")

    assert asset == "a.tar.gz"
    assert tag == "v1.0.0"


def test_find_recent_asset_raises_when_nothing_matches() -> None:
    release_data = {"v1.0.0": ["a.zip"]}

    with pytest.raises(GitHubError, match="No matching tag"):
        find_recent_asset(release_data, "*.tar.gz")


def test_get_remote_filename_extracts_from_content_disposition() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {"Content-Disposition": 'attachment; filename="archive.tar.gz"'}
    mock_session.get.return_value = mock_response

    result = get_remote_filename("https://example.com/dl", session=mock_session)

    assert result == "archive.tar.gz"
    mock_response.close.assert_called_once()


def test_get_remote_filename_strips_path_from_filename() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {
        "Content-Disposition": 'attachment; filename="some/path/archive.tar.gz"'
    }
    mock_session.get.return_value = mock_response

    result = get_remote_filename("https://example.com/dl", session=mock_session)

    assert result == "archive.tar.gz"


def test_get_remote_filename_raises_when_header_does_not_match_pattern() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {"Content-Disposition": "inline"}
    mock_session.get.return_value = mock_response

    with pytest.raises(HeaderError, match="Could not get filename"):
        get_remote_filename("https://example.com/dl", session=mock_session)


def test_get_remote_filename_raises_when_header_missing() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.headers = {}
    mock_session.get.return_value = mock_response

    with pytest.raises(HeaderError, match="Could not get Content-Disposition"):
        get_remote_filename("https://example.com/dl", session=mock_session)


def test_download_direct_writes_content_and_uses_url_tail_as_name(
    tmp_path: Path,
) -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"file-bytes"
    mock_session.get.return_value = mock_response

    result = download_direct(
        "https://example.com/dir/archive.tar.gz", tmp_path, session=mock_session
    )

    assert result == tmp_path / "archive.tar.gz"
    assert result.read_bytes() == b"file-bytes"


def test_download_direct_uses_explicit_name(tmp_path: Path) -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"content"
    mock_session.get.return_value = mock_response

    result = download_direct(
        "https://example.com/file", tmp_path, name="custom.bin", session=mock_session
    )

    assert result == tmp_path / "custom.bin"


def test_download_direct_raises_http_error_on_bad_status(tmp_path: Path) -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = requests.HTTPError("404")
    mock_session.get.return_value = mock_response

    with pytest.raises(HTTPError):
        download_direct("https://example.com/missing", tmp_path, session=mock_session)


def make_browser_with_page(existing_context: bool = True) -> tuple[MagicMock, MagicMock]:
    browser = MagicMock()
    page = MagicMock()
    if existing_context:
        context = MagicMock()
        context.pages = [page]
        browser.contexts = [context]
    else:
        browser.contexts = []
        new_context = MagicMock()
        new_context.new_page.return_value = page
        browser.new_context.return_value = new_context
    return browser, page


def test_get_pw_download_reuses_existing_context_page() -> None:
    browser, page = make_browser_with_page(existing_context=True)
    download = MagicMock()
    download_info = MagicMock()
    download_info.value = download
    page.expect_download.return_value.__enter__.return_value = download_info

    result = get_pw_download(browser, ("https://example.com",))

    assert result is download
    page.goto.assert_called_once_with("https://example.com")
    browser.new_context.assert_not_called()


def test_get_pw_download_creates_new_context_when_none_exist() -> None:
    browser, page = make_browser_with_page(existing_context=False)
    download = MagicMock()
    download_info = MagicMock()
    download_info.value = download
    page.expect_download.return_value.__enter__.return_value = download_info

    result = get_pw_download(browser, ("https://example.com",))

    assert result is download
    browser.new_context.assert_called_once_with(storage_state=None)


def test_get_pw_download_raises_if_download_never_starts() -> None:
    browser, page = make_browser_with_page()
    download_info = MagicMock()
    download_info.value = None
    page.expect_download.return_value.__enter__.return_value = download_info

    with pytest.raises(BrowserError, match="Download did not start"):
        get_pw_download(browser, ("https://example.com",))


def test_get_pw_download_clicks_by_selector() -> None:
    browser, page = make_browser_with_page()
    download = MagicMock()
    download_info = MagicMock()
    download_info.value = download
    # First expect_download() usage (no download expected for the goto,
    # since a click is queued): __enter__ returns None (nullcontext-like);
    # actual expect_download is only used for the final click.
    page.expect_download.return_value.__enter__.return_value = download_info

    handle = MagicMock()
    page.wait_for_selector.return_value = handle

    result = get_pw_download(browser, ("https://example.com", "#submit"))

    assert result is download
    page.wait_for_selector.assert_called_once_with("#submit", timeout=2000)
    handle.click.assert_called_once_with(timeout=2000, force=True)


def test_get_pw_download_raises_if_selector_not_found() -> None:
    browser, page = make_browser_with_page()
    page.wait_for_selector.return_value = None

    with pytest.raises(BrowserError, match="Could not find #missing"):
        get_pw_download(browser, ("https://example.com", "#missing"))


def test_get_pw_download_clicks_by_text() -> None:
    browser, page = make_browser_with_page()
    download = MagicMock()
    download_info = MagicMock()
    download_info.value = download
    page.expect_download.return_value.__enter__.return_value = download_info

    text_locator = MagicMock()
    page.get_by_text.return_value.first = text_locator

    result = get_pw_download(browser, ("https://example.com", "Download now"))

    assert result is download
    page.get_by_text.assert_called_once_with("Download now")
    text_locator.click.assert_called_once_with(timeout=2000, force=True)


def test_get_pw_download_multiple_clicks_only_expects_download_on_last() -> None:
    browser, page = make_browser_with_page()
    download = MagicMock()
    download_info = MagicMock()
    download_info.value = download
    page.expect_download.return_value.__enter__.return_value = download_info
    page.get_by_text.return_value.first = MagicMock()
    page.wait_for_selector.return_value = MagicMock()

    result = get_pw_download(browser, ("https://example.com", "#step1", "Finish"))

    assert result is download
    assert page.wait_for_selector.call_count == 1
    assert page.get_by_text.call_count == 1


def test_download_via_browser_succeeds_first_try(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    download = MagicMock()
    download.suggested_filename = "archive.tar.gz"
    mock_get_pw_download = MagicMock(return_value=download)
    monkeypatch.setattr("repo_utilities.download.get_pw_download", mock_get_pw_download)

    result = download_via_browser(MagicMock(), ("https://example.com",), tmp_path)

    assert result == tmp_path / "archive.tar.gz"
    download.save_as.assert_called_once_with(tmp_path / "archive.tar.gz")
    mock_get_pw_download.assert_called_once()


def test_download_via_browser_uses_stem_and_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    download = MagicMock()
    download.suggested_filename = "original.tar.gz"
    monkeypatch.setattr("repo_utilities.download.get_pw_download", MagicMock(return_value=download))

    result = download_via_browser(
        MagicMock(), ("https://example.com",), tmp_path, stem="renamed", prefix="pre_"
    )

    assert result == tmp_path / "pre_renamed.tar.gz"


def test_download_via_browser_returns_suggested_name_without_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    download = MagicMock()
    download.suggested_filename = "archive.tar.gz"
    monkeypatch.setattr("repo_utilities.download.get_pw_download", MagicMock(return_value=download))

    result = download_via_browser(MagicMock(), ("https://example.com",), None)

    assert result == Path("archive.tar.gz")
    download.cancel.assert_called_once()


def test_download_via_browser_retries_on_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    download = MagicMock()
    download.suggested_filename = "archive.tar.gz"
    mock_get_pw_download = MagicMock(side_effect=[pw_errors.TimeoutError("timed out"), download])
    monkeypatch.setattr("repo_utilities.download.get_pw_download", mock_get_pw_download)

    result = download_via_browser(MagicMock(), ("https://example.com",), tmp_path, retries=2)

    assert result == tmp_path / "archive.tar.gz"
    assert mock_get_pw_download.call_count == 2


def test_download_via_browser_raises_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mock_get_pw_download = MagicMock(side_effect=pw_errors.TimeoutError("timed out"))
    monkeypatch.setattr("repo_utilities.download.get_pw_download", mock_get_pw_download)

    with pytest.raises(DownloadError):
        download_via_browser(MagicMock(), ("https://example.com",), tmp_path, retries=2)

    assert mock_get_pw_download.call_count == 2
