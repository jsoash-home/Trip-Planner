"""Unit tests for src/prep_helpers.py."""

from datetime import date

from src.prep_helpers import (
    URGENCY_LATER,
    URGENCY_NONE,
    URGENCY_OVERDUE,
    URGENCY_SOON,
    URGENCY_URGENT,
    category_emoji,
    category_label,
    due_date,
    urgency_bucket,
)


# ─────────────────────────────  category metadata  ─────────────────────────


def test_category_label_known():
    assert category_label("gear") == "Gear"
    assert category_label("admin") == "Admin"


def test_category_label_unknown_returns_code():
    assert category_label("not_a_real_code") == "not_a_real_code"


def test_category_emoji_known():
    assert category_emoji("gear") == "🎒"
    assert category_emoji("buy") == "🛒"


# ─────────────────────────────  due_date  ──────────────────────────────────


def test_due_date_with_offset():
    # 14 days before Aug 17 → Aug 3
    assert due_date(date(2026, 8, 17), 14) == date(2026, 8, 3)


def test_due_date_no_offset_returns_none():
    assert due_date(date(2026, 8, 17), None) is None


def test_due_date_no_trip_start_returns_none():
    assert due_date(None, 14) is None


# ─────────────────────────────  urgency_bucket  ────────────────────────────


def test_urgency_bucket_overdue():
    today = date(2026, 6, 14)
    assert urgency_bucket(today, date(2026, 6, 13)) == URGENCY_OVERDUE


def test_urgency_bucket_urgent_at_7_days():
    today = date(2026, 6, 14)
    assert urgency_bucket(today, date(2026, 6, 21)) == URGENCY_URGENT


def test_urgency_bucket_soon_at_30_days():
    today = date(2026, 6, 14)
    assert urgency_bucket(today, date(2026, 7, 14)) == URGENCY_SOON


def test_urgency_bucket_later_at_31_days():
    today = date(2026, 6, 14)
    assert urgency_bucket(today, date(2026, 7, 15)) == URGENCY_LATER


def test_urgency_bucket_none_when_due_is_none():
    today = date(2026, 6, 14)
    assert urgency_bucket(today, None) == URGENCY_NONE
