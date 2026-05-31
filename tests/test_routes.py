"""Integration tests — exercise routes + DB end-to-end with an
in-memory SQLite database. Uses Flask's test_client and a fresh DB
per test via a pytest fixture."""

from datetime import date, datetime

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, TripView, User, db


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
    t = Trip(owner_id=owner.id, name="Test trip",
             start_date=date(2026, 6, 1), end_date=date(2026, 6, 10))
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
