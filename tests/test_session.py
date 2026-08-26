"""Tests for repo_utilities.session."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from requests import Response

from repo_utilities.session import CacheSession, ConnectionKeeper

if TYPE_CHECKING:
    import pytest


def make_response(url: str) -> Response:
    response = Response()
    response.url = url
    response.status_code = 200
    return response


def test_cache_session_caches_get_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    session = CacheSession()
    real_get = MagicMock(side_effect=lambda url, **kwargs: make_response(url))  # noqa: ARG005
    monkeypatch.setattr("requests.Session.get", real_get)

    first = session.get("https://example.com")
    second = session.get("https://example.com")

    assert first is second
    real_get.assert_called_once()


def test_cache_session_does_not_cache_different_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    session = CacheSession()
    real_get = MagicMock(side_effect=lambda url, **kwargs: make_response(url))  # noqa: ARG005
    monkeypatch.setattr("requests.Session.get", real_get)

    first = session.get("https://example.com/a")
    second = session.get("https://example.com/b")

    assert first is not second
    assert real_get.call_count == 2


def test_cache_session_stream_requests_bypass_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    session = CacheSession()
    real_get = MagicMock(side_effect=lambda url, **kwargs: make_response(url))  # noqa: ARG005
    monkeypatch.setattr("requests.Session.get", real_get)

    first = session.get("https://example.com", stream=True)
    second = session.get("https://example.com", stream=True)

    assert first is not second
    assert real_get.call_count == 2
    assert "https://example.com" not in session.cache


def test_connection_keeper_starts_playwright_and_closes_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_browser = MagicMock()
    mock_playwright = MagicMock()
    mock_playwright.webkit.launch.return_value = mock_browser
    mock_sync_playwright_ctx = MagicMock()
    mock_sync_playwright_ctx.start.return_value = mock_playwright
    mock_sync_playwright = MagicMock(return_value=mock_sync_playwright_ctx)

    monkeypatch.setattr("repo_utilities.session.sync_playwright", mock_sync_playwright)

    with ConnectionKeeper(headless=True, extra="value") as keeper:
        assert keeper.browser is mock_browser
        assert keeper.storage == {"extra": "value"}
        mock_playwright.webkit.launch.assert_called_once_with(headless=True)

    mock_browser.close.assert_called_once()
    mock_playwright.stop.assert_called_once()
