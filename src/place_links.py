"""Google Maps search URLs + practical-link HTML snippets.

The trip-guide skill calls these from the composer at compose time to turn
plain venue names into clickable links. Pure, no network, no dependencies
beyond stdlib.

See `docs/superpowers/specs/2026-06-25-trip-guide-phase2a-editorial-spine-design.md`
for the two-tier hyperlink rule that motivates this module.
"""

import html
import logging
import urllib.parse

logger = logging.getLogger(__name__)

GOOGLE_MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="


def maps_url(name: str, city: str) -> str:
    """Build a Google Maps search URL for `name` in `city`."""
    query = f"{name}, {city}"
    return GOOGLE_MAPS_SEARCH_URL + urllib.parse.quote(query, safe="")


def practical_link(name: str, city: str) -> str:
    """Return an <a> tag pointing at the Google Maps result for the venue.

    The visible link text is the HTML-escaped name. The URL is already
    URL-encoded by `maps_url`, so the only unsafe HTML char in the href
    would be `&` — browsers handle that fine inside double-quoted attrs.
    """
    return (
        f'<a class="practical-link" '
        f'href="{maps_url(name, city)}" '
        f'rel="noopener" target="_blank">'
        f"{html.escape(name)}</a>"
    )
