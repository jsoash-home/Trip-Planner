"""Unit tests for src/prep_helpers.py."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import pytest

from src.prep_helpers import (
    PREP_CATEGORIES,
    URGENCY_LATER,
    URGENCY_NONE,
    URGENCY_OVERDUE,
    URGENCY_SOON,
    URGENCY_URGENT,
    category_emoji,
    category_label,
    due_date,
    group_items_by_category,
    items_for_dashboard_panel,
    parse_prep_form,
    sort_key,
    urgency_bucket,
)


@dataclass
class FakeTrip:
    """Stand-in for a Trip row — just exposes start_date."""

    start_date: Optional[date]


@dataclass
class FakeItem:
    """Stand-in for a TripPrepItem row, duck-typed for the pure helpers."""

    id: int = 0
    title: str = ""
    category: str = "other"
    done: bool = False
    done_at: Optional[datetime] = None
    due_offset_days: Optional[int] = None
    sort_order: int = 0
    created_at: Optional[datetime] = field(default_factory=lambda: datetime(2026, 1, 1))
    trip: Optional[FakeTrip] = None


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


# ─────────────────────────────  sort_key  ──────────────────────────────────


def test_sort_key_overdue_before_urgent():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 6, 17))  # 3 days out
    overdue = FakeItem(id=1, trip=trip, due_offset_days=10)  # due Jun 7 → overdue
    urgent = FakeItem(id=2, trip=trip, due_offset_days=2)   # due Jun 15 → urgent
    ordered = sorted([urgent, overdue], key=lambda it: sort_key(it, today))
    assert ordered[0] is overdue
    assert ordered[1] is urgent


def test_sort_key_done_items_last_regardless_of_urgency():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 6, 17))
    # Done item with the most-overdue due date should still sort after any open item.
    done_overdue = FakeItem(id=1, trip=trip, due_offset_days=30, done=True)
    open_later = FakeItem(id=2, trip=trip, due_offset_days=-60)  # due far in future
    ordered = sorted([done_overdue, open_later], key=lambda it: sort_key(it, today))
    assert ordered[0] is open_later
    assert ordered[1] is done_overdue


def test_sort_key_tiebreaker_uses_sort_order_then_created_at():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 6, 17))
    # All three are open, all due Jun 15 (urgent bucket), same due date.
    a = FakeItem(id=1, trip=trip, due_offset_days=2, sort_order=2,
                 created_at=datetime(2026, 1, 1))
    b = FakeItem(id=2, trip=trip, due_offset_days=2, sort_order=1,
                 created_at=datetime(2026, 1, 2))
    c = FakeItem(id=3, trip=trip, due_offset_days=2, sort_order=1,
                 created_at=datetime(2026, 1, 1))
    ordered = sorted([a, b, c], key=lambda it: sort_key(it, today))
    # sort_order=1 wins → c and b before a. Within sort_order=1, earlier
    # created_at wins → c before b.
    assert [it.id for it in ordered] == [3, 2, 1]


# ─────────────────────────────  parse_prep_form  ───────────────────────────


def test_parse_prep_form_full_input():
    data = parse_prep_form({
        "title": "Renew passport",
        "notes": "expires Aug 2027",
        "category": "admin",
        "due_offset_days": "30",
        "trip_id": "5",
    })
    assert data == {
        "title": "Renew passport",
        "notes": "expires Aug 2027",
        "category": "admin",
        "due_offset_days": 30,
        "trip_id": 5,
    }


def test_parse_prep_form_strips_title():
    data = parse_prep_form({"title": "  Buy luggage tags  "})
    assert data["title"] == "Buy luggage tags"


def test_parse_prep_form_empty_title_raises():
    with pytest.raises(ValueError):
        parse_prep_form({"title": "   "})


def test_parse_prep_form_unknown_category_defaults_to_other():
    data = parse_prep_form({"title": "Thing", "category": "spaceship"})
    assert data["category"] == "other"


def test_parse_prep_form_blank_offset_returns_none():
    data = parse_prep_form({"title": "Thing", "due_offset_days": ""})
    assert data["due_offset_days"] is None


def test_parse_prep_form_non_integer_offset_returns_none():
    data = parse_prep_form({"title": "Thing", "due_offset_days": "soon-ish"})
    assert data["due_offset_days"] is None


def test_parse_prep_form_blank_trip_id_returns_none():
    blank = parse_prep_form({"title": "Thing", "trip_id": ""})
    explicit_none = parse_prep_form({"title": "Thing", "trip_id": "none"})
    assert blank["trip_id"] is None
    assert explicit_none["trip_id"] is None


# ─────────────────────────────  group_items_by_category  ───────────────────


def test_group_items_by_category_preserves_display_order():
    items = [
        FakeItem(id=1, category="admin"),
        FakeItem(id=2, category="gear"),
        FakeItem(id=3, category="buy"),
    ]
    out = group_items_by_category(items)
    expected_codes = [code for code, _, _ in PREP_CATEGORIES] + ["done"]
    assert list(out.keys()) == expected_codes
    # Each item lands in its own bucket.
    assert [it.id for it in out["gear"]] == [2]
    assert [it.id for it in out["buy"]] == [3]
    assert [it.id for it in out["admin"]] == [1]


def test_group_items_by_category_done_bucket_at_end():
    items = [
        FakeItem(id=1, category="gear", done=False),
        FakeItem(id=2, category="gear", done=True),
        FakeItem(id=3, category="buy",  done=True),
    ]
    out = group_items_by_category(items)
    # done bucket key is literally "done" and lives at the end.
    assert list(out.keys())[-1] == "done"
    # Done items are pulled out of their original categories.
    assert [it.id for it in out["gear"]] == [1]
    assert out["buy"] == []
    assert {it.id for it in out["done"]} == {2, 3}


# ─────────────────────────────  items_for_dashboard_panel  ─────────────────


def test_items_for_dashboard_panel_excludes_done():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 6, 17))
    items = [
        FakeItem(id=1, trip=trip, due_offset_days=2, done=True),
        FakeItem(id=2, trip=trip, due_offset_days=2, done=False),
    ]
    out = items_for_dashboard_panel(items, today)
    assert [it.id for it in out] == [2]


def test_items_for_dashboard_panel_respects_limit():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 6, 17))
    items = [FakeItem(id=i, trip=trip, due_offset_days=2) for i in range(10)]
    out = items_for_dashboard_panel(items, today, limit=3)
    assert len(out) == 3


def test_items_for_dashboard_panel_sorts_by_urgency():
    today = date(2026, 6, 14)
    trip = FakeTrip(start_date=date(2026, 7, 14))  # 30 days out
    overdue = FakeItem(id=1, trip=trip, due_offset_days=40)  # past
    urgent = FakeItem(id=2, trip=trip, due_offset_days=25)   # 5d → urgent
    soon = FakeItem(id=3, trip=trip, due_offset_days=10)     # 20d → soon
    later = FakeItem(id=4, trip=FakeTrip(start_date=date(2026, 12, 1)),
                     due_offset_days=10)
    no_due = FakeItem(id=5, trip=trip)  # no offset → no due
    out = items_for_dashboard_panel([no_due, later, soon, urgent, overdue], today)
    assert [it.id for it in out] == [1, 2, 3, 4, 5]
