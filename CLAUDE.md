# Vacation Planner — Agent Context

## Project overview
A Flask web app for planning, running, and remembering trips. Users sign
in with Google, create one or more trips, fill in bookings + itinerary +
packing list, and share trips with travel partners by email.

## Tech stack
- **Backend:** Python 3.9+, Flask, Flask-Login, Flask-Dance (Google OAuth), Flask-SQLAlchemy
- **Database:** SQLite locally (`vacation.db`), Postgres on cloud — auto-detected via `DATABASE_URL`
- **Frontend:** Jinja2 templates, Bootstrap 5 (CDN), vanilla JS for inline edits
- **Markdown:** `markdown` library renders trip / itinerary / packing notes

## File map
| File | Purpose |
|---|---|
| `app.py` | Flask routes, OAuth, access guards, DB bootstrap |
| `models.py` | SQLAlchemy: `User`, `Trip`, `TripCollaborator`, `Booking`, `ItineraryItem`, `PackingItem` |
| `src/trip_helpers.py` | Pure: `derive_status`, `days_until`, `countdown_label`, `parse_trip_form`, `group_trips_by_state` |
| `src/booking_helpers.py` | Pure: `parse_booking_form`, `group_bookings_by_type`, `auto_itinerary_items_for_booking`, `format_datetime_range` |
| `src/itinerary.py` | Pure: `parse_itinerary_form`, `group_items_by_day`, `sort_within_day`, `format_time_range` |
| `src/budget.py` | Pure: `rollup_bookings_by_category`, `format_money_totals` |
| `src/packing.py` | Pure: `parse_packing_form`, `group_packing_by_category`, `packing_progress`, `DEFAULT_PACKING_ITEMS` |
| `src/sharing.py` | Pure: `get_user_role_for_trip`, `role_satisfies`, `can_edit`, `is_owner`, `parse_collaborator_form` |
| `src/currency.py` | Pure: `format_money`, `is_valid_currency`, `SUPPORTED_CURRENCIES` |
| `templates/` | Jinja2 — `base.html` is the shared layout |
| `static/css/app.css` | Custom styles on top of Bootstrap |
| `tests/test_*.py` | One test file per pure helper module (197 tests at the v1 milestone) |

## Conventions
- Flask routes live entirely in `app.py` — no blueprints
- Pure helpers live in `src/`; tests in `tests/test_<module>.py`
- Logging via `logging.getLogger(__name__)`; never `print()`
- Type hints on every new function
- Python 3.9 — no `X | Y` union syntax; use `Optional[X]`

## Sharing model
Per-trip access is controlled by `TripCollaborator` rows keyed by email.
The owner always has full access. A collaborator with role=`editor` can
add/edit/delete child rows; role=`viewer` can read only. The
`require_trip_access(trip_id, role)` guard in `src/sharing.py` is called
by every `/trips/<id>/...` route.

A user added as a collaborator before they've ever logged in still gets
access — when they sign in with Google later using the same email, the
trip just appears on their dashboard. No invite tokens, no email sending.

## Smart booking → itinerary auto-link
When a booking is **created** (not edited), the `booking_new` route in
`app.py` calls `auto_itinerary_items_for_booking()` from
`src/booking_helpers.py` and writes matching `ItineraryItem` rows linked
back to the booking via `linked_booking_id`:

| Booking type | Auto-created itinerary items | Category |
|---|---|---|
| flight | "Depart {vendor}" on dep day, "Arrive {vendor}" on arr day | transit |
| hotel | "Check in: {vendor}" on start day, "Check out: {vendor}" on end day | other |
| car | "Pick up car: {vendor}" on start day, "Return car: {vendor}" on end day | transit |
| restaurant | booking title on the booked day at booked time | meal |
| activity | booking title on the booked day at booked time | sightseeing |
| transport / other | none | — |

Required-field rule: an item is only auto-created when its source
datetime exists. A flight with no `start_datetime` emits no Depart
item; a flight with no `end_datetime` emits no Arrive item. The vendor
falls back to the booking title when vendor is empty.

**Edit policy:** editing a booking does NOT regenerate its linked items.
This avoids clobbering any tweaks the user has made (renaming a chip,
moving it to a different day, changing the time). The form shows a note
explaining this.

**Delete policy:** deleting a booking deletes its linked items via the
`Booking.itinerary_items` SQLAlchemy relationship's
`cascade="save-update, merge, delete"`. We don't use `delete-orphan` —
that would also delete an item if a user manually un-linked it.

Items whose `day_date` falls outside the trip's date range are skipped
at creation time (booking dates aren't constrained to trip dates).

## Database selection
Same pattern as stock-tracker. `DATABASE_URL` env var → Postgres on the
cloud; absent → SQLite in the project folder. The app rewrites
`postgres://` to `postgresql://` automatically for SQLAlchemy.

## Deployment caveat
`os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"` is set in `app.py` for
localhost HTTP. **Must be removed before deploying** — Railway, Render,
and Fly all serve over HTTPS where this flag breaks OAuth.

## Today view (Step 9)
The trip overview at `/trips/<id>` leads with a "Today" section when
`derive_status()` returns `in_progress`. The route computes today's
itinerary items via `sort_within_day(ItineraryItem.query.filter_by(...))`
and the day number `(today - trip.start_date).days + 1`. The section
shows category-coloured items with time, title, location, and notes;
empty days show a friendly nudge with a deep link to add an item to
today.

## Local port
Local dev server runs on port **5002** (stock-tracker uses 5001).
