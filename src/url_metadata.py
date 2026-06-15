"""
src/url_metadata.py

Helpers for the trip-prep "save by URL" feature.

Pure pieces:
  - looks_like_url(text) — quick check used by the form handler to decide
    whether the user typed a URL versus a free-text idea.
  - extract_metadata_from_html(html, source_url) — given the raw HTML of
    a page plus the URL it was fetched from, return a small dict with a
    title and (optionally) a hero image, using OpenGraph / Twitter Card
    meta tags with sensible fallbacks.

Impure piece:
  - fetch_url_metadata(url) — fetches a URL over HTTP and feeds the
    response through extract_metadata_from_html. Silent on failure: any
    error path returns a fallback dict and logs a WARNING.
"""

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


# Matches an entire string that is a single http/https URL. We use
# `\S+` (one or more non-whitespace chars) so "  https://x.com  "
# passes after strip() but "check this http://x.com" does not — the
# leading "check this " would have to be part of the match.
URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


# Maximum displayed length of a title before truncation. Titles longer
# than this get cut to TITLE_MAX_LEN - 3 chars plus the single-char "…"
# ellipsis, for a final visible length of TITLE_MAX_LEN - 2 characters.
TITLE_MAX_LEN = 200
TITLE_TRUNCATE_AT = 197


def looks_like_url(text: str) -> bool:
    """Return True iff the stripped text is a single http(s) URL."""
    if not text:
        return False
    return bool(URL_RE.match(text.strip()))


def _meta_content(soup: BeautifulSoup, attr: str, value: str) -> Optional[str]:
    """Return the `content` attribute of the first <meta {attr}="{value}">.

    Returns None if no such tag exists or its content is empty/missing.
    """
    tag = soup.find("meta", attrs={attr: value})
    if not tag:
        return None
    content = tag.get("content")
    if not content:
        return None
    return content


def extract_metadata_from_html(html: str, source_url: str) -> Dict[str, Any]:
    """Parse HTML and return {title, image_url, source_url}.

    Title preference: og:title → twitter:title → <title> → source_url.
    Image preference: og:image → twitter:image → None.
    Relative image URLs are resolved against source_url.
    """
    soup = BeautifulSoup(html, "html.parser")

    title_tag_text: Optional[str] = None
    if soup.title and soup.title.string:
        title_tag_text = soup.title.string

    title = (
        _meta_content(soup, "property", "og:title")
        or _meta_content(soup, "name", "twitter:title")
        or title_tag_text
        or source_url
    )
    title = title.strip()
    if len(title) > TITLE_MAX_LEN:
        title = title[:TITLE_TRUNCATE_AT] + "…"

    image: Optional[str] = (
        _meta_content(soup, "property", "og:image")
        or _meta_content(soup, "name", "twitter:image")
    )
    if image:
        image = urljoin(source_url, image.strip())

    return {"title": title, "image_url": image, "source_url": source_url}


# ───────────────────────────  fetch_url_metadata  ──────────────────────────

# Network timeout for the metadata fetch. Kept short — the user is waiting
# on a form submit. A slow page is fine to fall back on.
FETCH_TIMEOUT_SECONDS: float = 5.0

# Some sites serve a cleaner page (or any page at all) to non-bot UAs.
FETCH_USER_AGENT: str = "Mozilla/5.0 (compatible; VacationPlanner/1.0)"


def fetch_url_metadata(url: str, timeout: float = FETCH_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Fetch URL and return {title, image_url, source_url}.

    Silent failure: any requests exception, non-200 status, non-HTML
    content type, or parse exception is caught and logged at WARNING,
    and the function returns a fallback dict with the URL itself as
    the title and no image.
    """
    fallback: Dict[str, Any] = {"title": url, "image_url": None, "source_url": url}
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": FETCH_USER_AGENT},
        )
        if response.status_code != 200:
            logger.warning(
                "fetch_url_metadata: HTTP %s for %s", response.status_code, url
            )
            return fallback
        content_type = response.headers.get("content-type", "")
        if not (
            content_type.startswith("text/html")
            or content_type.startswith("application/xhtml")
        ):
            logger.warning(
                "fetch_url_metadata: non-HTML content-type %r for %s",
                content_type,
                url,
            )
            return fallback
        return extract_metadata_from_html(response.text, url)
    except Exception as e:
        logger.warning("fetch_url_metadata: failed for %s: %s", url, e)
        return fallback
