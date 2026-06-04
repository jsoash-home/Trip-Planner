"""
app.py

Flask entry point for the Vacation Planner.

Run with:
    python app.py
Then open http://localhost:5002 in your browser.

Step 2 of the build plan: full Trip CRUD (create / view / edit / delete)
plus the dashboard rendering real trip cards. Bookings, itinerary,
budget, packing, and sharing arrive in later steps.
"""

import logging
import os
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import markdown as md_lib
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_dance.consumer import oauth_authorized
from flask_dance.contrib.google import make_google_blueprint
from flask_login import (
    LoginManager,
    current_user,
    login_required,
    login_user,
    logout_user,
)

from models import (
    Booking,
    ItineraryItem,
    PackingItem,
    Trip,
    TripCollaborator,
    TripView,
    User,
    db,
)
from src.booking_helpers import (
    BOOKING_TYPE_CODES,
    BOOKING_TYPE_LABELS,
    BOOKING_TYPES,
    DRIFT_FIELDS,
    DriftReport,
    NewItemSuggestion,
    auto_itinerary_items_for_booking,
    booking_form_values,
    clear_stale_geocode_on_booking_edit,
    detect_drift,
    format_datetime_range,
    group_bookings_by_type,
    missing_auto_kinds_for_booking,
    parse_booking_form,
    parse_touched,
    serialize_touched,
    total_cost_by_currency,
)
from src.budget import format_money_totals, rollup_bookings_by_category
from src.currency import SUPPORTED_CURRENCIES, format_money, is_valid_currency
from src.drift_review import chronological_order
from src.geocoding import ensure_geocoded
from src.itinerary import (
    ITINERARY_CATEGORIES,
    category_css,
    category_emoji,
    clear_stale_geocode_on_item_edit,
    format_day_items_summary,
    format_time_range,
    group_items_by_day,
    initial_day_index,
    itinerary_form_values,
    parse_itinerary_form,
    sort_within_day,
)
from src.map_helpers import Pin, color_for_category, color_for_year, pins_to_geojson
from src.packing import (
    DEFAULT_PACKING_ITEMS,
    PACKING_CATEGORIES,
    group_packing_by_category,
    packing_form_values,
    packing_progress,
    packing_progress_for_group,
    parse_packing_form,
)
from src.sharing import (
    SHARE_ROLES,
    SHARE_ROLE_LABELS,
    can_edit,
    get_user_role_for_trip,
    is_owner,
    normalize_email,
    parse_collaborator_form,
    role_satisfies,
)
from src.trip_helpers import (
    SUGGESTED_TRIP_EMOJIS,
    countdown_label,
    day_of_trip,
    days_until,
    derive_status,
    emoji_theme,
    format_changes_since_label,
    group_trips_by_state,
    parse_trip_form,
    pick_active_trip,
    progress_fraction,
    sort_nav_trips,
    status_label,
    themed_countdown_label,
    trip_form_values,
)

# ─── Logging ────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Env ────────────────────────────────────────────────────────────
_APP_ROOT = Path(__file__).resolve().parent
load_dotenv(_APP_ROOT / ".env")

MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()
if not MAPBOX_TOKEN:
    logger.warning("MAPBOX_TOKEN not configured — map pages will show a banner.")


def _resolve_database_uri(app_root: Path) -> str:
    """
    Build SQLAlchemy's database URL.

    DATABASE_URL on cloud hosts → use that (Postgres). Absent → SQLite
    in the project folder. Postgres URLs come back as "postgres://"
    but SQLAlchemy 2.x requires "postgresql://" — we rewrite it.
    """
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return f"sqlite:///{(app_root / 'vacation.db').resolve().as_posix()}"
    if raw.startswith("postgres://"):
        return raw.replace("postgres://", "postgresql://", 1)
    return raw


# ─── App ────────────────────────────────────────────────────────────
app = Flask(__name__)

if "SECRET_KEY" not in os.environ:
    raise RuntimeError(
        "SECRET_KEY is not set. Copy .env.example to .env and fill it in."
    )
app.secret_key = os.environ["SECRET_KEY"]

_db_url = _resolve_database_uri(_APP_ROOT)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

if _db_url.startswith("sqlite:///"):
    logger.info("Using SQLite database at %s", _db_url.replace("sqlite:///", "", 1))
else:
    logger.info("Using SQLAlchemy database from DATABASE_URL")

# Flask-Dance refuses to do OAuth over plain HTTP unless this is set.
# REMOVE before deploying — production HTTPS will reject this.
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

def _ensure_drift_columns() -> None:
    """
    Add the drift-tracking columns to itinerary_item if they don't exist
    yet. SQLite + Postgres both accept the ANSI ``ALTER TABLE ... ADD
    COLUMN`` since the versions we support. We swallow OperationalError
    so a re-run on already-migrated DBs is a no-op.

    Also backfills auto_fields_touched from the deprecated
    customized_by_user flag — see the phase-3 design doc.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE itinerary_item ADD COLUMN auto_kind VARCHAR(20)",
        "ALTER TABLE itinerary_item ADD COLUMN customized_by_user BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE itinerary_item ADD COLUMN auto_fields_touched VARCHAR(255) NOT NULL DEFAULT ''",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                # Column already exists, or DB is mid-create — both fine.
                logger.warning("Migration skipped (%s): %s", stmt, e)

        # One-time backfill: translate the deprecated customized_by_user
        # flag into the equivalent "all fields touched" state. The
        # `auto_fields_touched = ''` guard makes the UPDATE a no-op on
        # re-run. Sort order matches what serialize_touched(DRIFT_FIELDS)
        # produces.
        try:
            result = conn.execute(text(
                "UPDATE itinerary_item "
                "SET auto_fields_touched = 'category,day_date,end_time,location,start_time,title' "
                "WHERE customized_by_user = TRUE "
                "AND (auto_fields_touched = '' OR auto_fields_touched IS NULL)"
            ))
            logger.info(
                "Migration: backfilled auto_fields_touched from customized_by_user (%d rows)",
                result.rowcount,
            )
        except Exception as e:
            logger.warning("Migration backfill skipped: %s", e)


def _ensure_trip_columns() -> None:
    """
    Add trip-level columns that were introduced after the first deploy.
    SQLite + Postgres both accept ANSI ``ALTER TABLE ... ADD COLUMN``;
    we swallow OperationalError so re-runs on already-migrated DBs are
    a no-op (same pattern as _ensure_drift_columns).
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE trip ADD COLUMN cover_image_url VARCHAR(800)",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                logger.warning("Migration skipped (%s): %s", stmt, e)


def _ensure_yearbook_columns() -> None:
    """
    Add yearbook columns introduced by the Trip Yearbook feature: a
    star flag per itinerary item, plus a share token + two visibility
    toggles per trip. Same swallow-on-duplicate pattern as the other
    _ensure_* helpers — re-runs are no-ops.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE itinerary_item ADD COLUMN starred BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE trip ADD COLUMN yearbook_share_token VARCHAR(32)",
        "CREATE UNIQUE INDEX ix_trip_yearbook_share_token ON trip (yearbook_share_token)",
        "ALTER TABLE trip ADD COLUMN yearbook_public_show_notes BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE trip ADD COLUMN yearbook_public_show_spend BOOLEAN NOT NULL DEFAULT 1",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                logger.warning("Migration skipped (%s): %s", stmt, e)


def _ensure_geocoding_columns() -> None:
    """
    Add geocoding columns to booking + itinerary_item (added by the
    map-view feature). Same swallow-on-duplicate pattern as the other
    _ensure_* helpers — re-runs are no-ops.
    """
    from sqlalchemy import text
    statements = [
        "ALTER TABLE booking ADD COLUMN geocoded_lat FLOAT",
        "ALTER TABLE booking ADD COLUMN geocoded_lng FLOAT",
        "ALTER TABLE booking ADD COLUMN geocoded_at DATETIME",
        "ALTER TABLE booking ADD COLUMN geocoded_manually BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE booking ADD COLUMN geocoded_city VARCHAR(120)",
        "ALTER TABLE booking ADD COLUMN geocoded_country_code VARCHAR(2)",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_lat FLOAT",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_lng FLOAT",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_at DATETIME",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_manually BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_city VARCHAR(120)",
        "ALTER TABLE itinerary_item ADD COLUMN geocoded_country_code VARCHAR(2)",
    ]
    with db.engine.begin() as conn:
        for stmt in statements:
            try:
                conn.execute(text(stmt))
                logger.info("Migration: applied %s", stmt)
            except Exception as e:
                logger.warning("Migration skipped (%s): %s", stmt, e)


db.init_app(app)
with app.app_context():
    db.create_all()
    _ensure_drift_columns()
    _ensure_trip_columns()
    _ensure_geocoding_columns()
    _ensure_yearbook_columns()
    logger.info("Database schema ensured")

login_manager = LoginManager(app)
login_manager.login_view = "index"

# ─── Jinja helpers ──────────────────────────────────────────────────
# Templates can call these directly: {{ derive_status(...) }} / {{ "**hi**" | markdown }}
app.jinja_env.globals.update(
    countdown_label=countdown_label,
    day_of_trip=day_of_trip,
    days_until=days_until,
    derive_status=derive_status,
    emoji_theme=emoji_theme,
    format_datetime_range=format_datetime_range,
    format_day_items_summary=format_day_items_summary,
    format_money=format_money,
    format_money_totals=format_money_totals,
    format_time_range=format_time_range,
    category_emoji=category_emoji,
    category_css=category_css,
    can_edit=can_edit,
    is_owner=is_owner,
    packing_progress_for_group=packing_progress_for_group,
    progress_fraction=progress_fraction,
    share_role_label=lambda code: SHARE_ROLE_LABELS.get(code, code),
    themed_countdown_label=themed_countdown_label,
)


def _markdown_filter(text: Optional[str]) -> str:
    """Render user-entered markdown to HTML.

    Note: this does NOT sanitize raw HTML. For now the only writers are
    the trip's owner + their explicit collaborators (added in Step 8),
    so untrusted input isn't possible. If we add public sharing later,
    swap this for `bleach.clean(md_lib.markdown(...))`.
    """
    if not text:
        return ""
    return md_lib.markdown(text, extensions=["extra", "sane_lists"])


app.jinja_env.filters["markdown"] = _markdown_filter


# ─── Context processors ────────────────────────────────────────────
@app.context_processor
def inject_nav_trips():
    """
    Make ``nav_trips`` available to base.html so the navbar can render
    a "Trips" dropdown when the user is viewing a specific trip page.

    Short-circuits cheaply when:
      - the user isn't logged in,
      - or the current route isn't a trip page (no ``trip_id`` view arg).

    Trip pages are detected by ``request.view_args["trip_id"]`` — every
    /trips/<int:trip_id>/... route has that parameter, so we don't have
    to maintain a list of endpoint names by hand.
    """
    empty = {"nav_trips": [], "nav_current_trip_id": None}
    if not current_user.is_authenticated:
        return empty
    if not request.view_args or "trip_id" not in request.view_args:
        return empty

    owned = Trip.query.filter_by(owner_id=current_user.id).all()
    user_email = normalize_email(current_user.email)
    shared: List[Trip] = []
    if user_email:
        shared = (
            Trip.query.join(TripCollaborator)
            .filter(TripCollaborator.email == user_email)
            .all()
        )
    trips = list({t.id: t for t in owned + shared}.values())
    return {
        "nav_trips": sort_nav_trips(trips, date.today(), limit=5),
        "nav_current_trip_id": request.view_args.get("trip_id"),
    }


@app.context_processor
def inject_active_trip():
    """
    Make ``active_trip`` available to base.html so every page can render
    a coral ribbon above the navbar when one of the user's trips is
    currently in progress.

    Runs on every authenticated page render. Narrows the SQL filter to
    trips that contain today's date (both owned and shared via
    TripCollaborator), then delegates to ``pick_active_trip`` for the
    final selection — that helper handles the rare "two overlapping
    in-progress trips" case.
    """
    empty = {"active_trip": None, "active_trip_day": None, "active_trip_total": None}
    if not current_user.is_authenticated:
        return empty

    today = date.today()
    owned = Trip.query.filter(
        Trip.owner_id == current_user.id,
        Trip.start_date <= today,
        Trip.end_date >= today,
    ).all()
    user_email = normalize_email(current_user.email)
    shared: List[Trip] = []
    if user_email:
        shared = (
            Trip.query.join(TripCollaborator)
            .filter(
                TripCollaborator.email == user_email,
                Trip.start_date <= today,
                Trip.end_date >= today,
            )
            .all()
        )
    candidates = list({t.id: t for t in owned + shared}.values())
    active = pick_active_trip(candidates, today)
    if not active:
        return empty
    day, total = day_of_trip(active.start_date, active.end_date, today)
    return {"active_trip": active, "active_trip_day": day, "active_trip_total": total}


@app.context_processor
def inject_mapbox_token():
    """Make ``mapbox_token`` available to base.html so the head can render
    a ``<meta name="mapbox-token">`` tag for the map-view JS to read.
    """
    return {"mapbox_token": MAPBOX_TOKEN}


# ─── Google OAuth ───────────────────────────────────────────────────
for required in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"):
    if required not in os.environ:
        raise RuntimeError(
            f"{required} is not set. See .env.example for setup instructions."
        )

google_bp = make_google_blueprint(
    client_id=os.environ["GOOGLE_CLIENT_ID"],
    client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
    scope=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    redirect_to="trips_list",
)
app.register_blueprint(google_bp, url_prefix="/login")


@oauth_authorized.connect_via(google_bp)
def google_logged_in(blueprint, token):
    """Runs after Google returns a token. Creates / updates the user, logs them in."""
    if not token:
        flash("Google login failed. Please try again.", "danger")
        return

    resp = blueprint.session.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Could not fetch your Google profile. Please try again.", "danger")
        return

    google_info = resp.json()
    google_id_raw = google_info.get("sub") or google_info.get("id")
    if not google_id_raw:
        flash("Could not read your Google account id. Please try again.", "danger")
        return
    google_id = str(google_id_raw).strip()

    avatar_url = (google_info.get("picture") or "").strip() or None

    user = User.query.filter_by(google_id=google_id).first()
    if user is None:
        email = (google_info.get("email") or "").strip()
        if email:
            existing_by_email = User.query.filter_by(email=email).first()
            if existing_by_email is not None and existing_by_email.google_id != google_id:
                existing_by_email.google_id = google_id
                db.session.commit()
                user = existing_by_email
                logger.info("Updated google_id for user id=%s email=%s", user.id, email)

    if user is None:
        email = (google_info.get("email") or "").strip()
        name = (google_info.get("name") or "").strip() or (
            email.split("@")[0] if email else "Traveler"
        )
        if not email:
            flash("Google did not provide an email. This app needs one to sign you in.", "danger")
            return
        user = User(google_id=google_id, email=email, name=name, avatar_url=avatar_url)
        db.session.add(user)
        db.session.commit()
        logger.info("Created new user id=%s email=%s", user.id, email)
    else:
        if user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            db.session.commit()

    login_user(user)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ─── Helpers ────────────────────────────────────────────────────────
def _trip_with_access_or_404(trip_id: int, role: str = "viewer"):
    """
    Return (trip, user_role) only if the current user has at least `role`.

    404 (not 403) on no-access so a guess can't probe trip existence.
    Roles, lowest first: viewer, editor, owner. The trip owner is always
    "owner"; collaborators come from TripCollaborator rows.
    """
    trip = Trip.query.get(trip_id)
    if trip is None:
        abort(404)
    user_role = get_user_role_for_trip(trip, current_user)
    if not role_satisfies(user_role, role):
        abort(404)
    return trip, user_role


def _owned_trip_or_404(trip_id: int) -> Trip:
    """Owner-only access. Thin wrapper for backwards compatibility."""
    trip, _ = _trip_with_access_or_404(trip_id, role="owner")
    return trip


def _countdown_class(status: str) -> str:
    """CSS modifier for the countdown badge. Same vocabulary as _trip_card.html."""
    if status == "in_progress":
        return "is-active"
    if status == "completed":
        return "is-past"
    return ""


def _booking_with_access_or_404(trip_id: int, booking_id: int, role: str = "editor"):
    """Return (trip, booking, user_role). Defaults to editor since these
    helpers are mostly called from mutation routes."""
    trip, user_role = _trip_with_access_or_404(trip_id, role=role)
    booking = Booking.query.get(booking_id)
    if booking is None or booking.trip_id != trip.id:
        abort(404)
    return trip, booking, user_role


def _itinerary_item_with_access_or_404(trip_id: int, item_id: int, role: str = "editor"):
    """Return (trip, itinerary_item, user_role)."""
    trip, user_role = _trip_with_access_or_404(trip_id, role=role)
    item = ItineraryItem.query.get(item_id)
    if item is None or item.trip_id != trip.id:
        abort(404)
    return trip, item, user_role


def _packing_item_with_access_or_404(trip_id: int, item_id: int, role: str = "editor"):
    """Return (trip, packing_item, user_role)."""
    trip, user_role = _trip_with_access_or_404(trip_id, role=role)
    item = PackingItem.query.get(item_id)
    if item is None or item.trip_id != trip.id:
        abort(404)
    return trip, item, user_role


def _seed_default_packing(trip_id: int) -> None:
    """Pre-populate a fresh trip's packing list with the universal defaults."""
    for d in DEFAULT_PACKING_ITEMS:
        db.session.add(PackingItem(trip_id=trip_id, packed=False, **d))


def _next_order_within_day(trip_id: int, day_date) -> int:
    """Highest existing order_within_day on this day, plus 1.

    New items added on a day always sort after existing ones with the
    same time (or after all untimed items, when itself untimed).
    """
    rows = ItineraryItem.query.filter_by(trip_id=trip_id, day_date=day_date).all()
    if not rows:
        return 0
    return max(r.order_within_day or 0 for r in rows) + 1


def _section_tiles_for(trip: Trip):
    """Build the section-tile grid shown on the trip overview page.

    Each step replaces its own tile's `summary` and flips `status` from
    "soon" to "ready" once the section is built. Bookings is the first
    one to flip in Step 3.
    """
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    booking_count = len(bookings)
    if booking_count == 0:
        bookings_summary = "Add your first booking"
    elif booking_count == 1:
        bookings_summary = "1 booking"
    else:
        bookings_summary = f"{booking_count} bookings"

    item_count = ItineraryItem.query.filter_by(trip_id=trip.id).count()
    if item_count == 0:
        itinerary_summary = "Build your day-by-day plan"
    elif item_count == 1:
        itinerary_summary = "1 scheduled item"
    else:
        itinerary_summary = f"{item_count} scheduled items"

    # Budget summary — use the same rollup logic as the budget page so the
    # tile and the page agree exactly.
    budget_totals: dict = {}
    for b in bookings:
        if b.cost is None:
            continue
        cur = (b.currency or "USD").upper()
        budget_totals[cur] = budget_totals.get(cur, 0.0) + float(b.cost)
    if not bookings:
        budget_summary = "Add bookings to track costs"
    elif not budget_totals:
        budget_summary = "Add cost to your bookings"
    else:
        budget_summary = format_money_totals(budget_totals)

    # Packing summary — X / Y packed.
    packing_items = PackingItem.query.filter_by(trip_id=trip.id).all()
    packed_n, total_n, _ = packing_progress(packing_items)
    if total_n == 0:
        packing_summary = "Add packing items"
    elif packed_n == total_n:
        packing_summary = f"All {total_n} packed ✓"
    else:
        packing_summary = f"{packed_n} / {total_n} packed"

    # Share summary — count of people on the trip beyond the owner.
    collab_count = TripCollaborator.query.filter_by(trip_id=trip.id).count()
    if collab_count == 0:
        share_summary = "Just you"
    elif collab_count == 1:
        share_summary = "Shared with 1 person"
    else:
        share_summary = f"Shared with {collab_count} people"

    return [
        {
            "emoji": "🎫",
            "name": "Bookings",
            "summary": bookings_summary,
            "url": url_for("bookings_list", trip_id=trip.id),
            "status": "ready",
        },
        {
            "emoji": "🗓️",
            "name": "Itinerary",
            "summary": itinerary_summary,
            "url": url_for("trip_itinerary", trip_id=trip.id),
            "status": "ready",
        },
        {
            "emoji": "💰",
            "name": "Budget",
            "summary": budget_summary,
            "url": url_for("trip_budget", trip_id=trip.id),
            "status": "ready",
        },
        {
            "emoji": "🧳",
            "name": "Packing",
            "summary": packing_summary,
            "url": url_for("trip_packing", trip_id=trip.id),
            "status": "ready",
        },
        {
            "emoji": "🗺️",
            "name": "Map",
            "summary": _map_tile_summary(trip),
            "url": url_for("trip_map", trip_id=trip.id),
            "status": "ready",
        },
        {
            "emoji": "👥",
            "name": "Share",
            "summary": share_summary,
            "url": url_for("trip_share", trip_id=trip.id),
            "status": "ready",
        },
    ]


def _map_tile_summary(trip: Trip) -> str:
    """Short summary for the Map tile (e.g., '14 pins').

    Counts rows with a non-empty `location`, not rows that have been
    geocoded — geocoding is lazy (only runs on first map open) and we
    don't want the tile to say "Add a location" while locations exist.
    """
    with_location = sum(
        1 for r in list(trip.bookings) + list(trip.itinerary_items)
        if (r.location or "").strip()
    )
    if with_location == 0:
        return "Add a location to get started"
    return f"{with_location} pin{'s' if with_location != 1 else ''}"


# ─── Public routes ──────────────────────────────────────────────────
@app.route("/")
def index():
    """Logged-out landing page. Redirects to /trips when signed in."""
    if current_user.is_authenticated:
        return redirect(url_for("trips_list"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out. See you next adventure.", "info")
    return redirect(url_for("index"))


# ─── Trips ──────────────────────────────────────────────────────────
@app.route("/trips")
@login_required
def trips_list():
    """Dashboard. Includes trips owned + trips shared via collaboration."""
    today = date.today()

    owned = Trip.query.filter_by(owner_id=current_user.id).all()

    # Trips shared with this user — match by their normalized Google email.
    user_email = normalize_email(current_user.email)
    shared = []
    if user_email:
        shared = (
            Trip.query.join(TripCollaborator)
            .filter(TripCollaborator.email == user_email)
            .all()
        )

    # Dedupe (defensive — owner is never their own collaborator, but a
    # corrupt row could cause a duplicate).
    trips = list({t.id: t for t in owned + shared}.values())

    grouped = group_trips_by_state(trips, today)
    has_any = any(grouped.values())
    counts = _drift_counts_for_trips(trips)
    return render_template(
        "trips_list.html",
        grouped=grouped,
        has_any_trips=has_any,
        today=today,
        counts=counts,
    )


@app.route("/trips/new", methods=["GET", "POST"])
@login_required
def trip_new():
    """Form to create a new trip."""
    if request.method == "POST":
        data, field_errors = parse_trip_form(request.form)
        if not is_valid_currency(data["primary_currency"]):
            field_errors["primary_currency"] = "Primary currency is not supported."
        if field_errors:
            return render_template(
                "trip_form.html",
                trip=None,
                form=request.form,
                field_errors=field_errors,
                supported_currencies=SUPPORTED_CURRENCIES,
                suggested_emojis=SUGGESTED_TRIP_EMOJIS,
            )

        trip = Trip(owner_id=current_user.id, **data)
        db.session.add(trip)
        db.session.flush()  # populate trip.id so the packing seeds can FK to it
        _seed_default_packing(trip.id)
        db.session.commit()
        logger.info(
            "Created trip id=%s name=%r for user_id=%s (seeded %s packing items)",
            trip.id, trip.name, current_user.id, len(DEFAULT_PACKING_ITEMS),
        )
        flash(f"Trip “{trip.name}” created.", "success")
        return redirect(url_for("trip_overview", trip_id=trip.id))

    # GET — fresh form
    return render_template(
        "trip_form.html",
        trip=None,
        form={"primary_currency": "USD"},
        field_errors={},
        supported_currencies=SUPPORTED_CURRENCIES,
        suggested_emojis=SUGGESTED_TRIP_EMOJIS,
    )


@app.route("/trips/<int:trip_id>")
@login_required
def trip_overview(trip_id):
    """Single-trip overview page. Viewer / editor / owner all see this."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    today = date.today()
    status = derive_status(trip.start_date, trip.end_date, today)
    duration = (trip.end_date - trip.start_date).days + 1

    # Today view (Step 9): when the trip is in progress, surface today's
    # itinerary items and the day number on top of the page.
    today_items = []
    today_day_number = None
    if status == "in_progress":
        today_day_number = (today - trip.start_date).days + 1
        today_items = sort_within_day(
            ItineraryItem.query.filter_by(trip_id=trip.id, day_date=today).all()
        )

    # Step 18: "what changed since your last visit" banner. First-ever
    # visit creates the TripView row and shows nothing. Subsequent visits
    # count bookings + itinerary items created after `last_seen_at`, then
    # bump it to now so the next reload starts fresh.
    changes_banner = _changes_banner_and_mark_seen(trip.id, current_user.id)

    # Mini-map teaser (Task 10): only show the section when at least one
    # booking or itinerary item has already been geocoded.
    has_pins = any(
        r.geocoded_lat is not None
        for r in list(trip.bookings) + list(trip.itinerary_items)
    )

    return render_template(
        "trip_overview.html",
        trip=trip,
        user_role=user_role,
        status=status,
        countdown=countdown_label(trip.start_date, trip.end_date, today),
        countdown_cls=_countdown_class(status),
        status_label=status_label(status),
        duration_days=duration,
        tiles=_section_tiles_for(trip),
        today_items=today_items,
        today_day_number=today_day_number,
        today_date=today,
        changes_banner=changes_banner,
        has_pins=has_pins,
    )


def _changes_banner_and_mark_seen(trip_id: int, user_id: int) -> Optional[str]:
    """
    Read this user's TripView for the trip, build the banner string from
    rows created after `last_seen_at`, then upsert `last_seen_at` to now.

    Returns None on first-ever visit (no prior TripView) and when nothing
    has been added since the last visit.
    """
    now = datetime.utcnow()
    view = TripView.query.filter_by(trip_id=trip_id, user_id=user_id).first()

    if view is None:
        db.session.add(TripView(trip_id=trip_id, user_id=user_id, last_seen_at=now))
        db.session.commit()
        return None

    last_seen = view.last_seen_at
    new_bookings = Booking.query.filter(
        Booking.trip_id == trip_id,
        Booking.created_at > last_seen,
    ).count()
    new_items = ItineraryItem.query.filter(
        ItineraryItem.trip_id == trip_id,
        ItineraryItem.created_at > last_seen,
    ).count()

    view.last_seen_at = now
    db.session.commit()

    return format_changes_since_label(new_bookings, new_items)


@app.route("/trips/<int:trip_id>/edit", methods=["GET", "POST"])
@login_required
def trip_edit(trip_id):
    """Edit an existing trip."""
    trip = _owned_trip_or_404(trip_id)

    if request.method == "POST":
        data, field_errors = parse_trip_form(request.form)
        if not is_valid_currency(data["primary_currency"]):
            field_errors["primary_currency"] = "Primary currency is not supported."
        if field_errors:
            return render_template(
                "trip_form.html",
                trip=trip,
                form=request.form,
                field_errors=field_errors,
                supported_currencies=SUPPORTED_CURRENCIES,
                suggested_emojis=SUGGESTED_TRIP_EMOJIS,
            )

        for field, value in data.items():
            setattr(trip, field, value)
        db.session.commit()
        logger.info("Edited trip id=%s name=%r", trip.id, trip.name)
        flash("Changes saved.", "success")
        return redirect(url_for("trip_overview", trip_id=trip.id))

    return render_template(
        "trip_form.html",
        trip=trip,
        form=trip_form_values(trip),
        field_errors={},
        supported_currencies=SUPPORTED_CURRENCIES,
        suggested_emojis=SUGGESTED_TRIP_EMOJIS,
    )


@app.route("/trips/<int:trip_id>/delete", methods=["POST"])
@login_required
def trip_delete(trip_id):
    """Delete a trip the current user owns."""
    trip = _owned_trip_or_404(trip_id)
    name = trip.name
    db.session.delete(trip)
    db.session.commit()
    logger.info("Deleted trip id=%s name=%r", trip_id, name)
    flash(f"Deleted trip “{name}”.", "success")
    return redirect(url_for("trips_list"))


# ─── Trip map (in-trip view) ────────────────────────────────────────


def _booking_category(btype: str) -> str:
    """Map a Booking.type to the same category names used on the itinerary.

    Mirrors the implicit category mapping in
    `src.booking_helpers.auto_itinerary_items_for_booking`. If that
    function's mapping changes (e.g. hotel → lodging), update this
    helper too — otherwise map pins will silently disagree with the
    itinerary's colors.
    """
    mapping = {
        "flight": "transit",
        "car": "transit",
        "transport": "transit",
        "hotel": "other",
        "restaurant": "meal",
        "activity": "sightseeing",
        "other": "other",
    }
    return mapping.get(btype, "other")


def _day_index(trip: Trip, the_date) -> Optional[int]:
    """1-based day index within the trip's date range. None when out of range or NULL."""
    if the_date is None or trip.start_date is None:
        return None
    delta = (the_date - trip.start_date).days
    if delta < 0:
        return None
    return delta + 1


def _build_pins_for_trip(trip: Trip) -> List[Pin]:
    """Collect pins for a single trip's bookings + non-linked items.

    De-duplication rule: items with linked_booking_id are skipped — their
    parent booking is the authoritative pin.
    """
    pins: List[Pin] = []
    year = trip.start_date.year if trip.start_date else 0

    for b in trip.bookings:
        if not b.location or b.geocoded_lat is None:
            continue
        category = _booking_category(b.type)
        pins.append(Pin(
            row_type="booking",
            row_id=b.id,
            trip_id=trip.id,
            trip_name=trip.name,
            title=b.title or b.vendor or b.type,
            location_text=b.location,
            lat=b.geocoded_lat,
            lng=b.geocoded_lng,
            geocoded_city=b.geocoded_city,
            geocoded_country_code=b.geocoded_country_code,
            year=year,
            category=category,
            datetime_iso=b.start_datetime.isoformat() if b.start_datetime else None,
            day_index=_day_index(
                trip, b.start_datetime.date() if b.start_datetime else None
            ),
        ))

    for it in trip.itinerary_items:
        if not it.location or it.geocoded_lat is None:
            continue
        if it.linked_booking_id is not None:
            continue
        pins.append(Pin(
            row_type="item",
            row_id=it.id,
            trip_id=trip.id,
            trip_name=trip.name,
            title=it.title,
            location_text=it.location,
            lat=it.geocoded_lat,
            lng=it.geocoded_lng,
            geocoded_city=it.geocoded_city,
            geocoded_country_code=it.geocoded_country_code,
            year=year,
            category=it.category or "other",
            datetime_iso=(
                datetime.combine(it.day_date, it.start_time).isoformat()
                if it.day_date and it.start_time else None
            ),
            day_index=_day_index(trip, it.day_date),
        ))

    return pins


@app.route("/trips/<int:trip_id>/map")
@login_required
def trip_map(trip_id):
    """In-trip map page — shows all geocoded bookings and itinerary items
    as pins on a Mapbox base map. Viewer access is enough to see it."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    no_loc = sum(
        1 for r in list(trip.bookings) + list(trip.itinerary_items)
        if not (r.location or "").strip()
    )
    days = []
    if trip.start_date and trip.end_date:
        n_days = (trip.end_date - trip.start_date).days + 1
        for i in range(n_days):
            d = trip.start_date + timedelta(days=i)
            days.append({
                "index": i + 1,
                "date": d.isoformat(),
                "label": d.strftime("%a %-m/%-d"),
            })
    can_edit = role_satisfies(user_role, "editor")
    has_any_location = any(
        (r.location or "").strip()
        for r in list(trip.bookings) + list(trip.itinerary_items)
    )
    return render_template(
        "trip_map.html",
        trip=trip,
        no_location_count=no_loc,
        trip_days=days,
        can_edit=can_edit,
        has_any_location=has_any_location,
    )


@app.route("/trips/<int:trip_id>/map/data.geojson")
@login_required
def trip_map_data(trip_id):
    """GeoJSON pin data for the in-trip map. Lazy-geocodes rows on the way."""
    trip, _ = _trip_with_access_or_404(trip_id, role="viewer")

    # Lazy-geocode any rows that need it. Only attempt when a token is
    # configured — otherwise the helper would just no-op for every row.
    if MAPBOX_TOKEN:
        rows_with_location = [
            r for r in list(trip.bookings) + list(trip.itinerary_items)
            if (r.location or "").strip()
        ]
        ensure_geocoded(rows_with_location, db_session=db.session, token=MAPBOX_TOKEN)

    pins = _build_pins_for_trip(trip)
    payload = pins_to_geojson(pins, color_fn=lambda p: color_for_category(p.category))
    return jsonify(payload)


def _trip_is_for_lifetime(trip: Trip, today: date) -> bool:
    """True if a trip belongs on the lifetime map (completed or in-progress)."""
    if trip.start_date is None or trip.end_date is None:
        return False
    return trip.start_date <= today  # excludes purely future trips


@app.route("/map")
@login_required
def lifetime_map():
    """Top-level lifetime map page — every place this user has been
    across owned + collaborator trips. Data loads asynchronously from
    ``/map/data.geojson``."""
    today = date.today()
    owned = Trip.query.filter_by(owner_id=current_user.id).all()
    collab_trip_ids = [
        c.trip_id for c in TripCollaborator.query.filter_by(
            email=current_user.email,
        ).all()
    ]
    collab = (
        Trip.query.filter(Trip.id.in_(collab_trip_ids)).all()
        if collab_trip_ids else []
    )
    qualifying = [t for t in owned + collab if _trip_is_for_lifetime(t, today)]
    return render_template(
        "lifetime_map.html",
        has_any_qualifying_trips=bool(qualifying),
    )


@app.route("/map/data.geojson")
@login_required
def lifetime_map_data():
    """GeoJSON for the lifetime map — owned + collaborator trips that have
    started (completed or in progress). Lazy-geocodes rows when a token is
    configured. Pins are returned in chronological trip order so the
    front-end fade-in can replay them in the same sequence."""
    today = date.today()

    owned = Trip.query.filter_by(owner_id=current_user.id).all()
    collab_trip_ids = [
        c.trip_id for c in TripCollaborator.query.filter_by(
            email=current_user.email,
        ).all()
    ]
    collab = (
        Trip.query.filter(Trip.id.in_(collab_trip_ids)).all()
        if collab_trip_ids else []
    )

    all_trips = [t for t in owned + collab if _trip_is_for_lifetime(t, today)]

    if MAPBOX_TOKEN:
        rows = []
        for t in all_trips:
            rows.extend(b for b in t.bookings if (b.location or "").strip())
            rows.extend(i for i in t.itinerary_items if (i.location or "").strip())
        ensure_geocoded(rows, db_session=db.session, token=MAPBOX_TOKEN)

    pins = []
    for t in sorted(all_trips, key=lambda x: x.start_date):
        pins.extend(_build_pins_for_trip(t))

    visited = sorted({p.geocoded_country_code for p in pins if p.geocoded_country_code})
    payload = pins_to_geojson(pins, color_fn=lambda p: color_for_year(p.year))
    payload["meta"] = {"visited_country_codes": visited}
    return jsonify(payload)


@app.route("/trips/<int:trip_id>/map/pin/<string:row_type>/<int:row_id>", methods=["POST"])
@login_required
def trip_map_pin_update(trip_id, row_type, row_id):
    """Editor-only: save a drag-corrected pin position for a booking or
    itinerary item. Marks the row as manually geocoded so future re-
    geocodes don't overwrite the user's correction."""
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")

    payload = request.get_json(silent=True) or {}
    try:
        lat = float(payload["lat"])
        lng = float(payload["lng"])
    except (KeyError, ValueError, TypeError):
        return ("Invalid coordinates", 400)
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        return ("Coordinates out of range", 400)

    if row_type == "booking":
        row = Booking.query.filter_by(id=row_id, trip_id=trip.id).first_or_404()
    elif row_type == "item":
        row = ItineraryItem.query.filter_by(id=row_id, trip_id=trip.id).first_or_404()
    else:
        return ("Unknown row type", 400)

    row.geocoded_lat = lat
    row.geocoded_lng = lng
    row.geocoded_manually = True
    row.geocoded_at = datetime.utcnow()
    db.session.commit()
    return ("", 204)


# ─── Bookings ───────────────────────────────────────────────────────
@app.route("/trips/<int:trip_id>/bookings")
@login_required
def bookings_list(trip_id):
    """List all bookings for this trip, grouped by type.

    Supports a ?type=<code> query param to filter to a single booking type.
    Invalid or missing values silently fall back to "all".
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")

    requested_type = (request.args.get("type") or "").strip().lower()
    active_type = requested_type if requested_type in BOOKING_TYPE_CODES else None

    bookings_query = Booking.query.filter_by(trip_id=trip.id)
    if active_type:
        bookings_query = bookings_query.filter_by(type=active_type)
    bookings = bookings_query.all()
    grouped = group_bookings_by_type(bookings)

    totals = total_cost_by_currency(bookings)
    if totals:
        total_label = " + ".join(
            format_money(amount, code) for code, amount in sorted(totals.items())
        )
    else:
        total_label = ""

    active_type_label = BOOKING_TYPE_LABELS.get(active_type) if active_type else None

    return render_template(
        "bookings_list.html",
        trip=trip,
        user_role=user_role,
        grouped=grouped,
        total_label=total_label,
        booking_types=BOOKING_TYPES,
        active_type=active_type,
        active_type_label=active_type_label,
    )


@app.route("/trips/<int:trip_id>/bookings/new", methods=["GET", "POST"])
@login_required
def booking_new(trip_id):
    """Form to add a booking to this trip. Editor+ only."""
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_booking_form(request.form, default_currency=trip.primary_currency)
        if not is_valid_currency(data["currency"]):
            field_errors["currency"] = "Currency is not supported."
        if field_errors:
            return render_template(
                "booking_form.html",
                trip=trip,
                booking=None,
                form=request.form,
                field_errors=field_errors,
                booking_types=BOOKING_TYPES,
                supported_currencies=SUPPORTED_CURRENCIES,
            )

        booking = Booking(trip_id=trip.id, **data)
        db.session.add(booking)
        # flush to populate booking.id so we can use it in the linked items below.
        db.session.flush()

        # Smart auto-link: spawn linked itinerary items based on the booking type.
        # We filter to items that fall within the trip's date range so a flight
        # booked outside the trip dates doesn't pollute the timeline.
        linked_count = 0
        for item_data in auto_itinerary_items_for_booking(booking):
            day = item_data["day_date"]
            if day < trip.start_date or day > trip.end_date:
                logger.info(
                    "Skipping auto-itinerary item for booking id=%s — day %s outside trip range",
                    booking.id, day,
                )
                continue
            item_data["order_within_day"] = _next_order_within_day(trip.id, day)
            db.session.add(ItineraryItem(
                trip_id=trip.id,
                linked_booking_id=booking.id,
                **item_data,
            ))
            linked_count += 1

        db.session.commit()
        logger.info(
            "Created booking id=%s type=%s title=%r linked_items=%s for trip_id=%s",
            booking.id, booking.type, booking.title, linked_count, trip.id,
        )

        if linked_count > 0:
            noun = "item" if linked_count == 1 else "items"
            flash(
                f"Added booking “{booking.title}”. Created {linked_count} linked itinerary {noun}.",
                "success",
            )
        else:
            flash(f"Added booking “{booking.title}”.", "success")
        return redirect(url_for("bookings_list", trip_id=trip.id))

    # GET — fresh form. Default to a flight + the trip's primary currency.
    return render_template(
        "booking_form.html",
        trip=trip,
        booking=None,
        form={"type": "flight", "currency": trip.primary_currency},
        field_errors={},
        booking_types=BOOKING_TYPES,
        supported_currencies=SUPPORTED_CURRENCIES,
    )


@app.route("/trips/<int:trip_id>/bookings/<int:booking_id>/edit", methods=["GET", "POST"])
@login_required
def booking_edit(trip_id, booking_id):
    """Edit an existing booking. Editor+ only."""
    trip, booking, _ = _booking_with_access_or_404(trip_id, booking_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_booking_form(request.form, default_currency=trip.primary_currency)
        if not is_valid_currency(data["currency"]):
            field_errors["currency"] = "Currency is not supported."
        if field_errors:
            return render_template(
                "booking_form.html",
                trip=trip,
                booking=booking,
                form=request.form,
                field_errors=field_errors,
                booking_types=BOOKING_TYPES,
                supported_currencies=SUPPORTED_CURRENCIES,
            )

        clear_stale_geocode_on_booking_edit(booking, new_location=data["location"])
        for field, value in data.items():
            setattr(booking, field, value)
        db.session.commit()
        logger.info("Edited booking id=%s title=%r", booking.id, booking.title)

        linked_items = ItineraryItem.query.filter_by(
            linked_booking_id=booking.id
        ).all()
        linked_count = len(linked_items)
        existing_kinds = {it.auto_kind for it in linked_items if it.auto_kind}
        new_items = missing_auto_kinds_for_booking(
            booking, existing_kinds, trip.start_date, trip.end_date,
        )
        new_count = len(new_items)

        parts: list = []
        if linked_count > 0:
            parts.append(
                f"{linked_count} linked itinerary item"
                f"{'' if linked_count == 1 else 's'} may now be out of sync"
            )
        if new_count > 0:
            parts.append(
                f"{new_count} new item{'' if new_count == 1 else 's'} available"
            )
        if parts:
            flash(
                f"Booking updated. {', '.join(parts)} — review on the Itinerary page.",
                "success",
            )
        else:
            flash("Booking updated.", "success")
        return redirect(url_for("bookings_list", trip_id=trip.id))

    return render_template(
        "booking_form.html",
        trip=trip,
        booking=booking,
        form=booking_form_values(booking),
        field_errors={},
        booking_types=BOOKING_TYPES,
        supported_currencies=SUPPORTED_CURRENCIES,
    )


@app.route("/trips/<int:trip_id>/bookings/<int:booking_id>/delete", methods=["POST"])
@login_required
def booking_delete(trip_id, booking_id):
    """Delete a booking. Editor+ only."""
    trip, booking, _ = _booking_with_access_or_404(trip_id, booking_id, role="editor")
    title = booking.title
    db.session.delete(booking)
    db.session.commit()
    logger.info("Deleted booking id=%s title=%r", booking_id, title)
    flash(f"Deleted “{title}”.", "success")
    return redirect(url_for("bookings_list", trip_id=trip.id))


# ─── Section placeholders ───────────────────────────────────────────
# Each of these will be replaced with a real page in the step listed.
# They exist now so the section-tile grid on the trip overview never 404s.
def _placeholder_section(trip_id, *, name, emoji, step_number, description):
    trip = _owned_trip_or_404(trip_id)
    return render_template(
        "trip_section_placeholder.html",
        trip=trip,
        section_name=name,
        section_emoji=emoji,
        step_number=step_number,
        description=description,
    )


def _annotate_drift_for_items(items):
    """Annotate each item in-place with a `.drift` attribute (DriftReport or None).

    Pre-fetches all referenced bookings in one query to avoid N+1.
    Returns the count of items with non-None drift, so callers that
    just need the count don't have to re-iterate.
    """
    linked_booking_ids = {it.linked_booking_id for it in items if it.linked_booking_id}
    bookings_by_id = {
        b.id: b for b in Booking.query.filter(Booking.id.in_(linked_booking_ids)).all()
    } if linked_booking_ids else {}

    drift_count = 0
    for it in items:
        it.drift = None
        if not it.linked_booking_id:
            continue
        booking = bookings_by_id.get(it.linked_booking_id)
        if booking is None:
            # Booking row is gone but the cascade didn't clean this item up.
            it.drift = DriftReport(is_orphaned=True)
            drift_count += 1
            continue
        it.drift = detect_drift(it, booking)
        if it.drift is not None:
            drift_count += 1
    return drift_count


def _drift_counts_for_trips(trips: List["Trip"]) -> Dict[int, Tuple[int, int]]:
    """For each trip, return (drift_count, new_items_count).

    Batched: two queries cover all relevant bookings and itinerary items,
    then in-memory grouping. Skips trips whose status is 'completed' or
    whose end_date is before today (drift on a finished trip isn't
    actionable).

    Returns a dict keyed by trip.id. Trips not in the result dict
    implicitly have (0, 0). Used by the dashboard to render per-trip
    pills.
    """
    today = date.today()
    active = [
        t for t in trips
        if t.status != "completed" and t.end_date >= today
    ]
    if not active:
        return {}
    trip_ids = [t.id for t in active]

    bookings = Booking.query.filter(Booking.trip_id.in_(trip_ids)).all()
    items = ItineraryItem.query.filter(
        ItineraryItem.trip_id.in_(trip_ids)
    ).all()

    bookings_by_trip: Dict[int, list] = {}
    bookings_by_id: Dict[int, Any] = {}
    for b in bookings:
        bookings_by_trip.setdefault(b.trip_id, []).append(b)
        bookings_by_id[b.id] = b

    items_by_trip: Dict[int, list] = {}
    existing_kinds_by_booking: Dict[int, set] = {}
    for it in items:
        items_by_trip.setdefault(it.trip_id, []).append(it)
        if it.linked_booking_id and it.auto_kind:
            existing_kinds_by_booking.setdefault(
                it.linked_booking_id, set()
            ).add(it.auto_kind)

    out: Dict[int, Tuple[int, int]] = {}
    for t in active:
        drift = 0
        for it in items_by_trip.get(t.id, []):
            if not it.linked_booking_id:
                continue
            booking = bookings_by_id.get(it.linked_booking_id)
            if booking is None:
                # Orphan: the linked booking is gone but the cascade
                # didn't clean this item up. Count it as drift so the
                # dashboard pill matches what the itinerary page shows
                # via _annotate_drift_for_items.
                drift += 1
                continue
            if detect_drift(it, booking) is not None:
                drift += 1

        new_count = 0
        for b in bookings_by_trip.get(t.id, []):
            existing = existing_kinds_by_booking.get(b.id, set())
            new_count += len(missing_auto_kinds_for_booking(
                b, existing, t.start_date, t.end_date,
            ))

        if drift > 0 or new_count > 0:
            out[t.id] = (drift, new_count)
    return out


def _annotate_new_items_for_trip(trip) -> List["NewItemSuggestion"]:
    """Return every NewItemSuggestion across all bookings for the trip.

    Pre-fetches all bookings and their linked items in two queries to
    avoid N+1.
    """
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    if not bookings:
        return []
    booking_ids = [b.id for b in bookings]
    items = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.in_(booking_ids)
    ).all()
    existing_by_booking: dict = {}
    for it in items:
        if it.auto_kind:
            existing_by_booking.setdefault(it.linked_booking_id, set()).add(it.auto_kind)

    out: List[NewItemSuggestion] = []
    for b in bookings:
        existing = existing_by_booking.get(b.id, set())
        for w in missing_auto_kinds_for_booking(
            b, existing, trip.start_date, trip.end_date,
        ):
            out.append(NewItemSuggestion(
                booking=b, auto_kind=w["auto_kind"], item_data=w,
            ))
    return out


@app.route("/trips/<int:trip_id>/itinerary")
@login_required
def trip_itinerary(trip_id):
    """Day-by-day timeline view. Viewer+ access."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    drift_count = _annotate_drift_for_items(items)
    new_items_count = len(_annotate_new_items_for_trip(trip))
    days = group_items_by_day(items, trip.start_date, trip.end_date)
    initial_day = initial_day_index(trip.start_date, trip.end_date, date.today())
    return render_template(
        "trip_itinerary.html",
        trip=trip,
        user_role=user_role,
        days=days,
        initial_day=initial_day,
        drift_count=drift_count,
        new_items_count=new_items_count,
    )


@app.route("/trips/<int:trip_id>/itinerary/new", methods=["GET", "POST"])
@login_required
def itinerary_new(trip_id):
    """Form to add an itinerary item.

    Accepts ?day=YYYY-MM-DD on GET to prefill the day field — used by the
    "Add to this day" button on each day column of the timeline.
    Editor+ only.
    """
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_itinerary_form(request.form, trip.start_date, trip.end_date)
        if field_errors:
            return render_template(
                "itinerary_form.html",
                trip=trip,
                item=None,
                form=request.form,
                field_errors=field_errors,
                itinerary_categories=ITINERARY_CATEGORIES,
            )

        data["order_within_day"] = _next_order_within_day(trip.id, data["day_date"])
        item = ItineraryItem(trip_id=trip.id, **data)
        db.session.add(item)
        db.session.commit()
        logger.info(
            "Created itinerary item id=%s title=%r day=%s for trip_id=%s",
            item.id, item.title, item.day_date, trip.id,
        )
        flash(f"Added “{item.title}”.", "success")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    # GET — fresh form. Prefill the day if one was passed in the query string.
    requested_day = (request.args.get("day") or "").strip()
    prefill_day = trip.start_date.isoformat()
    if requested_day:
        try:
            d = date.fromisoformat(requested_day)
            if trip.start_date <= d <= trip.end_date:
                prefill_day = d.isoformat()
        except ValueError:
            logger.warning("itinerary_new ignored bad ?day=%r", requested_day)

    return render_template(
        "itinerary_form.html",
        trip=trip,
        item=None,
        form={"category": "sightseeing", "day_date": prefill_day},
        field_errors={},
        itinerary_categories=ITINERARY_CATEGORIES,
    )


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def itinerary_edit(trip_id, item_id):
    """Edit an existing itinerary item. Editor+ only."""
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_itinerary_form(request.form, trip.start_date, trip.end_date)
        if field_errors:
            return render_template(
                "itinerary_form.html",
                trip=trip,
                item=item,
                form=request.form,
                field_errors=field_errors,
                itinerary_categories=ITINERARY_CATEGORIES,
            )

        # If the day moved, give the item a fresh sort key on the new day.
        if data["day_date"] != item.day_date:
            data["order_within_day"] = _next_order_within_day(trip.id, data["day_date"])

        # Compute which DRIFT_FIELDS actually changed value, BEFORE writing.
        # parse_itinerary_form returns a dict with all DRIFT_FIELDS keys
        # (title, category, day_date, start_time, end_time, location) plus
        # `notes` — so data.get(f) is safe to compare for every f in DRIFT_FIELDS.
        changed_fields: set = set()
        if item.linked_booking_id is not None:
            for f in DRIFT_FIELDS:
                if data.get(f) != getattr(item, f):
                    changed_fields.add(f)

        clear_stale_geocode_on_item_edit(item, new_location=data["location"])
        for field, value in data.items():
            setattr(item, field, value)

        if item.linked_booking_id is not None and changed_fields:
            prior = parse_touched(item.auto_fields_touched)
            item.auto_fields_touched = serialize_touched(prior | changed_fields)
        db.session.commit()
        logger.info("Edited itinerary item id=%s title=%r", item.id, item.title)
        flash("Itinerary item updated.", "success")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    return render_template(
        "itinerary_form.html",
        trip=trip,
        item=item,
        form=itinerary_form_values(item),
        field_errors={},
        itinerary_categories=ITINERARY_CATEGORIES,
    )


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/delete", methods=["POST"])
@login_required
def itinerary_delete(trip_id, item_id):
    """Delete an itinerary item. Editor+ only."""
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    title = item.title
    db.session.delete(item)
    db.session.commit()
    logger.info("Deleted itinerary item id=%s title=%r", item_id, title)
    flash(f"Deleted “{title}”.", "success")
    return redirect(url_for("trip_itinerary", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/itinerary/drift-review")
@login_required
def itinerary_drift_review(trip_id):
    """Landing page for the drift review wizard. Viewer+ access.

    Shows total / resyncable / orphan counts and two CTAs (Start
    review, Resync N unchanged). Doubles as the "all done" view when
    the wizard finishes.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    resyncable = [it for it in drifting if not it.drift.is_orphaned]
    orphans = [it for it in drifting if it.drift.is_orphaned]
    new_items = _annotate_new_items_for_trip(trip)
    return render_template(
        "drift_review.html",
        trip=trip,
        user_role=user_role,
        drift_count=len(drifting),
        resyncable_count=len(resyncable),
        orphans=orphans,
        first_drifting_id=drifting[0].id if drifting else None,
        new_items=new_items,
    )


@app.route("/trips/<int:trip_id>/itinerary/drift-review/item/<int:item_id>")
@login_required
def itinerary_drift_review_item(trip_id, item_id):
    """One wizard step — render one drifting item's diff and actions.
    Viewer+ access (the action POSTs still require editor).

    Redirects back to the landing page if the item isn't drifting (e.g.,
    user bookmarked the URL and the drift has since been resolved).
    """
    trip, item, user_role = _itinerary_item_with_access_or_404(
        trip_id, item_id, role="viewer"
    )
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]

    current = next((it for it in drifting if it.id == item_id), None)
    if current is None:
        flash("That item isn't out of sync — nothing to review.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    idx = drifting.index(current)
    next_item = drifting[idx + 1] if idx + 1 < len(drifting) else None
    booking = (
        db.session.get(Booking, current.linked_booking_id)
        if current.linked_booking_id else None
    )
    return render_template(
        "drift_review_item.html",
        trip=trip,
        user_role=user_role,
        item=current,
        booking=booking,
        drift=current.drift,
        next_item=next_item,
        progress_current=idx + 1,
        progress_total=len(drifting),
    )


@app.route(
    "/trips/<int:trip_id>/itinerary/drift-review/bulk-resync",
    methods=["GET", "POST"],
)
@login_required
def itinerary_drift_review_bulk_resync(trip_id):
    """Confirmation page (GET) + bulk apply (POST). Editor+ access.

    Lists every eligible item (drifting + not orphaned) with its diff.
    Flags the count of orphaned items being skipped. Redirects back to
    the landing page if no eligible items exist.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="editor")
    items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
    _annotate_drift_for_items(items)
    drifting = [it for it in chronological_order(items) if it.drift is not None]
    eligible = [it for it in drifting if not it.drift.is_orphaned]
    orphan_count = sum(1 for it in drifting if it.drift.is_orphaned)

    if not eligible:
        flash("Nothing to bulk-resync — all drifting items need individual review.",
              "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    if request.method == "POST":
        # Re-fetch each item's booking (avoid trusting stale objects),
        # then apply resync. Single commit covers all items. We ignore
        # the per-call was_last flag — see below for the trip-level check.
        updated = 0
        for it in eligible:
            booking = db.session.get(Booking, it.linked_booking_id)
            if booking is None:
                continue
            applied, _ = _apply_resync_to_item(it, booking)
            if applied:
                updated += 1
        db.session.commit()
        logger.info("Bulk-resynced %d itinerary items for trip_id=%s",
                    updated, trip.id)

        # After the bulk commit, recompute whether any drift remains
        # on the trip. If not, use the celebration flash.
        remaining_items = ItineraryItem.query.filter_by(trip_id=trip.id).all()
        any_drift_left = _annotate_drift_for_items(remaining_items) > 0
        if updated > 0 and not any_drift_left:
            flash("Everything is in sync with your bookings ✓", "success-celebrate")
        else:
            flash(
                f"Resynced {updated} item{'' if updated == 1 else 's'} to "
                f"{'its' if updated == 1 else 'their'} booking"
                f"{'' if updated == 1 else 's'}.",
                "success",
            )
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    return render_template(
        "drift_bulk_resync_confirm.html",
        trip=trip,
        user_role=user_role,
        eligible=eligible,
        eligible_count=len(eligible),
        orphan_count=orphan_count,
    )


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/drift")
@login_required
def itinerary_drift(trip_id, item_id):
    """Show the drift report for a linked itinerary item. Viewer+ access."""
    trip, item, user_role = _itinerary_item_with_access_or_404(
        trip_id, item_id, role="viewer"
    )
    if item.linked_booking_id is None:
        flash("This item isn't linked to a booking.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    booking = db.session.get(Booking, item.linked_booking_id)
    if booking is None:
        flash("The linked booking is gone — try Unlink instead.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    drift = detect_drift(item, booking)
    return render_template(
        "itinerary_drift.html",
        trip=trip,
        item=item,
        booking=booking,
        drift=drift,
        user_role=user_role,
    )


def _apply_resync_to_item(item, booking) -> Tuple[bool, bool]:
    """Apply the booking's auto-generated values to one item.

    Only overwrites fields that the user hasn't personally touched
    (auto_fields_touched). The touched set itself is preserved, so a
    user who touched `title` will continue to keep their title across
    future resyncs — by design, per the phase-3 spec.

    Returns:
        (applied, was_last_drift_on_trip)

        applied is True when the item was updated, False when the
        booking no longer generates an item of this auto_kind
        (orphaned slot — caller should suggest Unlink/Delete).

        was_last_drift_on_trip is True when, after this resync, no
        remaining drifting items exist on the trip. Caller uses this
        to pick the celebration flash variant. False when applied is
        False.

    was_last_drift_on_trip is computed BEFORE the caller commits, using
    the in-memory item state after the setattr loop above. detect_drift
    is pure and reads attributes directly, so it correctly sees the
    post-resync values on this item even though they haven't been
    flushed to the DB yet.
    """
    would_be_items = auto_itinerary_items_for_booking(booking)
    matches = [w for w in would_be_items if w.get("auto_kind") == item.auto_kind]
    if not matches:
        return (False, False)
    would_be = matches[0]
    touched = parse_touched(item.auto_fields_touched)
    for f in DRIFT_FIELDS:
        if f in touched:
            continue
        setattr(item, f, would_be.get(f))
    # auto_fields_touched preserved intentionally.

    # Compute was_last_drift on the trip by checking every other linked
    # item against its booking. The item we just resynced is included —
    # detect_drift on it will return None now, so it doesn't count.
    remaining = ItineraryItem.query.filter_by(trip_id=item.trip_id).all()
    booking_ids = {it.linked_booking_id for it in remaining if it.linked_booking_id}
    bookings_by_id = {
        b.id: b for b in Booking.query.filter(Booking.id.in_(booking_ids)).all()
    } if booking_ids else {}
    was_last = True
    for it in remaining:
        if not it.linked_booking_id:
            continue
        b = bookings_by_id.get(it.linked_booking_id)
        if b is None:
            # Orphan — counts as drift, so this is not the last.
            was_last = False
            break
        if detect_drift(it, b) is not None:
            was_last = False
            break
    return (True, was_last)


def _redirect_after_wizard_action(trip_id: int, current_item_id: int):
    """After a wizard-originated action, redirect to the next drifting
    item's wizard step — or to the landing page if no more drift.

    The "next" is computed against the chronological position of
    `current_item_id` in the full trip, which works even after the
    action has cleared drift on the current item.
    """
    items = ItineraryItem.query.filter_by(trip_id=trip_id).all()
    _annotate_drift_for_items(items)
    all_ordered = chronological_order(items)
    current_pos = next(
        (i for i, it in enumerate(all_ordered) if it.id == current_item_id),
        -1,
    )
    next_item = next(
        (it for i, it in enumerate(all_ordered)
         if i > current_pos and it.drift is not None),
        None,
    )
    if next_item is not None:
        return redirect(url_for(
            "itinerary_drift_review_item",
            trip_id=trip_id, item_id=next_item.id,
        ))
    return redirect(url_for("itinerary_drift_review", trip_id=trip_id))


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/resync", methods=["POST"])
@login_required
def itinerary_resync(trip_id, item_id):
    """Re-apply the auto-generated values from the linked booking. Editor+ only.

    Updates only fields the user hasn't personally touched (auto_fields_touched
    is preserved across resync — touched fields stay the user's). Leaves
    linked_booking_id intact.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    if item.linked_booking_id is None:
        flash("This item isn’t linked to a booking.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    booking = db.session.get(Booking, item.linked_booking_id)
    if booking is None:
        flash("The linked booking is gone — try Unlink instead.", "warning")
        return redirect(url_for("trip_itinerary", trip_id=trip.id))

    applied, was_last = _apply_resync_to_item(item, booking)
    if not applied:
        flash(
            "The booking no longer suggests this item. Use Unlink or Delete.",
            "warning",
        )
        return redirect(url_for("trip_itinerary", trip_id=trip.id))
    db.session.commit()
    logger.info("Resynced itinerary item id=%s from booking id=%s",
                item.id, booking.id)
    if was_last:
        flash("Everything is in sync with your bookings ✓", "success-celebrate")
    else:
        flash(f'Resynced "{item.title}" to the booking.', "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id, just_synced=item.id))


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/keep-mine", methods=["POST"])
@login_required
def itinerary_keep_mine(trip_id, item_id):
    """Silence drift detection for this item by marking every field as
    user-touched. Editor+ only."""
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.auto_fields_touched = serialize_touched(DRIFT_FIELDS)
    db.session.commit()
    logger.info("Marked itinerary item id=%s as fully touched (keep mine)", item.id)
    flash(f"Kept your version of “{item.title}”.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/itinerary/<int:item_id>/unlink", methods=["POST"])
@login_required
def itinerary_unlink(trip_id, item_id):
    """Sever the booking link. Editor+ only.

    Sets linked_booking_id and auto_kind to NULL and clears the touched
    set — the item becomes a plain stand-alone itinerary entry.
    """
    trip, item, _ = _itinerary_item_with_access_or_404(trip_id, item_id, role="editor")
    item.linked_booking_id = None
    item.auto_kind = None
    item.auto_fields_touched = ""
    db.session.commit()
    logger.info("Unlinked itinerary item id=%s from its booking", item.id)
    flash(f"Unlinked “{item.title}” from its booking.", "success")
    if request.args.get("from") == "wizard":
        return _redirect_after_wizard_action(trip.id, item.id)
    return redirect(url_for("trip_itinerary", trip_id=trip.id))


@app.route(
    "/trips/<int:trip_id>/itinerary/add-suggested/<int:booking_id>/<string:auto_kind>",
    methods=["POST"],
)
@login_required
def itinerary_add_suggested(trip_id, booking_id, auto_kind):
    """Create one new linked itinerary item from a booking's suggestion.

    Editor+ only. Re-derives the missing list to verify the slot really is
    missing (in case of concurrent state). Redirects to drift review.
    """
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")
    booking = db.session.get(Booking, booking_id)
    if booking is None or booking.trip_id != trip.id:
        flash("That booking doesn't exist.", "warning")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    existing_kinds = {
        it.auto_kind for it in ItineraryItem.query.filter_by(
            linked_booking_id=booking.id
        ).all() if it.auto_kind
    }
    missing = missing_auto_kinds_for_booking(
        booking, existing_kinds, trip.start_date, trip.end_date,
    )
    match = next((w for w in missing if w["auto_kind"] == auto_kind), None)
    if match is None:
        flash("That item already exists or is no longer suggested.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    match["order_within_day"] = _next_order_within_day(trip.id, match["day_date"])
    item = ItineraryItem(
        trip_id=trip.id,
        linked_booking_id=booking.id,
        auto_fields_touched="",
        **match,
    )
    db.session.add(item)
    db.session.commit()
    logger.info(
        "Added suggested item id=%s kind=%s for booking id=%s",
        item.id, auto_kind, booking.id,
    )
    flash(
        f"Added “{item.title}” to {item.day_date.strftime('%a, %b %d')}.",
        "success",
    )
    return redirect(url_for("itinerary_drift_review", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/itinerary/add-all-suggested", methods=["GET"])
@login_required
def itinerary_add_all_suggested_confirm(trip_id):
    """Confirmation page listing every missing item that would be added.

    Viewer+ to view; the submit button only renders for editor+ in the
    template.
    """
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    new_items = _annotate_new_items_for_trip(trip)
    return render_template(
        "drift_bulk_add_confirm.html",
        trip=trip,
        user_role=user_role,
        new_items=new_items,
    )


@app.route("/trips/<int:trip_id>/itinerary/add-all-suggested", methods=["POST"])
@login_required
def itinerary_add_all_suggested(trip_id):
    """Add every missing suggested item across all bookings on this trip.

    Editor+ only. Re-derives the missing list per booking to avoid
    duplicates from concurrent state changes. One commit per request.
    """
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    if not bookings:
        flash("No bookings on this trip.", "info")
        return redirect(url_for("itinerary_drift_review", trip_id=trip.id))

    booking_ids = [b.id for b in bookings]
    items = ItineraryItem.query.filter(
        ItineraryItem.linked_booking_id.in_(booking_ids)
    ).all()
    existing_by_booking: dict = {}
    for it in items:
        if it.auto_kind:
            existing_by_booking.setdefault(it.linked_booking_id, set()).add(it.auto_kind)

    added = 0
    for b in bookings:
        existing = existing_by_booking.get(b.id, set())
        for w in missing_auto_kinds_for_booking(
            b, existing, trip.start_date, trip.end_date,
        ):
            w["order_within_day"] = _next_order_within_day(trip.id, w["day_date"])
            db.session.add(ItineraryItem(
                trip_id=trip.id,
                linked_booking_id=b.id,
                auto_fields_touched="",
                **w,
            ))
            added += 1
    db.session.commit()
    logger.info("Bulk-added %d suggested items for trip_id=%s", added, trip.id)
    if added == 0:
        flash("No new suggestions to add.", "info")
    else:
        flash(
            f"Added {added} suggested item{'' if added == 1 else 's'}.",
            "success",
        )
    return redirect(url_for("itinerary_drift_review", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/budget")
@login_required
def trip_budget(trip_id):
    """Auto-rollup of booking costs by category. No data of its own. Viewer+."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    bookings = Booking.query.filter_by(trip_id=trip.id).all()
    categories = rollup_bookings_by_category(
        bookings, primary_currency=trip.primary_currency
    )

    # Grand total = sum across every category's per-currency totals.
    grand_totals: dict = {}
    for cat in categories:
        for code, amount in cat["totals_by_currency"].items():
            grand_totals[code] = grand_totals.get(code, 0.0) + amount
    grand_total_label = format_money_totals(grand_totals, empty="No costs entered yet")

    total_uncosted = sum(cat["uncosted_count"] for cat in categories)

    return render_template(
        "trip_budget.html",
        trip=trip,
        user_role=user_role,
        categories=categories,
        grand_total_label=grand_total_label,
        total_bookings=len(bookings),
        total_uncosted=total_uncosted,
    )


@app.route("/trips/<int:trip_id>/packing")
@login_required
def trip_packing(trip_id):
    """Packing list grouped by category, with progress bar. Viewer+."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    items = PackingItem.query.filter_by(trip_id=trip.id).all()
    grouped = group_packing_by_category(items)
    packed_count, total, percent = packing_progress(items)
    return render_template(
        "trip_packing.html",
        trip=trip,
        user_role=user_role,
        grouped=grouped,
        packed_count=packed_count,
        total=total,
        percent=percent,
    )


@app.route("/trips/<int:trip_id>/packing/new", methods=["GET", "POST"])
@login_required
def packing_new(trip_id):
    """Form to add a packing item. Editor+ only."""
    trip, _ = _trip_with_access_or_404(trip_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_packing_form(request.form)
        if field_errors:
            return render_template(
                "packing_form.html",
                trip=trip,
                item=None,
                form=request.form,
                field_errors=field_errors,
                packing_categories=PACKING_CATEGORIES,
            )

        item = PackingItem(trip_id=trip.id, **data)
        db.session.add(item)
        db.session.commit()
        logger.info(
            "Created packing item id=%s name=%r for trip_id=%s",
            item.id, item.name, trip.id,
        )
        flash(f"Added “{item.name}”.", "success")
        return redirect(url_for("trip_packing", trip_id=trip.id))

    return render_template(
        "packing_form.html",
        trip=trip,
        item=None,
        form={"category": "other"},
        field_errors={},
        packing_categories=PACKING_CATEGORIES,
    )


@app.route("/trips/<int:trip_id>/packing/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def packing_edit(trip_id, item_id):
    """Edit an existing packing item. Editor+ only."""
    trip, item, _ = _packing_item_with_access_or_404(trip_id, item_id, role="editor")

    if request.method == "POST":
        data, field_errors = parse_packing_form(request.form)
        if field_errors:
            return render_template(
                "packing_form.html",
                trip=trip,
                item=item,
                form=request.form,
                field_errors=field_errors,
                packing_categories=PACKING_CATEGORIES,
            )
        for field, value in data.items():
            setattr(item, field, value)
        db.session.commit()
        logger.info("Edited packing item id=%s name=%r", item.id, item.name)
        flash("Item updated.", "success")
        return redirect(url_for("trip_packing", trip_id=trip.id))

    return render_template(
        "packing_form.html",
        trip=trip,
        item=item,
        form=packing_form_values(item),
        field_errors={},
        packing_categories=PACKING_CATEGORIES,
    )


@app.route("/trips/<int:trip_id>/packing/<int:item_id>/toggle", methods=["POST"])
@login_required
def packing_toggle(trip_id, item_id):
    """Flip the packed state of an item. Called by the row checkbox. Editor+."""
    trip, item, _ = _packing_item_with_access_or_404(trip_id, item_id, role="editor")
    item.packed = not item.packed
    db.session.commit()
    return redirect(url_for("trip_packing", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/packing/<int:item_id>/delete", methods=["POST"])
@login_required
def packing_delete(trip_id, item_id):
    """Delete a packing item. Editor+ only."""
    trip, item, _ = _packing_item_with_access_or_404(trip_id, item_id, role="editor")
    name = item.name
    db.session.delete(item)
    db.session.commit()
    logger.info("Deleted packing item id=%s name=%r", item_id, name)
    flash(f"Deleted “{name}”.", "success")
    return redirect(url_for("trip_packing", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/share")
@login_required
def trip_share(trip_id):
    """View collaborators (anyone with access) + add/remove (owner only)."""
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    collaborators = (
        TripCollaborator.query
        .filter_by(trip_id=trip.id)
        .order_by(TripCollaborator.added_at.asc())
        .all()
    )
    owner = User.query.get(trip.owner_id)
    return render_template(
        "trip_share.html",
        trip=trip,
        user_role=user_role,
        owner=owner,
        collaborators=collaborators,
        share_roles=SHARE_ROLES,
        form={},
        field_errors={},
    )


@app.route("/trips/<int:trip_id>/share/add", methods=["POST"])
@login_required
def share_add(trip_id):
    """Owner-only: add a collaborator by email."""
    trip = _owned_trip_or_404(trip_id)
    owner = User.query.get(trip.owner_id)
    existing = TripCollaborator.query.filter_by(trip_id=trip.id).all()
    existing_emails = [c.email for c in existing]

    data, field_errors = parse_collaborator_form(
        request.form,
        owner_email=owner.email,
        existing_emails=existing_emails,
    )
    if field_errors:
        # Re-render the share page with the failed input pre-filled.
        return render_template(
            "trip_share.html",
            trip=trip,
            user_role="owner",
            owner=owner,
            collaborators=existing,
            share_roles=SHARE_ROLES,
            form=request.form,
            field_errors=field_errors,
        )

    collab = TripCollaborator(trip_id=trip.id, **data)
    db.session.add(collab)
    db.session.commit()
    logger.info(
        "Added collaborator email=%s role=%s to trip_id=%s",
        collab.email, collab.role, trip.id,
    )
    flash(f"Shared with {collab.email} as {collab.role}.", "success")
    return redirect(url_for("trip_share", trip_id=trip.id))


@app.route("/trips/<int:trip_id>/share/<int:collab_id>/remove", methods=["POST"])
@login_required
def share_remove(trip_id, collab_id):
    """Owner-only: remove a collaborator."""
    trip = _owned_trip_or_404(trip_id)
    collab = TripCollaborator.query.get(collab_id)
    if collab is None or collab.trip_id != trip.id:
        abort(404)
    email = collab.email
    db.session.delete(collab)
    db.session.commit()
    logger.info("Removed collaborator email=%s from trip_id=%s", email, trip.id)
    flash(f"Removed {email} from this trip.", "success")
    return redirect(url_for("trip_share", trip_id=trip.id))


# ─── Local entry point ──────────────────────────────────────────────
def _run_startup_backup() -> None:
    """Run the SQLite backup script before the dev server starts.

    Wrapped in a try/except so a backup failure can never prevent the
    app from starting. Skipped automatically if the DB file doesn't
    exist yet (fresh install) or if the script is missing.
    """
    project_dir = Path(__file__).resolve().parent
    db_file = project_dir / "vacation.db"
    backup_script = project_dir / "scripts" / "backup_db.sh"

    if not db_file.exists():
        logger.info("Startup backup skipped — no database file yet")
        return
    if not backup_script.exists():
        logger.warning("Startup backup skipped — script not found at %s", backup_script)
        return

    try:
        # `timeout=30` means: if the backup hangs for any reason, give
        # up after 30 seconds rather than blocking the app from starting.
        result = subprocess.run(
            ["/bin/bash", str(backup_script)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Startup backup OK")
        else:
            logger.error(
                "Startup backup failed (exit %d): %s",
                result.returncode,
                result.stderr.strip(),
            )
    except Exception as e:
        logger.error("Startup backup raised an exception: %s", e)


if __name__ == "__main__":
    _run_startup_backup()
    app.run(debug=True, host="127.0.0.1", port=5002)
