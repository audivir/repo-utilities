"""Create a session which caches GET requests."""

from __future__ import annotations

import logging
from typing import Any

from playwright.sync_api import sync_playwright
from requests import Response, Session
from typing_extensions import Self, override

logger = logging.getLogger("repo_utilities")


class CacheSession(Session):
    """A requests session that can cache GET responses.

    Attributes:
        cache: The cache.
    """

    def __init__(self) -> None:
        """Initialize the class."""
        super().__init__()
        self.cache: dict[str, Response] = {}

    @override
    def get(  # type: ignore[override,unused-ignore]
        self, url: str, stream: bool | None = False, **kwargs: Any
    ) -> Response:
        """Get the response from the cache or send a request."""
        if stream:
            return super().get(url, stream=stream, **kwargs)
        if url not in self.cache:
            self.cache[url] = super().get(url, **kwargs)
        else:
            logger.debug("Using cached response for %s", url)

        return self.cache[url]


class ConnectionKeeper:
    """A class to keep the connection alive and cache some results.

    Attributes:
        session: The requests session with a cache.
        browser: The Playwright browser.
    """

    def __init__(self, headless: bool = False, **storage: str) -> None:
        """Initialize the class.

        Args:
            headless: Whether to run the browser in headless mode.
            **storage: Storage for additional arguments.
        """
        self.session = CacheSession()
        self._pw = sync_playwright().start()
        self.browser = self._pw.webkit.launch(headless=headless)
        self.storage = storage

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(self, *args: object) -> None:
        """Close the session and the driver."""
        self.session.close()
        self.browser.close()
        self._pw.stop()


__all__ = ["CacheSession", "ConnectionKeeper"]
