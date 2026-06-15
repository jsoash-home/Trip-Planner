"""Integration tests — exercise routes + DB end-to-end with an
in-memory SQLite database. Uses Flask's test_client and a fresh DB
per test via a pytest fixture."""

import calendar
from datetime import date, datetime

import pytest

from app import _ensure_prep_tables, _ensure_trip_timezone, app as flask_app
from models import (
    Booking,
    ItineraryItem,
    PackingItem,
    Trip,
    TripPrepItem,
    TripPrepLink,
    TripView,
    User,
    db,
)


@pytest.fixture
def app():
    """Reset the in-memory DB schema before each test for clean state.

    The engine is already bound to in-memory SQLite via conftest.py's
    DATABASE_URL override, which runs at pytest load time (before
    app.py is imported). Setting SQLALCHEMY_DATABASE_URI here would
    NOT rebind the engine — earlier versions of this fixture did that
    and silently wiped the real vacation.db on every pytest run.
    """
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def owner(app):
    u = User(google_id="g1", email="owner@example.com", name="Owner")
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture
def trip(app, owner):
    # end_date is far in the future so the fixture stays "active" no
    # matter when the suite runs — drift checks skip trips whose
    # end_date is before today.
    t = Trip(owner_id=owner.id, name="Test trip",
             start_date=date(2026, 6, 1), end_date=date(2030, 12, 31))
    db.session.add(t)
    db.session.commit()
    return t


def test_delete_booking_cascades_linked_items(app, trip):
    """Deleting a booking removes its auto-linked itinerary items."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    db.session.add_all([
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="depart", day_date=date(2026, 6, 1),
                      title="Depart UA"),
        ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="arrive", day_date=date(2026, 6, 1),
                      title="Arrive UA"),
        # A stand-alone item with no linked_booking — should survive.
        ItineraryItem(trip_id=trip.id, linked_booking_id=None,
                      day_date=date(2026, 6, 1), title="Coffee"),
    ])
    db.session.commit()

    assert ItineraryItem.query.filter_by(trip_id=trip.id).count() == 3

    db.session.delete(b)
    db.session.commit()

    remaining = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    assert len(remaining) == 1
    assert remaining[0].title == "Coffee"
    assert db.session.get(Booking, b.id) is None


def test_itinerary_edit_records_changed_fields_only(app, trip, owner):
    """Editing only the title flips just `title` in auto_fields_touched."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         start_time=datetime(2026, 6, 2, 15, 0).time(),
                         title="Check in: Hilton", category="other")
    db.session.add(item)
    db.session.commit()
    assert item.auto_fields_touched == ""

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton (front desk)",  # CHANGED
                "category": "other",                       # unchanged
                "day_date": "2026-06-02",                  # unchanged
                "start_time": "15:00",                     # unchanged
                "end_time": "",                            # unchanged
                "location": "",                            # unchanged
                "notes": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.auto_fields_touched == "title"
    assert item.title == "Check in: Hilton (front desk)"


def test_itinerary_edit_no_op_does_not_change_touched_set(app, trip, owner):
    """Submitting the edit form without changing anything leaves the
    auto_fields_touched set untouched."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 2, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="check_in", day_date=date(2026, 6, 2),
                         start_time=datetime(2026, 6, 2, 15, 0).time(),
                         title="Check in: Hilton", category="other",
                         auto_fields_touched="day_date")  # pre-existing touch
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/edit",
            data={
                "title": "Check in: Hilton",
                "category": "other",
                "day_date": "2026-06-02",
                "start_time": "15:00",
                "end_time": "",
                "location": "",
                "notes": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(item)
    # No change → touched set untouched.
    assert item.auto_fields_touched == "day_date"


def _make_flight_with_arrive(trip):
    """Helper: make a flight booking + its 'arrive' linked item (already drifted).

    The item's title is intentionally stale ('Arrive Delta') so resync
    has something to do.
    """
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta",  # stale — booking now says United
                         category="transit")
    db.session.add(item)
    db.session.commit()
    return b, item


def _login(client, user):
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_resync_updates_fields_from_booking(app, trip, owner):
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.title == "Arrive United"
    # No touches to start → resync updates the field, touched set stays empty.
    assert item.auto_fields_touched == ""


def test_keep_mine_sets_all_touched(app, trip, owner):
    """Keep mine fills auto_fields_touched with every DRIFT_FIELD."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/keep-mine")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.auto_fields_touched == "category,day_date,end_time,location,start_time,title"
    assert item.title == "Arrive Delta"  # field values unchanged


def test_unlink_clears_linked_booking_and_touched_set(app, trip, owner):
    """Unlink severs the link AND clears auto_fields_touched."""
    b, item = _make_flight_with_arrive(trip)
    # Pretend the user had touched something before unlinking.
    item.auto_fields_touched = "title"
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/unlink")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.linked_booking_id is None
    assert item.auto_kind is None
    assert item.auto_fields_touched == ""
    assert Booking.query.get(b.id) is not None


def test_drift_review_landing_empty(app, trip, owner):
    """No drift anywhere → landing page shows the all-clear state."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    assert b"Nothing" in resp.data or b"all in sync" in resp.data.lower() or b"0 items" in resp.data


def test_drift_review_landing_counts_resyncable_vs_orphan(app, trip, owner):
    """One resyncable + one orphaned → page shows both counts."""
    # Booking + a stale linked item (resyncable drift).
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item_a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                           auto_kind="arrive", day_date=date(2026, 6, 1),
                           title="Arrive Delta",  # drifted: booking says United
                           category="transit")
    db.session.add(item_a)
    # Booking that no longer suggests "depart" (start_datetime cleared).
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    item_b = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(item_b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # 2 total drifting, 1 resyncable, 1 orphan.
    assert "2" in body and "1" in body
    assert "Start review" in body
    assert "Resync 1 unchanged" in body


def test_drift_review_wizard_renders_first_item(app, trip, owner):
    """GET wizard step on a drifting item shows the diff + Skip + buttons."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}"
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Item 1 of 1" in body
    assert "Skip" in body
    assert "Resync to booking" in body
    assert "Keep mine" in body
    assert "Unlink from booking" in body


def test_drift_review_wizard_progress_counts(app, trip, owner):
    """Two drifting items → 'Item 1 of 2' on the first, 'Item 2 of 2' on the second."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    # Two linked items, both drifted on title.
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp1 = client.get(f"/trips/{trip.id}/itinerary/drift-review/item/{a.id}")
        resp2 = client.get(f"/trips/{trip.id}/itinerary/drift-review/item/{z.id}")
    assert b"Item 1 of 2" in resp1.data
    assert b"Item 2 of 2" in resp2.data


def test_drift_review_wizard_redirects_when_item_not_drifting(app, trip, owner):
    """GET wizard step on an item that isn't drifting → redirect to landing."""
    b = Booking(trip_id=trip.id, type="restaurant", title="Noma", vendor="Noma",
                start_datetime=datetime(2026, 6, 1, 19, 0), end_datetime=None)
    db.session.add(b)
    db.session.commit()
    # In-sync item — no drift.
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="single", day_date=date(2026, 6, 1),
                         start_time=__import__("datetime").time(19, 0),
                         title="Noma", category="meal")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert "/drift-review" in resp.headers["Location"]
    assert f"/item/{item.id}" not in resp.headers["Location"]


def test_wizard_resync_redirects_to_next_drifting(app, trip, owner):
    """Resync with ?from=wizard advances to the next drifting item's wizard."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/resync?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


def test_wizard_resync_redirects_to_landing_when_no_more_drift(app, trip, owner):
    """Resync the last drifting item with ?from=wizard → land on review home."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{item.id}/resync?from=wizard"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(f"/trips/{trip.id}/itinerary/drift-review")


def test_wizard_keep_mine_redirects_to_next_drifting(app, trip, owner):
    """Keep mine with ?from=wizard advances to the next drifting item."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/keep-mine?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


def test_wizard_unlink_redirects_to_next_drifting(app, trip, owner):
    """Unlink with ?from=wizard advances to the next drifting item."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/{a.id}/unlink?from=wizard"
        )
    assert resp.status_code == 302
    assert f"/drift-review/item/{z.id}" in resp.headers["Location"]


# ─── Celebration flash ─────────────────────────────────────────────

def test_resync_last_drift_uses_celebration_flash(app, trip, owner):
    """When a resync clears the only drifting item, flash category is
    success-celebrate."""
    _, item = _make_flight_with_arrive(trip)
    # Add the in-sync 'depart' item so resync truly clears all drift
    # (otherwise the missing depart auto-slot wouldn't matter for drift,
    # but a stray drift report from a separate orphan would).
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=Booking.query.first().id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
        # Follow redirect to inspect the rendered flash.
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" in resp.data
    assert b"Everything is in sync" in resp.data


def test_resync_with_remaining_drift_uses_regular_flash(app, trip, owner):
    """When other drift remains after a resync, use the regular success flash."""
    _, item1 = _make_flight_with_arrive(trip)
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=Booking.query.first().id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    # A second drifting item on a different booking.
    b2 = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                 start_datetime=datetime(2026, 6, 2, 15, 0),
                 end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b2)
    db.session.commit()
    # Add both check_in and check_out items — one drifting, one in-sync.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b2.id, auto_kind="check_in",
        day_date=date(2026, 6, 2),
        start_time=datetime(2026, 6, 2, 15, 0).time(),
        title="STALE TITLE", category="other",
    ))
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b2.id, auto_kind="check_out",
        day_date=date(2026, 6, 5),
        start_time=datetime(2026, 6, 5, 11, 0).time(),
        title="Check out: Hilton", category="other",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item1.id}/resync")
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" not in resp.data
    # Plain success flash should still appear.
    assert b"vp-flash--success" in resp.data


def test_resync_redirect_includes_just_synced_param(app, trip, owner):
    """The redirect URL after a successful resync carries ?just_synced=<id>."""
    _, item = _make_flight_with_arrive(trip)
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=Booking.query.first().id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    assert f"just_synced={item.id}" in resp.headers["Location"]


def test_just_synced_param_stamps_data_attribute(app, trip, owner):
    """The itinerary page renders data-just-synced='true' on the matching chip."""
    _, item = _make_flight_with_arrive(trip)
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=Booking.query.first().id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    # Resync changes the item's title back to "Arrive United" so the chip
    # exists; we then visit with the query param.
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
        resp = client.get(f"/trips/{trip.id}/itinerary?just_synced={item.id}")
    assert resp.status_code == 200
    assert b'data-just-synced="true"' in resp.data


def test_bulk_resync_clearing_all_uses_celebration_flash(app, trip, owner):
    """Bulk resync that clears all drift uses the celebration flash."""
    _, _ = _make_flight_with_arrive(trip)
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=Booking.query.first().id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/drift-review/bulk-resync")
        resp = client.get(f"/trips/{trip.id}/itinerary")
    assert b"vp-flash--success-celebrate" in resp.data


def test_non_wizard_resync_still_redirects_to_itinerary(app, trip, owner):
    """Phase-1 behavior preserved: no ?from=wizard → redirect to itinerary."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    assert f"/trips/{trip.id}/itinerary" in resp.headers["Location"]
    assert f"just_synced={item.id}" in resp.headers["Location"]


def test_bulk_resync_confirm_lists_eligible_items(app, trip, owner):
    """GET confirmation page lists each resyncable item with its diff."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                         auto_kind="arrive", day_date=date(2026, 6, 1),
                         title="Arrive Delta", category="transit")
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Item appears in the list, and the resync button mentions count = 1.
    assert "Arrive Delta" in body
    assert "Resync these 1" in body or "Resync these 1 item" in body


def test_bulk_resync_confirm_mentions_orphans(app, trip, owner):
    """When orphans exist alongside eligible items, page notes them."""
    # Resyncable: a normal flight with drift.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    item_ok = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                            auto_kind="arrive", day_date=date(2026, 6, 1),
                            title="Arrive Delta", category="transit")
    db.session.add(item_ok)
    # Orphan: booking that no longer suggests "depart" (start_datetime cleared).
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    orphan = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(orphan)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    body = resp.data.decode("utf-8")
    assert "1 orphan" in body or "1 item can't be auto-resynced" in body
    # Orphan item title NOT in the resync list block.
    assert "Resync these 1" in body or "Resync these 1 item" in body


def test_bulk_resync_confirm_redirects_when_nothing_eligible(app, trip, owner):
    """No eligible items → flash + redirect to landing."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )


def test_bulk_resync_post_updates_all_eligible(app, trip, owner):
    """POST resyncs every eligible item in one transaction."""
    b = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                start_datetime=datetime(2026, 6, 1, 15, 0),
                end_datetime=datetime(2026, 6, 5, 11, 0))
    db.session.add(b)
    db.session.commit()
    a = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_in", day_date=date(2026, 6, 1),
                      title="WRONG check-in", category="other")
    z = ItineraryItem(trip_id=trip.id, linked_booking_id=b.id,
                      auto_kind="check_out", day_date=date(2026, 6, 5),
                      title="WRONG check-out", category="other")
    db.session.add_all([a, z])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )
    db.session.refresh(a)
    db.session.refresh(z)
    assert a.title == "Check in: Hilton"
    assert z.title == "Check out: Hilton"
    assert a.auto_fields_touched == ""
    assert z.auto_fields_touched == ""


def test_bulk_resync_post_skips_orphans(app, trip, owner):
    """Orphans in the mix don't break the resync of eligible items."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    eligible_item = ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id,
        auto_kind="arrive", day_date=date(2026, 6, 1),
        title="Arrive Delta", category="transit",
    )
    db.session.add(eligible_item)
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=None,
                 end_datetime=datetime(2026, 6, 2, 14, 0))
    db.session.add(b2)
    db.session.commit()
    orphan = ItineraryItem(trip_id=trip.id, linked_booking_id=b2.id,
                           auto_kind="depart", day_date=date(2026, 6, 2),
                           title="Depart Delta", category="transit")
    db.session.add(orphan)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    db.session.refresh(eligible_item)
    db.session.refresh(orphan)
    # Eligible was resynced.
    assert eligible_item.title == "Arrive United"
    # Orphan untouched.
    assert orphan.title == "Depart Delta"


def test_bulk_resync_post_redirects_when_nothing_eligible(app, trip, owner):
    """POST with no eligible items → flash + redirect, no DB change."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/drift-review/bulk-resync"
        )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(
        f"/trips/{trip.id}/itinerary/drift-review"
    )


def test_resync_skips_touched_fields_and_preserves_touched_set(app, trip, owner):
    """Partial-touched item: untouched fields update, touched fields stay,
    touched set is preserved."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # User has touched title (renamed it) AND day differs (booking moved).
    # On resync, title should stay, day should update, touched stays "title".
    item = ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="arrive",
        day_date=date(2026, 6, 5),     # stale; booking says Jun 1
        title="Arrive at JFK gate B22",  # user-touched
        category="transit",
        auto_fields_touched="title",
    )
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/{item.id}/resync")
    assert resp.status_code == 302
    db.session.refresh(item)
    assert item.title == "Arrive at JFK gate B22"   # preserved (touched)
    assert item.day_date == date(2026, 6, 1)         # updated (not touched)
    assert item.auto_fields_touched == "title"       # preserved


def test_drift_review_lists_new_item_suggestions(app, trip, owner):
    """After a booking edit that adds a previously-missing auto-slot, the
    drift review landing page lists the suggestion."""
    # Flight that started with only a depart datetime (so only the depart
    # item exists). Now end_datetime is filled in → 'arrive' is missing.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))  # newly added
    db.session.add(b)
    db.session.commit()
    # Only the depart item exists — no arrive yet.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/drift-review")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Suggestion text appears.
    assert "Arrive United" in body
    assert "New items the booking would create" in body


def test_add_suggested_creates_linked_item(app, trip, owner):
    """POST /add-suggested/<bid>/<kind> creates the missing linked item."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # Only depart exists.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    assert ItineraryItem.query.filter_by(linked_booking_id=b.id).count() == 1

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive"
        )
    assert resp.status_code == 302
    arrive_items = ItineraryItem.query.filter_by(
        linked_booking_id=b.id, auto_kind="arrive"
    ).all()
    assert len(arrive_items) == 1
    assert arrive_items[0].title == "Arrive United"
    assert arrive_items[0].auto_fields_touched == ""


def test_add_suggested_is_idempotent(app, trip, owner):
    """A second POST for an already-existing slot is a no-op (no duplicate)."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive")
        client.post(f"/trips/{trip.id}/itinerary/add-suggested/{b.id}/arrive")
    arrive_items = ItineraryItem.query.filter_by(
        linked_booking_id=b.id, auto_kind="arrive"
    ).all()
    assert len(arrive_items) == 1


def test_bulk_add_confirm_lists_all_missing_items(app, trip, owner):
    """GET /add-all-suggested renders the confirmation page with each missing item."""
    b1 = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                 start_datetime=datetime(2026, 6, 1, 10, 0),
                 end_datetime=datetime(2026, 6, 1, 14, 0))
    b2 = Booking(trip_id=trip.id, type="flight", title="DL200", vendor="Delta",
                 start_datetime=datetime(2026, 6, 2, 8, 0),
                 end_datetime=datetime(2026, 6, 2, 12, 0))
    db.session.add_all([b1, b2])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Depart United" in body
    assert "Arrive United" in body
    assert "Depart Delta" in body
    assert "Arrive Delta" in body


def test_bulk_add_creates_all_missing_items(app, trip, owner):
    """POST /add-all-suggested creates every missing item in one transaction."""
    b1 = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                 start_datetime=datetime(2026, 6, 1, 10, 0),
                 end_datetime=datetime(2026, 6, 1, 14, 0))
    b2 = Booking(trip_id=trip.id, type="hotel", title="Hilton", vendor="Hilton",
                 start_datetime=datetime(2026, 6, 1, 15, 0),
                 end_datetime=datetime(2026, 6, 3, 11, 0))
    db.session.add_all([b1, b2])
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert resp.status_code == 302

    # 4 items total: depart + arrive (flight), check_in + check_out (hotel)
    all_items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    kinds = sorted(it.auto_kind for it in all_items)
    assert kinds == ["arrive", "check_in", "check_out", "depart"]
    assert all(it.auto_fields_touched == "" for it in all_items)


def test_bulk_add_is_idempotent(app, trip, owner):
    """A second POST after all suggestions are accepted is a safe no-op."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
        client.post(f"/trips/{trip.id}/itinerary/add-all-suggested")
    assert ItineraryItem.query.filter_by(trip_id=trip.id).count() == 2


# ─── Dashboard drift counts ─────────────────────────────────────────

def test_drift_counts_empty_when_no_trips(app, owner):
    """No trips → helper returns an empty dict."""
    from app import _drift_counts_for_trips
    assert _drift_counts_for_trips([]) == {}


def test_drift_counts_includes_drifting_trip(app, trip):
    """A trip with one drifting linked item shows (1, 0)."""
    from app import _drift_counts_for_trips
    b, _ = _make_flight_with_arrive(trip)  # 1 drifting 'arrive' item
    # Also add the in-sync 'depart' item so there are no missing auto-slots.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    counts = _drift_counts_for_trips([trip])
    assert counts == {trip.id: (1, 0)}


def test_drift_counts_skips_completed_trip(app, owner):
    """status='completed' trip is omitted from the result dict."""
    from app import _drift_counts_for_trips
    t = Trip(owner_id=owner.id, name="Done trip",
             start_date=date(2026, 1, 1), end_date=date(2026, 1, 7),
             status="completed")
    db.session.add(t)
    db.session.commit()
    _make_flight_with_arrive(t)  # would drift, but trip is completed
    counts = _drift_counts_for_trips([t])
    assert counts == {}


def test_drift_counts_skips_past_trip(app, owner):
    """A trip whose end_date is before today is omitted."""
    from app import _drift_counts_for_trips
    t = Trip(owner_id=owner.id, name="Past trip",
             start_date=date(2020, 1, 1), end_date=date(2020, 1, 7))
    db.session.add(t)
    db.session.commit()
    _make_flight_with_arrive(t)
    counts = _drift_counts_for_trips([t])
    assert counts == {}


def test_drift_counts_includes_new_items_only_trip(app, trip):
    """A trip with no drift but a missing auto-slot shows (0, 1)."""
    from app import _drift_counts_for_trips
    # Flight booking with both datetimes, but only the 'depart' item exists —
    # 'arrive' is the missing auto-slot.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),  # matches booking start
        title="Depart United", category="transit",
    ))
    db.session.commit()
    counts = _drift_counts_for_trips([trip])
    assert counts == {trip.id: (0, 1)}


def test_drift_counts_treats_orphan_items_as_drift(app, trip, owner):
    """An itinerary item whose linked booking was force-deleted (bypassing
    the cascade) still counts as drift, matching _annotate_drift_for_items."""
    from app import _drift_counts_for_trips
    # Create a linked item, then force-delete the booking row directly
    # so the cascade doesn't clean up the item.
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    bid = b.id
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=bid, auto_kind="arrive",
        day_date=date(2026, 6, 1), title="Arrive United", category="transit",
    ))
    db.session.commit()
    # Use a raw delete to bypass the SQLAlchemy cascade.
    db.session.execute(
        Booking.__table__.delete().where(Booking.id == bid)
    )
    db.session.commit()
    counts = _drift_counts_for_trips([trip])
    assert counts == {trip.id: (1, 0)}


def test_booking_edit_flash_mentions_new_items_available(app, trip, owner):
    """Editing a flight to add end_datetime creates a new 'arrive' slot;
    the flash should mention it."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=None)
    db.session.add(b)
    db.session.commit()
    # Existing depart item — no arrive yet (since booking had no end_datetime).
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        # Edit: add end_datetime → arrive slot becomes available as a new suggestion.
        resp = client.post(
            f"/trips/{trip.id}/bookings/{b.id}/edit",
            data={
                "type": "flight", "title": "UA101", "vendor": "United",
                "confirmation_number": "", "location": "",
                "start_datetime": "2026-06-01T10:00",
                "end_datetime": "2026-06-01T14:00",
                "cost": "", "currency": "USD", "url": "", "notes": "",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "new item" in body.lower()
    assert "1" in body  # the count


# ─── Dashboard pill rendering ───────────────────────────────────────

def test_dashboard_renders_drift_pill(app, trip, owner):
    """A drifting trip shows the amber drift pill on the dashboard."""
    b, _ = _make_flight_with_arrive(trip)
    # Also add the in-sync 'depart' item so the new-items count is 0
    # — we want to test the drift pill in isolation.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id,
        auto_kind="depart", day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"trip-card-pill--drift" in resp.data
    assert b"1 out of sync" in resp.data


def test_dashboard_renders_new_pill(app, trip, owner):
    """A trip with a missing auto-slot shows the blue 'suggested' pill."""
    b = Booking(trip_id=trip.id, type="flight", title="UA101", vendor="United",
                start_datetime=datetime(2026, 6, 1, 10, 0),
                end_datetime=datetime(2026, 6, 1, 14, 0))
    db.session.add(b)
    db.session.commit()
    # Only the in-sync 'depart' item exists; 'arrive' is the missing slot.
    db.session.add(ItineraryItem(
        trip_id=trip.id, linked_booking_id=b.id, auto_kind="depart",
        day_date=date(2026, 6, 1),
        start_time=datetime(2026, 6, 1, 10, 0).time(),
        title="Depart United", category="transit",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert b"trip-card-pill--new" in resp.data
    assert b"1 suggested" in resp.data


def test_dashboard_no_pills_when_clean(app, trip, owner):
    """A trip with no drift and no new items renders no status row."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert b"trip-card-pill" not in resp.data
    assert b"trip-card-status-row" not in resp.data


def test_wizard_step_has_action_ids(app, trip, owner):
    """The wizard step renders id attributes on each action element."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}"
        )
    assert resp.status_code == 200
    assert b'id="resync-btn"' in resp.data
    assert b'id="keep-btn"' in resp.data
    assert b'id="unlink-btn"' in resp.data
    assert b'id="skip-link"' in resp.data
    assert b'id="back-link"' in resp.data


def test_wizard_step_has_shortcut_hint(app, trip, owner):
    """The wizard step renders the keyboard-shortcut hint row."""
    _, item = _make_flight_with_arrive(trip)
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(
            f"/trips/{trip.id}/itinerary/drift-review/item/{item.id}"
        )
    assert resp.status_code == 200
    assert b"vp-shortcut-hint" in resp.data
    # Each key is rendered inside a <kbd> tag.
    assert b"<kbd>R</kbd>" in resp.data
    assert b"<kbd>Esc</kbd>" in resp.data


# ───────────────  "What changed since last visit" banner  ───────────────


def test_changes_banner_absent_on_first_visit(app, trip, owner):
    """First-ever visit creates a TripView row and shows no banner, even if
    bookings already exist on the trip."""
    db.session.add(Booking(
        trip_id=trip.id, type="hotel", title="Hilton",
        created_at=datetime(2026, 5, 1, 12, 0),  # well before first visit
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}")

    assert resp.status_code == 200
    assert b"since your last visit" not in resp.data
    # The TripView row was created so subsequent visits can compare against it.
    assert TripView.query.filter_by(trip_id=trip.id, user_id=owner.id).count() == 1


def test_changes_banner_appears_on_second_visit_after_new_booking(app, trip, owner):
    """After a first visit, a booking added later shows in the banner on
    the next visit."""
    with flask_app.test_client() as client:
        _login(client, owner)
        client.get(f"/trips/{trip.id}")  # first visit — establishes baseline

        # Backdate the TripView so a freshly-created booking is unambiguously
        # newer than last_seen_at without relying on sleep().
        view = TripView.query.filter_by(trip_id=trip.id, user_id=owner.id).one()
        view.last_seen_at = datetime(2026, 5, 1, 12, 0)
        db.session.commit()

        db.session.add(Booking(
            trip_id=trip.id, type="hotel", title="Hilton",
            created_at=datetime(2026, 5, 2, 12, 0),  # newer than last_seen
        ))
        db.session.commit()

        resp = client.get(f"/trips/{trip.id}")

    assert resp.status_code == 200
    assert b"1 booking was added since your last visit." in resp.data


def test_changes_banner_clears_after_revisit(app, trip, owner):
    """After the banner shows, an immediate reload clears it."""
    with flask_app.test_client() as client:
        _login(client, owner)
        client.get(f"/trips/{trip.id}")
        view = TripView.query.filter_by(trip_id=trip.id, user_id=owner.id).one()
        view.last_seen_at = datetime(2026, 5, 1, 12, 0)
        db.session.commit()

        db.session.add(Booking(
            trip_id=trip.id, type="hotel", title="Hilton",
            created_at=datetime(2026, 5, 2, 12, 0),
        ))
        db.session.commit()

        resp_a = client.get(f"/trips/{trip.id}")
        resp_b = client.get(f"/trips/{trip.id}")

    assert b"since your last visit" in resp_a.data
    assert b"since your last visit" not in resp_b.data


def test_changes_banner_combines_bookings_and_items(app, trip, owner):
    """Banner copy reflects both new bookings and new itinerary items."""
    with flask_app.test_client() as client:
        _login(client, owner)
        client.get(f"/trips/{trip.id}")
        view = TripView.query.filter_by(trip_id=trip.id, user_id=owner.id).one()
        view.last_seen_at = datetime(2026, 5, 1, 12, 0)
        db.session.commit()

        db.session.add_all([
            Booking(trip_id=trip.id, type="hotel", title="Hilton",
                    created_at=datetime(2026, 5, 2, 12, 0)),
            Booking(trip_id=trip.id, type="flight", title="UA101",
                    created_at=datetime(2026, 5, 2, 12, 5)),
            ItineraryItem(trip_id=trip.id, day_date=date(2026, 6, 2),
                          title="Coffee",
                          created_at=datetime(2026, 5, 2, 12, 10)),
        ])
        db.session.commit()

        resp = client.get(f"/trips/{trip.id}")

    assert (
        b"2 bookings and 1 itinerary item were added since your last visit."
        in resp.data
    )


# ───────────────  In-trip /map/data.geojson route  ───────────────

import json
from unittest.mock import patch, MagicMock


@patch("src.geocoding.requests.get")
def test_trip_map_data_returns_geojson_for_owner(
    mock_get, app, trip, owner, monkeypatch
):
    # The route only calls ensure_geocoded when MAPBOX_TOKEN is set; the
    # token is loaded at module import time, so override it here.
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "features": [{
                "center": [18.0686, 59.3293],
                "context": [
                    {"id": "place.1", "text": "Stockholm"},
                    {"id": "country.1", "short_code": "SE", "text": "Sweden"},
                ],
            }],
        },
    )
    b = Booking(trip_id=trip.id, type="hotel", title="Skansen",
                location="Hotel Skansen")
    db.session.add(b)
    db.session.commit()

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.get(f"/trips/{trip.id}/map/data.geojson")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 1
    feat = payload["features"][0]
    assert feat["geometry"]["coordinates"] == [18.0686, 59.3293]
    assert feat["properties"]["title"] == "Skansen"


def test_trip_map_data_404_for_non_member(app, trip):
    other = User(google_id="g99", email="other@e.com", name="Other")
    db.session.add(other)
    db.session.commit()

    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(other.id)

    resp = client.get(f"/trips/{trip.id}/map/data.geojson")
    assert resp.status_code in (403, 404)


def test_trip_map_data_skips_items_linked_to_booking(app, trip, owner, monkeypatch):
    """De-dup rule: itinerary items with linked_booking_id should NOT
    produce their own pin — the parent booking is the authoritative pin.
    """
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")

    # Booking with coords already set (skip geocoding entirely).
    b = Booking(
        trip_id=trip.id, type="hotel", title="Skansen",
        location="Hotel Skansen",
        geocoded_lat=59.33, geocoded_lng=18.07,
    )
    db.session.add(b)
    db.session.commit()

    # Linked itinerary item — should NOT pin (booking wins).
    linked = ItineraryItem(
        trip_id=trip.id,
        linked_booking_id=b.id,
        auto_kind="check_in",
        day_date=date(2026, 6, 1),
        title="Check in: Skansen",
        location="Hotel Skansen",
        geocoded_lat=59.33, geocoded_lng=18.07,
    )
    # Standalone itinerary item with its own location — SHOULD pin.
    standalone = ItineraryItem(
        trip_id=trip.id,
        day_date=date(2026, 6, 2),
        title="Vasa Museum",
        location="Galärvarvsvägen 14",
        geocoded_lat=59.328, geocoded_lng=18.092,
    )
    db.session.add_all([linked, standalone])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.get(f"/trips/{trip.id}/map/data.geojson")
    payload = json.loads(resp.data)
    titles = sorted(f["properties"]["title"] for f in payload["features"])
    # Booking + standalone = 2 features. Linked auto-item is excluded.
    assert titles == ["Skansen", "Vasa Museum"]


# ─── Task 9: Drag-to-correct ──────────────────────────────────────


@pytest.fixture
def editor(app, owner, trip):
    e = User(google_id="g2", email="editor@e.com", name="Editor")
    db.session.add(e)
    db.session.commit()
    from models import TripCollaborator
    db.session.add(TripCollaborator(
        trip_id=trip.id, email="editor@e.com", role="editor",
    ))
    db.session.commit()
    return e


@pytest.fixture
def viewer(app, owner, trip):
    v = User(google_id="g3", email="viewer@e.com", name="Viewer")
    db.session.add(v)
    db.session.commit()
    from models import TripCollaborator
    db.session.add(TripCollaborator(
        trip_id=trip.id, email="viewer@e.com", role="viewer",
    ))
    db.session.commit()
    return v


def test_drag_correct_succeeds_for_editor(app, trip, editor):
    b = Booking(trip_id=trip.id, type="hotel", title="X",
                location="Hotel", geocoded_lat=0.0, geocoded_lng=0.0)
    db.session.add(b)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    resp = client.post(
        f"/trips/{trip.id}/map/pin/booking/{b.id}",
        json={"lat": 59.33, "lng": 18.07},
    )
    assert resp.status_code == 204
    db.session.refresh(b)
    assert b.geocoded_lat == 59.33
    assert b.geocoded_lng == 18.07
    assert b.geocoded_manually is True


def test_drag_correct_forbidden_for_viewer(app, trip, viewer):
    b = Booking(trip_id=trip.id, type="hotel", title="X",
                location="Hotel", geocoded_lat=0.0, geocoded_lng=0.0)
    db.session.add(b)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(viewer.id)

    resp = client.post(
        f"/trips/{trip.id}/map/pin/booking/{b.id}",
        json={"lat": 1.0, "lng": 2.0},
    )
    assert resp.status_code in (403, 404)
    db.session.refresh(b)
    assert b.geocoded_lat == 0.0   # unchanged


def test_drag_correct_rejects_invalid_coords(app, trip, editor):
    b = Booking(trip_id=trip.id, type="hotel", title="X",
                location="Hotel", geocoded_lat=0.0, geocoded_lng=0.0)
    db.session.add(b)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    for bad in [{"lat": 999, "lng": 0}, {"lat": 0, "lng": 999}, {"lat": "x", "lng": 0}]:
        resp = client.post(
            f"/trips/{trip.id}/map/pin/booking/{b.id}", json=bad,
        )
        assert resp.status_code == 400


# ───────────────  Lifetime /map/data.geojson route  ───────────────


@patch("src.geocoding.requests.get")
def test_lifetime_map_data_includes_owned_completed_trips(
    mock_get, app, owner, monkeypatch
):
    """Owned trips with start_date <= today are included; purely future
    (planning) trips are excluded."""
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")
    mock_get.return_value = MagicMock(
        status_code=200,
        json=lambda: {
            "features": [{
                "center": [18.0686, 59.3293],
                "context": [
                    {"id": "place.1", "text": "Stockholm"},
                    {"id": "country.1", "short_code": "SE", "text": "Sweden"},
                ],
            }],
        },
    )

    # Past trip (completed because end_date < today).
    t1 = Trip(owner_id=owner.id, name="Past trip",
              start_date=date(2024, 6, 1), end_date=date(2024, 6, 10))
    # Planning trip in the future (should be excluded).
    t2 = Trip(owner_id=owner.id, name="Future trip",
              start_date=date(2099, 1, 1), end_date=date(2099, 1, 10))
    db.session.add_all([t1, t2])
    db.session.commit()
    db.session.add_all([
        Booking(trip_id=t1.id, type="hotel", title="X", location="Hotel A"),
        Booking(trip_id=t2.id, type="hotel", title="Y", location="Hotel B"),
    ])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.get("/map/data.geojson")
    assert resp.status_code == 200
    payload = json.loads(resp.data)
    titles = [f["properties"]["title"] for f in payload["features"]]
    assert "X" in titles
    assert "Y" not in titles  # future trip excluded


# ───────────────  Yearbook Task 3: Star toggle route  ─────────────────


def _make_starrable_item(trip_id: int) -> ItineraryItem:
    item = ItineraryItem(
        trip_id=trip_id,
        day_date=date(2026, 6, 2),
        title="Vasa Museum",
    )
    db.session.add(item)
    db.session.commit()
    return item


def test_star_toggle_editor_flips_false_to_true(app, trip, editor):
    item = _make_starrable_item(trip.id)
    assert item.starred is False

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    resp = client.post(f"/trips/{trip.id}/items/{item.id}/star")
    assert resp.status_code == 200
    assert resp.get_json() == {"starred": True}
    db.session.refresh(item)
    assert item.starred is True


def test_star_toggle_editor_flips_true_to_false(app, trip, editor):
    item = _make_starrable_item(trip.id)
    item.starred = True
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    resp = client.post(f"/trips/{trip.id}/items/{item.id}/star")
    assert resp.status_code == 200
    assert resp.get_json() == {"starred": False}
    db.session.refresh(item)
    assert item.starred is False


def test_star_toggle_owner_allowed(app, trip, owner):
    item = _make_starrable_item(trip.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.post(f"/trips/{trip.id}/items/{item.id}/star")
    assert resp.status_code == 200
    db.session.refresh(item)
    assert item.starred is True


def test_star_toggle_viewer_forbidden(app, trip, viewer):
    item = _make_starrable_item(trip.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(viewer.id)

    resp = client.post(f"/trips/{trip.id}/items/{item.id}/star")
    # Project convention: insufficient role returns 404 so the trip's
    # existence can't be probed by guess. Accept 403 too in case a
    # later refactor distinguishes the cases.
    assert resp.status_code in (403, 404)
    db.session.refresh(item)
    assert item.starred is False  # unchanged


def test_star_toggle_non_collaborator_404(app, trip):
    item = _make_starrable_item(trip.id)
    stranger = User(google_id="g99", email="stranger@e.com", name="Stranger")
    db.session.add(stranger)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(stranger.id)

    resp = client.post(f"/trips/{trip.id}/items/{item.id}/star")
    assert resp.status_code == 404


def test_star_toggle_item_belongs_to_different_trip_404(app, owner, trip, editor):
    # Item on a second trip — but editor only has access to the first.
    other_trip = Trip(owner_id=owner.id, name="Other",
                     start_date=date(2026, 7, 1), end_date=date(2026, 7, 5))
    db.session.add(other_trip)
    db.session.commit()
    other_item = _make_starrable_item(other_trip.id)

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    # Editor has access to `trip`, but we POST with other_item.id in the
    # path — the trip_id/item_id mismatch must 404.
    resp = client.post(f"/trips/{trip.id}/items/{other_item.id}/star")
    assert resp.status_code == 404


def test_star_toggle_unknown_item_404(app, trip, editor):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(editor.id)

    resp = client.post(f"/trips/{trip.id}/items/999999/star")
    assert resp.status_code == 404


# ───────────────  Yearbook Task 5: page route + skeleton  ─────────────


from datetime import timedelta as _td


def _make_trip(owner_id: int, *, start_offset: int, end_offset: int, **kw):
    """Create a Trip whose dates land in a chosen state relative to today.

    start_offset / end_offset are days from today. So
    (-30, -20) → completed, (-1, +5) → in_progress, (+30, +35) → planning.
    """
    today = date.today()
    t = Trip(
        owner_id=owner_id,
        name=kw.get("name", "Test trip"),
        start_date=today + _td(days=start_offset),
        end_date=today + _td(days=end_offset),
        notes=kw.get("notes"),
    )
    db.session.add(t)
    db.session.commit()
    return t


def test_yearbook_planning_returns_404(app, owner):
    t = _make_trip(owner.id, start_offset=30, end_offset=35)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 404


def test_yearbook_upcoming_returns_404(app, owner):
    # "Upcoming" maps to planning in derive_status — hidden either way.
    t = _make_trip(owner.id, start_offset=1, end_offset=5)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 404


def test_yearbook_in_progress_returns_200_with_preview_banner(app, owner):
    t = _make_trip(owner.id, start_offset=-1, end_offset=5)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "preview of your yearbook" in body


def test_yearbook_completed_returns_200_no_preview_banner(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-20)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "preview of your yearbook" not in body


def test_yearbook_viewer_allowed(app, owner, trip, viewer):
    # Bring the shared `trip` fixture into completed state.
    today = date.today()
    trip.start_date = today - _td(days=30)
    trip.end_date = today - _td(days=20)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(viewer.id)
    resp = client.get(f"/trips/{trip.id}/yearbook")
    assert resp.status_code == 200


def test_yearbook_non_collaborator_404(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-20)
    stranger = User(google_id="g99", email="stranger@e.com", name="Stranger")
    db.session.add(stranger)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(stranger.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 404


def test_yearbook_renders_stats_chips(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    db.session.add_all([
        Booking(trip_id=t.id, type="flight", title="UA101"),
        Booking(trip_id=t.id, type="hotel", title="Plaza"),
    ])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    # 6-day trip, 1 flight, 1 hotel — all three chips should appear.
    assert "6 days" in body
    assert "1 Flights" in body
    assert "1 Hotels" in body


def test_yearbook_renders_notes_when_present(app, owner):
    t = _make_trip(
        owner.id, start_offset=-30, end_offset=-20,
        notes="What a **trip**.",
    )
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    assert "yearbook-notes" in body
    assert "<strong>trip</strong>" in body  # markdown rendered


def test_yearbook_skips_notes_section_when_blank(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-20, notes=None)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    assert "yearbook-notes" not in body


# ───────────────  Yearbook Task 6: interactive map block  ─────────────


def test_yearbook_renders_map_block_when_pins_exist(app, owner, monkeypatch):
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    db.session.add(Booking(
        trip_id=t.id, type="hotel", title="Plaza",
        location="Plaza Hotel",
        geocoded_lat=59.33, geocoded_lng=18.07,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    assert 'id="yearbook-map"' in body
    # Map JS + CSS only load when there are pins.
    assert "mapbox-gl.css" in body


def test_yearbook_omits_map_block_when_no_pins(app, owner, monkeypatch):
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")
    # No bookings + no itinerary → no pins.
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    assert 'id="yearbook-map"' not in body
    # No need to pull mapbox-gl when there's nothing to map.
    assert "mapbox-gl.css" not in body


def test_yearbook_passes_geojson_to_template(app, owner, monkeypatch):
    monkeypatch.setattr("app.MAPBOX_TOKEN", "pk.test")
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    db.session.add(Booking(
        trip_id=t.id, type="hotel", title="Vasa Museum",
        location="Galärvarvsvägen 14",
        geocoded_lat=59.328, geocoded_lng=18.092,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    # The pins payload is rendered into the data-pins attribute.
    assert "data-pins=" in body
    assert "FeatureCollection" in body
    assert "Vasa Museum" in body


# ───────────────  Yearbook Task 7: highlights + all-days strip  ─────


def test_yearbook_highlights_section_with_zero_stars_shows_nudge(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=t.start_date, title="Walk", starred=False,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    assert "yearbook-highlights-nudge" in body
    assert "Star items on your itinerary" in body


def test_yearbook_highlights_section_with_stars_renders_day_groups(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    # Two starred items on different days.
    db.session.add_all([
        ItineraryItem(trip_id=t.id, day_date=t.start_date,
                      title="Vasa Museum", starred=True),
        ItineraryItem(trip_id=t.id, day_date=t.start_date + _td(days=2),
                      title="Skansen", starred=True),
        ItineraryItem(trip_id=t.id, day_date=t.start_date + _td(days=1),
                      title="Coffee", starred=False),
    ])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    # Both starred items should render, unstarred one should not appear
    # in a highlight card.
    assert body.count("yearbook-card") >= 2
    assert "Vasa Museum" in body
    assert "Skansen" in body
    # Day headers for days 1 and 3 (not day 2 — no starred on day 2).
    assert "Day 1 ·" in body
    assert "Day 3 ·" in body
    assert "Day 2 ·" not in body or body.find("Day 2 ·") > body.find("All days at a glance")


def test_yearbook_all_days_strip_renders_every_day_in_range(app, owner):
    t = _make_trip(owner.id, start_offset=-12, end_offset=-5)  # 8-day trip
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    # All-days strip rows — Day 1 through Day 8 each have their own row.
    for n in range(1, 9):
        assert f"Day {n} ·" in body


def test_yearbook_all_days_empty_day_renders_empty_chip_row(app, owner):
    t = _make_trip(owner.id, start_offset=-12, end_offset=-10)  # 3-day trip
    # Item on day 2 only.
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=t.start_date + _td(days=1), title="Brunch",
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    body = resp.get_data(as_text=True)
    # The em-dash placeholder appears on the two empty days.
    assert body.count("yearbook-day-row__empty") == 2
    assert "Brunch" in body


def test_yearbook_tile_subtitle_planning_says_after_trip(app, owner):
    t = _make_trip(owner.id, start_offset=30, end_offset=35)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}")
    body = resp.get_data(as_text=True)
    assert "After the trip" in body


def test_yearbook_tile_subtitle_in_progress_says_preview(app, owner):
    t = _make_trip(owner.id, start_offset=-1, end_offset=5)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}")
    body = resp.get_data(as_text=True)
    assert "Preview while in progress" in body


def test_yearbook_tile_subtitle_completed_shows_starred_count(app, owner):
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    db.session.add_all([
        ItineraryItem(trip_id=t.id, day_date=t.start_date,
                      title="A", starred=True),
        ItineraryItem(trip_id=t.id, day_date=t.start_date,
                      title="B", starred=True),
        ItineraryItem(trip_id=t.id, day_date=t.start_date,
                      title="C", starred=False),
    ])
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}")
    body = resp.get_data(as_text=True)
    assert "2 highlights" in body


# ───────────────  Yearbook Task 8: share + visibility routes  ─────────


def _completed_trip(owner_id: int) -> Trip:
    return _make_trip(owner_id, start_offset=-30, end_offset=-25)


def test_share_enable_creates_token(app, owner):
    t = _completed_trip(owner.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.post(f"/trips/{t.id}/yearbook/share",
                       json={"action": "enable"})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["token"] is not None
    assert len(payload["token"]) >= 20  # token_urlsafe(24) -> ~32 chars
    assert payload["url"] and payload["token"] in payload["url"]
    db.session.refresh(t)
    assert t.yearbook_share_token == payload["token"]


def test_share_enable_again_is_idempotent(app, owner):
    t = _completed_trip(owner.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    r1 = client.post(f"/trips/{t.id}/yearbook/share",
                     json={"action": "enable"})
    r2 = client.post(f"/trips/{t.id}/yearbook/share",
                     json={"action": "enable"})
    assert r1.get_json()["token"] == r2.get_json()["token"]


def test_share_rotate_replaces_token(app, owner):
    t = _completed_trip(owner.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    r1 = client.post(f"/trips/{t.id}/yearbook/share",
                     json={"action": "enable"})
    r2 = client.post(f"/trips/{t.id}/yearbook/share",
                     json={"action": "rotate"})
    assert r1.get_json()["token"] != r2.get_json()["token"]


def test_share_disable_clears_token(app, owner):
    t = _completed_trip(owner.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    client.post(f"/trips/{t.id}/yearbook/share", json={"action": "enable"})
    resp = client.post(f"/trips/{t.id}/yearbook/share",
                       json={"action": "disable"})
    assert resp.get_json()["token"] is None
    assert resp.get_json()["url"] is None
    db.session.refresh(t)
    assert t.yearbook_share_token is None


def test_share_on_in_progress_trip_returns_400(app, owner):
    t = _make_trip(owner.id, start_offset=-1, end_offset=5)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(f"/trips/{t.id}/yearbook/share",
                       json={"action": "enable"})
    assert resp.status_code == 400
    assert "after trip completes" in resp.get_json()["error"]


def test_share_on_planning_trip_returns_400(app, owner):
    t = _make_trip(owner.id, start_offset=30, end_offset=35)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(f"/trips/{t.id}/yearbook/share",
                       json={"action": "enable"})
    assert resp.status_code == 400


def test_share_viewer_forbidden(app, owner, trip, viewer):
    # Move shared trip to completed state.
    today = date.today()
    trip.start_date = today - _td(days=30)
    trip.end_date = today - _td(days=25)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(viewer.id)
    resp = client.post(f"/trips/{trip.id}/yearbook/share",
                       json={"action": "enable"})
    assert resp.status_code in (403, 404)


def test_visibility_toggle_persists(app, owner):
    t = _completed_trip(owner.id)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    resp = client.post(f"/trips/{t.id}/yearbook/visibility",
                       json={"show_notes": True, "show_spend": False})
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload == {"show_notes": True, "show_spend": False}
    db.session.refresh(t)
    assert t.yearbook_public_show_notes is True
    assert t.yearbook_public_show_spend is False


def test_visibility_viewer_forbidden(app, owner, trip, viewer):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(viewer.id)
    resp = client.post(f"/trips/{trip.id}/yearbook/visibility",
                       json={"show_notes": True, "show_spend": True})
    assert resp.status_code in (403, 404)


# ───────────────  Yearbook Task 9: public route + share UI  ──────────


def _completed_shared_trip(owner_id: int, **kw) -> Trip:
    """Completed trip with a public share token pre-set."""
    t = _make_trip(owner_id, start_offset=-30, end_offset=-25, **kw)
    t.yearbook_share_token = "abc123token"
    db.session.commit()
    return t


def test_public_yearbook_valid_token_renders(app, owner):
    t = _completed_shared_trip(owner.id, name="Scandinavia '24")
    client = app.test_client()
    # No login on purpose — public route.
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Scandinavia &#39;24" in body or "Scandinavia '24" in body
    # No navbar on the public layout.
    assert "vp-navbar" not in body
    # Public layout has its own footer marker.
    assert "Powered by" in body


def test_public_yearbook_unknown_token_404(app):
    client = app.test_client()
    resp = client.get("/yearbook/this-token-does-not-exist")
    assert resp.status_code == 404


def test_public_yearbook_token_on_in_progress_trip_404(app, owner):
    t = _make_trip(owner.id, start_offset=-1, end_offset=5)
    t.yearbook_share_token = "still-running"
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    assert resp.status_code == 404


def test_public_yearbook_response_has_noindex_header(app, owner):
    t = _completed_shared_trip(owner.id)
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"


def test_public_yearbook_strips_confirmation_numbers(app, owner):
    t = _completed_shared_trip(owner.id)
    db.session.add(Booking(
        trip_id=t.id, type="hotel", title="Plaza",
        confirmation_number="TOPSECRET-123",
    ))
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    assert "TOPSECRET-123" not in body


def test_public_yearbook_strips_booking_costs(app, owner):
    t = _completed_shared_trip(owner.id)
    db.session.add(Booking(
        trip_id=t.id, type="hotel", title="Plaza", cost=4999.99,
    ))
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    assert "4999.99" not in body
    # Spend chip aggregates costs — gated by show_spend toggle (default True).
    # We separately assert nothing reveals the raw per-booking number itself.


def test_public_yearbook_hides_notes_when_toggle_off(app, owner):
    t = _completed_shared_trip(
        owner.id, notes="A private memory about **the trip**.",
    )
    t.yearbook_public_show_notes = False
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    assert "private memory" not in body
    assert "yearbook-notes" not in body


def test_public_yearbook_includes_notes_when_toggle_on(app, owner):
    t = _completed_shared_trip(
        owner.id, notes="A shareable memory.",
    )
    t.yearbook_public_show_notes = True
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    assert "shareable memory" in body


def test_public_yearbook_hides_spend_when_toggle_off(app, owner):
    t = _completed_shared_trip(owner.id)
    db.session.add(Booking(
        trip_id=t.id, type="hotel", title="Plaza", cost=500.0, currency="USD",
    ))
    t.yearbook_public_show_spend = False
    db.session.commit()
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    # Spend section markup gone.
    assert "yearbook-spend" not in body


def test_public_yearbook_uses_base_public_template(app, owner):
    t = _completed_shared_trip(owner.id)
    client = app.test_client()
    resp = client.get(f"/yearbook/{t.yearbook_share_token}")
    body = resp.get_data(as_text=True)
    assert 'class="vp-public"' in body
    assert "noindex" in body


def test_auth_yearbook_still_renders_after_partial_extraction(app, owner):
    """Sanity: the auth route still works end-to-end after Task 9
    moved the body into a shared partial."""
    t = _make_trip(owner.id, start_offset=-30, end_offset=-25)
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get(f"/trips/{t.id}/yearbook")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "yearbook-hero" in body
    assert "All days at a glance" in body


def test_dashboard_renders_on_this_day_section_when_past_trip_matches(app, owner):
    """Dashboard renders the ✨ On this day section when a past trip in
    a prior calendar year overlaps today's (month, day).

    Builds such a trip and asserts that the section header markup and
    the trip's name both appear in the response body.
    """
    today = date.today()
    prior_year = today.year - 1
    # Build a range spanning today's (month, day) in the prior year.
    # Pad +/- a few days, clamped to the actual month length so we
    # don't run off month boundaries (e.g. Dec 31 or Feb 29).
    last_day_of_month = calendar.monthrange(prior_year, today.month)[1]
    start_day = max(1, today.day - 2)
    end_day = min(last_day_of_month, today.day + 2)
    start_date = date(prior_year, today.month, start_day)
    end_date = date(prior_year, today.month, end_day)

    t = Trip(
        owner_id=owner.id,
        name="On This Day Trip",
        start_date=start_date,
        end_date=end_date,
    )
    db.session.add(t)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get("/trips")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "On This Day Trip" in body
    assert "On this day" in body


def test_settings_get_renders_form_with_current_unit(app, owner):
    """/settings GET renders the form with the current user's unit
    pre-selected."""
    owner.weather_units = "imperial"
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Imperial radio should be the one with `checked`.
    assert 'value="imperial"' in body
    assert "Fahrenheit" in body


def test_settings_post_updates_user_weather_units(app, owner):
    """POST with a valid unit (and a valid home currency) saves to the
    User row and redirects."""
    assert owner.weather_units == "metric"

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(
        "/settings",
        data={"weather_units": "imperial", "home_currency": "USD"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.session.refresh(owner)
    assert owner.weather_units == "imperial"


def test_settings_post_rejects_invalid_unit(app, owner):
    """An unknown unit doesn't change the User row and re-renders the
    form with an error flash."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(
        "/settings",
        data={"weather_units": "kelvin", "home_currency": "USD"},
    )
    assert resp.status_code == 200
    db.session.refresh(owner)
    assert owner.weather_units == "metric"


# ─── B3: home_currency on /settings ─────────────────────────────


def test_settings_get_renders_home_currency_field(app, owner):
    """GET shows the home_currency select with the user's current
    code pre-selected."""
    owner.home_currency = "EUR"
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get("/settings")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'name="home_currency"' in body
    # The EUR option should be the one with `selected`.
    assert 'value="EUR"\n                selected' in body or \
           'value="EUR" selected' in body or \
           'value="EUR"\nselected' in body


def test_settings_post_saves_both_units_and_home_currency(app, owner):
    """A valid POST saves both fields atomically and redirects."""
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(
        "/settings",
        data={"weather_units": "imperial", "home_currency": "GBP"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    db.session.refresh(owner)
    assert owner.weather_units == "imperial"
    assert owner.home_currency == "GBP"


def test_settings_post_rejects_invalid_home_currency(app, owner):
    """An unknown currency doesn't change EITHER field — atomic save."""
    owner.weather_units = "metric"
    owner.home_currency = "USD"
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(
        "/settings",
        data={"weather_units": "imperial", "home_currency": "XYZ"},
    )
    assert resp.status_code == 200
    db.session.refresh(owner)
    # Neither field changed because the currency was invalid.
    assert owner.weather_units == "metric"
    assert owner.home_currency == "USD"


def test_settings_post_rejects_invalid_units_even_when_currency_valid(app, owner):
    """Atomic — bad units + good currency → neither field saves."""
    owner.weather_units = "metric"
    owner.home_currency = "USD"
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.post(
        "/settings",
        data={"weather_units": "kelvin", "home_currency": "EUR"},
    )
    assert resp.status_code == 200
    db.session.refresh(owner)
    assert owner.weather_units == "metric"
    assert owner.home_currency == "USD"


def test_lifetime_map_renders_stats_strip_for_user_with_completed_trip(
    app, owner,
):
    """/map renders the lifetime stats strip + trips-per-year chart
    when the user has at least one completed trip."""
    today = date.today()
    start = date(today.year - 1, 6, 1)
    end = date(today.year - 1, 6, 8)
    t = Trip(
        owner_id=owner.id,
        name="Lifetime Stats Trip",
        start_date=start,
        end_date=end,
    )
    db.session.add(t)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)
    resp = client.get("/map")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<strong>1</strong> trips" in body
    assert "Trips per year" in body


# ─────────────────────────  Weather chips (B1)  ────────────────────────


def _ok_open_meteo_payload(d):
    """Minimal Open-Meteo response covering one day for chip tests."""
    iso = d.isoformat()
    return {
        "daily": {
            "time": [iso],
            "weather_code": [2],
            "temperature_2m_max": [22.0],
            "temperature_2m_min": [14.0],
            "precipitation_probability_max": [20],
            "relative_humidity_2m_mean": [64],
        },
        "hourly": {
            "time": [f"{iso}T{h:02d}:00" for h in range(24)],
            "temperature_2m": [float(h + 10) for h in range(24)],
            "weather_code": [0] * 24,
        },
    }


def test_itinerary_renders_weather_chip_for_today(app, owner):
    """The day-header weather chip renders when today is in the
    forecast window and the day has a geocoded item."""
    today = date.today()
    t = Trip(
        owner_id=owner.id, name="Weather chip trip",
        start_date=today, end_date=today + (date(2026, 6, 14) - date(2026, 6, 7)),
    )
    db.session.add(t)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=today, title="Walking tour",
        geocoded_lat=48.85, geocoded_lng=2.35,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    with patch("src.weather.fetch_forecast") as mock_fetch:
        mock_fetch.return_value = _ok_open_meteo_payload(today)
        resp = client.get(f"/trips/{t.id}/itinerary")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-weather-chip" in body
    assert "⛅" in body  # WMO 2 = partly cloudy
    assert "22°" in body


def test_itinerary_skips_chip_for_day_beyond_window(app, owner):
    """A trip 30 days out: no chips render anywhere."""
    today = date.today()
    far_start = date(today.year + 1, 1, 1)
    t = Trip(
        owner_id=owner.id, name="Future trip",
        start_date=far_start,
        end_date=date(far_start.year, far_start.month, far_start.day + 3),
    )
    db.session.add(t)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=far_start, title="Future thing",
        geocoded_lat=48.85, geocoded_lng=2.35,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    with patch("src.weather.fetch_forecast") as mock_fetch:
        resp = client.get(f"/trips/{t.id}/itinerary")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-weather-chip" not in body
    assert mock_fetch.called is False  # never called for out-of-window days


def test_weather_failure_does_not_break_itinerary_page(app, owner):
    """When the upstream API fails, the page still renders 200 with
    no chip markup."""
    today = date.today()
    t = Trip(
        owner_id=owner.id, name="Trip",
        start_date=today, end_date=today,
    )
    db.session.add(t)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=today, title="Thing",
        geocoded_lat=48.85, geocoded_lng=2.35,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    with patch("src.weather.fetch_forecast") as mock_fetch:
        mock_fetch.return_value = None
        resp = client.get(f"/trips/{t.id}/itinerary")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-weather-chip" not in body


def test_trip_overview_today_section_renders_hero_chip(app, owner):
    """The hero weather chip renders at the top of Today when the
    trip is in progress and the day has a geocoded item."""
    today = date.today()
    t = Trip(
        owner_id=owner.id, name="In-progress trip",
        start_date=today, end_date=today,
    )
    db.session.add(t)
    db.session.commit()
    db.session.add(ItineraryItem(
        trip_id=t.id, day_date=today, title="Walking tour",
        geocoded_lat=48.85, geocoded_lng=2.35,
    ))
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = str(owner.id)

    with patch("src.weather.fetch_forecast") as mock_fetch:
        mock_fetch.return_value = _ok_open_meteo_payload(today)
        resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-weather-hero" in body
    assert "⛅" in body
    assert "22°" in body


# ─── _ensure_trip_timezone helper (B2 T4) ───────────────────────────
# Patch at app.iana_from_coords (not src.destination_clock.iana_from_coords) because
# app.py binds the name into its own namespace at import time.
def test_ensure_trip_timezone_returns_existing_when_set(app, trip):
    """Already-set timezone is returned untouched and iana_from_coords
    is never called."""
    trip.timezone_iana = "Europe/Paris"
    db.session.commit()

    with patch("app.iana_from_coords") as mock_iana:
        result = _ensure_trip_timezone(trip)

    assert result == "Europe/Paris"
    assert mock_iana.call_count == 0


def test_ensure_trip_timezone_returns_none_when_no_bookings(app, trip):
    """No bookings at all → returns None and column stays NULL."""
    assert trip.timezone_iana is None

    with patch("app.iana_from_coords") as mock_iana:
        result = _ensure_trip_timezone(trip)

    assert result is None
    assert mock_iana.call_count == 0
    db.session.refresh(trip)
    assert trip.timezone_iana is None


def test_ensure_trip_timezone_returns_none_when_no_geocoded_bookings(app, trip):
    """Bookings exist but none have coords → returns None, no DB write."""
    db.session.add(Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        geocoded_lat=None, geocoded_lng=None,
    ))
    db.session.add(Booking(
        trip_id=trip.id, type="hotel", title="Hilton",
        start_datetime=datetime(2026, 6, 2, 15, 0),
        geocoded_lat=None, geocoded_lng=None,
    ))
    db.session.commit()

    with patch("app.iana_from_coords") as mock_iana:
        result = _ensure_trip_timezone(trip)

    assert result is None
    assert mock_iana.call_count == 0
    db.session.refresh(trip)
    assert trip.timezone_iana is None


def test_ensure_trip_timezone_derives_and_persists_from_first_booking(app, trip):
    """Earlier-start_datetime geocoded booking wins; derived value is
    written to the DB."""
    early = Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        geocoded_lat=48.85, geocoded_lng=2.35,  # Paris-ish
    )
    later = Booking(
        trip_id=trip.id, type="hotel", title="Hilton",
        start_datetime=datetime(2026, 6, 3, 15, 0),
        geocoded_lat=51.5, geocoded_lng=-0.12,  # London-ish
    )
    db.session.add_all([early, later])
    db.session.commit()

    with patch("app.iana_from_coords") as mock_iana:
        mock_iana.return_value = "Europe/Paris"
        result = _ensure_trip_timezone(trip)

    assert result == "Europe/Paris"
    mock_iana.assert_called_once_with(48.85, 2.35)
    refreshed = db.session.get(Trip, trip.id)
    assert refreshed.timezone_iana == "Europe/Paris"


def test_ensure_trip_timezone_handles_iana_lookup_returning_none(app, trip):
    """If iana_from_coords returns None (ocean / library missing), the
    helper returns None and leaves the column NULL — no exception."""
    db.session.add(Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        geocoded_lat=0.0, geocoded_lng=0.0,
    ))
    db.session.commit()

    with patch("app.iana_from_coords") as mock_iana:
        mock_iana.return_value = None
        result = _ensure_trip_timezone(trip)

    assert result is None
    db.session.refresh(trip)
    assert trip.timezone_iana is None


# ─── Trip form: timezone_iana field (B2 T5) ────────────────────────
def test_trip_new_saves_timezone_iana(app, owner):
    """POSTing a valid IANA name on /trips/new persists it on Trip."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/trips/new",
            data={
                "name": "Tokyo trip",
                "start_date": "2026-09-01",
                "end_date": "2026-09-10",
                "primary_currency": "USD",
                "timezone_iana": "Asia/Tokyo",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    saved = Trip.query.filter_by(name="Tokyo trip").one()
    assert saved.timezone_iana == "Asia/Tokyo"


def test_trip_new_rejects_invalid_timezone(app, owner):
    """An unknown IANA name re-renders the form with the error message
    and creates no trip."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/trips/new",
            data={
                "name": "Bad tz trip",
                "start_date": "2026-09-01",
                "end_date": "2026-09-10",
                "primary_currency": "USD",
                "timezone_iana": "Europe/Pariss",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Not a recognized time zone." in body
    assert Trip.query.filter_by(name="Bad tz trip").count() == 0


def test_trip_edit_saves_timezone_iana(app, trip, owner):
    """POST /trips/<id>/edit with a valid IANA name persists it."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/edit",
            data={
                "name": trip.name,
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
                "primary_currency": "USD",
                "timezone_iana": "Asia/Tokyo",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(trip)
    assert trip.timezone_iana == "Asia/Tokyo"


def test_trip_edit_clears_timezone_when_empty_string_posted(app, trip, owner):
    """Submitting an empty timezone_iana clears the column to NULL."""
    trip.timezone_iana = "Asia/Tokyo"
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/trips/{trip.id}/edit",
            data={
                "name": trip.name,
                "start_date": trip.start_date.isoformat(),
                "end_date": trip.end_date.isoformat(),
                "primary_currency": "USD",
                "timezone_iana": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    db.session.refresh(trip)
    assert trip.timezone_iana is None


def test_trip_edit_get_renders_autodetect_preview_when_tz_null(app, trip, owner):
    """GET /trips/<id>/edit with a geocoded booking and NULL timezone_iana
    shows the auto-detected preview hint. We patch _ensure_trip_timezone
    so the column stays NULL (otherwise the form value gates the preview
    off), and patch iana_from_coords so the route's own preview computation
    returns a deterministic name."""
    db.session.add(Booking(
        trip_id=trip.id, type="flight", title="UA101",
        start_datetime=datetime(2026, 6, 1, 10, 0),
        geocoded_lat=48.85, geocoded_lng=2.35,  # Paris-ish
    ))
    db.session.commit()
    assert trip.timezone_iana is None

    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app._ensure_trip_timezone", return_value=None), \
             patch("app.iana_from_coords", return_value="Europe/Paris"):
            resp = client.get(f"/trips/{trip.id}/edit")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Auto-detected from your first booking" in body
    assert "Europe/Paris" in body


# ─── Trip overview: destination clock hero panel (B2 T6) ───────────
def test_trip_overview_renders_clock_panel_when_tz_set(app, owner):
    """A planning trip with timezone_iana set shows the clock panel in
    the hero, with a server-rendered initial time (not the '—' fallback)."""
    t = Trip(
        owner_id=owner.id, name="Paris trip",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 10),
        timezone_iana="Europe/Paris",
    )
    db.session.add(t)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "data-vp-clock" in body
    assert 'data-clock-iana="Europe/Paris"' in body

    marker = '<span class="vp-destclock__time" data-clock-time>'
    assert marker in body
    after = body.split(marker, 1)[1]
    rendered_time = after.split("</span>", 1)[0]
    assert rendered_time.strip() != "—"


def test_trip_overview_skips_clock_panel_when_tz_null(app, owner):
    """A planning trip with no timezone and no geocoded bookings shows
    no clock panel in the hero."""
    t = Trip(
        owner_id=owner.id, name="Mystery trip",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 10),
        timezone_iana=None,
    )
    db.session.add(t)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app._ensure_trip_timezone", return_value=None):
            resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "data-vp-clock" not in body


def test_trip_overview_auto_derives_timezone_on_first_visit(app, owner):
    """First GET of a planning trip with NULL timezone and a geocoded
    booking auto-derives + persists the IANA name, then renders the
    clock panel with that name."""
    t = Trip(
        owner_id=owner.id, name="Tokyo trip",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 10),
        timezone_iana=None,
    )
    db.session.add(t)
    db.session.commit()
    db.session.add(Booking(
        trip_id=t.id, type="flight", title="JL5",
        start_datetime=datetime(2026, 8, 1, 10, 0),
        geocoded_lat=35.68, geocoded_lng=139.76,
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.iana_from_coords", return_value="Asia/Tokyo"):
            resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    refreshed = db.session.get(Trip, t.id)
    assert refreshed.timezone_iana == "Asia/Tokyo"
    body = resp.get_data(as_text=True)
    assert 'data-clock-iana="Asia/Tokyo"' in body


# ─── Today-section destination clock chip (B2 T7) ──────────────────
def test_today_section_renders_clock_chip_when_tz_set(app, owner):
    """An in-progress trip with timezone_iana set shows the destination
    clock chip inside the Today section."""
    today = date.today()
    t = Trip(
        owner_id=owner.id, name="Tokyo trip",
        start_date=today - _td(days=1), end_date=today + _td(days=2),
        timezone_iana="Asia/Tokyo",
    )
    db.session.add(t)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-destclock--chip" in body
    assert 'data-clock-iana="Asia/Tokyo"' in body


def test_today_section_skips_clock_chip_when_tz_null(app, owner):
    """An in-progress trip with no timezone and no geocoded bookings
    shows no destination clock chip in the Today section."""
    today = date.today()
    t = Trip(
        owner_id=owner.id, name="Mystery trip",
        start_date=today - _td(days=1), end_date=today + _td(days=2),
        timezone_iana=None,
    )
    db.session.add(t)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app._ensure_trip_timezone", return_value=None):
            resp = client.get(f"/trips/{t.id}")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "vp-destclock--chip" not in body


# ─── B3: trip_budget — show_as toggle + conversion ──────────────


def _budget_trip_with_mixed_currencies(owner):
    """Build a trip with three bookings in three currencies for the
    B3 conversion tests."""
    t = Trip(
        owner_id=owner.id, name="Budget trip",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        primary_currency="USD",
    )
    db.session.add(t)
    db.session.commit()
    db.session.add_all([
        Booking(trip_id=t.id, type="flight", title="UA001",
                cost=1000.0, currency="USD"),
        Booking(trip_id=t.id, type="hotel", title="Hotel Lutetia",
                cost=500.0, currency="EUR"),
        Booking(trip_id=t.id, type="restaurant", title="Lunch",
                cost=100.0, currency="GBP"),
    ])
    db.session.commit()
    return t


def test_budget_default_show_as_uses_home_currency(app, owner):
    """No querystring → convert to user's home currency."""
    owner.home_currency = "USD"
    db.session.commit()
    t = _budget_trip_with_mixed_currencies(owner)

    fake_rates = {"EUR": 1.10, "GBP": 1.27, "USD": 1.0}
    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.get_rates_for", return_value=fake_rates):
            resp = client.get(f"/trips/{t.id}/budget")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Expect: 1000 USD + 500/1.10 USD + 100/1.27 USD ≈ 1533.13 USD
    # Disclaimer line present:
    assert "via exchangerate.host" in body
    # USD option in the dropdown should be selected:
    assert 'value="USD"' in body and "selected" in body
    # No multi-currency split (no EUR/GBP symbols in the grand total):
    assert "€" not in body or "vp-destclock" in body  # destclock allowed
    # The unconverted footnote should NOT appear:
    assert "not converted" not in body


def test_budget_show_as_mixed_disables_conversion(app, owner):
    """?show_as=MIXED → original multi-currency rollup, no disclaimer."""
    t = _budget_trip_with_mixed_currencies(owner)

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{t.id}/budget?show_as=MIXED")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "via exchangerate.host" not in body
    assert "Showing original currencies." in body
    # Original currencies visible in the grand total area:
    assert "€500.00" in body
    assert "£100.00" in body
    assert "$1,000.00" in body


def test_budget_show_as_specific_currency_overrides_home(app, owner):
    """?show_as=EUR overrides user's home (USD)."""
    owner.home_currency = "USD"
    db.session.commit()
    t = _budget_trip_with_mixed_currencies(owner)

    fake_rates = {"EUR": 1.10, "GBP": 1.27, "USD": 1.0}
    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.get_rates_for", return_value=fake_rates):
            resp = client.get(f"/trips/{t.id}/budget?show_as=EUR")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "via exchangerate.host" in body
    # Grand total should be in EUR (€ symbol present in the formatted total):
    assert "€" in body


def test_budget_invalid_show_as_falls_back_to_home(app, owner):
    """?show_as=ZZZ is unknown → silently use home_currency."""
    owner.home_currency = "USD"
    db.session.commit()
    t = _budget_trip_with_mixed_currencies(owner)

    fake_rates = {"EUR": 1.10, "GBP": 1.27, "USD": 1.0}
    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.get_rates_for", return_value=fake_rates):
            resp = client.get(f"/trips/{t.id}/budget?show_as=ZZZ")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # No error, no crash — conversion happened with USD as target.
    assert "via exchangerate.host" in body
    # Mixed option should NOT be the selected one.
    assert '<option value="MIXED"\n                    selected' not in body


def test_budget_unconverted_codes_listed_when_rate_missing(app, owner):
    """A trip currency without a fetched rate passes through with a
    footnote naming the code."""
    owner.home_currency = "USD"
    db.session.commit()
    t = _budget_trip_with_mixed_currencies(owner)

    # Only EUR rate available — GBP will pass through unconverted.
    fake_rates = {"EUR": 1.10, "USD": 1.0}
    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.get_rates_for", return_value=fake_rates):
            resp = client.get(f"/trips/{t.id}/budget")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "GBP not converted" in body
    # GBP amount still visible somewhere in the totals:
    assert "£100.00" in body


def test_budget_api_down_falls_back_to_mixed_with_note(app, owner):
    """get_rates_for returns empty → can't compute cross-rates →
    show the warning line and render mixed totals."""
    owner.home_currency = "USD"
    db.session.commit()
    t = _budget_trip_with_mixed_currencies(owner)

    with flask_app.test_client() as client:
        _login(client, owner)
        with patch("app.get_rates_for", return_value={}):
            resp = client.get(f"/trips/{t.id}/budget")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Jinja autoescapes the apostrophe in "Couldn't" to &#39; — assert
    # against the unambiguous portion of the message instead.
    assert "fetch rates" in body
    assert "showing per-currency totals" in body
    # No conversion disclaimer when conversion failed:
    assert "via exchangerate.host" not in body
    # Original currencies still visible in the totals:
    assert "€500.00" in body
    assert "£100.00" in body


def test_budget_no_categories_skips_toggle_and_disclaimer(app, owner):
    """A trip with zero bookings → empty-state nudge, no toggle, no
    disclaimer."""
    t = Trip(
        owner_id=owner.id, name="Empty trip",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 7),
        primary_currency="USD",
    )
    db.session.add(t)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{t.id}/budget")

    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "via exchangerate.host" not in body
    assert 'name="show_as"' not in body
    assert "No costs to show yet" in body


# ──────────────────────────────────────────────────────────────────
# Trip-prep models — TripPrepItem + TripPrepLink (Task 2)
# ──────────────────────────────────────────────────────────────────


def test_trip_prep_item_persists_round_trip(app, owner, trip):
    """All TripPrepItem fields round-trip through a save + fetch."""
    created = datetime(2026, 6, 14, 9, 30, 0)
    item = TripPrepItem(
        owner_id=owner.id,
        trip_id=trip.id,
        title="Renew passport",
        notes="Check expiry vs return date.",
        category="documents",
        link_url="https://travel.state.gov/renew",
        link_image_url="https://travel.state.gov/og.png",
        done=False,
        due_offset_days=60,
        created_at=created,
        sort_order=3,
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    db.session.expire_all()
    fetched = db.session.get(TripPrepItem, item_id)
    assert fetched is not None
    assert fetched.owner_id == owner.id
    assert fetched.trip_id == trip.id
    assert fetched.title == "Renew passport"
    assert fetched.notes == "Check expiry vs return date."
    assert fetched.category == "documents"
    assert fetched.link_url == "https://travel.state.gov/renew"
    assert fetched.link_image_url == "https://travel.state.gov/og.png"
    assert fetched.done is False
    assert fetched.done_at is None
    assert fetched.due_offset_days == 60
    assert fetched.packing_prompt_dismissed_at is None
    assert fetched.created_at == created
    assert fetched.sort_order == 3


def test_trip_prep_link_unique_constraint(app, owner, trip):
    """Two links with the same (item_id, trip_id) raise IntegrityError."""
    from sqlalchemy.exc import IntegrityError

    item = TripPrepItem(owner_id=owner.id, title="Buy adapter", category="packing")
    db.session.add(item)
    db.session.commit()

    db.session.add(TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id))
    db.session.commit()

    db.session.add(TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_trip_prep_item_cascade_deletes_links(app, owner, trip):
    """Deleting a TripPrepItem cascades to its TripPrepLink rows."""
    item = TripPrepItem(owner_id=owner.id, title="Confirm hotel", category="other")
    db.session.add(item)
    db.session.commit()

    db.session.add(TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id))
    db.session.commit()
    assert TripPrepLink.query.filter_by(trip_prep_item_id=item.id).count() == 1

    db.session.delete(item)
    db.session.commit()

    assert db.session.get(TripPrepItem, item.id) is None
    assert TripPrepLink.query.filter_by(trip_id=trip.id).count() == 0


def test_ensure_prep_tables_is_idempotent(app):
    """_ensure_prep_tables creates missing tables, then is a no-op."""
    from sqlalchemy import inspect

    # The app fixture's db.create_all() already created both prep tables.
    # Drop them to exercise the create branch on the first call, then
    # confirm the second call is a safe no-op. Drop the link first
    # because it has an FK to trip_prep_item.
    TripPrepLink.__table__.drop(db.engine)
    TripPrepItem.__table__.drop(db.engine)
    tables_before = set(inspect(db.engine).get_table_names())
    assert "trip_prep_item" not in tables_before
    assert "trip_prep_link" not in tables_before

    _ensure_prep_tables()  # first call must create both tables

    tables_after_create = set(inspect(db.engine).get_table_names())
    assert "trip_prep_item" in tables_after_create
    assert "trip_prep_link" in tables_after_create

    _ensure_prep_tables()  # second call must be a safe no-op

    tables_after_noop = set(inspect(db.engine).get_table_names())
    assert "trip_prep_item" in tables_after_noop
    assert "trip_prep_link" in tables_after_noop


def test_trip_delete_cascades_prep_items_and_links_but_keeps_cross_trip_items(
    app, owner, trip,
):
    """Deleting a trip removes its per-trip prep items and link rows,
    but leaves cross-trip (user-level) prep items intact."""
    # Cross-trip item — lives at user level, should survive trip deletion.
    cross_trip_item = TripPrepItem(
        owner_id=owner.id, trip_id=None, title="Renew passport", category="documents",
    )
    # Per-trip item — pinned directly to the trip, should die with it.
    per_trip_item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id, title="Confirm hotel", category="other",
    )
    # Per-trip packing item — sanity check that the existing cascade
    # still works alongside the new ones.
    packing = PackingItem(trip_id=trip.id, name="Adapter", category="electronics")
    db.session.add_all([cross_trip_item, per_trip_item, packing])
    db.session.commit()

    # Link the cross-trip item to this trip — the link row should die
    # with the trip while the cross-trip item itself survives.
    link = TripPrepLink(trip_prep_item_id=cross_trip_item.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()

    cross_trip_item_id = cross_trip_item.id
    per_trip_item_id = per_trip_item.id
    link_id = link.id
    packing_id = packing.id
    trip_id = trip.id

    db.session.delete(trip)
    db.session.commit()

    assert db.session.get(Trip, trip_id) is None
    assert db.session.get(TripPrepItem, per_trip_item_id) is None
    assert db.session.get(TripPrepLink, link_id) is None
    assert db.session.get(PackingItem, packing_id) is None
    # The cross-trip item is at the user level — it must survive.
    surviving = db.session.get(TripPrepItem, cross_trip_item_id)
    assert surviving is not None
    assert surviving.trip_id is None


# ─── GET /prep — cross-trip prep list (Task 7) ──────────────────────
def test_prep_page_requires_login(app):
    """GET /prep without auth redirects to the login landing page."""
    with flask_app.test_client() as client:
        resp = client.get("/prep", follow_redirects=False)
    assert resp.status_code == 302


def test_prep_page_renders_for_owner(app, owner):
    """A signed-in user with one cross-trip item sees its title in the page."""
    db.session.add(TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Renew passport", category="admin",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/prep")
    assert resp.status_code == 200
    assert b"Renew passport" in resp.data


def test_prep_page_empty_state_when_no_items(app, owner):
    """A signed-in user with zero prep items sees the empty-state nudge."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/prep")
    assert resp.status_code == 200
    assert b"no prep to-dos yet" in resp.data


def test_prep_page_renders_items_grouped_by_category(app, owner):
    """Two items in different categories each appear with their category label."""
    db.session.add_all([
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="Buy travel adapter", category="buy"),
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="Research Lisbon neighborhoods", category="research"),
    ])
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/prep")
    assert resp.status_code == 200
    assert b"Buy travel adapter" in resp.data
    assert b"Research Lisbon neighborhoods" in resp.data
    # Each category's label should appear as a group heading.
    assert b"Buy" in resp.data
    assert b"Research" in resp.data


def test_prep_page_hides_per_trip_items(app, owner, trip):
    """Per-trip items (trip_id set) are NOT shown on the cross-trip /prep page."""
    db.session.add_all([
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="Cross-trip passport renewal", category="admin"),
        TripPrepItem(owner_id=owner.id, trip_id=trip.id,
                     title="Per-trip confirm hotel", category="admin"),
    ])
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/prep")
    assert resp.status_code == 200
    assert b"Cross-trip passport renewal" in resp.data
    assert b"Per-trip confirm hotel" not in resp.data


def test_prep_page_hides_other_users_items(app, owner):
    """User B does not see User A's cross-trip prep items on /prep."""
    other = User(google_id="g2", email="other@example.com", name="Other")
    db.session.add(other)
    db.session.commit()
    db.session.add_all([
        TripPrepItem(owner_id=other.id, trip_id=None,
                     title="OtherUserSecretRenewVisa", category="admin"),
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="OwnerOwnPrepItem", category="admin"),
    ])
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/prep")
    assert resp.status_code == 200
    assert b"OwnerOwnPrepItem" in resp.data
    assert b"OtherUserSecretRenewVisa" not in resp.data


# ─── POST /prep — create + paste-to-create flow (Task 8) ────────────
def test_prep_create_plain_text_title(app, owner):
    """Plain text in `input` becomes the item title; no URL fields set."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post("/prep", data={"input": "Renew passport"},
                           follow_redirects=False)
    assert resp.status_code == 302
    rows = TripPrepItem.query.filter_by(owner_id=owner.id).all()
    assert len(rows) == 1
    assert rows[0].title == "Renew passport"
    assert rows[0].link_url is None
    assert rows[0].link_image_url is None


def test_prep_create_with_url_calls_fetch_metadata(app, owner, monkeypatch):
    """A pasted URL triggers fetch_url_metadata; returned title + image
    are stored on the new item, link_url holds the original URL."""
    called: dict = {}

    def fake_fetch(url: str):
        called["url"] = url
        return {
            "title": "Best Hiking Boots 2026",
            "image_url": "https://example.com/boots.jpg",
            "source_url": url,
        }

    monkeypatch.setattr("app.fetch_url_metadata", fake_fetch)

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/prep",
            data={"input": "https://example.com/boots"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert called["url"] == "https://example.com/boots"
    row = TripPrepItem.query.filter_by(owner_id=owner.id).one()
    assert row.title == "Best Hiking Boots 2026"
    assert row.link_url == "https://example.com/boots"
    assert row.link_image_url == "https://example.com/boots.jpg"


def test_prep_create_url_failure_still_creates_item_with_url_as_title(
    app, owner, monkeypatch,
):
    """When fetch_url_metadata's fallback shape comes back (title=URL,
    image=None), we still create the item — title is the URL itself."""
    def fake_fetch(url: str):
        return {"title": url, "image_url": None, "source_url": url}

    monkeypatch.setattr("app.fetch_url_metadata", fake_fetch)

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/prep",
            data={"input": "https://example.com/unreachable"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    row = TripPrepItem.query.filter_by(owner_id=owner.id).one()
    assert row.title == "https://example.com/unreachable"
    assert row.link_url == "https://example.com/unreachable"
    assert row.link_image_url is None


def test_prep_create_assigns_owner_to_current_user(app, owner):
    """A new item's owner_id is the signed-in user, not anyone else."""
    other = User(google_id="g99", email="other@example.com", name="Other")
    db.session.add(other)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post("/prep", data={"input": "Buy adapter"},
                           follow_redirects=False)
    assert resp.status_code == 302
    row = TripPrepItem.query.filter_by(title="Buy adapter").one()
    assert row.owner_id == owner.id
    assert row.owner_id != other.id


def test_prep_create_with_trip_id_creates_per_trip_item(app, owner, trip):
    """trip_id pointing at one of the user's trips creates a per-trip item."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/prep",
            data={"input": "Confirm hotel", "trip_id": str(trip.id)},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    row = TripPrepItem.query.filter_by(title="Confirm hotel").one()
    assert row.trip_id == trip.id
    assert row.owner_id == owner.id


def test_prep_create_with_other_users_trip_id_rejects(app, owner):
    """trip_id pointing at someone else's trip returns 403 — no item created."""
    other = User(google_id="g42", email="stranger@example.com", name="Stranger")
    db.session.add(other)
    db.session.commit()
    other_trip = Trip(owner_id=other.id, name="Their trip",
                      start_date=date(2026, 7, 1), end_date=date(2026, 7, 10))
    db.session.add(other_trip)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            "/prep",
            data={"input": "Sneaky item", "trip_id": str(other_trip.id)},
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert TripPrepItem.query.filter_by(title="Sneaky item").count() == 0


def test_prep_create_defaults_category_to_other(app, owner):
    """When no category is submitted, the new item lands in 'other'."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post("/prep", data={"input": "Untagged thing"},
                           follow_redirects=False)
    assert resp.status_code == 302
    row = TripPrepItem.query.filter_by(title="Untagged thing").one()
    assert row.category == "other"


def test_prep_create_empty_input_shows_error_flash(app, owner):
    """Submitting a blank input flashes an error and creates nothing."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post("/prep", data={"input": "   "},
                           follow_redirects=True)
    assert resp.status_code == 200
    assert TripPrepItem.query.filter_by(owner_id=owner.id).count() == 0
    # The flashed warning is rendered into the page.
    assert b"Add a to-do or paste a URL" in resp.data


# ─── POST /prep/<id>/toggle (Task 9) ────────────────────────────────
def test_prep_toggle_owner_can_flip_done(app, owner):
    """The item's owner can flip done from False to True via POST."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Renew passport", category="documents",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
    assert resp.status_code == 302
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is True


def test_prep_toggle_sets_done_at_when_marking_done(app, owner):
    """Marking an item done stamps done_at with utcnow."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Buy adapter", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id
    assert item.done_at is None

    before = datetime.utcnow()
    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
    after = datetime.utcnow()

    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is True
    assert refreshed.done_at is not None
    assert before <= refreshed.done_at <= after


def test_prep_toggle_clears_done_at_when_marking_undone(app, owner):
    """Toggling an already-done item back to undone clears done_at."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Confirm hotel", category="other",
        done=True, done_at=datetime(2026, 1, 1, 12, 0),
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)

    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is False
    assert refreshed.done_at is None


def test_prep_toggle_resets_packing_prompt_dismissed_at_when_undone(app, owner):
    """Un-checking an item also clears packing_prompt_dismissed_at so
    the prompt can fire again on the next done-toggle."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Pack umbrella", category="packing",
        done=True, done_at=datetime(2026, 1, 1, 12, 0),
        packing_prompt_dismissed_at=datetime(2026, 1, 2, 9, 0),
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)

    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is False
    assert refreshed.packing_prompt_dismissed_at is None


def test_prep_toggle_404_when_missing(app, owner):
    """Toggling a non-existent item id returns 404."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post("/prep/99999/toggle", follow_redirects=False)
    assert resp.status_code == 404


def test_prep_toggle_403_for_unrelated_user_on_cross_trip_item(app, owner):
    """A stranger toggling someone else's cross-trip item gets 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="My private to-do", category="other",
    )
    db.session.add(item)
    other = User(google_id="g77", email="stranger@example.com", name="Stranger")
    db.session.add(other)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, other)
        resp = client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
    assert resp.status_code == 403
    # Item state unchanged.
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is False


def test_prep_toggle_403_for_viewer_on_per_trip_item(app, owner, trip, viewer):
    """A viewer collaborator on the trip cannot toggle a per-trip prep item."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Confirm hotel", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, viewer)
        resp = client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
    assert resp.status_code == 403
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is False


def test_prep_toggle_allows_editor_collaborator_on_per_trip_item(
    app, owner, trip, editor,
):
    """An editor collaborator on the trip CAN toggle a per-trip prep item."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Confirm hotel", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, editor)
        resp = client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
    assert resp.status_code == 302
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.done is True


# ─── POST /prep/<id>/edit + /prep/<id>/delete (Task 10) ─────────────
def test_prep_edit_owner_updates_title_and_notes(app, owner):
    """The owner can rename a cross-trip item and update its notes."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Old title", notes="Old notes", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "New title",
                "notes": "New notes",
                "category": "other",
                "trip_id": "none",
                "due_offset_days": "",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.title == "New title"
    assert refreshed.notes == "New notes"


def test_prep_edit_changes_category(app, owner):
    """Editing an item can change its category code."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Buy thing", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "Buy thing",
                "category": "buy",
                "trip_id": "none",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.category == "buy"


def test_prep_edit_changes_due_offset(app, owner):
    """Editing an item can set or change due_offset_days."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Renew passport", category="admin",
        due_offset_days=None,
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "Renew passport",
                "category": "admin",
                "trip_id": "none",
                "due_offset_days": "30",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 302
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.due_offset_days == 30


def test_prep_edit_changing_trip_id_to_inaccessible_trip_rejected(app, owner):
    """If the user edits an item to point at a trip they can't edit, 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="My item", category="other",
    )
    db.session.add(item)

    # A different user owns a different trip; current owner has no
    # access to it.
    stranger = User(google_id="g88", email="stranger@example.com", name="Stranger")
    db.session.add(stranger)
    db.session.commit()
    foreign_trip = Trip(
        owner_id=stranger.id, name="Foreign trip",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 10),
    )
    db.session.add(foreign_trip)
    db.session.commit()
    item_id = item.id
    foreign_trip_id = foreign_trip.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "My item",
                "category": "other",
                "trip_id": str(foreign_trip_id),
            },
            follow_redirects=False,
        )
    assert resp.status_code == 403
    # Item unchanged.
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.trip_id is None


def test_prep_edit_empty_title_returns_error_flash(app, owner):
    """Submitting an edit with an empty title flashes an error and does
    not change the item."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Keep me", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "   ",
                "category": "other",
                "trip_id": "none",
            },
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert b"Title is required" in resp.data
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.title == "Keep me"


def test_prep_delete_owner_removes_item(app, owner):
    """The owner can delete a cross-trip item."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Goodbye", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/prep/{item_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(TripPrepItem, item_id) is None


def test_prep_delete_cascades_links(app, owner, trip):
    """Deleting a prep item also removes its TripPrepLink rows via the
    cascade='all, delete-orphan' relationship."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Cross-trip", category="other",
    )
    db.session.add(item)
    db.session.commit()
    link = TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()
    item_id = item.id
    link_id = link.id
    assert db.session.get(TripPrepLink, link_id) is not None

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(f"/prep/{item_id}/delete", follow_redirects=False)
    assert resp.status_code == 302
    assert db.session.get(TripPrepItem, item_id) is None
    assert db.session.get(TripPrepLink, link_id) is None


def test_prep_edit_403_for_unrelated_user(app, owner):
    """A stranger editing someone else's cross-trip item gets 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="My private to-do", category="other",
    )
    db.session.add(item)
    stranger = User(google_id="g99", email="stranger2@example.com", name="Stranger")
    db.session.add(stranger)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, stranger)
        resp = client.post(
            f"/prep/{item_id}/edit",
            data={
                "title": "Hacked",
                "category": "other",
                "trip_id": "none",
            },
            follow_redirects=False,
        )
    assert resp.status_code == 403
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.title == "My private to-do"


def test_prep_delete_403_for_viewer_collaborator(app, owner, trip, viewer):
    """A viewer collaborator on the trip cannot delete a per-trip prep item."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Confirm hotel", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, viewer)
        resp = client.post(f"/prep/{item_id}/delete", follow_redirects=False)
    assert resp.status_code == 403
    assert db.session.get(TripPrepItem, item_id) is not None


# ─── GET /trips/<id>/prep — per-trip tab (Task 11) ──────────────────
def test_trip_prep_tab_owner_sees_trip_specific_items(app, owner, trip):
    """Owner viewing the per-trip prep tab sees per-trip items in body."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Confirm hotel booking", category="other",
    )
    db.session.add(item)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 200
    assert b"Confirm hotel booking" in resp.data


def test_trip_prep_tab_owner_sees_linked_cross_trip_items(app, owner, trip):
    """Owner sees a cross-trip item that's linked to this trip via TripPrepLink."""
    cross = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Pack travel adapter", category="gear",
    )
    db.session.add(cross)
    db.session.commit()
    link = TripPrepLink(trip_prep_item_id=cross.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 200
    assert b"Pack travel adapter" in resp.data


def test_trip_prep_tab_editor_collaborator_sees_trip_specific_only(
    app, owner, trip, editor,
):
    """Editor collaborator sees per-trip items but NOT the owner's linked
    cross-trip items (the gear section is owner-only)."""
    per_trip = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Print boarding passes", category="other",
    )
    cross = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Owner private gear item", category="gear",
    )
    db.session.add_all([per_trip, cross])
    db.session.commit()
    db.session.add(TripPrepLink(
        trip_prep_item_id=cross.id, trip_id=trip.id,
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, editor)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 200
    assert b"Print boarding passes" in resp.data
    assert b"Owner private gear item" not in resp.data


def test_trip_prep_tab_viewer_collaborator_sees_trip_specific_only_readonly(
    app, owner, trip, viewer,
):
    """Viewer collaborator sees per-trip items but NOT owner's linked
    items, and the create form is hidden (gated on can_edit)."""
    per_trip = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Print boarding passes", category="other",
    )
    cross = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Owner private gear item", category="gear",
    )
    db.session.add_all([per_trip, cross])
    db.session.commit()
    db.session.add(TripPrepLink(
        trip_prep_item_id=cross.id, trip_id=trip.id,
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, viewer)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 200
    assert b"Print boarding passes" in resp.data
    assert b"Owner private gear item" not in resp.data
    # Create form's text input is named "input" — viewers don't see it.
    assert b'name="input"' not in resp.data


def test_trip_prep_tab_viewer_collaborator_does_not_see_linked_section(
    app, owner, trip, viewer,
):
    """The 'Linked from your gear' section header is owner-only."""
    per_trip = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Print boarding passes", category="other",
    )
    cross = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Owner private gear item", category="gear",
    )
    db.session.add_all([per_trip, cross])
    db.session.commit()
    db.session.add(TripPrepLink(
        trip_prep_item_id=cross.id, trip_id=trip.id,
    ))
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, viewer)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 200
    assert b"Linked from your gear" not in resp.data


def test_trip_prep_tab_404_when_trip_missing(app, owner):
    """A signed-in user requesting a non-existent trip gets 404."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips/9999/prep")
    assert resp.status_code == 404


def test_trip_prep_tab_403_when_not_a_collaborator(app, owner, trip):
    """A signed-in user with no access to the trip gets 404.

    Note: test name says 403 to match the plan vocabulary, but
    _trip_with_access_or_404 deliberately returns 404 (not 403) so
    that probing for trip existence is blocked. Assertion matches
    the helper's actual behaviour.
    """
    stranger = User(
        google_id="g_stranger_prep", email="stranger_prep@example.com",
        name="Stranger",
    )
    db.session.add(stranger)
    db.session.commit()

    with flask_app.test_client() as client:
        _login(client, stranger)
        resp = client.get(f"/trips/{trip.id}/prep")
    assert resp.status_code == 404


def test_trip_overview_nav_includes_prep_link(app, owner, trip):
    """The trip overview page surfaces a link to the per-trip prep tab."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get(f"/trips/{trip.id}")
    assert resp.status_code == 200
    expected = f"/trips/{trip.id}/prep".encode("utf-8")
    assert expected in resp.data


# ─── POST /prep/<id>/link + /prep/<id>/link/<link_id> (Task 12) ─────
def test_prep_link_create_attaches_link(app, owner, trip):
    """Posting trip_id links a cross-trip item to that trip."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Pack travel adapter", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id)},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    links = TripPrepLink.query.filter_by(
        trip_prep_item_id=item_id, trip_id=trip.id,
    ).all()
    assert len(links) == 1


def test_prep_link_create_stores_offset(app, owner, trip):
    """A submitted due_offset_days is stored on the new link row."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Renew passport", category="documents",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id), "due_offset_days": "14"},
            follow_redirects=False,
        )
    assert resp.status_code == 302
    link = TripPrepLink.query.filter_by(
        trip_prep_item_id=item_id, trip_id=trip.id,
    ).one()
    assert link.due_offset_days == 14


def test_prep_link_create_400_when_item_is_per_trip(app, owner, trip):
    """Per-trip items (trip_id set) cannot be linked — 400."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Confirm hotel", category="other",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id)},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert TripPrepLink.query.count() == 0


def test_prep_link_create_400_when_trip_id_missing(app, owner):
    """A POST without a trip_id field returns 400."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Buy adapter", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={},
            follow_redirects=False,
        )
    assert resp.status_code == 400
    assert TripPrepLink.query.count() == 0


def test_prep_link_create_403_when_user_not_owner_of_item(app, owner, trip):
    """A stranger linking someone else's cross-trip item gets 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Owner private item", category="packing",
    )
    db.session.add(item)
    stranger = User(google_id="g_stranger_lnk", email="stranger_lnk@example.com",
                    name="Stranger")
    db.session.add(stranger)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, stranger)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id)},
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert TripPrepLink.query.count() == 0


def test_prep_link_create_403_when_user_has_no_access_to_target_trip(app, owner):
    """Linking the owner's own item to a trip they can't see returns 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="My gear", category="packing",
    )
    db.session.add(item)
    stranger = User(google_id="g_stranger_t", email="stranger_t@example.com",
                    name="Stranger")
    db.session.add(stranger)
    db.session.commit()
    foreign_trip = Trip(
        owner_id=stranger.id, name="Foreign trip",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 10),
    )
    db.session.add(foreign_trip)
    db.session.commit()
    item_id = item.id
    foreign_trip_id = foreign_trip.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(foreign_trip_id)},
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert TripPrepLink.query.count() == 0


def test_prep_link_create_rejects_duplicate_link(app, owner, trip):
    """A second link with the same (item_id, trip_id) flashes a warning
    and is NOT inserted — total link count stays at 1."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Pack travel adapter", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        first = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id)},
            follow_redirects=False,
        )
        assert first.status_code == 302
        second = client.post(
            f"/prep/{item_id}/link",
            data={"trip_id": str(trip.id)},
            follow_redirects=False,
        )
    assert second.status_code == 302
    assert TripPrepLink.query.filter_by(
        trip_prep_item_id=item_id, trip_id=trip.id,
    ).count() == 1


def test_prep_link_delete_removes_link(app, owner, trip):
    """Posting to /prep/<id>/link/<link_id> deletes that link."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Pack travel adapter", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    link = TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()
    item_id = item.id
    link_id = link.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/link/{link_id}",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert db.session.get(TripPrepLink, link_id) is None


def test_prep_link_delete_404_when_link_does_not_belong_to_item(app, owner, trip):
    """A link_id that exists but belongs to a different item returns 404."""
    item_x = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Item X", category="packing",
    )
    item_y = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Item Y", category="packing",
    )
    db.session.add_all([item_x, item_y])
    db.session.commit()
    # The link belongs to item_y, but we'll POST to item_x's URL.
    link = TripPrepLink(trip_prep_item_id=item_y.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()
    item_x_id = item_x.id
    link_id = link.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_x_id}/link/{link_id}",
            follow_redirects=False,
        )
    assert resp.status_code == 404
    # Link survives.
    assert db.session.get(TripPrepLink, link_id) is not None


def test_prep_link_delete_403_when_user_not_owner_of_item(app, owner, trip):
    """A stranger unlinking someone else's item gets 403."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Owner private item", category="packing",
    )
    db.session.add(item)
    db.session.commit()
    link = TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id)
    db.session.add(link)
    stranger = User(google_id="g_stranger_dl", email="stranger_dl@example.com",
                    name="Stranger")
    db.session.add(stranger)
    db.session.commit()
    item_id = item.id
    link_id = link.id

    with flask_app.test_client() as client:
        _login(client, stranger)
        resp = client.post(
            f"/prep/{item_id}/link/{link_id}",
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert db.session.get(TripPrepLink, link_id) is not None


# ─── Done → packing-list prompt (Task 13) ───────────────────────────
def _packing_prompt_in_session(client) -> dict:
    """Return the prep_packing_prompt flash payload from the client's
    session, or None. Flash messages live in session['_flashes'] as a
    list of (category, message) tuples."""
    with client.session_transaction() as sess:
        flashes = sess.get("_flashes", [])
    for category, msg in flashes:
        if category == "decision" and isinstance(msg, dict) and \
                msg.get("type") == "prep_packing_prompt":
            return msg
    return None


def test_done_packing_prompt_fires_for_gear_per_trip_item(app, owner, trip):
    """Marking a per-trip gear item done fires the packing-list prompt."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is not None
    assert payload["item_id"] == item_id
    assert payload["item_title"] == "Hiking boots"
    assert payload["trip_id"] == trip.id
    assert payload["trip_name"] == trip.name


def test_done_packing_prompt_fires_for_buy_with_single_link(app, owner, trip):
    """A cross-trip buy item with exactly one link fires the prompt
    using the linked trip."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Travel adapter", category="buy",
    )
    db.session.add(item)
    db.session.commit()
    link = TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id)
    db.session.add(link)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is not None
    assert payload["item_id"] == item_id
    assert payload["trip_id"] == trip.id
    assert payload["trip_name"] == trip.name


def test_done_packing_prompt_does_not_fire_for_research_category(
    app, owner, trip,
):
    """A per-trip item with a non-gear/buy category does not fire the
    prompt — research items aren't packing candidates."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Read up on Naples", category="research",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is None


def test_done_packing_prompt_does_not_fire_for_cross_trip_with_zero_links(
    app, owner,
):
    """A cross-trip gear item with no links is ambiguous — no prompt."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Backpack", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is None


def test_done_packing_prompt_does_not_fire_for_cross_trip_with_multiple_links(
    app, owner, trip,
):
    """A cross-trip item linked to multiple trips is ambiguous — no prompt."""
    other_trip = Trip(
        owner_id=owner.id, name="Other trip",
        start_date=date(2027, 1, 1), end_date=date(2027, 1, 5),
    )
    db.session.add(other_trip)
    db.session.commit()

    item = TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="Travel pillow", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    db.session.add_all([
        TripPrepLink(trip_prep_item_id=item.id, trip_id=trip.id),
        TripPrepLink(trip_prep_item_id=item.id, trip_id=other_trip.id),
    ])
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is None


def test_done_packing_prompt_does_not_fire_when_already_dismissed(
    app, owner, trip,
):
    """If packing_prompt_dismissed_at is set, the prompt stays quiet
    even on a fresh done-toggle."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
        packing_prompt_dismissed_at=datetime(2026, 1, 1, 12, 0),
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is None


def test_done_packing_prompt_fires_again_after_undone_then_done(
    app, owner, trip,
):
    """Toggling done True (prompt fires), dismissing, toggling done
    False (clears dismissed_at), toggling done True again — the prompt
    fires again. Confirms Task 9's reset path is wired."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        # First done → prompt fires.
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        assert _packing_prompt_in_session(client) is not None
        # Dismiss the prompt — stamps packing_prompt_dismissed_at.
        client.post(
            f"/prep/{item_id}/packing-decision?action=dismiss",
            follow_redirects=False,
        )
        # Un-done → clears packing_prompt_dismissed_at.
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        # Re-done → prompt fires again.
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        payload = _packing_prompt_in_session(client)
    assert payload is not None
    assert payload["item_id"] == item_id


def test_packing_decision_add_creates_packing_item(app, owner, trip):
    """POST /prep/<id>/packing-decision?action=add creates a PackingItem
    on the resolved trip with name = item title and category 'other'."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/packing-decision?action=add",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    created = PackingItem.query.filter_by(trip_id=trip.id).all()
    assert len(created) == 1
    assert created[0].name == "Hiking boots"
    assert created[0].category == "other"
    assert created[0].packed is False


def test_packing_decision_dismiss_does_not_create_packing_item(
    app, owner, trip,
):
    """POST /prep/<id>/packing-decision?action=dismiss stamps
    dismissed_at but does NOT create a PackingItem."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/packing-decision?action=dismiss",
            follow_redirects=False,
        )
    assert resp.status_code == 302
    assert PackingItem.query.filter_by(trip_id=trip.id).count() == 0
    refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.packing_prompt_dismissed_at is not None


def test_packing_decision_add_marks_dismissed_so_prompt_does_not_refire(
    app, owner, trip,
):
    """After action=add, packing_prompt_dismissed_at is stamped, so
    the prompt would not re-fire on the next done-toggle as long as
    the item isn't un-done first. (Task 9 clears dismissed_at on
    un-toggle — covered separately by the fires_again_after_undone
    test.)"""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        # Toggle done -> prompt fires.
        client.post(f"/prep/{item_id}/toggle", follow_redirects=False)
        assert _packing_prompt_in_session(client) is not None
        # User clicks "Yes, add to packing list".
        client.post(
            f"/prep/{item_id}/packing-decision?action=add",
            follow_redirects=False,
        )
        # Drain any flashes from the add response.
        with client.session_transaction() as sess:
            sess.pop("_flashes", None)
        # The item is still done; dismissed_at is set; the next time
        # we (somehow) toggled THIS done item again the prompt
        # wouldn't fire. We verify the persistent state instead:
        refreshed = db.session.get(TripPrepItem, item_id)
    assert refreshed.packing_prompt_dismissed_at is not None
    assert PackingItem.query.filter_by(trip_id=trip.id).count() == 1


def test_packing_decision_403_when_not_owner(app, owner, trip):
    """A non-owner of the item cannot POST the decision route."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    stranger = User(
        google_id="g_pkdec_stranger", email="pkdec_stranger@example.com",
        name="Stranger",
    )
    db.session.add(stranger)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, stranger)
        resp = client.post(
            f"/prep/{item_id}/packing-decision?action=add",
            follow_redirects=False,
        )
    assert resp.status_code == 403
    assert PackingItem.query.filter_by(trip_id=trip.id).count() == 0


def test_packing_decision_400_when_action_invalid(app, owner, trip):
    """Any action other than 'add' or 'dismiss' is rejected with 400."""
    item = TripPrepItem(
        owner_id=owner.id, trip_id=trip.id,
        title="Hiking boots", category="gear",
    )
    db.session.add(item)
    db.session.commit()
    item_id = item.id

    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/packing-decision?action=bogus",
            follow_redirects=False,
        )
    assert resp.status_code == 400
    # And no action arg at all is also a 400.
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.post(
            f"/prep/{item_id}/packing-decision",
            follow_redirects=False,
        )
    assert resp.status_code == 400


# ─── Dashboard trip-prep panel (Task 14) ────────────────────────────
def test_dashboard_includes_prep_panel_when_items_exist(app, owner):
    """The dashboard renders the prep panel title + item titles when
    the user has at least one open prep item."""
    db.session.add(TripPrepItem(
        owner_id=owner.id, trip_id=None,
        title="DashboardPrepPanelItem", category="admin",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"Trip prep" in resp.data
    assert b"DashboardPrepPanelItem" in resp.data


def test_dashboard_hides_prep_panel_when_no_items(app, owner):
    """With zero prep items, the dashboard does NOT render the panel
    (the section, including its title, is omitted entirely)."""
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"Trip prep" not in resp.data
    assert b"prep-panel" not in resp.data


def test_dashboard_prep_panel_shows_at_most_five_items(app, owner):
    """Six open prep items render only five rows in the dashboard panel."""
    for i in range(6):
        db.session.add(TripPrepItem(
            owner_id=owner.id, trip_id=None,
            title=f"PanelItem{i}", category="other",
        ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert resp.data.count(b'class="prep-panel-row ') == 5


def test_dashboard_prep_panel_excludes_done_items(app, owner):
    """A done item is filtered out of the panel; an open one appears."""
    db.session.add_all([
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="OpenPanelItem", category="other", done=False),
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="DonePanelItem", category="other", done=True),
    ])
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"OpenPanelItem" in resp.data
    assert b"DonePanelItem" not in resp.data


def test_dashboard_prep_panel_includes_per_trip_and_cross_trip_items(
    app, owner, trip,
):
    """The panel surfaces both per-trip and cross-trip open items."""
    db.session.add_all([
        TripPrepItem(owner_id=owner.id, trip_id=trip.id,
                     title="PerTripPanelItem", category="other"),
        TripPrepItem(owner_id=owner.id, trip_id=None,
                     title="CrossTripPanelItem", category="other"),
    ])
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"PerTripPanelItem" in resp.data
    assert b"CrossTripPanelItem" in resp.data


def test_dashboard_prep_panel_other_users_items_hidden(app, owner):
    """User B does not see user A's prep items in the dashboard panel."""
    other = User(google_id="g2", email="other@example.com", name="Other")
    db.session.add(other)
    db.session.commit()
    db.session.add(TripPrepItem(
        owner_id=other.id, trip_id=None,
        title="OtherUserPanelSecret", category="other",
    ))
    db.session.commit()
    with flask_app.test_client() as client:
        _login(client, owner)
        resp = client.get("/trips")
    assert resp.status_code == 200
    assert b"OtherUserPanelSecret" not in resp.data
