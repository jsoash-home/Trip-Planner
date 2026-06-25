"""Tests for src/place_links.py — Google Maps URLs + practical-link HTML."""

from src.place_links import maps_url, practical_link


def test_maps_url_builds_google_search_query():
    url = maps_url("Vasa Museum", "Stockholm")
    assert url.startswith("https://www.google.com/maps/search/?api=1&query=")
    assert "Vasa%20Museum" in url
    assert "Stockholm" in url
    assert "%2C" in url  # comma between name and city is URL-encoded


def test_maps_url_url_encodes_punctuation():
    url = maps_url("L'Atelier", "Paris")
    # Apostrophe is URL-encoded as %27 (safe="" encodes everything non-alphanumeric)
    assert "%27" in url
    assert "L'Atelier" not in url  # raw apostrophe should NOT appear


def test_maps_url_url_encodes_unicode():
    url = maps_url("Café Tortoni", "Buenos Aires")
    # é is UTF-8 0xC3 0xA9 → %C3%A9
    assert "%C3%A9" in url
    assert "Café" not in url  # raw é should NOT appear


def test_practical_link_includes_rel_noopener():
    html_str = practical_link("Vasa Museum", "Stockholm")
    assert 'rel="noopener"' in html_str


def test_practical_link_escapes_html_in_name():
    html_str = practical_link('Bar "Three Crowns"', "Stockholm")
    # The raw double-quote must NOT appear in the link text portion
    # (it would prematurely close the href attribute or the text). html.escape
    # turns " into &quot; when quote=True (the default).
    assert "&quot;" in html_str
    assert '>Bar "Three Crowns"<' not in html_str


def test_practical_link_target_blank():
    html_str = practical_link("Vasa Museum", "Stockholm")
    assert 'target="_blank"' in html_str
