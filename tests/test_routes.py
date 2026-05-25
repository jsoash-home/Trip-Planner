"""Integration tests — exercise routes + DB end-to-end with an
in-memory SQLite database. Uses Flask's test_client and a fresh DB
per test via a pytest fixture."""

from datetime import date, datetime

import pytest

from app import app as flask_app
from models import Booking, ItineraryItem, Trip, User, db


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
    assert resp.headers["Location"].endswith(f"/trips/{trip.id}/itinerary")


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
    assert a.customized_by_user is False
    assert z.customized_by_user is False


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
