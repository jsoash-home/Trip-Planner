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
| `src/trip_helpers.py` | Pure: `derive_status`, `days_until`, `countdown_label`, `progress_fraction`, `emoji_theme`, `themed_countdown_label`, `parse_trip_form`, `group_trips_by_state` |
| `src/booking_helpers.py` | Pure: `parse_booking_form`, `group_bookings_by_type`, `auto_itinerary_items_for_booking`, `format_datetime_range` |
| `src/itinerary.py` | Pure: `parse_itinerary_form`, `group_items_by_day`, `sort_within_day`, `format_time_range` |
| `src/budget.py` | Pure: `rollup_bookings_by_category`, `format_money_totals` |
| `src/packing.py` | Pure: `parse_packing_form`, `group_packing_by_category`, `packing_progress`, `DEFAULT_PACKING_ITEMS` |
| `src/sharing.py` | Pure: `get_user_role_for_trip`, `role_satisfies`, `can_edit`, `is_owner`, `parse_collaborator_form` |
| `src/currency.py` | Pure: `format_money`, `is_valid_currency`, `SUPPORTED_CURRENCIES` |
| `templates/` | Jinja2 — `base.html` is the shared layout; `_countdown_hero.html` is the trip-overview hero partial |
| `static/css/app.css` | Custom styles on top of Bootstrap |
| `static/js/countdown.js` | Vanilla JS for the fun-countdown system: unit toggle, hero ticker, milestone confetti |
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

## Data safety rules (read before touching anything DB-related)

The user's real trips live in `vacation.db` at the project root. Treat
it as production data:

- **Never write seed, fixture, sample, or demo data to `vacation.db`.**
  Not even temporarily. If you need to verify behaviour with realistic
  data, write to a throwaway path under `data/` (gitignored) and delete
  it when done — or ask first.
- **Never run scripts that call `db.create_all()`, `db.drop_all()`, or
  raw SQL against `vacation.db`** without confirming with the user
  first. Migrations are the only exception, and even then say what
  you're about to do.
- **Tests must use the in-memory DB.** [tests/conftest.py](tests/conftest.py)
  sets `DATABASE_URL=sqlite:///:memory:` before importing the app and
  asserts the binding stuck (the tripwire). Don't weaken either.
- **Pre-flight snapshots are automatic.** `src/backup.py` snapshots
  `vacation.db` to `data/backups/` at app startup when the latest
  snapshot is older than 6 hours, keeping the 20 most recent. To
  recover: `cp data/backups/vacation-<timestamp>.db vacation.db`
  (stop the app first).
- **If the user reports "lost data," check the DB before agreeing.**
  Query `vacation.db` directly with `sqlite3` and confirm. A
  redirect_uri_mismatch or wrong-account sign-in looks identical to
  data loss from the browser but the rows are still there.

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

## Fun countdown
The dashboard cards and trip overview share a "fun countdown" system
driven by `static/js/countdown.js`. Key invariants:

- **DOM convention.** Any countdown that swaps between day/sleeps forms
  uses `<span data-countdown-unit>` as the wrapper with two children
  carrying `data-countdown-form="days"` and `data-countdown-form="sleeps"`.
  The unit toggle (in the navbar, `data-countdown-toggle`) sets the
  `hidden` attribute on whichever child doesn't match.
- **Persistence.** Unit choice lives in `localStorage["vp.countdown.unit"]`;
  per-trip milestone dedup uses keys like `vp.celebrated.<trip_id>.<thresh>`.
  Both wrap localStorage access in try/catch (private browsing degrades
  gracefully — toggle still works for the session).
- **Trip overview hero.** `_countdown_hero.html` renders three states
  based on `derive_status`: upcoming trips get a purple gradient with
  a live-ticking H/M/S; completed trips get a static "Welcomed home N
  days ago"; in-progress trips render nothing (the existing Today
  section is the hero). The route passes `today_date` — the include
  aliases it to `today` for the partial.
- **Hero ticker target.** `data-countdown-target` is an ISO timestamp
  WITHOUT a timezone (e.g. `2026-08-17T00:00:00`). The browser parses
  this as local time, which is correct — trips have no time-of-day.
  Don't add `Z`.
- **Milestones.** 30/14/7/3/1 days. Celebrations fire once per trip per
  threshold. Uses `Math.floor(diffMs / 86400000)` so the celebration
  matches the day count the user sees in the hero. `prefers-reduced-motion:
  reduce` skips the confetti burst; the copy overlay still shows.

Three pure helpers in `src/trip_helpers.py` back this:
`progress_fraction` (dashboard ring), `emoji_theme` (emoji → theme
phrase lookup), `themed_countdown_label` (wraps `countdown_label` with
theme + unit).

## Local port
Local dev server runs on port **5002** (stock-tracker uses 5001).
