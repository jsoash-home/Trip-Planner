"""Unit tests for src/drift_review — chronological ordering of items."""

from datetime import date, time
from types import SimpleNamespace

from src.drift_review import chronological_order


def _item(item_id, day, start=None, order=0):
    return SimpleNamespace(
        id=item_id,
        day_date=day,
        start_time=start,
        order_within_day=order,
    )


def test_empty_list_returns_empty():
    assert chronological_order([]) == []


def test_items_sorted_across_days():
    a = _item(1, date(2026, 6, 3), time(9, 0))
    b = _item(2, date(2026, 6, 1), time(9, 0))
    c = _item(3, date(2026, 6, 2), time(9, 0))
    assert [it.id for it in chronological_order([a, b, c])] == [2, 3, 1]


def test_untimed_items_come_first_within_day():
    timed = _item(1, date(2026, 6, 1), time(9, 0))
    untimed = _item(2, date(2026, 6, 1), None)
    assert [it.id for it in chronological_order([timed, untimed])] == [2, 1]


def test_untimed_items_sorted_by_order_within_day():
    a = _item(1, date(2026, 6, 1), None, order=2)
    b = _item(2, date(2026, 6, 1), None, order=1)
    assert [it.id for it in chronological_order([a, b])] == [2, 1]


def test_timed_items_sorted_by_start_time_within_day():
    a = _item(1, date(2026, 6, 1), time(15, 0))
    b = _item(2, date(2026, 6, 1), time(9, 0))
    assert [it.id for it in chronological_order([a, b])] == [2, 1]


def test_id_tiebreaker_is_stable():
    a = _item(2, date(2026, 6, 1), time(9, 0), order=0)
    b = _item(1, date(2026, 6, 1), time(9, 0), order=0)
    assert [it.id for it in chronological_order([a, b])] == [1, 2]


def test_items_with_no_day_date_are_skipped():
    a = _item(1, date(2026, 6, 1), time(9, 0))
    b = _item(2, None, time(9, 0))
    assert [it.id for it in chronological_order([a, b])] == [1]
