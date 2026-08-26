"""Download a file from a link or github."""

from __future__ import annotations

import fnmatch
import logging
import re
from contextlib import nullcontext
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests
from playwright._impl import _errors as pw_errors
from requests import Session

from repo_utilities.ext import filter_exts

if TYPE_CHECKING:
    from _typeshed import StrPath
    from playwright._impl._sync_base import EventContextManager, EventInfo
    from playwright.sync_api import Browser, Download

logger = logging.getLogger("repo_utilities")


class DownloadError(Exception):
    """Download failed."""


class HeaderError(DownloadError):
    """Header extraction failed."""


class HTTPError(requests.HTTPError, DownloadError):
    """HTTP request failed."""


class BrowserError(DownloadError):
    """Browser download failed."""


class GitHubError(Exception):
    """GitHub API error."""


class GitHubSession:
    """Updates the session headers for GitHub API requests.

    Attributes:
        session: The requests session to use.
    """

    def __init__(self, token: str, session: Session | None = None) -> None:
        """Initialize the class.

        Args:
            token: The GitHub token.
            session: The requests session to use. Defaults to None.
                Creates a new session if None.
        """
        self.token = token
        self.session = session or Session()

    def __enter__(self) -> Session:
        """Enter the context manager.

        Returns:
            The session with updated headers.

        Raises:
            GitHubTokenError: If no GitHub token is set.
        """
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        return self.session

    def __exit__(self, *args: object) -> None:
        """Exit the context manager. Clear the headers."""
        self.session.headers.clear()


def get_release_data(
    repo: str,
    token: str,
    exclude_prereleases: bool = True,
    session: Session | None = None,
) -> dict[str, list[str]]:
    """Get all tag names and assets for a GitHub repository.

    Args:
        repo: The GitHub repository in the format "owner/repo".
        token: The GitHub token.
        exclude_prereleases: Whether to exclude prereleases. Defaults to True.
        session: The requests session to use. Defaults to None.
            Creates a new session if None.

    Returns:
        A dictionary with tag names as keys and asset names as values.
    """
    with GitHubSession(token, session) as gh_session:
        url = f"https://api.github.com/repos/{repo}/releases"
        response = gh_session.get(url)
        response.raise_for_status()

    def _exclude_release(release: dict[str, Any]) -> bool:
        return exclude_prereleases and release["prerelease"]

    def _get_assets(release: dict[str, Any]) -> list[str]:
        return [asset["name"] for asset in release["assets"]]

    return {
        release["tag_name"]: _get_assets(release)
        for release in response.json()
        if not _exclude_release(release)
    }


def find_asset_by_tag(release_data: dict[str, list[str]], pattern: str, tag: str) -> str | None:
    """Find an asset by tag in the GitHub repo.

    Args:
        release_data: The release data dictionary (tag name: asset names).
        pattern: The pattern to match.
        tag: The tag to search for.

    Returns:
        The asset name if found, otherwise None.

    Raises:
        GitHubError: If no assets are found for the tag.
    """
    assets = release_data.get(tag)
    if not assets:
        raise GitHubError(f"No assets found for tag {tag}.")

    matches = fnmatch.filter(assets, pattern)
    if not matches:
        return None
    if len(matches) > 1:
        raise GitHubError(f"Multiple matching tags for pattern {pattern}: {matches}.")
    return matches.pop()


def find_recent_asset(release_data: dict[str, list[str]], pattern: str) -> tuple[str, str]:
    """Find the most recent tag and asset that matches the pattern.

    Args:
        release_data: The release data dictionary (tag name: asset names).
        pattern: The pattern to match.

    Returns:
        A tuple with the asset name and tag name.

    Raises:
        GitHubError: If no matching tag is found.
    """
    for tag in release_data:
        if asset := find_asset_by_tag(release_data, pattern, tag):
            return asset, tag

    raise GitHubError(f"No matching tag found for pattern {pattern}.")


def get_remote_filename(url: str, session: Session | None = None) -> str:
    """Get the remote filename from a URL.

    Starts the download of the first byte of the file to get the filename.

    Args:
        url: The URL to get the filename from.
        session: The requests session to use. Defaults to None.
            Creates a new session if None.

    Returns:
        The filename extracted from the Content-Disposition header.

    Raises:
        HeaderError: If the filename could not be extracted.
    """
    # if session is provided, use it, otherwise create a new one
    session = session or Session()

    # try a get request and close ASAP
    response = session.get(url, stream=True)
    response.close()

    # read the Content-Disposition header and extract the filename
    # attachment; filename="filename"; filename*=UTF-8''filename ...
    if content := response.headers.get("Content-Disposition"):
        if match := re.match(r'attachment; filename="([^"]+)"', content):
            return match.group(1).rsplit("/", 1)[-1]
        raise HeaderError(f"Could not get filename from {content}")
    raise HeaderError(f"Could not get Content-Disposition from {url}")


def download_direct(
    url: str, target: StrPath, name: str | None = None, session: Session | None = None
) -> Path:
    """Download a file from a URL to a target directory.

    Args:
        url: The URL to download from.
        target: The directory to download to.
        name: The name of the file to save as. Defaults to None.
        session: The requests session to use. Defaults to None.
            Creates a new session if None.

    Returns:
        The path to the downloaded file.

    Raises:
        HTTPError: If the response status code is not OK.
    """
    # if session is provided, use it, otherwise create a new one
    session = session or Session()

    # filename is the last part of the URL if not provided
    name = name or url.rsplit("/", maxsplit=1)[-1]

    logger.info("Downloading %s directly...", name)

    # get the content and check for errors
    response = session.get(url)
    try:
        response.raise_for_status()
    except requests.HTTPError as e:
        raise HTTPError from e

    # save the content to the target directory
    target_path = Path(target) / name
    target_path.write_bytes(response.content)

    logger.info("Downloaded %s.", name)

    return target_path


def get_pw_download(
    browser: Browser, urls: tuple[str, ...], dl_timeout: int = 2000, timeout: int = 2000
) -> Download:
    """Get playwright download content from a URL and >-separated clicks.

    Downloaded uses larger value from dl_timeout and timeout, clicks use timeout.

    Raises:
        BrowserError: If the download did not start or a click could not be found.
    """
    url, *clicks = urls

    # Use the first page in the first context if available
    # Else create a new context and page
    if browser.contexts:
        page = browser.contexts[0].pages[0]
    else:
        context = browser.new_context(storage_state=None)
        page = context.new_page()

    # Mostly for type checking
    # returns an expect_download context manager if ctx=True
    # else returns a nullcontext which just outputs None
    def _build_ctx(
        expect_download: bool = False,
    ) -> EventContextManager[Download] | nullcontext[None]:
        """Build the context manager depending if a download is expected."""
        if expect_download:
            return page.expect_download(timeout=max(dl_timeout, timeout))
        return nullcontext(None)

    def _return_download_info(download_info: EventInfo[Download] | None) -> Download:
        """Return the download info."""
        if download_info is None or download_info.value is None:
            raise BrowserError("Download did not start.")

        return download_info.value

    expect_download = len(clicks) == 0
    with _build_ctx(expect_download) as download_info:
        logger.debug("Go to %s", url)
        # just open the url
        page.goto(url)

    # if no clicks are provided, it is finished here
    if expect_download:
        return _return_download_info(download_info)

    for ix, click in enumerate(clicks):
        logger.debug("Click %s", click)

        # if this is the last click, expect a download
        expect_download = ix == len(clicks) - 1
        with _build_ctx(expect_download) as download_info:
            # click can be selector (#id) or text (text)
            if click.startswith("#"):
                if handle := page.wait_for_selector(click, timeout=timeout):
                    handle.click(timeout=timeout, force=True)
                else:
                    raise BrowserError(f"Could not find {click} on {page.url}")
            else:
                page.get_by_text(click).first.click(timeout=timeout, force=True)

    # after all clicks, return the download info
    return _return_download_info(download_info)


def download_via_browser(  # noqa: PLR0913, PLR0917
    browser: Browser,
    urls: tuple[str, ...],
    target: StrPath | None,
    stem: str | None = None,
    prefix: str | None = None,
    timeout: int = 2000,
    retries: int = 1,
) -> Path:
    """Download a file from a URL via a browser.

    Args:
        browser: The playwright browser to use.
        urls: The URL to download from.
        target: The directory to download to. If None, get only the name.
        stem: The stem of the file to save as. Defaults to None.
        prefix: The prefix of the file to save as. Defaults to None.
        timeout: The timeout for each click. Defaults to 2000.
        retries: The number of retries if a download does not start. Defaults to 1.

    Returns:
        Path to the downloaded file (or just the name if target is None).

    Raises:
        DownloadError: If the download did not start.
    """
    err: pw_errors.TimeoutError | None = None
    download: Download | None = None
    for retry in range(1, retries + 1):  # retries
        try:
            download = get_pw_download(browser, urls, retry * timeout, retry * timeout)
            break
        except pw_errors.TimeoutError as e:
            err = e

    if download is None:
        raise DownloadError from err

    # Wait for the download process to complete
    # and save the downloaded file somewhere
    sugg_name = download.suggested_filename
    sugg_path = Path(sugg_name)
    sugg_suffix = "".join(filter_exts(sugg_path))
    if not target:
        download.cancel()
        return sugg_path

    name = (stem + sugg_suffix) if stem else sugg_name
    name = prefix + name if prefix else name

    target_path = Path(target) / name

    logger.info("Downloading %s via browser...", name)

    # wait for the download to finish
    # and save the file to the target path
    download.save_as(target_path)

    logger.info("Downloaded %s.", name)

    return target_path


__all__ = [
    "DownloadError",
    "GitHubError",
    "GitHubSession",
    "download_direct",
    "download_via_browser",
    "find_asset_by_tag",
    "find_recent_asset",
    "get_release_data",
    "get_remote_filename",
]
