"""Unit tests for src/guide_emit.py.

All tests are plain-Python string checks on function return values. No fixtures,
no DB, no Flask. Runs in well under a second.
"""

from datetime import date
from typing import Any, Dict, List

import pytest

from src import guide_emit
from src.guide_emit import (
    category_color,
    emit_css,
    emit_go_deeper,
    emit_h2,
    emit_hero,
    emit_js,
    emit_practical_link,
    emit_section_wrapper,
    emit_toc,
    emit_walking_chip,
    esc,
    permalink,
    reading_time,
    reading_time_chip,
)


# ── Palette / eras fixtures (plain dicts, not pytest fixtures) ─────────────

def _palette() -> Dict[str, Any]:
    return {
        "name": "nordlys",
        "colors": {
            "bg":          "#0e131a",
            "surface":     "#1a212c",
            "ink":         "#e9e6dd",
            "ink_soft":    "#a8a39a",
            "ink_display": "#f5f0e3",
            "accent":      "#7ec8b1",
            "accent_2":    "#d59a6a",
            "muted":       "#6b7889",
            "hairline":    "#2a323f",
            "warning":     "#e07c5b",
        },
        "fonts": {
            "display": "Fraunces",
            "body":    "Inter",
            "mono":    "JetBrains Mono",
        },
    }


def _eras() -> List[Dict[str, str]]:
    return [
        {"slug": "viking",   "label": "Viking",   "hex": "#7a8b5c", "year_range": "793–1066"},
        {"slug": "medieval", "label": "Medieval", "hex": "#9a7140", "year_range": "1066–1500"},
    ]


def _trip_meta() -> Dict[str, Any]:
    return {
        "title": "Scandinavia '26",
        "subtitle": "Twenty-three days across five countries.",
        "narrator_dek": "A dark-mode field notebook for a Nordic loop.",
        "start_date": date(2026, 8, 14),
        "end_date":   date(2026, 9, 5),
        "countries": ["Norway", "Finland", "Estonia", "Sweden", "Denmark"],
        "countries_count": 5,
        "nights": 22,
        "bookings_count": 27,
    }


# ── esc ────────────────────────────────────────────────────────────────────

def test_esc_escapes_html_special_chars():
    assert esc("<script>alert('x')</script>") == (
        "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;"
    )


def test_esc_quote_mode_on():
    # quote=True → double quotes escaped too (attribute-safe)
    assert '&quot;' in esc('say "hi"')


# ── reading_time ────────────────────────────────────────────────────────────

def test_reading_time_words_over_220_wpm_ceil():
    # 221 words / 220 wpm = 1.004... → ceil to 2
    text = " ".join(["word"] * 221)
    assert reading_time(text) == 2


def test_reading_time_strips_html_tags():
    # HTML tags should not count as words
    text = "<p>one two three</p>"
    assert reading_time(text) == 1  # 3 words, floor to 1


def test_reading_time_returns_at_least_one():
    assert reading_time("") == 1
    assert reading_time("   ") == 1


# ── permalink ───────────────────────────────────────────────────────────────

def test_permalink_produces_anchor_with_hash_slug():
    out = permalink("days", "Day by day")
    assert 'href="#days"' in out
    assert 'class="permalink"' in out
    assert '¶' in out


def test_permalink_escapes_label_in_aria():
    out = permalink("x", '<b>bad</b>')
    assert 'aria-label="Permalink to &lt;b&gt;bad&lt;/b&gt;"' in out


# ── reading_time_chip ───────────────────────────────────────────────────────

def test_reading_time_chip_contains_minutes_and_slug_label():
    chip = reading_time_chip("word " * 500, "timeline")
    assert 'class="reading-time"' in chip
    assert 'min · timeline' in chip
    # 500 words / 220 = 2.27 → 3 min
    assert '3 min' in chip


# ── emit_h2 ─────────────────────────────────────────────────────────────────

def test_emit_h2_contains_slug_id_reading_time_chip_permalink():
    h2 = emit_h2("days", "Day by day", "timeline", "one two three")
    assert 'id="days"' in h2
    assert 'Day by day' in h2
    assert 'class="reading-time"' in h2
    assert 'class="permalink"' in h2


def test_emit_h2_escapes_label():
    h2 = emit_h2("s", "<i>bad</i>", "sl", "body")
    assert '&lt;i&gt;bad&lt;/i&gt;' in h2


# ── category_color ──────────────────────────────────────────────────────────

def test_category_color_known_categories_map_correctly():
    assert category_color("transit") == "transit"
    assert category_color("meal") == "meal"
    assert category_color("sightseeing") == "sight"
    assert category_color("other") == "other"


def test_category_color_unknown_falls_back_to_other():
    assert category_color("mystery") == "other"
    assert category_color("") == "other"


# ── emit_practical_link ─────────────────────────────────────────────────────

def test_emit_practical_link_url_encodes_name_and_city():
    out = emit_practical_link("Camp Barentz", "Longyearbyen, Svalbard")
    # The URL comes from maps_url which URL-encodes; espace() then
    # HTML-escapes any & in the URL to &amp;. Check the encoded query.
    assert "Camp%20Barentz" in out
    assert "Longyearbyen" in out


def test_emit_practical_link_sets_rel_noopener_target_blank():
    out = emit_practical_link("Fruene Coffee", "Longyearbyen, Svalbard")
    assert 'rel="noopener"' in out
    assert 'target="_blank"' in out
    assert 'class="practical-link"' in out


def test_emit_practical_link_uses_full_text_when_passed():
    out = emit_practical_link("Fruene Coffee", "Longyearbyen", "the coffee shop")
    # Visible link text is the full_text, not the name
    assert 'the coffee shop</a>' in out
    # But the URL still uses the name
    assert "Fruene%20Coffee" in out


# ── emit_walking_chip ───────────────────────────────────────────────────────

VC = {"camp barentz": (78.2200, 15.6300)}
VR = {"camp barentz": 0.95}
HOTEL = {"lat": 78.2232, "lng": 15.6267, "title": "Funken Lodge"}


def test_emit_walking_chip_empty_when_venue_key_none():
    assert emit_walking_chip(None, HOTEL, VC, VR) == ""


def test_emit_walking_chip_empty_when_hotel_none():
    assert emit_walking_chip("Camp Barentz", None, VC, VR) == ""


def test_emit_walking_chip_empty_when_coords_missing():
    # venue_key not in venue_coords → ""
    assert emit_walking_chip("Unknown Venue", HOTEL, VC, VR) == ""


def test_emit_walking_chip_empty_when_hotel_missing_lat():
    # hotel dict without lat → ""
    hotel_no_lat = {"lng": 15.6267, "title": "Funken Lodge"}
    assert emit_walking_chip("Camp Barentz", hotel_no_lat, VC, VR) == ""


def test_emit_walking_chip_delegates_confidence_to_walking_distance():
    # A low-confidence venue (below 0.7) makes walking_distance.walking_chip
    # return "" — proves our helper is passing venue_confidence through.
    low_relevance = {"camp barentz": 0.5}
    assert emit_walking_chip("Camp Barentz", HOTEL, VC, low_relevance) == ""


def test_emit_walking_chip_passes_hotel_title_through():
    # High confidence → chip should render and contain the hotel title
    out = emit_walking_chip("Camp Barentz", HOTEL, VC, VR)
    assert "Funken Lodge" in out
    assert 'class="walkchip"' in out


# ── emit_css ────────────────────────────────────────────────────────────────

def test_emit_css_palette_colors_emitted_as_root_vars():
    css = emit_css(_palette(), _eras())
    assert "--bg: #0e131a" in css
    assert "--accent: #7ec8b1" in css
    assert "--warning: #e07c5b" in css


def test_emit_css_era_slugs_emitted_as_variables_and_class_rules():
    css = emit_css(_palette(), _eras())
    # Variables in :root
    assert "--era-viking: #7a8b5c" in css
    assert "--era-medieval: #9a7140" in css
    # Class rules
    assert ".era-viking { --era: var(--era-viking); }" in css
    assert ".era-medieval { --era: var(--era-medieval); }" in css


def test_emit_css_fonts_substituted():
    css = emit_css(_palette(), _eras())
    assert "'Fraunces'" in css
    assert "'Inter'" in css
    assert "'JetBrains Mono'" in css


def test_emit_css_empty_eras_produces_no_era_css_no_crash():
    css = emit_css(_palette(), [])
    # No era-<slug> variables emitted
    assert "--era-" not in css
    # And no crash — function returned a non-empty string
    assert len(css) > 100


# ── emit_js ─────────────────────────────────────────────────────────────────

def test_emit_js_returns_non_empty_string():
    js = emit_js()
    assert isinstance(js, str)
    assert len(js) > 100


def test_emit_js_contains_mode_toggle_iife_marker():
    js = emit_js()
    # The mode-toggle IIFE inside the wayfinding bundle
    assert "initModeToggle" in js
    assert "vp.guide.mode" in js
    assert "VPGuide" in js


# ── emit_hero ───────────────────────────────────────────────────────────────

def test_emit_hero_contains_trip_title_and_palette_name_eyebrow():
    out = emit_hero(_trip_meta(), "nordlys")
    assert "Trip guide · nordlys" in out
    assert "Scandinavia &#x27;26" in out  # apostrophe HTML-escaped by quote=True


def test_emit_hero_route_svg_inserted_verbatim():
    tm = _trip_meta()
    tm["route_svg"] = '<svg class="route-svg" data-marker="X"><circle/></svg>'
    out = emit_hero(tm, "nordlys")
    # Verbatim insertion — no escaping
    assert '<svg class="route-svg" data-marker="X"><circle/></svg>' in out


def test_emit_hero_absent_route_svg_omits_element():
    tm = _trip_meta()
    # No route_svg key at all
    tm.pop("route_svg", None)
    out = emit_hero(tm, "nordlys")
    assert "<svg" not in out


def test_emit_hero_escapes_user_supplied_strings():
    tm = _trip_meta()
    tm["title"] = "<script>alert(1)</script>"
    tm["subtitle"] = 'quotes "here"'
    out = emit_hero(tm, "nordlys")
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out
    assert "&quot;here&quot;" in out
    # Raw injection did not leak through
    assert "<script>alert(1)" not in out


def test_emit_hero_sources_note_renders_verbatim_when_present():
    tm = _trip_meta()
    tm["sources_note"] = "Drawn from <i>Nordic History</i> Vol. 1."
    out = emit_hero(tm, "nordlys")
    assert 'class="sources-note"' in out
    assert "Drawn from <i>Nordic History</i> Vol. 1." in out


def test_emit_hero_sources_note_absent_omits_details_block():
    tm = _trip_meta()
    tm.pop("sources_note", None)
    out = emit_hero(tm, "nordlys")
    assert 'class="sources-note"' not in out


# ── emit_toc ────────────────────────────────────────────────────────────────

def test_emit_toc_produces_anchor_per_slug():
    out = emit_toc([("days", "Day by day"), ("food", "Food")])
    assert 'href="#days"' in out
    assert 'href="#food"' in out
    assert out.count('<a href="#') == 2


def test_emit_toc_escapes_label():
    out = emit_toc([("x", "<b>bad</b>")])
    assert "&lt;b&gt;bad&lt;/b&gt;" in out


def test_emit_toc_empty_slugs_renders_aside_with_no_anchors():
    out = emit_toc([])
    assert 'class="vp-toc"' in out
    assert "<a " not in out


# ── emit_go_deeper ──────────────────────────────────────────────────────────

def test_emit_go_deeper_empty_card_list_returns_empty_string():
    assert emit_go_deeper([]) == ""


def test_emit_go_deeper_n_cards_produce_n_articles():
    cards = [
        {"kind": "Book",    "title": "T1", "url": "https://a.example", "annotation": "A"},
        {"kind": "Podcast", "title": "T2", "url": "https://b.example", "annotation": "B"},
        {"kind": "Film",    "title": "T3", "url": "https://c.example", "annotation": "C"},
    ]
    out = emit_go_deeper(cards)
    assert out.count('<article class="gd-card">') == 3
    # Kinds appear
    assert "Book" in out and "Podcast" in out and "Film" in out
    # URLs wired to href
    assert 'href="https://a.example"' in out
    assert 'href="https://b.example"' in out
    assert 'href="https://c.example"' in out


def test_emit_go_deeper_escapes_card_fields():
    cards = [{
        "kind": "Book",
        "title": "<b>Bad</b>",
        "url": "https://x.example/?q=1&r=2",
        "annotation": 'say "hi"',
    }]
    out = emit_go_deeper(cards)
    assert "&lt;b&gt;Bad&lt;/b&gt;" in out
    assert "&quot;hi&quot;" in out
    assert "https://x.example/?q=1&amp;r=2" in out


# ── emit_section_wrapper ────────────────────────────────────────────────────

def test_emit_section_wrapper_atmospheric_kind_class():
    out = emit_section_wrapper("days", "Day by day", "atmospheric", "<p>body</p>")
    assert 'class="section--atmospheric"' in out


def test_emit_section_wrapper_practical_kind_class():
    out = emit_section_wrapper("weather", "Weather", "practical", "<p>body</p>")
    assert 'class="section--practical"' in out


def test_emit_section_wrapper_slug_becomes_section_id():
    out = emit_section_wrapper("days", "Day by day", "atmospheric", "<p>x</p>")
    assert 'id="days"' in out
    # The slug shows up on both the outer section AND the h2 (both use id="days")
    assert out.count('id="days"') >= 1


def test_emit_section_wrapper_body_html_spliced_inside():
    body = '<p class="unique-marker">hello world</p>'
    out = emit_section_wrapper("s", "Section", "atmospheric", body)
    assert body in out


def test_emit_section_wrapper_go_deeper_appended_when_non_empty():
    body = "<p>body</p>"
    gd = '<aside class="go-deeper"><p>gd</p></aside>'
    out = emit_section_wrapper("s", "Section", "atmospheric", body, go_deeper_html=gd)
    assert gd in out
    # go_deeper is inside the wrapper (before closing </section>)
    assert out.endswith("</section>")
    assert out.index(gd) < out.rindex("</section>")


def test_emit_section_wrapper_no_trailing_aside_when_go_deeper_empty():
    out = emit_section_wrapper("s", "Section", "atmospheric", "<p>body</p>")
    assert 'class="go-deeper"' not in out


def test_emit_section_wrapper_slug_label_falls_back_to_label():
    # Without slug_label, the label should be used as the reading-time chip label
    out = emit_section_wrapper("s", "MyLabel", "atmospheric", "one two three")
    # The reading-time chip contains "min · <slug_label>"
    assert "min · MyLabel" in out


def test_emit_section_wrapper_slug_label_used_when_supplied():
    out = emit_section_wrapper(
        "s", "MyLabel", "atmospheric", "one two three", slug_label="my-slug-lbl"
    )
    assert "min · my-slug-lbl" in out
