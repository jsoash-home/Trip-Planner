"""
src/url_metadata.py

Pure helpers for the trip-prep "save by URL" feature.

Two pieces:
  - looks_like_url(text) — quick check used by the form handler to decide
    whether the user typed a URL versus a free-text idea.
  - extract_metadata_from_html(html, source_url) — given the raw HTML of
    a page plus the URL it was fetched from, return a small dict with a
    title and (optionally) a hero image, using OpenGraph / Twitter Card
    meta tags with sensible fallbacks.

No network here — this module is the pure half. The impure fetch wrapper
lives in a separate task.
"""

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urljoin

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
