"""Unit tests for src/map_helpers.py."""

import pytest

from src.map_helpers import (
    Pin,
    build_static_map_url,
    color_for_category,
    color_for_year,
    normalize_location,
    pins_to_geojson,
    should_clear_geocode,
    stats_for_pins,
    years_present,
)


# ─────────────────────────── normalize_location ──────────────────────


def test_normalize_strips_whitespace():
    assert normalize_location("  Hotel Skansen  ") == "hotel skansen"


def test_normalize_lowercases():
    assert normalize_location("Eiffel Tower") == "eiffel tower"


def test_normalize_collapses_inner_whitespace():
    assert normalize_location("Eiffel    Tower\n\tParis") == "eiffel tower paris"


def test_normalize_empty_returns_empty():
    assert normalize_location("") == ""
    assert normalize_location("   ") == ""


# ─────────────────────────── should_clear_geocode ────────────────────


def test_clear_geocode_when_text_changes_and_not_manual():
    assert should_clear_geocode("Paris", "Lyon", manually_pinned=False) is True


def test_keep_geocode_when_text_unchanged():
    assert should_clear_geocode("Paris", "Paris", manually_pinned=False) is False


def test_keep_geocode_when_manually_pinned_even_if_text_changes():
    assert should_clear_geocode("Paris", "Lyon", manually_pinned=True) is False


def test_clear_geocode_when_text_emptied():
    assert should_clear_geocode("Paris", "", manually_pinned=False) is True


def test_normalize_difference_only_does_not_clear():
    # Same logical text, different whitespace — don't bust the geocode.
    assert should_clear_geocode("Paris", "  paris  ", manually_pinned=False) is False


# ────────────────────────── color_for_year ───────────────────────────


def test_color_for_year_returns_hex():
    color = color_for_year(2024)
    assert color.startswith("#")
    assert len(color) == 7  # #RRGGBB


def test_color_for_year_cycles_consistently():
    # Same year ⇒ same color, every time.
    assert color_for_year(2024) == color_for_year(2024)


def test_color_for_year_distinct_for_adjacent_years():
    # Adjacent years should look different.
    assert color_for_year(2024) != color_for_year(2025)


# ────────────────────── color_for_category ───────────────────────────


def test_color_for_category_known():
    assert color_for_category("transit").startswith("#")
    assert color_for_category("meal").startswith("#")
    assert color_for_category("sightseeing").startswith("#")
    assert color_for_category("break").startswith("#")
    assert color_for_category("other").startswith("#")


def test_color_for_category_unknown_falls_back_to_other():
    assert color_for_category("garbage") == color_for_category("other")


# ───────────────────────── helpers below need a Pin ──────────────────


def _pin(**overrides) -> Pin:
    """Build a Pin with reasonable defaults for testing."""
    defaults = dict(
        row_type="booking",
        row_id=1,
        trip_id=10,
        trip_name="Test Trip",
        title="Hotel X",
        location_text="Stockholm",
        lat=59.33,
        lng=18.07,
        geocoded_city="Stockholm",
        geocoded_country_code="SE",
        year=2024,
        category="other",
        datetime_iso=None,
        day_index=1,
    )
    defaults.update(overrides)
    return Pin(**defaults)


# ────────────────────────────── years_present ────────────────────────


def test_years_present_returns_descending_unique():
    pins = [_pin(year=2022), _pin(year=2024), _pin(year=2023), _pin(year=2024)]
    assert years_present(pins) == [2024, 2023, 2022]


def test_years_present_empty():
    assert years_present([]) == []


# ────────────────────────────── stats_for_pins ───────────────────────


def test_stats_counts_unique_countries_cities_trips():
    pins = [
        _pin(geocoded_country_code="SE", geocoded_city="Stockholm", trip_id=1),
        _pin(geocoded_country_code="SE", geocoded_city="Stockholm", trip_id=1),
        _pin(geocoded_country_code="SE", geocoded_city="Göteborg",  trip_id=2),
        _pin(geocoded_country_code="NO", geocoded_city="Bergen",    trip_id=3),
    ]
    stats = stats_for_pins(pins)
    assert stats == {"countries": 2, "cities": 3, "trips": 3}


def test_stats_ignores_pins_without_country_or_city():
    pins = [
        _pin(geocoded_country_code=None, geocoded_city=None, trip_id=1),
        _pin(geocoded_country_code="FR", geocoded_city="Paris", trip_id=2),
    ]
    stats = stats_for_pins(pins)
    assert stats == {"countries": 1, "cities": 1, "trips": 2}


# ────────────────────────────── pins_to_geojson ──────────────────────


def test_pins_to_geojson_basic_structure():
    pins = [_pin(lat=59.33, lng=18.07)]
    gj = pins_to_geojson(pins, color_fn=lambda p: "#000000")
    assert gj["type"] == "FeatureCollection"
    assert len(gj["features"]) == 1
    feat = gj["features"][0]
    assert feat["type"] == "Feature"
    assert feat["geometry"]["type"] == "Point"
    assert feat["geometry"]["coordinates"] == [18.07, 59.33]  # GeoJSON is [lng, lat]
    assert feat["properties"]["color"] == "#000000"
    assert feat["properties"]["trip_name"] == "Test Trip"


def test_pins_to_geojson_color_fn_called_per_pin():
    pins = [_pin(year=2024), _pin(year=2025)]
    gj = pins_to_geojson(pins, color_fn=lambda p: f"#{p.year}")
    colors = [f["properties"]["color"] for f in gj["features"]]
    assert colors == ["#2024", "#2025"]


def test_pins_to_geojson_empty():
    gj = pins_to_geojson([], color_fn=lambda p: "#000000")
    assert gj == {"type": "FeatureCollection", "features": []}


# ─────────────────────────── build_static_map_url ────────────────────


def _static_pin(lng: float, lat: float, category: str = "other") -> Pin:
    return Pin(
        row_type="booking", row_id=1, trip_id=1, trip_name="T",
        title="X", location_text="Y",
        lat=lat, lng=lng,
        geocoded_city=None, geocoded_country_code=None,
        year=2026, category=category,
        datetime_iso=None, day_index=None,
    )


def test_build_static_map_url_empty_pins_returns_none():
    assert build_static_map_url([], token="pk.test") is None


def test_build_static_map_url_no_token_returns_none():
    assert build_static_map_url([_static_pin(18.07, 59.33)], token=None) is None


def test_build_static_map_url_single_pin_format():
    url = build_static_map_url(
        [_static_pin(18.07, 59.33, category="other")],
        token="pk.test",
    )
    assert url.startswith("https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/")
    assert "/auto/600x360@2x" in url
    assert url.endswith("?access_token=pk.test")
    # The marker segment is URL-encoded: parens and commas become %xx.
    assert "%28" in url and "%29" in url  # ( and )
    assert "pin-s%2B" in url               # the literal "+" before the color


def test_build_static_map_url_multiple_pins_comma_separated():
    url = build_static_map_url(
        [_static_pin(18.07, 59.33), _static_pin(2.35, 48.86)],
        token="pk.test",
    )
    # Two markers → encoded comma %2C between them.
    assert url.count("pin-s%2B") == 2
    assert "%2C" in url


def test_build_static_map_url_includes_width_height_in_path():
    url = build_static_map_url(
        [_static_pin(18.07, 59.33)],
        width=800, height=400, token="pk.test",
    )
    assert "/auto/800x400@2x" in url


def test_build_static_map_url_uses_color_for_category():
    url_meal = build_static_map_url([_static_pin(0, 0, "meal")], token="pk.test")
    url_other = build_static_map_url([_static_pin(0, 0, "other")], token="pk.test")
    # color_for_category("meal") = #E07B5B → "e07b5b" in URL.
    assert "e07b5b" in url_meal.lower()
    # And category "other" should differ from "meal".
    assert url_other != url_meal
