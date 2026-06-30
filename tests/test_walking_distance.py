"""Tests for src/walking_distance.py — haversine + adaptive chip."""

import pytest

from src.walking_distance import haversine_km, walking_chip


def test_haversine_km_known_landmark_pair():
    # Statue of Liberty (40.6892, -74.0445) to Empire State Building
    # (40.7484, -73.9857) — well-known straight-line distance ~8.2 km.
    d = haversine_km(40.6892, -74.0445, 40.7484, -73.9857)
    assert 8.0 < d < 8.5


def test_haversine_km_zero_for_same_point():
    assert haversine_km(48.8584, 2.2945, 48.8584, 2.2945) == 0.0


def test_haversine_km_symmetric():
    a = haversine_km(40.6892, -74.0445, 40.7484, -73.9857)
    b = haversine_km(40.7484, -73.9857, 40.6892, -74.0445)
    assert a == pytest.approx(b)


# Walking chip — coords chosen so each band fires deterministically.
# km_route = haversine_km(...) * 1.3.

# (0, 0) -> (0.001, 0) is ~0.111 km straight -> 0.144 km routed -> ≤2km band
NEAR_VENUE = (0.001, 0.0)
NEAR_HOTEL = (0.0, 0.0)

# (0, 0) -> (0.027, 0) is ~3.00 km straight -> ~3.9 km routed -> 2-5km band
MID_VENUE = (0.027, 0.0)
MID_HOTEL = (0.0, 0.0)

# (0, 0) -> (0.05, 0) is ~5.56 km straight -> ~7.22 km routed -> >5km band
FAR_VENUE = (0.05, 0.0)
FAR_HOTEL = (0.0, 0.0)


def test_walking_chip_under_2km_format():
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, "Hotel One")
    assert chip.startswith('<span class="walkchip">')
    assert chip.endswith("</span>")
    assert "min walk" in chip
    assert "by car" not in chip
    assert "from Hotel One" in chip


def test_walking_chip_2_to_5km_format():
    chip = walking_chip(MID_VENUE, MID_HOTEL, "Hotel One")
    assert "min walk" in chip
    assert "by car" in chip  # adapted format includes the driving alternate
    assert " · or " in chip


def test_walking_chip_over_5km_format():
    chip = walking_chip(FAR_VENUE, FAR_HOTEL, "Hotel One")
    assert "by car" in chip
    assert "min walk" not in chip  # >5km band drops the walking time


def test_walking_chip_returns_empty_on_none_venue_coords():
    assert walking_chip(None, NEAR_HOTEL, "Hotel One") == ""


def test_walking_chip_returns_empty_on_none_hotel_coords():
    assert walking_chip(NEAR_VENUE, None, "Hotel One") == ""


def test_walking_chip_html_escapes_hotel_name():
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, 'Bar "Three Crowns" & Co')
    assert "&quot;" in chip
    assert "&amp;" in chip
    assert '"Three Crowns"' not in chip  # raw quotes must not survive


# ────────────── confidence threshold (Phase 2b T6) ──────────────


def test_renders_chip_when_confidence_above_threshold():
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, "Hotel One", venue_confidence=0.95)
    assert chip.startswith('<span class="walkchip">')


def test_skips_chip_when_confidence_below_threshold():
    # 0.5 < 0.7 default threshold → skip.
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, "Hotel One", venue_confidence=0.5)
    assert chip == ""


def test_renders_chip_when_confidence_none_legacy_trusted():
    # None means "we don't know" (cache hit / non-Mapbox provider) → trust.
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, "Hotel One", venue_confidence=None)
    assert chip.startswith('<span class="walkchip">')


def test_renders_chip_at_exact_threshold_boundary():
    # Exactly equal to threshold → still rendered (>= semantics).
    chip = walking_chip(NEAR_VENUE, NEAR_HOTEL, "Hotel One", venue_confidence=0.7)
    assert chip.startswith('<span class="walkchip">')


def test_min_confidence_param_overrides_default():
    # Confidence 0.65, default threshold 0.7 → would skip.
    # With min_confidence=0.5 → renders.
    chip_with_lower_threshold = walking_chip(
        NEAR_VENUE, NEAR_HOTEL, "Hotel One",
        venue_confidence=0.65, min_confidence=0.5,
    )
    assert chip_with_lower_threshold.startswith('<span class="walkchip">')


def test_other_skip_paths_still_work_with_confidence_passed():
    # None-coords path still wins, regardless of confidence value.
    assert walking_chip(None, NEAR_HOTEL, "X", venue_confidence=0.99) == ""
    assert walking_chip(NEAR_VENUE, None, "X", venue_confidence=0.99) == ""
