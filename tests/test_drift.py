"""Tests for detect_drift — compares a stored itinerary item against
what its linked booking would auto-generate now."""

from datetime import date, datetime, time
from types import SimpleNamespace

from src.booking_helpers import DriftReport, FieldDrift, detect_drift, serialize_touched


def _item(**overrides):
    """Convenience: build a stand-in itinerary item with sensible defaults."""
    base = dict(
        linked_booking_id=1,
        auto_kind="depart",
        customized_by_user=False,
        auto_fields_touched="",
        title="Depart United",
        category="transit",
        day_date=date(2026, 6, 1),
        start_time=time(10, 0),
        end_time=None,
        location=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _flight():
    return SimpleNamespace(
        type="flight", title="UA101", vendor="United",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        end_datetime=datetime(2026, 6, 1, 14, 0),
        location=None,
    )


def test_in_sync_returns_none():
    assert detect_drift(_item(), _flight()) is None


def test_no_linked_booking_returns_none():
    assert detect_drift(_item(linked_booking_id=None), _flight()) is None


def test_customized_by_user_flag_is_ignored_under_per_field_model():
    """The deprecated customized_by_user flag no longer silences drift.
    Silencing is expressed by populating auto_fields_touched instead."""
    item = _item(customized_by_user=True, day_date=date(2026, 1, 1))
    report = detect_drift(item, _flight())
    assert report is not None
    fields = {f.field_name for f in report.fields}
    assert "day_date" in fields


def test_legacy_item_without_auto_kind_returns_none():
    item = _item(auto_kind=None, day_date=date(2026, 1, 1))
    assert detect_drift(item, _flight()) is None


def test_day_change_detected():
    item = _item(day_date=date(2026, 6, 2))  # booking now says Jun 1
    report = detect_drift(item, _flight())
    assert isinstance(report, DriftReport)
    assert report.is_orphaned is False
    fields = {f.field_name: (f.current, f.would_be) for f in report.fields}
    assert fields["day_date"] == (date(2026, 6, 2), date(2026, 6, 1))


def test_title_change_detected():
    item = _item(title="Depart Delta")  # booking says United
    report = detect_drift(item, _flight())
    fields = {f.field_name for f in report.fields}
    assert "title" in fields


def test_orphaned_when_booking_no_longer_generates_kind():
    # Booking had an end_datetime so it generated arrive. Now the user
    # cleared end_datetime, so no "arrive" item would be generated.
    flight_no_end = SimpleNamespace(
        type="flight", title="UA101", vendor="United",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        end_datetime=None, location=None,
    )
    arrive_item = _item(auto_kind="arrive", title="Arrive United",
                        day_date=date(2026, 6, 1), start_time=time(14, 0))
    report = detect_drift(arrive_item, flight_no_end)
    assert report.is_orphaned is True
    assert report.fields == []


def test_has_drift_property():
    assert DriftReport(fields=[], is_orphaned=True).has_drift is True
    assert DriftReport(fields=[], is_orphaned=False).has_drift is False
    assert DriftReport(
        fields=[FieldDrift(field_name="title", current="a", would_be="b")],
        is_orphaned=False,
    ).has_drift is True


def test_touched_field_is_silently_ignored():
    """If the user has touched the title, a title drift should not be flagged."""
    item = _item(title="Depart Delta",
                 auto_fields_touched=serialize_touched({"title"}))
    # Booking still says United, but user has touched the title — no drift.
    assert detect_drift(item, _flight()) is None


def test_partial_touched_still_flags_untouched_fields():
    """Touched=title; day_date differs → report has only day_date."""
    item = _item(
        title="Depart Delta",
        day_date=date(2026, 6, 5),  # booking says Jun 1
        auto_fields_touched=serialize_touched({"title"}),
    )
    report = detect_drift(item, _flight())
    assert report is not None
    fields = {f.field_name for f in report.fields}
    assert fields == {"day_date"}


def test_all_touched_returns_none():
    """auto_fields_touched contains every DRIFT_FIELD → silenced."""
    from src.booking_helpers import DRIFT_FIELDS
    item = _item(
        title="Depart Delta",
        day_date=date(2026, 1, 1),
        auto_fields_touched=serialize_touched(DRIFT_FIELDS),
    )
    assert detect_drift(item, _flight()) is None


def test_touched_set_without_actual_drift_returns_none():
    """Touched but no drifted untouched field → returns None."""
    item = _item(auto_fields_touched=serialize_touched({"title"}))
    # All fields match the booking → no drift even though title is touched.
    assert detect_drift(item, _flight()) is None
