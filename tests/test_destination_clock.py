"""Unit tests for src/destination_clock.py."""

import src.destination_clock as dc
from src.destination_clock import (
    format_clock_label,
    hours_offset_label,
    iana_from_coords,
    is_valid_iana,
)


class _FakeFinder:
    """Stand-in for the real TimezoneFinder so tests don't depend on
    the bundled coordinate data. The real instance's attributes are
    read-only (C extension), so we swap the whole singleton instead."""

    def __init__(self, *, returns=None, raises=None):
        self._returns = returns
        self._raises = raises

    def timezone_at(self, *, lat, lng):
        if self._raises is not None:
            raise self._raises
        return self._returns


# ─────────────────────────  iana_from_coords  ─────────────────────────


def test_iana_from_coords_returns_value_when_finder_returns_value(monkeypatch):
    monkeypatch.setattr(dc, "_TF", _FakeFinder(returns="Europe/Paris"))
    assert iana_from_coords(48.85, 2.35) == "Europe/Paris"


def test_iana_from_coords_returns_none_when_finder_returns_none(monkeypatch):
    monkeypatch.setattr(dc, "_TF", _FakeFinder(returns=None))
    assert iana_from_coords(0.0, 0.0) is None


def test_iana_from_coords_handles_finder_exception(monkeypatch):
    monkeypatch.setattr(dc, "_TF", _FakeFinder(raises=RuntimeError("boom")))
    assert iana_from_coords(48.85, 2.35) is None


def test_iana_from_coords_returns_none_when_finder_unavailable(monkeypatch):
    monkeypatch.setattr(dc, "_TF", None)
    assert iana_from_coords(48.85, 2.35) is None


# ──────────────────────────  is_valid_iana  ───────────────────────────


def test_is_valid_iana_known_zone():
    assert is_valid_iana("Europe/Paris") is True


def test_is_valid_iana_mistyped_zone():
    assert is_valid_iana("Europe/Pariss") is False


def test_is_valid_iana_empty_string():
    assert is_valid_iana("") is False


# ────────────────────────  hours_offset_label  ────────────────────────


def test_hours_offset_label_zero_same_time():
    assert hours_offset_label(0) == "same time"


def test_hours_offset_label_positive_whole_hours():
    assert hours_offset_label(840) == "14 h ahead"


def test_hours_offset_label_negative_whole_hours():
    assert hours_offset_label(-480) == "8 h behind"


def test_hours_offset_label_positive_half_hour():
    assert hours_offset_label(330) == "5 h 30 min ahead"


def test_hours_offset_label_positive_45_min():
    assert hours_offset_label(345) == "5 h 45 min ahead"


def test_hours_offset_label_negative_half_hour():
    assert hours_offset_label(-570) == "9 h 30 min behind"


def test_hours_offset_label_one_hour_singular_ok():
    assert hours_offset_label(60) == "1 h ahead"


# ────────────────────────  format_clock_label  ────────────────────────


def test_format_clock_label_with_city_hint():
    assert format_clock_label("Tokyo", "Asia/Tokyo") == "🕒 Tokyo"


def test_format_clock_label_without_city_hint_uses_iana_tail():
    assert format_clock_label(None, "Asia/Tokyo") == "🕒 Tokyo"


def test_format_clock_label_underscore_in_iana_tail():
    assert format_clock_label(None, "Asia/Ho_Chi_Minh") == "🕒 Ho Chi Minh"
