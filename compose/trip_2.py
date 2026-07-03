"""
Compose Trip 2 (Scandinavia '26) Deep-tier trip guide end-to-end.
Validation pass for Phase 2a markup: practical-link wraps, walkchip emission,
multi-hotel things_to_do skip, transit-day skip.

Author: Claude Code session 2026-06-27
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("compose_trip2")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if not os.environ.get("MAPBOX_TOKEN"):
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("MAPBOX_TOKEN="):
                os.environ["MAPBOX_TOKEN"] = line.split("=", 1)[1].strip().strip('"\'')
                break
os.environ.pop("DATABASE_URL", None)

from app import app, db
from models import Booking, ItineraryItem
from src import guide_builder
from src.data_check import find_hotel_night_gaps, HotelNightGap
from src.geocoding import geocode_with_cache
from src.place_links import maps_url, practical_link
from src.walking_distance import walking_chip
from src.guide_emit import (
    esc, emit_h2, emit_practical_link, emit_walking_chip, category_color,
    emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper,
    emit_section_wrapper,
)

TRIP_ID = 2
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()
GEN_DATE_STR = "2026-06-27"

# ============================================================================
# PALETTE + ERAS
# ============================================================================

PALETTE = {
    "name": "nordlys",
    "colors": {
        "bg":          "#0e131a",
        "surface":     "#1a212c",
        "ink":         "#e9e6dd",
        "ink_soft":    "#a8a39a",
        "ink_display": "#f5f0e3",
        "accent":      "#7ec8b1",
        "accent_2":    "#d59a6a",
        "muted":       "#6b7889",
        "hairline":    "#2a323f",
        "warning":     "#e07c5b",
    },
    "fonts": {
        "display": "Fraunces",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
}

ERAS = [
    {"slug": "viking",       "label": "Viking",       "hex": "#7a8b5c", "year_range": "793–1066"},
    {"slug": "medieval",     "label": "Medieval",     "hex": "#9a7140", "year_range": "1066–1500"},
    {"slug": "early-modern", "label": "Early Modern", "hex": "#6b8aa0", "year_range": "1500–1800"},
    {"slug": "modern",       "label": "Modern",       "hex": "#c97f3a", "year_range": "1800–1945"},
    {"slug": "contemporary", "label": "Contemporary", "hex": "#7ec8b1", "year_range": "1945–today"},
]

# ============================================================================
# VENUES
# ============================================================================

NAMED_VENUES = [
    # Oslo
    ("Vigeland Sculpture Park", "Oslo, Norway"),
    ("Oslo Opera House", "Oslo, Norway"),
    ("Munch Museum", "Oslo, Norway"),
    ("Akershus Fortress", "Oslo, Norway"),
    ("Viking Ship Museum", "Oslo, Norway"),
    ("Bygdøy peninsula", "Oslo, Norway"),
    ("Mathallen Oslo", "Oslo, Norway"),
    ("Grünerløkka", "Oslo, Norway"),
    ("Sørenga Sjøbad", "Oslo, Norway"),
    ("Maaemo", "Oslo, Norway"),
    ("Hot Shop", "Oslo, Norway"),
    ("Tim Wendelboe", "Oslo, Norway"),
    # Svalbard
    ("Svalbard Museum", "Longyearbyen, Svalbard"),
    ("Global Seed Vault", "Longyearbyen, Svalbard"),
    ("Camp Barentz", "Longyearbyen, Svalbard"),
    ("Huset", "Longyearbyen, Svalbard"),
    ("Fruene Coffee", "Longyearbyen, Svalbard"),
    ("Karlsberger Pub", "Longyearbyen, Svalbard"),
    # Tromsø
    ("Polaria", "Tromsø, Norway"),
    ("Arctic Cathedral", "Tromsø, Norway"),
    ("Tromsø Cable Car", "Tromsø, Norway"),
    ("Mack Brewery", "Tromsø, Norway"),
    ("Fiskekompaniet", "Tromsø, Norway"),
    # Lofoten / Reine
    ("Reinebringen", "Reine, Lofoten, Norway"),
    ("Hamnøy", "Lofoten, Norway"),
    ("Å i Lofoten", "Lofoten, Norway"),
    ("Nusfjord", "Lofoten, Norway"),
    ("Henningsvær", "Lofoten, Norway"),
    ("Anita's Sjømat", "Sakrisøy, Lofoten, Norway"),
    # Flåm / Bergen
    ("Flåm Railway", "Flåm, Norway"),
    ("Stegastein viewpoint", "Aurland, Norway"),
    ("Bryggen", "Bergen, Norway"),
    ("Fløibanen funicular", "Bergen, Norway"),
    ("Fish Market", "Bergen, Norway"),
    ("Lysverket", "Bergen, Norway"),
    # Helsinki
    ("Helsinki Cathedral", "Helsinki, Finland"),
    ("Senate Square", "Helsinki, Finland"),
    ("Suomenlinna", "Helsinki, Finland"),
    ("Temppeliaukio Church", "Helsinki, Finland"),
    ("Oodi Library", "Helsinki, Finland"),
    ("Old Market Hall", "Helsinki, Finland"),
    ("Löyly", "Helsinki, Finland"),
    ("Olo Restaurant", "Helsinki, Finland"),
    ("Café Regatta", "Helsinki, Finland"),
    # Tallinn
    ("Tallinn Old Town", "Tallinn, Estonia"),
    ("Toompea Hill", "Tallinn, Estonia"),
    ("Alexander Nevsky Cathedral", "Tallinn, Estonia"),
    ("Kohtuotsa viewing platform", "Tallinn, Estonia"),
    ("Kadriorg Palace", "Tallinn, Estonia"),
    ("Telliskivi Creative City", "Tallinn, Estonia"),
    ("Põhjala Tap Room", "Tallinn, Estonia"),
    ("Rataskaevu 16", "Tallinn, Estonia"),
    # Stockholm
    ("Vasa Museum", "Stockholm, Sweden"),
    ("Gamla Stan", "Stockholm, Sweden"),
    ("Royal Palace Stockholm", "Stockholm, Sweden"),
    ("Skansen", "Stockholm, Sweden"),
    ("Fotografiska", "Stockholm, Sweden"),
    ("Östermalms Saluhall", "Stockholm, Sweden"),
    ("Pelikan", "Stockholm, Sweden"),
    ("Drop Coffee", "Stockholm, Sweden"),
    # Copenhagen
    ("Nyhavn", "Copenhagen, Denmark"),
    ("Tivoli Gardens", "Copenhagen, Denmark"),
    ("Christiansborg Palace", "Copenhagen, Denmark"),
    ("Rosenborg Castle", "Copenhagen, Denmark"),
    ("Rundetårn", "Copenhagen, Denmark"),
    ("Torvehallerne", "Copenhagen, Denmark"),
    ("Noma", "Copenhagen, Denmark"),
    ("Geranium", "Copenhagen, Denmark"),
    ("Apollo Bar", "Copenhagen, Denmark"),
    ("Mikkeller Bar", "Copenhagen, Denmark"),
    ("Refshaleøen", "Copenhagen, Denmark"),
    ("Christiania", "Copenhagen, Denmark"),
    # Beer venues (new for Phase 2a fix)
    ("Crow Bryggeri", "Oslo, Norway"),
    ("Schouskjelleren Mikrobryggeri", "Oslo, Norway"),
    ("Cervisiam", "Oslo, Norway"),
    ("Bryggeri RorBua", "Tromsø, Norway"),
    ("7 Fjell Brewery", "Bergen, Norway"),
    ("Henrik Øl- og Vinstove", "Bergen, Norway"),
    ("Bryggeri Helsinki", "Helsinki, Finland"),
    ("Suomenlinnan Panimo", "Suomenlinna, Helsinki, Finland"),
    ("Pudel Baar", "Tallinn, Estonia"),
    ("Akkurat", "Stockholm, Sweden"),
    ("Omnipollos hatt", "Stockholm, Sweden"),
    ("Warpigs Brewpub", "Copenhagen, Denmark"),
    ("Brus", "Copenhagen, Denmark"),
    ("To Øl City", "Copenhagen, Denmark"),
]


def geocode_all_venues() -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Optional[float]]]:
    """Geocode every named venue. Returns (coords_by_key, relevance_by_key).

    Relevance is Mapbox's match confidence (0.0–1.0); None on cache hits or
    when Mapbox didn't supply one. Consumed by walking_chip's
    venue_confidence param to skip chips on low-confidence (often
    city-centroid) fallbacks.
    """
    coords: Dict[str, Tuple[float, float]] = {}
    relevance: Dict[str, Optional[float]] = {}
    if not MAPBOX_TOKEN:
        return coords, relevance
    with app.app_context():
        for name, city_country in NAMED_VENUES:
            key = name.lower()
            result = geocode_with_cache(
                text=f"{name}, {city_country}",
                db_session=db.session,
                token=MAPBOX_TOKEN,
            )
            if result is not None:
                coords[key] = (result.lat, result.lng)
                relevance[key] = result.relevance
        db.session.commit()
    return coords, relevance


# venue lookup helper, dual-citified: tries multiple keys
def venue_xy(coords: Dict[str, Tuple[float, float]], name: str) -> Optional[Tuple[float, float]]:
    return coords.get(name.lower())


# ============================================================================
# HOTELS
# ============================================================================

def load_hotels() -> List[Dict[str, Any]]:
    with app.app_context():
        rows = (Booking.query
                .filter_by(trip_id=TRIP_ID, type='hotel')
                .order_by(Booking.start_datetime)
                .all())
        return [{
            "id": h.id,
            "title": pretty_hotel_name(h),
            "city": _hotel_city(h),
            "start_date": h.start_datetime.date() if h.start_datetime else None,
            "end_date": h.end_datetime.date() if h.end_datetime else None,
            "address": h.location or "",
            "lat": h.geocoded_lat,
            "lng": h.geocoded_lng,
        } for h in rows]


def pretty_hotel_name(h: Booking) -> str:
    """Trim 'CityName -> ' prefix from titles, prefer vendor when sensible."""
    title = (h.title or "").strip()
    vendor = (h.vendor or "").strip()
    # Strip "City -> " prefix
    if " -> " in title:
        title = title.split(" -> ", 1)[1].strip()
    if "|" in title:
        title = title.split("|", 1)[1].strip()
    # Use vendor if it looks cleaner and not blank
    if vendor and not vendor.lower().startswith("booking"):
        # If title starts with vendor word, use title (more specific)
        if vendor.lower().split()[0] in title.lower():
            return title
        return vendor
    return title or vendor or "Hotel"


def _hotel_city(h: Booking) -> str:
    """Extract city from the title 'City -> Hotel' pattern or vendor."""
    title = (h.title or "")
    if " -> " in title:
        return title.split(" -> ", 1)[0].strip()
    # Heuristics
    if h.geocoded_city:
        return h.geocoded_city
    return ""


def resolve_hotel_for_night(hotels: List[Dict], target: date) -> Optional[Dict]:
    for h in hotels:
        if h["start_date"] is None or h["end_date"] is None:
            continue
        if h["start_date"] <= target < h["end_date"]:
            return h
    return None


# ============================================================================
# TRIP META
# ============================================================================

ROUTE_SVG = """
<svg class="route-svg" viewBox="0 0 600 80" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Route: Oslo via Svalbard to Helsinki, Tallinn, Stockholm, Copenhagen">
  <line x1="40" y1="50" x2="120" y2="20" stroke="var(--accent)" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="120" y1="20" x2="200" y2="40" stroke="var(--accent)" stroke-width="1"/>
  <line x1="200" y1="40" x2="280" y2="50" stroke="var(--accent)" stroke-width="1"/>
  <line x1="280" y1="50" x2="360" y2="50" stroke="var(--accent)" stroke-width="1"/>
  <line x1="360" y1="50" x2="440" y2="50" stroke="var(--accent)" stroke-width="1"/>
  <line x1="440" y1="50" x2="520" y2="60" stroke="var(--accent)" stroke-width="1"/>
  <line x1="520" y1="60" x2="560" y2="60" stroke="var(--accent)" stroke-width="1"/>
  <circle cx="40" cy="50" r="5" fill="var(--accent)"/>
  <circle cx="120" cy="20" r="7" fill="var(--accent-2)" stroke="var(--accent)" stroke-width="2"/>
  <circle cx="200" cy="40" r="4" fill="var(--accent)"/>
  <circle cx="280" cy="50" r="4" fill="var(--accent)"/>
  <circle cx="360" cy="50" r="4" fill="var(--accent)"/>
  <circle cx="440" cy="50" r="4" fill="var(--accent)"/>
  <circle cx="520" cy="60" r="4" fill="var(--accent)"/>
  <circle cx="560" cy="60" r="4" fill="var(--accent)"/>
  <text x="40" y="72" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Oslo</text>
  <text x="120" y="14" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Svalbard</text>
  <text x="200" y="32" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Tromsø</text>
  <text x="280" y="42" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Lofoten</text>
  <text x="360" y="42" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Bergen</text>
  <text x="440" y="42" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Helsinki</text>
  <text x="520" y="52" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Tallinn/Stockholm</text>
  <text x="560" y="72" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Cph</text>
</svg>
"""

TRIP_META = {
    "title": "Scandinavia '26",
    "subtitle": ("Twenty-three days from Oslo to Copenhagen by way of Svalbard, "
                 "the Lofoten Islands, Helsinki, Tallinn, and Stockholm — "
                 "an Arctic-to-Baltic arc threaded by sleeper trains, the "
                 "Hurtigruten coast, and one overnight ferry."),
    "narrator_dek": "For the returning traveler — what only Scandinavia and the Arctic offer.",
    "start_date": date(2026, 8, 14),
    "end_date": date(2026, 9, 5),
    "countries": ["Norway", "Finland", "Estonia", "Sweden", "Denmark"],
    "share_token": "1f1ad0d2-0c8a-4dfd-83cf-bfd5e8a7e7e0",  # filled at end
}
# Populate TRIP_META with all fields emit_hero now expects (was hard-coded in old emit_hero)
TRIP_META["nights"] = 22
TRIP_META["countries_count"] = 5
TRIP_META["bookings_count"] = 27
TRIP_META["route_svg"] = ROUTE_SVG
# SOURCES_NOTE is defined later in this file; assigned to TRIP_META after its def


# ============================================================================
# DAY-BY-DAY
# ============================================================================
# Each day: {"date": date, "city": str, "intro": str, "intro_deep": str,
#            "cards": [{"time": "HH:MM", "name": str, "venue": Optional[str],
#                       "body": str, "category": str, "notes": Optional[str],
#                       "travelpill": Optional[str], "venue_key": Optional[str]}],
#            "meta": str (weather + light context),
#            "country": str}

DAY_BY_DAY: List[Dict[str, Any]] = [
    # Day 1 — Aug 14, Fri — MSP → Oslo overnight flight
    {
        "date": date(2026, 8, 14), "country": "Norway", "city": "In flight",
        "meta": "Departing 15:05 CDT · seven-hour Atlantic crossing · sunset over Greenland",
        "intro": ("The trip starts not in Oslo but somewhere over Hudson Bay, "
                  "watching the sun set on a course that keeps it visible for an "
                  "extra hour because you are chasing it east. The first real "
                  "rule of a three-week northern arc: the journey out is part of "
                  "the geography."),
        "intro_deep": ("The MSP–Oslo overnight is short by transatlantic standards "
                       "(seven hours of dark) and worth treating as one of the trip's "
                       "scenic legs. North of 55°N in mid-August the cabin window stays "
                       "lit until well past midnight local; the polar route flies you "
                       "directly over Greenland's ice cap if the great-circle aligns. "
                       "Window seat over the left wing if you can choose."),
        "cards": [
            {"time": "15:05", "name": "Depart MSP", "category": "transit",
             "body": "Delta nonstop to Oslo Gardermoen — the only US-Oslo nonstop on the schedule.",
             "travelpill": "Flight · 7h30 · overnight"},
        ],
    },
    # Day 2 — Aug 15, Sat — Land Oslo, check in, walk
    {
        "date": date(2026, 8, 15), "country": "Norway", "city": "Oslo",
        "meta": "<b>21° → 13°C</b> · 15h light · check-in day",
        "intro": ("Oslo on a Saturday morning in mid-August has the particular "
                  "quiet of a Scandinavian city in vacation — fewer suits on the "
                  "trams, more strollers on the waterfront. The Wright Apartments "
                  "in Sørenga put you on the harbour's southeast edge, two minutes "
                  "from the heated saltwater Sørenga Sjøbad and a fifteen-minute "
                  "walk along the fjord to the Opera House's marble roof."),
            "intro_deep": ("Sørenga is the post-2010 redevelopment that turned the old "
                           "container-yard south of Bjørvika into a residential "
                           "promontory. The pool deck is free and uncrowded after 18:00 "
                           "when the day-trippers leave. Walk the waterfront west and "
                           "you cross the fjord-front parade: the Opera House (Snøhetta, "
                           "2008), the Munch Museum's vertical pile (estudio Herreros, "
                           "2021), and the new Deichman Library."),
        "cards": [
            {"time": "08:45", "name": "Arrive Oslo Gardermoen", "category": "transit",
             "body": "Flytoget airport express into Oslo S, 19 minutes — buy at the kiosk, accept the queue at passport control.",
             "travelpill": "Train · 19 min"},
            {"time": "10:00", "name": "Check in: Wright Apartments - Sørenga", "category": "other",
             "body": "Early check-in not guaranteed; bag drop accepted from 10:00. The receptionist will give you the door code and a half-litre of Voss.",
             "venue_key": None},
            {"time": "13:00", "name": "Sørenga Sjøbad", "venue_key": "Sørenga Sjøbad", "category": "sightseeing",
             "body": "Free heated saltwater pool on a wooden deck jutting into the fjord. 19°C even in August — the cold wakes you up after the red-eye.",
             "notes": "Bring a swimsuit and microfiber towel; no rental on site."},
            {"time": "15:30", "name": "Oslo Opera House", "venue_key": "Oslo Opera House", "category": "sightseeing",
             "body": "The Snøhetta-designed building (2008) you can walk up the side of — the marble roof is a public space. Skip the interior tour; the architecture's argument is exterior.",
             "notes": "Roof closes 30 minutes before sunset for safety."},
            {"time": "19:00", "name": "Mathallen Oslo", "venue_key": "Mathallen Oslo", "category": "meal",
             "body": "Indoor food hall in the Vulkan complex on the river — order at the counter you like, sit at the communal tables. Try the Solsiden cured-fish board.",
             "notes": "Kitchens close 21:00 Sat; arrive by 19:30."},
        ],
    },
    # Day 3 — Aug 16, Sun — full Oslo day
    {
        "date": date(2026, 8, 16), "country": "Norway", "city": "Oslo",
        "meta": "<b>23° → 14°C</b> · 14h45 light · full city day",
        "intro": ("Sunday is the day Oslo's museums are open and most of its shops "
                  "are closed — both work in your favour. The Bygdøy peninsula "
                  "carries the city's main museum cluster (Viking ships, Kon-Tiki, "
                  "Norwegian Folk Museum) and is a fifteen-minute ferry from "
                  "Aker Brygge. Save the afternoon for the Vigeland park and the "
                  "Munch — they are very different museums about very different "
                  "obsessions, and one of each is enough for the day."),
        "intro_deep": ("Vigeland (1869–1943) made the park sculptures himself in a "
                       "single 40-year contract with the city — there is no comparable "
                       "monomania in European public art. Edvard Munch (1863–1944) "
                       "left his estate to Oslo and the new building is the curatorial "
                       "argument for the breadth that was always there past *The Scream*. "
                       "Both museums are in their permanent collections — no rotating "
                       "exhibitions needed."),
        "cards": [
            {"time": "09:30", "name": "Ferry to Bygdøy", "category": "transit",
             "body": "Boat 91 from Pier 3 (Aker Brygge) — 15 minutes across the inner fjord. Buy with the Ruter app.",
             "travelpill": "Ferry · 15 min"},
            {"time": "10:15", "name": "Viking Ship Museum", "venue_key": "Viking Ship Museum", "category": "sightseeing",
             "body": "Closed for renovation until 2027 (Museum of the Viking Age replacement). The interim Historisk Museum downtown holds the major artefacts — Oseberg, Gokstad — until reopening."},
            {"time": "11:30", "name": "Bygdøy peninsula", "venue_key": "Bygdøy peninsula", "category": "sightseeing",
             "body": "Walk the loop south past Norsk Folkemuseum's open-air farm buildings and Maritime Museum to the Huk beach for a salt-water break."},
            {"time": "14:00", "name": "Vigeland Sculpture Park", "venue_key": "Vigeland Sculpture Park", "category": "sightseeing",
             "body": "200 bronze and granite figures in a public park, no entry fee. The Monolith — 121 entwined bodies in a single block — is the centerpiece you've seen in books."},
            {"time": "16:30", "name": "Munch Museum", "venue_key": "Munch Museum", "category": "sightseeing",
             "body": "Eleven-story tower on the harbour, the leaning silhouette is visible from across Bjørvika. *The Scream* is here in all four versions; rotation policy means three are out at a time.",
             "notes": "Buy the timed entry online — the walk-up queue starts before opening on summer Sundays."},
            {"time": "19:30", "name": "Maaemo", "venue_key": "Maaemo", "category": "meal",
             "body": "Three-Michelin-star, no rules but the seasonal menu. Reservations open exactly 90 days ahead at 09:00 Oslo time and book out in 12 minutes. Skip if you haven't already booked.",
             "notes": "If you do have the reservation: arrive 18 minutes early; the kitchen waits for the table to fill."},
        ],
    },
    # Day 4 — Aug 17, Mon — fly Oslo → Longyearbyen
    {
        "date": date(2026, 8, 17), "country": "Norway", "city": "Longyearbyen, Svalbard",
        "meta": "<b>8° → 3°C</b> · 24h light · enters Arctic Circle",
        "intro": ("The flight north crosses sixty-six degrees of latitude and lands "
                  "you somewhere genuinely strange. Longyearbyen at 78°N is the "
                  "northernmost settlement of consequence on the planet — about "
                  "two thousand permanent residents, one road in and out, and a "
                  "town rule that no one is buried in the cemetery (the permafrost "
                  "preserves the body and the influenza of 1918 is still "
                  "epidemiologically present in the soil). Bring a real coat. "
                  "August averages 5°C and the wind off the fjord adds another five."),
        "intro_deep": ("Svalbard sits inside a 1920 treaty that made it Norwegian "
                       "territory open to all signatory states' citizens — the reason "
                       "the town still has Russian, Thai, and Filipino-origin residents "
                       "running shops on the main street. The Russian coal-mining "
                       "settlement at Barentsburg (90 km south) and the abandoned one at "
                       "Pyramiden (160 km north) are the visible artefacts. Carry a rifle "
                       "outside town limits — the polar bear ratio (~3,000 across the "
                       "archipelago vs ~2,500 humans) is the operating constraint."),
        "cards": [
            {"time": "09:30", "name": "Depart Oslo", "category": "transit",
             "body": "Norwegian Air DY390 to Longyearbyen — one direct flight per day.",
             "travelpill": "Flight · 3h00"},
            {"time": "12:30", "name": "Arrive Longyearbyen", "category": "transit",
             "body": "The airport is a ten-minute drive from town. There is one taxi rank and one shared shuttle (180 NOK)."},
            {"time": "16:00", "name": "Check in: Svalbard Hotell | Lodge", "category": "other",
             "body": "Slippered-corridor protocol: take off your outdoor shoes at the entry mat. Every Svalbard hotel does this — local convention since the mining-era boarding houses."},
            {"time": "17:00", "name": "Svalbard Museum", "venue_key": "Svalbard Museum", "category": "sightseeing",
             "body": "Compact and dense — 90 minutes covers it. The fox-fur trapping section is grim and important; the section on the 1920 treaty explains the political oddity you're standing in."},
            {"time": "20:00", "name": "Huset", "venue_key": "Huset", "category": "meal",
             "body": "The old miners' cinema-and-mess, now a serious restaurant with one of the world's better wine cellars (a Svalbard treaty quirk — no national taxes on imports). The four-course tasting is the move."},
        ],
    },
    # Day 5 — Aug 18, Tue — Hurtigruten Wildlife & Glacier
    {
        "date": date(2026, 8, 18), "country": "Norway", "city": "Longyearbyen, Svalbard",
        "meta": "<b>7° → 2°C</b> · 24h light · catamaran day",
        "intro": ("Eight hours on a hybrid catamaran into Isfjorden's western "
                  "arm and out to the Esmark Glacier face — the boat does the work "
                  "of teaching you scale. The glacier is 30 metres tall at the "
                  "calving front and ten kilometres long; the iceberg pieces that "
                  "drift past the hull are the size of small houses. You are very "
                  "likely to see beluga, bearded seals, and Arctic terns. Polar "
                  "bears are possible but the operator does not promise them — "
                  "the boat's job is to give you the landscape, not stalk wildlife."),
        "intro_deep": ("Hurtigruten's expedition arm runs the catamaran tours; the "
                       "hybrid drive is for the silent approach to wildlife. Borrow "
                       "the rubber boots and survival suit they provide for the bow "
                       "deck — the boat is mostly enclosed but the air at the glacier "
                       "face is several degrees colder than open water. Bring a wool hat "
                       "and the binoculars the lodge will lend you for free."),
        "cards": [
            {"time": "08:15", "name": "Depart pier: Wildlife & Glacier catamaran", "category": "sightseeing",
             "body": "Eight-hour round trip into Isfjorden — Hurtigruten Svalbard's hybrid-electric Bard. Lunch (soup, sandwich) served on board."},
            {"time": "10:30", "name": "Borebreen Glacier ridge transit", "category": "sightseeing",
             "body": "The catamaran approaches the south-facing ridge first — fulmars in the cliffs, occasional bearded seal on a low ice piece."},
            {"time": "13:00", "name": "Esmark Glacier face", "category": "sightseeing",
             "body": "Calving front. The boat hovers 200 m off the ice — closer is illegal, and you don't want to be closer when a 50-metre chunk lets go."},
            {"time": "14:45", "name": "Return to Longyearbyen", "category": "transit",
             "body": "Back at the pier mid-afternoon. The lodge bar opens at 17:00; the day's wildlife list goes on the board."},
            {"time": "20:00", "name": "Karlsberger Pub", "venue_key": "Karlsberger Pub", "category": "meal",
             "body": "Whisky bar with the largest selection north of Trondheim — a hundred-plus malts, half of them you cannot buy at home. Cash gets you table service; cards work too.",
             "notes": "Closed Mondays."},
        ],
    },
    # Day 6 — Aug 19, Wed — Better Moment Catch of the Day
    {
        "date": date(2026, 8, 19), "country": "Norway", "city": "Longyearbyen, Svalbard",
        "meta": "<b>6° → 1°C</b> · 24h light · full-day catch",
        "intro": ("Better Moment's *Catch of the Day* is fifteen hours on a "
                  "smaller boat with a guide, a chef, and a much smaller passenger "
                  "manifest — the experience is built around hand-line cod fishing "
                  "in the cold mid-fjord water and cooking what you bring up on a "
                  "fire on a remote beach. The day moves slowly on purpose. Wear "
                  "everything you brought. If the wind is up, the chef has a "
                  "fallback plan; if the wind is down, this is the day of the trip "
                  "that people remember most."),
        "intro_deep": ("Better Moment runs three boats out of Longyearbyen and books "
                       "the same day-long format with rotating focuses — fishing, "
                       "wildlife, photography. The fishing day suits anyone who likes "
                       "boats and isn't squeamish about killing a fish. The boat does "
                       "carry a rifle and the guide has the polar-bear training the "
                       "Sysselmannen requires; the chef has the cooking-on-a-beach skills "
                       "that make the trip the trip."),
        "cards": [
            {"time": "08:23", "name": "Depart pier: Better Moment Catch of the Day", "category": "sightseeing",
             "body": "Small-group day boat (capped at 8 passengers). Guide + chef + skipper. Coffee on the boat from the moment you board."},
            {"time": "11:00", "name": "Fjord fishing", "category": "sightseeing",
             "body": "Hand-line cod fishing in 100m of cold water — Atlantic cod, haddock, sometimes wolffish. The guide cleans on board."},
            {"time": "14:00", "name": "Beach landing + cookfire", "category": "meal",
             "body": "Driftwood fire on a black-sand beach somewhere along Isfjorden's south shore. Lunch is whatever came up that morning, with crispbread and the chef's pickle plate."},
            {"time": "18:00", "name": "Return slow leg", "category": "sightseeing",
             "body": "The last three hours of the day are usually a slow run back along the cliff coast — auks in the rock, possibly seal-on-ice."},
            {"time": "23:00", "name": "Back at the lodge", "category": "other",
             "body": "The Arctic light makes 23:00 feel like 17:00. Skip the nightcap unless you want to be up at 03:00."},
        ],
    },
    # Day 7 — Aug 20, Thu — free Svalbard day
    {
        "date": date(2026, 8, 20), "country": "Norway", "city": "Longyearbyen, Svalbard",
        "meta": "<b>7° → 3°C</b> · 24h light · open day",
        "intro": ("A free day in Longyearbyen is the day to walk slowly, sit in the "
                  "coffee shop, and find the things the tours skip. The Global "
                  "Seed Vault — the doomsday backup of the world's agricultural "
                  "seed stock — is visible from town but not open to the public; "
                  "the walk up to its tunnel mouth (twenty minutes from the road "
                  "head) is the closest a civilian gets. Spend the afternoon on a "
                  "shorter excursion if the weather holds, or in the museum and "
                  "the coffee shop if it doesn't."),
        "intro_deep": ("Camp Barentz, a forty-minute drive out of town, runs short "
                       "evening 'polar history and coffee' programmes in a reconstructed "
                       "Willem Barentsz cabin — the Dutch explorer who overwintered on "
                       "Novaya Zemlya in 1596. Booking the same morning is usually fine "
                       "off-cruise-season; the cabin holds about fifteen. The drive out "
                       "is along the only road that leaves town."),
        "cards": [
            {"time": "10:00", "name": "Fruene Coffee", "venue_key": "Fruene Coffee", "category": "meal",
             "body": "The world's northernmost full-service café — open since 2007, run by three women whose names give the place its name. Try the cloudberry cheesecake.",
             "notes": "Cash and card both fine; service is slow on purpose."},
            {"time": "12:00", "name": "Global Seed Vault walk", "venue_key": "Global Seed Vault", "category": "sightseeing",
             "body": "Twenty-minute walk from the road head at the airport turn-off to the vault's tunnel entrance. You cannot enter; the silver wedge in the hillside is the photograph."},
            {"time": "15:00", "name": "Svalbard Museum (return)", "venue_key": "Svalbard Museum", "category": "sightseeing",
             "body": "Worth a second pass if Day 4 was tight — the rotating exhibit changes monthly and the silver-trapping section reads differently after three days on the fjord."},
            {"time": "19:00", "name": "Camp Barentz", "venue_key": "Camp Barentz", "category": "meal",
             "body": "Polar history talk + reindeer stew + apple cake by a wood fire in a reconstructed trapper cabin. The drive out (40 min) is the only time you'll see the road out of town.",
             "notes": "Book by 16:00 same day; pickup is at the Svalbardbutikken."},
        ],
    },
    # Day 8 — Aug 21, Fri — fly Svalbard → Tromsø, pick up car
    {
        "date": date(2026, 8, 21), "country": "Norway", "city": "Tromsø",
        "meta": "<b>14° → 7°C</b> · 18h light · transit day",
        "intro": ("Leaving Svalbard always feels like coming back from a place that "
                  "shouldn't exist. The 90-minute SAS flight south to Tromsø drops "
                  "you nine degrees of latitude (and ten degrees Celsius) in less "
                  "time than the cab ride to the airport. Tromsø — the 'Paris of "
                  "the North' nickname is an 1880s exaggeration but the wooden "
                  "city centre, the cathedral, and the cable-car view across the "
                  "strait are the actual things. Pick up the rental car at the "
                  "airport and drive across the Tromsø Bridge to the Clarion Edge "
                  "for the night."),
        "intro_deep": ("Tromsø sits on a small island in the Tromsøysundet strait; "
                       "the Tromsø Bridge (1960) connects to the mainland eastward. "
                       "The Sixt rental desk is in the arrivals hall — the car (likely a "
                       "Volvo XC40 or equivalent) needs to last to Leknes in three days "
                       "and back to Lofoten airport. Studded tyres are not legal yet (15 "
                       "October start); summer tyres on the E10 are fine in August."),
        "cards": [
            {"time": "12:35", "name": "Depart Longyearbyen", "category": "transit",
             "body": "SAS SK 4425 to Tromsø Langnes. Tromsø is on Norway local time year-round; you do not change timezones.",
             "travelpill": "Flight · 1h35"},
            {"time": "14:30", "name": "Pick up car: Sixt", "category": "transit",
             "body": "Sixt counter in arrivals; the booking covers Tromsø → Leknes Airport (4 days, one-way fee included)."},
            {"time": "18:00", "name": "Check in: Clarion Hotel The Edge", "category": "other",
             "body": "Eleventh-floor cocktail bar with the strait view — order one before dinner, even if you don't drink, just to see the angle of light."},
            {"time": "19:30", "name": "Fiskekompaniet", "venue_key": "Fiskekompaniet", "category": "meal",
             "body": "Harbourside white-tablecloth fish house, half a kilometre from the hotel. Order the day's catch grilled with brown butter; skip the sauce flights.",
             "notes": "Reservation strongly recommended on summer Fridays."},
        ],
    },
    # Day 9 — Aug 22, Sat — drive Tromsø → Lofoten (long day)
    {
        "date": date(2026, 8, 22), "country": "Norway", "city": "Reine, Lofoten",
        "meta": "<b>16° → 9°C</b> · 17h light · ferry + drive",
        "intro": ("Tromsø to Reine in one day is a 470-km drive plus one ferry "
                  "crossing on the E10 south. Allow nine hours including the "
                  "ferry from Lødingen to Bognes (if routed via the highway) or "
                  "the more scenic but slower Bjarkøy run. The drive is the trip's "
                  "geological lesson — you cross the boundary where the Lofoten "
                  "Wall (the mountain ridge that gives the islands their teeth) "
                  "rises out of flat coastal plain. Stop in Henningsvær for "
                  "coffee and the football pitch on the rocks."),
        "intro_deep": ("The Lofoten archipelago's geology is unusually old for the "
                       "region — 2.6-billion-year-old gneiss and gabbro, scoured by ice "
                       "into the serrated peaks you'll be looking at for the next three "
                       "days. The fishing-village colour scheme (red rorbu cabins on "
                       "stilts) is a 19th-century convention — red ochre paint was the "
                       "cheap option, mixed with fish oil and chalk. Real rorbuer "
                       "(rorbu, singular) are the cod-fisher cabins; modern reproductions "
                       "are everywhere but Reine Rorbuer's are largely original "
                       "buildings."),
        "cards": [
            {"time": "08:00", "name": "Check out + depart Tromsø", "category": "transit",
             "body": "Fuel up at the Circle K on E8 south of the bridge — the next reasonable petrol stop is Narvik (240 km)."},
            {"time": "12:30", "name": "Narvik lunch stop", "category": "meal",
             "body": "Roughly the halfway point. Café Sentrum on Kongens gate does a workmanlike fish soup; no need to plan ahead.",
             "travelpill": "Drive · ~7h30 · 470km · 1 ferry"},
            {"time": "16:30", "name": "Henningsvær", "venue_key": "Henningsvær", "category": "sightseeing",
             "body": "Detour off the E10 — the village clings to three islets joined by bridges, the famous football pitch on the rocks, and a single coffee shop (Klatrekaféen) worth the stop."},
            {"time": "16:00", "name": "Check in: Reine Rorbuer", "category": "other",
             "body": "The check-in office is at the marina building — Manuela will hand you a key and a map of which cabin is yours. Bring your own beer; the shop on the dock closes at 19:00 Saturdays."},
            {"time": "19:00", "name": "Hamnøy", "venue_key": "Hamnøy", "category": "sightseeing",
             "body": "The neighboring village three minutes' drive east — the postcard photograph of red cabins against the Festhælvtinden ridge is taken from the bridge here. Best at low evening sun."},
        ],
    },
    # Day 10 — Aug 23, Sun — full Lofoten day
    {
        "date": date(2026, 8, 23), "country": "Norway", "city": "Reine, Lofoten",
        "meta": "<b>17° → 10°C</b> · 17h light · hike day",
        "intro": ("Reinebringen — the 448-metre peak across the harbour from your "
                  "cabin — is the iconic Lofoten hike. The Sherpa-built staircase "
                  "(1,978 steps, completed 2019) makes it doable in two hours up "
                  "and one back; the view from the top is the picture that sold "
                  "you on Lofoten. Start before 09:00 to avoid both the morning "
                  "cruise-ship crowd and the afternoon condensation that closes "
                  "the view. The rest of the day is Å, the village at the end of "
                  "the road, and dinner at Anita's in Sakrisøy."),
        "intro_deep": ("The Reinebringen staircase was built by Nepali stonemasons "
                       "between 2016 and 2019, paid for by the local kommune and a "
                       "Norwegian tourism trust — the alternative, an unmaintained mud "
                       "track up the same slope, had killed three hikers and was closing "
                       "the route in summer. The staircase is open from late May through "
                       "September; in winter it ices and the route closes officially. "
                       "Wear hiking shoes with grip — the granite gets slick in rain."),
        "cards": [
            {"time": "08:30", "name": "Reinebringen ascent", "venue_key": "Reinebringen", "category": "sightseeing",
             "body": "Two hours up at moderate pace, one hour down. The staircase is the route — do not free-climb the gravel sections.",
             "notes": "Pack water and a wind shell; the summit ridge is 8°C colder than the harbour."},
            {"time": "13:30", "name": "Å i Lofoten", "venue_key": "Å i Lofoten", "category": "sightseeing",
             "body": "End of the E10 — a museum-village of the cod-fishing era. The Stockfish Museum is small and excellent; the bakery (open since 1844) makes cinnamon buns from a stone oven."},
            {"time": "16:30", "name": "Nusfjord", "venue_key": "Nusfjord", "category": "sightseeing",
             "body": "Forty-minute drive east — one of Norway's best-preserved 19th-century fishing villages, now a hotel-museum hybrid you can walk around freely."},
            {"time": "19:00", "name": "Anita's Sjømat", "venue_key": "Anita's Sjømat", "category": "meal",
             "body": "Family-run fish-market-and-kitchen in Sakrisøy (the orange village across from Hamnøy). Stockfish burgers, dried-fish samples, salmon sashimi flown from the boat. Order at the window.",
             "notes": "Cash only; the line moves fast."},
        ],
    },
    # Day 11 — Aug 24, Mon — quieter Lofoten day
    {
        "date": date(2026, 8, 24), "country": "Norway", "city": "Reine, Lofoten",
        "meta": "<b>15° → 9°C</b> · 16h45 light · slow day",
        "intro": ("A second full day in Reine is for the things you cannot do in a "
                  "first. Take the small ferry from Reine to Vindstad and walk the "
                  "ninety-minute trail to Bunes Beach — a wide white-sand beach "
                  "trapped between Lofoten Wall peaks, accessible only on foot, "
                  "almost always empty even in August. If the weather is hostile, "
                  "drive east to Henningsvær and spend the day there. If it is "
                  "still and clear, kayak the harbour out toward Hamnøy at "
                  "golden hour — the cabin office rents tandems by the hour."),
        "intro_deep": ("Lofoten weather changes fast — the Gulf Stream gives the "
                       "islands a maritime climate that swings from 18°C and clear to "
                       "8°C and horizontal rain within an afternoon. Have two plans every "
                       "day and watch the yr.no forecast in the morning — it's the "
                       "Norwegian state met office and the most accurate read available."),
        "cards": [
            {"time": "09:30", "name": "Reine → Vindstad passenger ferry", "category": "transit",
             "body": "Small boat from the Reine harbour — 25-minute crossing to Vindstad. Cash to the operator on the boat.",
             "travelpill": "Ferry · 25 min"},
            {"time": "11:00", "name": "Bunes Beach hike", "category": "sightseeing",
             "body": "Ninety-minute walk from Vindstad over a low pass to Bunes — wide white-sand beach with a single-stone monument to the wartime dead. Bring lunch; there is nothing on the trail."},
            {"time": "16:30", "name": "Reine harbour kayak", "category": "sightseeing",
             "body": "Tandem rental at the marina kiosk — 350 NOK per hour. Stay close to shore and inside the Reinefjord; the open Vestfjord beyond is not for casual paddling."},
            {"time": "19:30", "name": "Cabin dinner — what you brought", "category": "meal",
             "body": "Reine has limited evening dining and reservations book out — most cabin guests cook in. The shop on the dock sells fresh cod, lamb, and the standard Norwegian dairy and bread."},
        ],
    },
    # Day 12 — Aug 25, Tue — Reine → Leknes → Oslo
    {
        "date": date(2026, 8, 25), "country": "Norway", "city": "Oslo (transit)",
        "meta": "<b>14° → 13°C</b> · 16h light · transit day",
        "intro": ("Out of Lofoten the same way most travellers go — the 90-minute "
                  "drive from Reine to Leknes Airport, the short Widerøe hop to "
                  "Bodø, then the SAS regional to Oslo in the early afternoon. "
                  "You're in Oslo by mid-day with the rest of the day open. The "
                  "Radisson Plaza is the tall glass building behind Oslo S — "
                  "convenient but characterless, picked for the central transfer "
                  "to the Bergen train tomorrow morning."),
        "intro_deep": ("Norway's domestic short-hop network is operated mostly by "
                       "Widerøe (Dash-8 propeller aircraft) with SAS running the larger "
                       "regional jets — the Leknes runway is short enough that only "
                       "Widerøe's Dash-8s can land on it. Drop the rental car at the "
                       "airport office; the same Sixt agent handles the inbound and "
                       "outbound. Don't oversleep — the morning's flights are the only "
                       "way out and they fill."),
        "cards": [
            {"time": "07:30", "name": "Depart Reine", "category": "transit",
             "body": "90-minute drive to Leknes Airport on the E10 — coastal road, no rush traffic in August."},
            {"time": "09:35", "name": "Depart Leknes", "category": "transit",
             "body": "Widerøe WF 892 — short hop to Bodø then SAS SK 4107 onward to Oslo Gardermoen.",
             "travelpill": "Flight · 2h30 + connect"},
            {"time": "14:00", "name": "Check in: Radisson Blu Plaza Hotel", "category": "other",
             "body": "Tall glass tower behind Oslo S — efficient, anodyne, exactly what you want for a one-night transfer stop."},
            {"time": "16:30", "name": "Akershus Fortress", "venue_key": "Akershus Fortress", "category": "sightseeing",
             "body": "Medieval castle on the fjord-side, walls dating to 1290s. Free outdoor walk; pay if you want the interior (Resistance Museum is the better of the two interior options)."},
            {"time": "19:00", "name": "Tim Wendelboe", "venue_key": "Tim Wendelboe", "category": "meal",
             "body": "Tiny Grünerløkka coffee bar from the namesake World Barista Champion. The shop closes 18:00 most days — check before you walk over.",
             "notes": "Espresso-only operation; no milk drinks past 17:00."},
        ],
    },
    # Day 13 — Aug 26, Wed — Oslo → Bergen → Flåm scenic train
    {
        "date": date(2026, 8, 26), "country": "Norway", "city": "Flåm",
        "meta": "<b>16° → 11°C</b> · 15h30 light · scenic rail day",
        "intro": ("The Bergen Railway is one of the world's named scenic train "
                  "lines and the route to Flåm runs across the Hardangervidda "
                  "plateau — a treeless tundra at 1,200 metres that you cross for "
                  "two hours before dropping to the fjord. Change at Myrdal for "
                  "the Flåmsbana, the 20-km branch line that descends 866 metres "
                  "in 55 minutes on a 1-in-18 gradient and stops at the "
                  "Kjosfossen waterfall for ten minutes of photographs. Spend the "
                  "evening on the fjord-side at Flåmsbrygga, the cabin-style hotel "
                  "above the village pier."),
        "intro_deep": ("The Bergen Railway was completed in 1909, the Flåmsbana in "
                       "1940 — both are unusual for the era's mountain railways in that "
                       "they were built without the help of a single cog rail, relying "
                       "instead on tight curves, twenty tunnels, and the limits of steel-"
                       "on-steel adhesion. The Flåmsbana ride is touristy in the literal "
                       "sense — every passenger has a window seat opportunity if they "
                       "switch sides at Berekvam where the train passes itself."),
        "cards": [
            {"time": "08:30", "name": "Depart Oslo S — Bergen Railway", "category": "transit",
             "body": "Vy train 601 to Myrdal — 5h30 across the Hardangervidda. Reserved seating; pick the south-facing window.",
             "travelpill": "Train · 5h40 scenic"},
            {"time": "12:30", "name": "Finse station window", "category": "sightseeing",
             "body": "Halfway point and the highest station on the line (1,222 m). The Hardangerjøkulen glacier visible to the north on a clear day — and yes, this is where *The Empire Strikes Back* shot the Hoth exteriors."},
            {"time": "14:10", "name": "Flåm Railway arrival", "venue_key": "Flåm Railway", "category": "sightseeing",
             "body": "Step off the Bergen train at Myrdal, cross the platform, board the Flåmsbana. Camera-ready; the descent starts immediately."},
            {"time": "14:30", "name": "Check in: Flåmsbrygga Apartments", "category": "other",
             "body": "Cabin-style waterfront apartments above the village pier — small but well-equipped kitchens. The Ægir brewery and brewpub is next door."},
            {"time": "15:30", "name": "Flåm zipline", "category": "sightseeing",
             "body": "Norway's Best operates the 1,381m zipline from Vatnahalsen down to the village — 100 km/h on a 305-metre drop. Strap-in window opens hourly.",
             "notes": "Closed-toe shoes required."},
            {"time": "19:30", "name": "Ægir BrewPub (Flåmsbrygga)", "category": "meal",
             "body": "Viking-themed stone-and-timber brewpub with the village's only real dinner option — the seven-course Viking Plank if you're hungry, the cured-meat board if not."},
        ],
    },
    # Day 14 — Aug 27, Thu — Flåm → Oslo (return scenic)
    {
        "date": date(2026, 8, 27), "country": "Norway", "city": "Bergen",
        "meta": "<b>18° → 12°C</b> · 15h light · scenic rail day",
        "intro": ("The reverse leg — Flåm back up the cog-less branch line to "
                  "Myrdal, then west on the Bergen Railway to its terminus. The "
                  "second half of the route is the section you didn't see "
                  "yesterday: forested valleys, the Voss lake, descent into "
                  "Bergen. Check in at the Radisson Blu downtown and walk to "
                  "Bryggen for the late afternoon — the Hanseatic wharf at "
                  "golden hour is one of the trip's great photographs."),
        "intro_deep": ("Bergen was Norway's capital before Oslo and the Hanseatic "
                       "League's northern hub — the wooden warehouses at Bryggen are the "
                       "league's surviving artefacts, rebuilt repeatedly after fires "
                       "(1702, 1955) but in the same medieval footprint and material. "
                       "UNESCO-listed since 1979. The streets behind the wharf — Øvregaten "
                       "and Tanks plass — are the unrenovated working-trade alleys, less "
                       "photographed and more interesting."),
        "cards": [
            {"time": "08:30", "name": "Depart Flåm — Flåmsbana", "category": "transit",
             "body": "Cog-less branch line back up to Myrdal — 55-minute climb in reverse, same views, far quieter than yesterday's downhill.",
             "travelpill": "Train · ~6h30 to Bergen"},
            {"time": "12:10", "name": "Bergen Railway westbound", "category": "transit",
             "body": "Catch the through train at Myrdal; reserved seats again. Voss station around 14:00 is the lunch stop if the trolley hasn't reached you."},
            {"time": "15:00", "name": "Check in: Radisson Blu Bergen", "category": "other",
             "body": "Royal hotel on the harbour, walking distance to Bryggen and the fish market. The water-view rooms cost the upgrade."},
            {"time": "16:30", "name": "Bryggen", "venue_key": "Bryggen", "category": "sightseeing",
             "body": "Walk the Hanseatic wharf's outer face first, then duck into the back alleys — Schøtstuene's meeting-house and the Bryggens Museum are both worth the entry."},
            {"time": "18:30", "name": "Fløibanen funicular", "venue_key": "Fløibanen funicular", "category": "sightseeing",
             "body": "Eight-minute climb to Fløyen (320m) — sunset view across the harbour and the seven mountains. Walk down via the marked Hellige Kors trail (60 minutes)."},
            {"time": "20:00", "name": "Lysverket", "venue_key": "Lysverket", "category": "meal",
             "body": "Pre-meal cocktail at the KODE 4 museum's restaurant — sea-led tasting menu in a Bauhaus-era electrical power station. The chef's table on the kitchen counter is the move if available."},
        ],
    },
    # Day 15 — Aug 28, Fri — Bergen (full day)
    {
        "date": date(2026, 8, 28), "country": "Norway", "city": "Bergen",
        "meta": "<b>19° → 13°C</b> · 14h45 light · city day",
        "intro": ("A full Bergen day for the fish market and the museums you'd "
                  "rather not skip. The Fish Market is more for tourists than "
                  "locals (locals shop at Mathallen) but the stalls — Hansa's "
                  "salmon, the Skagerrak crab tower — are still the best entry "
                  "to Norwegian seafood economics. KODE's four buildings hold "
                  "the country's largest art collection outside Oslo: KODE 3 "
                  "is the Munch holding (smaller than Oslo's but with the early "
                  "Bergen work), KODE 4 the international modern, KODE 1 the "
                  "Norwegian arts-and-crafts."),
        "intro_deep": ("KODE bundles four museum buildings on Lille Lungegårdsvannet "
                       "lake under one ticket — buy the 24-hour pass if you'll do more "
                       "than two. The Edvard Grieg house (Troldhaugen) is 8 km south "
                       "and worth the bus 250 ride if you have any taste for late-"
                       "Romantic piano — daily noon recitals in the composer's villa, "
                       "performed on his own Steinway."),
        "cards": [
            {"time": "09:00", "name": "Fish Market", "venue_key": "Fish Market", "category": "meal",
             "body": "Walk through before 11:00 to see the vendors set up — order a small portion of the smoked salmon flight and one whale-meat sample if curious. The covered hall is at the back."},
            {"time": "11:00", "name": "KODE 3 (Munch + Astrup)", "category": "sightseeing",
             "body": "The Munch room is small but holds early Bergen work — the *Madonna* lithograph variants are not in Oslo. Nikolai Astrup's neighbouring room is the discovery."},
            {"time": "14:00", "name": "Troldhaugen (optional)", "category": "sightseeing",
             "body": "Bus 250 to Hop, 20-minute walk. Daily 13:00 piano recital in the composer's hut on the fjord — 30 minutes of Grieg's own work on his own piano. Buy the museum + concert combo ticket."},
            {"time": "18:00", "name": "Bryggen sunset return", "venue_key": "Bryggen", "category": "sightseeing",
             "body": "The wharf is the photograph; the long August evening means you can shoot from 19:30 to 21:00 and the light keeps changing."},
            {"time": "20:30", "name": "Cabin / hotel — early night", "category": "other",
             "body": "Early start tomorrow for the Bergen → Helsinki flight; pack tonight."},
        ],
    },
    # Day 16 — Aug 29, Sat — Bergen → Helsinki
    {
        "date": date(2026, 8, 29), "country": "Finland", "city": "Helsinki",
        "meta": "<b>20° → 14°C</b> · 15h light · cross-country day",
        "intro": ("The first border crossing of the trip — Finnair direct from "
                  "Bergen to Helsinki Vantaa, in the air four hours, on the ground "
                  "by 15:00. Helsinki is shaped differently from any Norwegian "
                  "city you've just left: the Senate Square's neoclassical "
                  "ensemble (Helsinki Cathedral, the Senate, the University) is "
                  "the Swedish-era axis around which the rest of the city was "
                  "designed in the 1820s by C. L. Engel — the German architect "
                  "imported because Russia had just taken Finland from Sweden "
                  "and wanted a capital to look the part."),
        "intro_deep": ("Hotel Klaus K is the design-hotel block on Bulevardi, walking "
                       "distance to the Senate Square and the Esplanade. The room "
                       "category names (Mystical, Passion, Envy, Desire) are taken "
                       "directly from the *Kalevala* — Finland's national epic, compiled "
                       "by Elias Lönnrot in 1835 — and the wall art and binders in your "
                       "room are quotations from it. Read them. It's a better honesty "
                       "about the source material than most theme hotels manage."),
        "cards": [
            {"time": "10:25", "name": "Depart Bergen", "category": "transit",
             "body": "Finnair AY7M nonstop to Helsinki. Two-hour time-change adjustment when you land.",
             "travelpill": "Flight · 3h20 + 1h ahead"},
            {"time": "15:00", "name": "Check in: Hotel Klaus K", "category": "other",
             "body": "Design-hotel block on Bulevardi 2-4. The Kalevala-themed rooms are a curatorial argument, not a gimmick — read the bedside binder for the room's namesake passage."},
            {"time": "17:00", "name": "Senate Square", "venue_key": "Senate Square", "category": "sightseeing",
             "body": "The white-and-green-domed Helsinki Cathedral (1852, Engel) tops the square's east-west axis. Walk the steps; the view back toward the harbour is the city's standard postcard."},
            {"time": "19:30", "name": "Olo Restaurant", "venue_key": "Olo Restaurant", "category": "meal",
             "body": "Michelin-starred Finnish tasting menu on the harbour — the chef's-counter seats put you across from the open kitchen. Eight courses, three hours, books out two weeks ahead."},
        ],
    },
    # Day 17 — Aug 30, Sun — full Helsinki day
    {
        "date": date(2026, 8, 30), "country": "Finland", "city": "Helsinki",
        "meta": "<b>21° → 13°C</b> · 14h30 light · sauna day",
        "intro": ("Sunday in Helsinki is the day to do the sauna properly. Löyly "
                  "on Hernesaarenranta is the architect-designed waterfront "
                  "sauna complex (Avanto Architects, 2016) with three sauna "
                  "rooms — wood-heated, smoke, and electric — and direct access "
                  "to the Baltic for the cold-water plunge. Two hours minimum; "
                  "go in the morning before the crowds. The rest of the day is "
                  "Suomenlinna — the 18th-century sea fortress on the islands "
                  "guarding the harbour, a UNESCO site reached by 15-minute "
                  "ferry."),
        "intro_deep": ("Suomenlinna was built by the Swedish Empire in 1748 as "
                       "Sveaborg ('Swedish fortress'); it fell to the Russians in 1808, "
                       "then to Finland at independence in 1918. The site is still "
                       "inhabited — about 800 residents live in former military housing "
                       "— and the walking circuit (4 km, two hours) crosses bridges "
                       "between six islands. The dry dock is one of the world's oldest "
                       "still in active use."),
        "cards": [
            {"time": "09:30", "name": "Löyly", "venue_key": "Löyly", "category": "sightseeing",
             "body": "Pre-book the two-hour public sauna slot at 10:00. Bring a swimsuit (towel + robe rentable). The cold plunge dock has a ladder; the Baltic in August is 18°C — chillier than it sounds."},
            {"time": "13:00", "name": "Old Market Hall", "venue_key": "Old Market Hall", "category": "meal",
             "body": "Walk back along the harbour to the Vanha Kauppahalli (1889) — the old red-brick market hall on the South Harbour quay. The salmon-soup stall is the standard lunch."},
            {"time": "14:30", "name": "Suomenlinna ferry", "venue_key": "Suomenlinna", "category": "sightseeing",
             "body": "Public ferry from Kauppatori — 15 minutes each way, runs on the Helsinki transit pass. Loop the islands counter-clockwise; the King's Gate at the south is the photograph.",
             "travelpill": "Ferry · 15 min"},
            {"time": "17:30", "name": "Oodi Library", "venue_key": "Oodi Library", "category": "sightseeing",
             "body": "Helsinki Central Library opened 2018, designed by ALA Architects — the third-floor reading room with its glass-roof view of the Parliament is the modern Finnish architecture statement."},
            {"time": "19:30", "name": "Hotel-area dinner", "category": "meal",
             "body": "Casual evening near Bulevardi — Klaus K's own Toscanini does straightforward Italian; for Finnish, Sea Horse three blocks south has run since 1934 and the salt-cured Baltic herring is the order."},
        ],
    },
    # Day 18 — Aug 31, Mon — ferry Helsinki → Tallinn
    {
        "date": date(2026, 8, 31), "country": "Estonia", "city": "Tallinn",
        "meta": "<b>19° → 14°C</b> · 14h light · cross-Baltic day",
        "intro": ("The Tallink Megastar is the fast-ferry that does the 80-km "
                  "Helsinki–Tallinn crossing in two hours and ten minutes — one "
                  "of the great underrated short-sea routes. You board at "
                  "Helsinki's West Terminal mid-morning, you walk down the gangway "
                  "into Tallinn's harbour mid-afternoon, and the medieval old town "
                  "is a fifteen-minute walk uphill. The Tallinn City Apartments "
                  "are inside the old-town walls on Raekoja plats — the medieval "
                  "town square — which means you sleep inside a UNESCO site."),
        "intro_deep": ("The Tallink fleet's identity is part of the modern Baltic — "
                       "Finnish-Swedish-Estonian ownership, Estonian flag, English-"
                       "Finnish-Swedish announcements, a duty-free shop the size of a "
                       "supermarket, and a Finnish vodka-tourism subculture that is "
                       "exactly what it sounds like. The crossing itself is unremarkable "
                       "weather-wise — the Gulf of Finland is shallow and the ferry is "
                       "fast — but the sense of being in transit between two clearly "
                       "different worlds (Helsinki is Lutheran-Nordic; Tallinn is "
                       "Hanseatic-medieval-Soviet-EU) makes the two hours feel like "
                       "more."),
        "cards": [
            {"time": "08:30", "name": "Tallink Megastar boarding", "category": "transit",
             "body": "West Terminal (Länsiterminaali) — tram 7 from Bulevardi or 12-minute walk from Klaus K. Check-in closes 30 min before departure.",
             "travelpill": "Ferry · 2h10"},
            {"time": "10:30", "name": "Crossing — Gulf of Finland", "category": "transit",
             "body": "Deck 9 has the panoramic windows and the better coffee bar (not the buffet, which is for the Finnish-vodka-tourism crowd)."},
            {"time": "12:30", "name": "Arrive Tallinn Old City Harbour", "category": "transit",
             "body": "Walk 12 minutes uphill via Mere puiestee to the old-town walls — enter via the Viru Gates."},
            {"time": "13:30", "name": "Check in: Tallinn City Apartments Old Town Square", "category": "other",
             "body": "Apartment building inside the city walls on Raekoja plats — the medieval town square. The reception is at Number 22; the apartments are in adjacent buildings (numbered 1, 4, 16)."},
            {"time": "15:00", "name": "Tallinn Old Town walking start", "venue_key": "Tallinn Old Town", "category": "sightseeing",
             "body": "Walk Pikk street north from the square — the merchants' guild halls and St Olaf's Church spire (159m, briefly the world's tallest building, 1549–1625) are the major monuments."},
            {"time": "19:00", "name": "Rataskaevu 16", "venue_key": "Rataskaevu 16", "category": "meal",
             "body": "Restaurant in a 14th-century cellar three minutes from the square. Estonian-modern menu, elk pâté, beetroot dumplings. The kitchen finishes the elderflower granita tableside.",
             "notes": "Book ahead — the cellar seats 40 and is full by 19:30."},
        ],
    },
    # Day 19 — Sep 1, Tue — full Tallinn day
    {
        "date": date(2026, 9, 1), "country": "Estonia", "city": "Tallinn",
        "meta": "<b>20° → 13°C</b> · 13h45 light · full city day",
        "intro": ("Tallinn's old town is small enough that a slow day covers it. "
                  "Walk up to Toompea Hill in the morning for the Alexander Nevsky "
                  "Cathedral (a Russian-imperial 1900 statement that the local "
                  "Lutherans wanted demolished after independence and didn't, "
                  "because it was already iconic) and the Kohtuotsa viewing "
                  "platform looking down on the lower town's red rooftops. Spend "
                  "the afternoon at the Kadriorg palace garden and the KUMU "
                  "art museum, then take a tram out to Telliskivi for the "
                  "post-Soviet creative district and dinner."),
        "intro_deep": ("Estonian independence (re-established 1991 from the USSR) "
                       "has shaped Tallinn faster than any other capital on the trip — "
                       "in 30 years the city built a tech industry (Skype was Estonian) "
                       "and turned a chunk of its old industrial zone into a creative "
                       "district. Telliskivi Creative City is the largest of these — "
                       "around 250 small businesses on a former locomotive-factory site, "
                       "a 12-minute tram ride from the old town."),
        "cards": [
            {"time": "09:30", "name": "Toompea Hill ascent", "venue_key": "Toompea Hill", "category": "sightseeing",
             "body": "Climb Pikk jalg ('long leg') from the lower town. The Parliament building (the orange palace) and the German Lutheran cathedral are on top."},
            {"time": "10:00", "name": "Alexander Nevsky Cathedral", "venue_key": "Alexander Nevsky Cathedral", "category": "sightseeing",
             "body": "Onion-domed Russian Orthodox cathedral (1900) — built on Tsar Nicholas II's orders to assert imperial presence over a Lutheran city. Free entry; modest dress."},
            {"time": "11:30", "name": "Kohtuotsa viewing platform", "venue_key": "Kohtuotsa viewing platform", "category": "sightseeing",
             "body": "The view down on the lower town's red rooftops is the photograph. Patkuli platform (five minutes further west) is the better light in the late afternoon."},
            {"time": "13:00", "name": "Old town lunch — Vaike Rataskaevu", "category": "meal",
             "body": "Smaller sibling of Rataskaevu 16 around the corner — cellar with a more limited menu and no booking required."},
            {"time": "15:00", "name": "Tram 4 to Kadriorg Palace", "venue_key": "Kadriorg Palace", "category": "sightseeing",
             "body": "Peter the Great's 1718 baroque palace and gardens, 4 km east. KUMU art museum (Estonian 1800–today) is in the grounds and worth 90 minutes."},
            {"time": "18:30", "name": "Telliskivi Creative City", "venue_key": "Telliskivi Creative City", "category": "sightseeing",
             "body": "Tram back to Balti jaam — the creative district is across the tracks. Walk the F-blocks for galleries, the printmakers' studio, and the vinyl shop."},
            {"time": "20:00", "name": "Põhjala Tap Room", "venue_key": "Põhjala Tap Room", "category": "meal",
             "body": "Tallinn's best craft brewery's flagship — 20+ taps in a brutalist warehouse. The smoked-lamb tacos from the kitchen pair with their Öö imperial stout."},
        ],
    },
    # Day 20 — Sep 2, Wed — Tallinn → Stockholm overnight ferry arrives
    {
        "date": date(2026, 9, 2), "country": "Sweden", "city": "Stockholm",
        "meta": "<b>18° → 12°C</b> · 13h30 light · sea-arrival day",
        "intro": ("The Tallink Baltic Queen runs overnight from Tallinn at 18:00 "
                  "and lands in Stockholm at 10:30 the next morning — sixteen and "
                  "a half hours that includes a buffet dinner, an overnight in a "
                  "cabin, and the slow morning approach through the Stockholm "
                  "archipelago (one of the trip's quiet visual highlights). The "
                  "key move is being on deck for the last hour — the islands of "
                  "the outer archipelago thin to inner-archipelago summer houses "
                  "and then the city itself materialises out of low cloud."),
        "intro_deep": ("The Baltic Queen carries 2,800 passengers in 800 cabins. Book "
                       "an outside cabin with a window (the inside cabins are cheaper "
                       "but you wake to a wall). Breakfast buffet opens 06:30; the "
                       "approach to Stockholm is most visually rewarding between 08:30 "
                       "and 10:00 when the boat is threading the Vaxholm-Sandhamn "
                       "narrows."),
        "cards": [
            {"time": "08:30", "name": "Archipelago approach", "category": "sightseeing",
             "body": "Deck 9 forward — overnight ferry's last 90 minutes through the Stockholm archipelago. Pine-tree summer houses, painted red, on small islands."},
            {"time": "10:30", "name": "Arrive Stockholm Värtahamnen", "category": "transit",
             "body": "Disembark via the foot-passenger gangway; bus 76 into the city or a 12-minute taxi to Norrmalm.",
             "travelpill": "Ferry · 16h30 overnight"},
            {"time": "14:00", "name": "Check in: Radisson Blu Waterfront Hotel", "category": "other",
             "body": "Glass-and-steel hotel beside the Central Station — the higher-floor rooms face Riddarholmen and the old town."},
            {"time": "15:30", "name": "Vasa Museum", "venue_key": "Vasa Museum", "category": "sightseeing",
             "body": "The 1628 warship that sank ten minutes into its maiden voyage, recovered intact from the harbour mud in 1961. 98% original timber, in one room. Pay the audio guide; the wood-conservation science alone is worth 30 minutes."},
            {"time": "18:30", "name": "Gamla Stan", "venue_key": "Gamla Stan", "category": "sightseeing",
             "body": "Walk south across Strömbron to the old town island — Stortorget (the square in front of the Stock Exchange) is the photograph; Mårten Trotzigs gränd is the city's narrowest alley at 90 cm."},
            {"time": "20:00", "name": "Pelikan", "venue_key": "Pelikan", "category": "meal",
             "body": "Working-class Söder beer hall, 1733 in present form, all dark wood and brass. Order the schnitzel and the akvavit flight. The dining hall is enormous and loud; that's the point."},
        ],
    },
    # Day 21 — Sep 3, Thu — Stockholm → Copenhagen train
    {
        "date": date(2026, 9, 3), "country": "Denmark", "city": "Copenhagen",
        "meta": "<b>17° → 12°C</b> · 13h15 light · last train day",
        "intro": ("The SJ direct train from Stockholm to Copenhagen takes 6h15 "
                  "and crosses the Øresund Bridge in the last 30 minutes — the "
                  "fixed-link road-and-rail crossing that since 2000 has made the "
                  "two cities feel like one metropolitan area. The route passes "
                  "Norrköping, Linköping, and Malmö on the Swedish side, then "
                  "crosses the strait at Lernacken. Lunch on the train (the bistro "
                  "is acceptable; bring snacks). Check in mid-afternoon at the "
                  "NH Collection on Christianshavn — across the harbour from "
                  "Nyhavn, in the Christianshavn canal district that the locals "
                  "actually walk through."),
        "intro_deep": ("The Øresund Bridge is 16 km total (8 km bridge, 4 km artificial "
                       "island, 4 km submerged tunnel) — the tunnel section was a "
                       "Copenhagen-airport concession so that planes could still take off. "
                       "It carries the high-speed train, regional Pågatåg, and four lanes "
                       "of road. Daily ridership is over 17,000 commuters each way; the "
                       "label 'Greater Copenhagen' for the bi-national region is a 2020 "
                       "official designation."),
        "cards": [
            {"time": "09:19", "name": "Depart Stockholm C", "category": "transit",
             "body": "SJ direct train to Copenhagen. Reserved seating; coach 1 is the quiet car.",
             "travelpill": "Train · 6h15 cross-border"},
            {"time": "14:30", "name": "Øresund Bridge crossing", "category": "sightseeing",
             "body": "South side of the train for the bridge view if seated forward; ten minutes from coast to coast over open water."},
            {"time": "15:35", "name": "Arrive Copenhagen Central", "category": "transit",
             "body": "Walk or metro to Christianshavn — the M2 yellow line, three stops."},
            {"time": "15:30", "name": "Check in: NH Collection Copenhagen", "category": "other",
             "body": "Christianshavn waterfront hotel — kayak-launch dock out front and Lille Mølle windmill across the canal. Walking distance to most of the centre."},
            {"time": "17:00", "name": "Nyhavn", "venue_key": "Nyhavn", "category": "sightseeing",
             "body": "Painted-house canal stretch you've seen in every Copenhagen photograph. Walk the south side for the better light; eat further inland (the canal-side restaurants are tourist-grade)."},
            {"time": "19:30", "name": "Apollo Bar", "venue_key": "Apollo Bar", "category": "meal",
             "body": "The Kunsthal Charlottenborg's restaurant — outdoor courtyard in the academy's quadrangle, market-driven menu, no white tablecloths. Daily-changing chalkboard."},
        ],
    },
    # Day 22 — Sep 4, Fri — full Copenhagen day
    {
        "date": date(2026, 9, 4), "country": "Denmark", "city": "Copenhagen",
        "meta": "<b>18° → 12°C</b> · 13h light · full city day",
        "intro": ("A full Copenhagen day for the things Stockholm didn't have — "
                  "Tivoli Gardens (the 1843 amusement park in the city centre, a "
                  "direct ancestor of Disneyland), the Round Tower's spiral ramp "
                  "up to the seventeenth-century observatory, Torvehallerne's "
                  "two-glass-hall market that is what Copenhagen built when it "
                  "wanted to do food halls right. Evening at Refshaleøen — the "
                  "former shipyard island east of the city, now the brewery-and-"
                  "warehouse food district where Mikkeller, Reffen street food, "
                  "and the new noma are."),
        "intro_deep": ("Refshaleøen was a Burmeister & Wain shipyard until 1996; "
                       "the conversion to creative-and-food district has been gradual "
                       "and is now most of the eastern harbour-island. Walk or bike "
                       "the loop — it is harder to do by bus and the taxi ride from "
                       "the centre is 15 minutes. The current Noma (2018, by Bjarke "
                       "Ingels) is a series of greenhouses-on-stilts; reservation is "
                       "the only way in and they open four months ahead."),
        "cards": [
            {"time": "09:30", "name": "Tivoli Gardens", "venue_key": "Tivoli Gardens", "category": "sightseeing",
             "body": "Open at 11:00 weekdays; arrive at 09:30 for the queue. The 1914 wooden Rutschebanen rollercoaster is the oldest still running. Buy the multi-ride pass."},
            {"time": "13:00", "name": "Torvehallerne", "venue_key": "Torvehallerne", "category": "meal",
             "body": "Two-glass-hall food market north of Nørreport station. Hallernes Smørrebrød does the open-face sandwich properly; Coffee Collective is the city's third-wave roaster."},
            {"time": "15:00", "name": "Rundetårn", "venue_key": "Rundetårn", "category": "sightseeing",
             "body": "Christian IV's 1642 round tower — climb the 209-metre spiral ramp (the architect didn't trust stairs) to the rooftop observatory. The view across the medieval city."},
            {"time": "16:30", "name": "Rosenborg Castle", "venue_key": "Rosenborg Castle", "category": "sightseeing",
             "body": "The Crown Jewels and a small Renaissance castle in a park. Limit it to 60 minutes; the gardens are the better experience."},
            {"time": "18:30", "name": "Refshaleøen evening", "venue_key": "Refshaleøen", "category": "meal",
             "body": "Bike or taxi out — Reffen street food market for the early evening (16 stalls, Vietnamese-Danish fusion is the standout), then Mikkeller Baghaven for the wild ales."},
            {"time": "21:00", "name": "Mikkeller Bar (city return)", "venue_key": "Mikkeller Bar", "category": "meal",
             "body": "Original Mikkeller location on Viktoriagade, ten minutes from Central. Twenty rotating taps and the most opinionated bartenders in the city.",
             "notes": "Closed Mondays."},
        ],
    },
    # Day 23 — Sep 5, Sat — Copenhagen → MSP
    {
        "date": date(2026, 9, 5), "country": "Denmark", "city": "Copenhagen → home",
        "meta": "<b>17° → 12°C</b> · 12h45 light · departure day",
        "intro": ("Out the way you came in — Copenhagen Kastrup is 12 minutes by "
                  "train from Central Station, and SAS flies the daily nonstop "
                  "to Minneapolis at 13:55. The transatlantic afternoon flight "
                  "is the chronotype-friendly direction: you land at MSP at "
                  "16:04 local, drive home, eat a late dinner, sleep on Central "
                  "Time. The lag is gone in two days."),
        "intro_deep": ("Copenhagen Kastrup is one of the better European hub airports "
                       "for a transit experience — connected to the central station by "
                       "the Metro M2 (one stop) and the Øresundståg regional train (12 "
                       "minutes, direct). Pre-clear US customs in Copenhagen if your "
                       "ticket is on a code-share carrier — saves the line at MSP."),
        "cards": [
            {"time": "10:00", "name": "Check out: NH Collection", "category": "other",
             "body": "Bags drop in lobby until departure; the hotel will hold them while you take a last walk along the canal."},
            {"time": "11:30", "name": "Metro to Kastrup", "category": "transit",
             "body": "M2 yellow line, 14 minutes door-to-airport. Buy the 36 DKK city-ticket; the airport zone counts the same as the centre."},
            {"time": "13:55", "name": "Depart Copenhagen", "category": "transit",
             "body": "SAS direct to MSP — the afternoon transatlantic flight, the chronotype-friendly direction.",
             "travelpill": "Flight · 9h30 + 7h west"},
        ],
    },
]


# ============================================================================
# FIELD GUIDE
# ============================================================================

FIELD_GUIDE = {
    "intro_lede": ("Eighteen entries split between Svalbard wildlife and the city "
                   "landmarks the rest of the trip is built around — search the "
                   "page, filter by region, click through to the Maps pin."),
    "regions": [
        {"slug": "svalbard", "label": "Svalbard · Days 4–7",
         "entries": [
             {"name": "Polar bear", "latin": "Ursus maritimus", "likelihood": "low (from boat) / nil (on foot in town)",
              "tags": ["wildlife", "svalbard"],
              "body": "About 3,000 across the Svalbard archipelago, more bears than people. The boat-trip "
                      "operators see a polar bear on roughly one in five trips in August — when ice retreats "
                      "they follow seals north and most of the population is in the pack ice. The on-land rifle "
                      "requirement outside the Longyearbyen settlement is not theatre."},
             {"name": "Beluga whale", "latin": "Delphinapterus leucas", "likelihood": "high (Isfjorden mouth, summer)",
              "tags": ["wildlife", "svalbard"],
              "body": "Pods of 5–20 visible from the Hurtigruten catamaran in August along the south Isfjorden "
                      "shoreline. White adults, gray juveniles. The hybrid-electric boat is quiet enough to drift "
                      "close without disturbing the pod."},
             {"name": "Bearded seal", "latin": "Erignathus barbatus", "likelihood": "medium",
              "tags": ["wildlife", "svalbard"],
              "body": "Hauled out on low ice floes in Isfjorden — the bristle moustache that gives the species "
                      "its name is the field-mark. Adults 2.5 m, up to 360 kg. The boat usually gets you within "
                      "50 m of an unbothered animal."},
             {"name": "Arctic tern", "latin": "Sterna paradisaea", "likelihood": "high",
              "tags": ["wildlife", "svalbard", "longyearbyen-town"],
              "body": "Dive-bombs anyone walking near a nesting colony — head protection (a hat with a stick) "
                      "is the local convention from late June through August. Migrates 70,000 km each year; the "
                      "longest annual migration of any animal."},
             {"name": "Svalbard reindeer", "latin": "Rangifer tarandus platyrhynchus", "likelihood": "high",
              "tags": ["wildlife", "svalbard", "longyearbyen-town"],
              "body": "Endemic Svalbard subspecies — shorter legs, rounder body, half the size of mainland "
                      "Norwegian reindeer. Grazing on the slopes around Longyearbyen all summer. They are not "
                      "afraid of humans and will let you walk within 10 m."},
             {"name": "Walrus", "latin": "Odobenus rosmarus", "likelihood": "low (haul-out lottery)",
              "tags": ["wildlife", "svalbard"],
              "body": "The Poolepynten haul-out on Prins Karls Forland is the famous beach — but it is a "
                      "two-hour boat ride west of Longyearbyen and only some day trips reach it. If you see "
                      "walrus on the Hurtigruten Wildlife & Glacier route, count yourself lucky."},
         ]},
        {"slug": "norway-mainland", "label": "Norway mainland · Days 8–15",
         "entries": [
             # Landmarks
             {"name": "Bryggen", "likelihood": "open-air, free",
              "tags": ["landmark", "norway", "bergen"],
              "body": "The Hanseatic wooden warehouses on Bergen's harbour — UNESCO 1979. Rebuilt repeatedly "
                      "after fires (1702, 1955) but in the original medieval footprint. The back alleys behind "
                      "the front facade are the less-photographed working trade lanes."},
             {"name": "Reinebringen", "likelihood": "hikeable in 3 hours round trip",
              "tags": ["landscape", "norway", "lofoten"],
              "body": "The 448-metre peak across the harbour from Reine; the Sherpa-built staircase (1,978 "
                      "steps, completed 2019) makes it doable. The view from the summit is the picture that "
                      "sold most travelers on Lofoten."},
             {"name": "Flåm Railway", "likelihood": "scheduled service",
              "tags": ["landmark", "norway", "transit"],
              "body": "The 20-km branch line from Myrdal to Flåm — 866 metres of descent in 55 minutes on a "
                      "1-in-18 gradient, no cog rail. Stops at the Kjosfossen waterfall for ten minutes of "
                      "photographs. Built 1924–1940."},
             {"name": "Oslo Opera House", "likelihood": "exterior accessible 24/7",
              "tags": ["landmark", "norway", "oslo"],
              "body": "Snøhetta's 2008 design — the Carrara marble roof is a public walking surface, sloping "
                      "into the fjord. Skip the interior tour; the architecture's argument is the exterior."},
             # Wildlife per stop — Lofoten
             {"name": "White-tailed sea eagle", "latin": "Haliaeetus albicilla",
              "likelihood": "high (Lofoten waters)",
              "tags": ["wildlife", "norway", "lofoten"],
              "body": "Europe's largest raptor, wingspan 2.4 m. Nests on the cliff faces around Reine and "
                      "Henningsvær — the local boat operators run dedicated sea-eagle safaris but you'll often "
                      "spot one from the cabin pier in the late afternoon as they come back to the cliff."},
             {"name": "Atlantic puffin", "latin": "Fratercula arctica",
              "likelihood": "medium (Værøy + Røst, day-trip from Reine)",
              "tags": ["wildlife", "norway", "lofoten"],
              "body": "Norway's third-largest puffin colony (~700,000 birds) is on Røst, the southernmost "
                      "Lofoten island. August is the tail of the breeding season; chicks fledge mid-month. Day "
                      "ferries from Bodø; closer to a logistics-heavy half-day than a casual trip."},
             {"name": "Orca", "latin": "Orcinus orca",
              "likelihood": "low in August (peak Nov–Jan with the herring)",
              "tags": ["wildlife", "norway", "lofoten", "tromso"],
              "body": "The Lofoten orca pod follows the winter herring run into the fjords — November through "
                      "January is the canonical window. August sightings are rare but not unheard of on the "
                      "outer-island boats out of Bodø."},
             # Wildlife per stop — Bergen
             {"name": "Common eider", "latin": "Somateria mollissima",
              "likelihood": "high (Bergen harbour year-round)",
              "tags": ["wildlife", "norway", "bergen"],
              "body": "Heavy-bodied sea duck — males black-and-white, females cinnamon-brown. The Bergen "
                      "harbour basin holds a year-round population that's habituated to people; you'll see "
                      "them paddling between the Bryggen pilings."},
             {"name": "Harbour porpoise", "latin": "Phocoena phocoena",
              "likelihood": "medium (Bergen + Tromsø coastal waters)",
              "tags": ["wildlife", "norway", "bergen", "tromso"],
              "body": "Smallest cetacean in European waters — 1.5 m, dark grey, surfaces briefly without a "
                      "tail flip. The Tromsø Polaria aquarium has a captive pod; in the wild, the Bergen "
                      "Fløibanen-funicular view across to Askøy catches occasional groups."},
         ]},
        {"slug": "baltic-cities", "label": "Helsinki + Tallinn · Days 16–19",
         "entries": [
             # Landmarks
             {"name": "Suomenlinna", "likelihood": "ferry-accessible daily",
              "tags": ["landmark", "finland", "helsinki"],
              "body": "Six-island sea fortress built by the Swedish Empire in 1748 as Sveaborg, fell to Russia "
                      "1808, to independent Finland 1918. UNESCO 1991. Inhabited — 800 residents in former "
                      "military housing. The dry dock is one of the oldest still in active use."},
             {"name": "Helsinki Cathedral", "likelihood": "free entry",
              "tags": ["landmark", "finland", "helsinki"],
              "body": "Engel's 1852 neoclassical white-and-green-domed Lutheran cathedral on Senate Square. "
                      "Built as the architectural assertion of Russia's 1809 takeover of Finland from Sweden. "
                      "The steps face the harbour; the postcard photograph is from the south."},
             {"name": "Tallinn Old Town", "likelihood": "open city",
              "tags": ["landmark", "estonia", "tallinn"],
              "body": "UNESCO World Heritage 1997. The most complete preserved medieval old town in northern "
                      "Europe — partly because Tallinn was never on a major industrial-bombing target list. "
                      "St Olaf's Church spire was briefly the world's tallest building (1549–1625)."},
             {"name": "Alexander Nevsky Cathedral", "likelihood": "free entry",
              "tags": ["landmark", "estonia", "tallinn"],
              "body": "Russian Orthodox cathedral built 1900 on Toompea Hill — Tsar Nicholas II's assertion "
                      "of imperial presence over a Lutheran city. Independent Estonia debated demolishing it "
                      "in 1924 and didn't; it is now Tallinn's most photographed building."},
             # Wildlife per stop — Helsinki + Tallinn
             {"name": "Hooded crow", "latin": "Corvus cornix",
              "likelihood": "high (every Baltic city park)",
              "tags": ["wildlife", "finland", "estonia", "helsinki", "tallinn"],
              "body": "Grey-and-black corvid, the Baltic equivalent of the Western European carrion crow. "
                      "Bold around outdoor cafés — they'll steal a salmon-soup oyster cracker if you turn "
                      "your head. The Suomenlinna ferry dock holds a permanent gang."},
             {"name": "Barnacle goose", "latin": "Branta leucopsis",
              "likelihood": "high (Helsinki + Tallinn city parks, summer)",
              "tags": ["wildlife", "finland", "estonia", "helsinki", "tallinn"],
              "body": "Black-and-white goose with a white face — they breed in Svalbard and winter in the "
                      "Wadden Sea, but a growing urban subpopulation now stays year-round in Helsinki's "
                      "Kaisaniemi park and Tallinn's Kadriorg. Watch your shoes."},
             {"name": "White-tailed sea eagle (Baltic)", "latin": "Haliaeetus albicilla",
              "likelihood": "medium (Suomenlinna outer islands)",
              "tags": ["wildlife", "finland", "helsinki"],
              "body": "Same species as the Lofoten birds but the Baltic population is the conservation success "
                      "story — recovered from <50 pairs in Finland in the 1970s to >700 pairs today. Easiest "
                      "from the outer fortifications on Suomenlinna's south islands."},
             {"name": "Common ringed plover", "latin": "Charadrius hiaticula",
              "likelihood": "medium (Estonian beaches, August migration)",
              "tags": ["wildlife", "estonia", "tallinn"],
              "body": "Small grey-and-white shorebird with a black collar; mid-August is peak southbound "
                      "migration on the Estonian coast. The Pirita beach east of Tallinn old town holds "
                      "stopover flocks of 50+."},
         ]},
        {"slug": "stockholm-copenhagen", "label": "Stockholm + Copenhagen · Days 20–22",
         "entries": [
             # Landmarks
             {"name": "Vasa", "likelihood": "museum-housed",
              "tags": ["landmark", "sweden", "stockholm"],
              "body": "1628 royal warship that sank ten minutes into its maiden voyage. Recovered intact from "
                      "the harbour mud in 1961 — 98% original timber. The museum's wood-conservation programme "
                      "(polyethylene glycol substitution over 17 years) is its own scientific landmark."},
             {"name": "Gamla Stan", "likelihood": "walkable",
              "tags": ["landmark", "sweden", "stockholm"],
              "body": "Stockholm's old town island, settled since the 13th century. Stortorget square (in front "
                      "of the Stock Exchange) is the photograph; Mårten Trotzigs gränd is the narrowest alley "
                      "at 90 cm. Royal Palace is at the north end."},
             {"name": "Nyhavn", "likelihood": "open canal",
              "tags": ["landmark", "denmark", "copenhagen"],
              "body": "17th-century canal lined with painted townhouses — the most-photographed view in "
                      "Copenhagen. Hans Christian Andersen lived at No. 67 for twenty years. The canal-side "
                      "restaurants are tourist-grade; walk one block back for a real meal."},
             {"name": "Rundetårn", "likelihood": "paid entry",
              "tags": ["landmark", "denmark", "copenhagen"],
              "body": "Christian IV's 1642 round tower with a 209-metre spiral ramp climbing to the rooftop "
                      "observatory. The architect Hans van Steenwinckel didn't trust stairs at scale; the ramp "
                      "is wide enough that a horse-and-carriage can climb (and once did, on a 1714 royal bet)."},
             # Wildlife per stop — Stockholm + Copenhagen
             {"name": "Mute swan", "latin": "Cygnus olor",
              "likelihood": "high (both city harbours, year-round)",
              "tags": ["wildlife", "sweden", "denmark", "stockholm", "copenhagen"],
              "body": "Denmark's national bird since 1984 — orange-billed, S-curved neck, often in family groups "
                      "with grey juveniles. The Riddarholmen canal in Stockholm and the Nyhavn turning basin in "
                      "Copenhagen both hold habituated pairs. They will hiss at toddlers; respect the radius."},
             {"name": "Common goldeneye", "latin": "Bucephala clangula",
              "likelihood": "medium (Stockholm archipelago, summer)",
              "tags": ["wildlife", "sweden", "stockholm"],
              "body": "Small black-and-white diving duck with a startling yellow eye and a green-black head. "
                      "The Stockholm inner archipelago between Vaxholm and the city is the southern edge of "
                      "the breeding range. Visible from the overnight ferry's morning approach."},
             {"name": "Harbour porpoise (Øresund)", "latin": "Phocoena phocoena",
              "likelihood": "medium (Copenhagen harbour + Øresund crossing)",
              "tags": ["wildlife", "denmark", "copenhagen"],
              "body": "The Øresund population is the densest in Danish waters — ~10,000 animals between Sweden "
                      "and Denmark. The bridge crossing has a side-of-the-train chance; closer to Copenhagen, "
                      "the harbour bus route between Nyhavn and Refshaleøen sometimes catches a surfacing."},
             {"name": "Greater black-backed gull", "latin": "Larus marinus",
              "likelihood": "high (every Scandinavian harbour)",
              "tags": ["wildlife", "sweden", "denmark", "stockholm", "copenhagen"],
              "body": "World's largest gull, wingspan 1.7 m, all-black mantle. They run the Copenhagen harbour "
                      "and the Stockholm Slussen lock as effective alpha-predators — visibly larger than the "
                      "herring gulls they steal from. Open-air seafood lunch with a black-back overhead is the "
                      "experience the postcards don't warn about."},
         ]},
    ],
}


# ============================================================================
# BEER (themed bonus section)
# ============================================================================

BEER = {
    "intro_lede": ("Six countries, six craft scenes that grew up in the same decade "
                   "and went in different directions. Norwegian craft is fjord-water "
                   "minimalism; Danish is the Mikkeller-school export juggernaut; "
                   "Estonian (Põhjala in particular) does the most consistent imperial "
                   "stouts in the region; Finnish leans on rye sours and the "
                   "long-tradition farmhouse styles."),
    "groups": [
        {"city": "Oslo · 5 days here", "venue_key": None,
         "intro": "Schous Plass and Grünerløkka are the brewery district. Most of the city's craft scene grew out of the 2010-onwards licensing reform that let microbreweries sell on-site.",
         "venues": [
             {"name": "Crow Bryggeri", "venue_key": "Crow Bryggeri",
              "style": "saison · IPA · sour",
              "body": "Brewpub on Torggata since 2014 — kitchen does the only credible Korean fried-chicken in Norway. Try the Pinot Noir-barrel saison if it's on."},
             {"name": "Schouskjelleren Mikrobryggeri", "venue_key": "Schouskjelleren Mikrobryggeri",
              "style": "rotating taps · cellar",
              "body": "Vaulted cellar bar in Grünerløkka, 20 rotating taps from Norway's own breweries. The on-tap brett saison is usually the standout."},
             {"name": "Cervisiam", "venue_key": "Cervisiam",
              "style": "imperial stout · porter",
              "body": "Sandnes-brewed (Stavanger region) but the Oslo tap-bar on Markveien is where you find the rare ones. The bourbon-barrel imperial stout programme is the brewery's reputation-maker."},
         ]},
        {"city": "Tromsø · 1 night",
         "intro": "The world's northernmost brewery (until 2007's Svalbard Bryggeri took that title), Mack has been on the Tromsø waterfront since 1877.",
         "venues": [
             {"name": "Mack Brewery", "venue_key": "Mack Brewery",
              "style": "pilsner · brewery tour",
              "body": "Founded 1877 — the brewery moved to Balsfjord in 2012 but the Tromsø Ølhallen taproom is on the original site. Pilsner is the default; the Arctic Ale (smoked porter) is the souvenir."},
             {"name": "Bryggeri RorBua", "venue_key": "Bryggeri RorBua",
              "style": "harbour pub",
              "body": "Working-pub side of the Mack operation, three minutes from Clarion Edge. Heated patio in summer; live music most weekends."},
         ]},
        {"city": "Bergen · 2 nights",
         "intro": "Bergen's craft scene is younger than Oslo's but more concentrated — 7 Fjell anchors the production side, half a dozen taprooms within ten minutes of Bryggen.",
         "venues": [
             {"name": "7 Fjell Brewery", "venue_key": "7 Fjell Brewery",
              "style": "IPA · seasonal",
              "body": "Founded 2015 in a converted factory in Sandviken, named after Bergen's seven hills. The Sandviken IPA is the flagship; the Snemånad winter ale is the keepsake."},
             {"name": "Henrik Øl- og Vinstove", "venue_key": "Henrik Øl- og Vinstove",
              "style": "rotating · 50 taps",
              "body": "Vetrlidsallmenningen tap house with 50+ taps and a serious cellar selection. The 7 Fjell collaboration brews land here first."},
         ]},
        {"city": "Helsinki · 2 nights",
         "intro": "Finnish craft sits on the back of a long farmhouse-brewing tradition (sahti — rye-and-juniper, often unhopped). The modern scene gets there through stouts and Pacific-hopped IPAs.",
         "venues": [
             {"name": "Bryggeri Helsinki", "venue_key": "Bryggeri Helsinki",
              "style": "brewpub · IPA",
              "body": "Sofiankatu brewpub one block from Senate Square — the in-house IPA is the default order, the smoked rye porter is the better one."},
             {"name": "Suomenlinnan Panimo", "venue_key": "Suomenlinnan Panimo",
              "style": "fortress brewpub · porter",
              "body": "On the Suomenlinna fortress islands, in a 1700s munitions storehouse. The Helsinki Portteri (1888 recipe revival) is the canonical order. Worth the ferry trip even if you'd otherwise skip the fortress walk."},
         ]},
        {"city": "Tallinn · 2 nights",
         "intro": "Põhjala is the Estonian brewery that built the modern Baltic-craft category — imperial stouts, mostly, and very good ones. Tallinn's bar scene is the easiest in the region.",
         "venues": [
             {"name": "Põhjala Tap Room", "venue_key": "Põhjala Tap Room",
              "style": "imperial stout · 20 taps",
              "body": "Brutalist warehouse in Noblessner, 20+ Põhjala taps. The Öö Imperial Baltic Porter is the must-try — it built the brewery's international reputation."},
             {"name": "Pudel Baar", "venue_key": "Pudel Baar",
              "style": "craft beer bar · imports",
              "body": "Telliskivi Creative City tap bar with Estonian + Nordic rotating taps. The most curated 12-tap selection in Tallinn; the bartenders will steer you."},
         ]},
        {"city": "Stockholm · 1 night",
         "intro": "Stockholm's craft scene runs through the alcohol-monopoly Systembolaget at retail, but on-premise is liberalised — Omnipollo and Akkurat anchor.",
         "venues": [
             {"name": "Akkurat", "venue_key": "Akkurat",
              "style": "Belgian + craft · whisky",
              "body": "Hornsgatan bar since 1995 — pre-craft-wave Belgian-beer mecca that pivoted hard. Lambic selection is the best in Scandinavia; whisky cellar is the cathedral."},
             {"name": "Omnipollos hatt", "venue_key": "Omnipollos hatt",
              "style": "fruited sour · IPA · pizza",
              "body": "Hornsgatan brewpub from the Omnipollo team — sour-forward, the fruited sours pair with the wood-fired pizzas. Lines start at 17:00."},
         ]},
        {"city": "Copenhagen · 2 nights",
         "intro": "Copenhagen is the Mikkeller-shaped centre of Nordic craft beer — three flagship Mikkeller bars in the city, plus the broader Refshaleøen brewery cluster.",
         "venues": [
             {"name": "Mikkeller Bar", "venue_key": "Mikkeller Bar",
              "style": "original location · 20 taps",
              "body": "Viktoriagade cellar bar from 2010 — the original Mikkeller location. 20 taps, mostly Mikkeller and collaborations. Closed Mondays."},
             {"name": "Warpigs Brewpub", "venue_key": "Warpigs Brewpub",
              "style": "BBQ + IPA · Mikkeller+3 Floyds",
              "body": "Meatpacking-district brewpub, Mikkeller × 3 Floyds collaboration. American-style BBQ kitchen and 20 in-house taps including a permanent Foggy Geezer New England IPA."},
             {"name": "Brus", "venue_key": "Brus",
              "style": "Nørrebro brewpub · 33 taps",
              "body": "To Øl's flagship Nørrebro brewpub — 33 taps, eclectic menu, more rotation than Mikkeller's bars. The mixed-fermentation farmhouse stuff is the section to drink."},
             {"name": "To Øl City", "venue_key": "To Øl City",
              "style": "brewery · countryside day-trip",
              "body": "Brewery, taproom, bakery, restaurant on the old Carlsberg site in Svinninge (1 hour by train) — closer to a destination than a quick stop. Worth it if you have a free morning."},
         ]},
    ],
    "opinion": ("If you only do one beer stop on the trip: Põhjala Tap Room in Tallinn "
                "on Day 19. The Öö imperial Baltic porter is the single most distinctive "
                "beer in the entire region, and standing in the brutalist warehouse "
                "looking out at the harbour cranes while drinking it is the trip's "
                "most-Baltic moment. Copenhagen's Mikkeller is excellent and globally "
                "available; Põhjala is excellent and you'll never see most of these "
                "beers anywhere else."),
}


# ============================================================================
# THINGS TO DO
# ============================================================================

THINGS_TO_DO = {
    "intro_lede": ("Off-itinerary picks across the five countries — opinionated and "
                   "specific. The trip's bookings already cover most of the obvious "
                   "moves; these are the additions worth folding in if a day opens up."),
    "groups": [
        {"label": "Oslo · half-day picks",
         "entries": [
             {"name": "Vigeland Sculpture Park", "venue_key": "Vigeland Sculpture Park", "neighborhood": "Frogner",
              "body": "Free, walkable in 90 minutes, and the closest thing Norwegian sculpture has to a single "
                      "monomaniac statement — Gustav Vigeland's 40-year contract with the city. The Monolith is "
                      "the centerpiece you've seen in books."},
             {"name": "Mathallen Oslo", "venue_key": "Mathallen Oslo", "neighborhood": "Vulkan",
              "body": "Indoor food hall in the converted Vulkan industrial complex on the Akerselva. Order at the "
                      "counter you like; the Solsiden cured-fish board is the standout."},
             {"name": "Tim Wendelboe", "venue_key": "Tim Wendelboe", "neighborhood": "Grünerløkka",
              "body": "Tiny espresso bar run by the 2004 World Barista Champion — the namesake roastery's "
                      "flagship shop. Espresso-only past 17:00. Worth the walk from the Munch."},
         ]},
        {"label": "Svalbard · open-day picks",
         "opinion": "If you only do one thing on a free Svalbard day: the Global Seed Vault walk-up. The vault "
                    "is closed to the public, but standing at the tunnel mouth in 5°C wind, looking at the silver "
                    "wedge of a building that holds backup copies of every commercially significant agricultural "
                    "seed in the world, is the trip's most quietly serious moment.",
         "entries": [
             {"name": "Camp Barentz", "venue_key": "Camp Barentz", "neighborhood": "40 min from town",
              "body": "Reconstructed Dutch-trapper cabin 40 minutes outside Longyearbyen — short polar-history "
                      "evening programme with reindeer stew and apple cake by a wood fire. The drive out is "
                      "the only time you'll see the road that leaves town."},
             {"name": "Fruene Coffee", "venue_key": "Fruene Coffee", "neighborhood": "Longyearbyen centre",
              "body": "World's northernmost full-service café (since 2007). Cloudberry cheesecake is the dish; "
                      "the women-named-and-run business model is the story."},
         ]},
        {"label": "Bergen · half-day picks",
         "entries": [
             {"name": "Lysverket", "venue_key": "Lysverket", "neighborhood": "KODE 4",
              "body": "Sea-led tasting menu in the converted Bauhaus-era electrical power station — sit at the "
                      "kitchen counter if they have it open. The pre-dinner cocktail bar is the room to be in."},
             {"name": "Fløibanen + downhill walk", "venue_key": "Fløibanen funicular", "neighborhood": "Centre",
              "body": "Eight-minute funicular up to Fløyen (320 m); walk down the marked Hellige Kors trail in "
                      "60 minutes. The descent is the better half of the trip — beech forest, opens onto a "
                      "fish-market view."},
         ]},
        {"label": "Helsinki · half-day picks",
         "opinion": "Skip the Temppeliaukio rock church queue. The architecture is interesting in photographs and "
                    "underwhelming in person — 20 minutes in line for 5 minutes inside. The Oodi Library two "
                    "blocks east is the better modern-Finnish building, with no entry fee and a vastly more "
                    "interesting interior.",
         "entries": [
             {"name": "Löyly", "venue_key": "Löyly", "neighborhood": "Hernesaari waterfront",
              "body": "Avanto Architects' 2016 waterfront sauna complex — wood-heated, smoke, and electric "
                      "rooms with direct Baltic plunge access. Two-hour public slot at 10:00 is the move."},
             {"name": "Suomenlinna walk", "venue_key": "Suomenlinna", "neighborhood": "Off-harbour islands",
              "body": "15-minute public ferry; loop the six-island fortress counter-clockwise (4 km, two hours). "
                      "The King's Gate at the south is the photograph; the dry dock at the north is the surprise."},
             {"name": "Café Regatta", "venue_key": "Café Regatta", "neighborhood": "Sibelius Park",
              "body": "Red wooden seaside cabin café next to the Sibelius monument — outdoor benches, cinnamon "
                      "buns, no inside seating. The line is part of the experience."},
         ]},
        {"label": "Tallinn · half-day picks",
         "entries": [
             {"name": "Telliskivi Creative City", "venue_key": "Telliskivi Creative City", "neighborhood": "Pelgulinn",
              "body": "250 small businesses on a former locomotive-factory site — the F-blocks for galleries, "
                      "the vinyl shop, and a Saturday flea market. Tram 1 or 2 from the old town, 12 minutes."},
             {"name": "Põhjala Tap Room", "venue_key": "Põhjala Tap Room", "neighborhood": "Noblessner",
              "body": "Tallinn's best craft brewery in a brutalist warehouse — 20+ taps, smoked-lamb tacos from "
                      "the kitchen. Worth the 15-minute walk from the old town if beer is your interest."},
         ]},
        {"label": "Stockholm · half-day picks",
         "entries": [
             {"name": "Fotografiska", "venue_key": "Fotografiska", "neighborhood": "Södermalm waterfront",
              "body": "Photography museum in a converted 1906 customs house — the rotating exhibits are the draw; "
                      "the top-floor restaurant has the best view of Gamla Stan across the water."},
             {"name": "Skansen", "venue_key": "Skansen", "neighborhood": "Djurgården",
              "body": "World's oldest open-air museum (1891) — 150 historic buildings moved from across Sweden, "
                      "plus a working Nordic-fauna zoo (lynx, bear, wolf, moose). Two hours minimum."},
             {"name": "Drop Coffee", "venue_key": "Drop Coffee", "neighborhood": "Mariatorget",
              "body": "Söder roastery from the founders who started Stockholm's third-wave coffee scene in 2009. "
                      "The window seats face the square; the espresso is the order."},
         ]},
        {"label": "Copenhagen · half-day picks",
         "opinion": "Christiania is having a transitional decade — the cannabis market moved to a more regulated "
                    "format after the 2024 reorganisation and the social experiment has changed character. Still "
                    "worth the walk if you have any interest in late-20th-century counterculture geography, but "
                    "go with curiosity, not nostalgia.",
         "entries": [
             {"name": "Torvehallerne", "venue_key": "Torvehallerne", "neighborhood": "Nørreport",
              "body": "Two-glass-hall food market that is what Copenhagen built when it wanted to do food halls "
                      "right. Hallernes Smørrebrød does the open-face sandwich properly; Coffee Collective is "
                      "the city's third-wave roaster."},
             {"name": "Refshaleøen evening", "venue_key": "Refshaleøen", "neighborhood": "Eastern harbour island",
              "body": "Former Burmeister & Wain shipyard, now the food-and-brewery district. Reffen street food "
                      "for early evening (16 stalls); Mikkeller Baghaven for the wild ales next door."},
             {"name": "Rosenborg Castle gardens", "venue_key": "Rosenborg Castle", "neighborhood": "Inner city",
              "body": "Skip the interior castle (60 minutes for the Crown Jewels and not much else); the "
                      "Kongens Have park around it is the better experience — locals on blankets, the changing "
                      "of the guard at noon."},
         ]},
    ],
}


# ============================================================================
# WEATHER
# ============================================================================

WEATHER = {
    "intro_lede": ("Five regions, three climate zones — Arctic (Svalbard), maritime "
                   "northern (mainland Norway), and continental Baltic (Helsinki/Tallinn/"
                   "Stockholm/Copenhagen). Pack for all three; the warmest day on the "
                   "trip will be 22°C, the coldest 2°C."),
    "stat_grid": [
        {"label": "High (warm side)",  "value": "22°C", "context": "Oslo / Helsinki midday"},
        {"label": "Low (cold side)",   "value": "2°C",  "context": "Svalbard mid-fjord at night"},
        {"label": "Rain days expected","value": "8/23", "context": "Bergen guaranteed; Oslo + Copenhagen possible"},
        {"label": "Daylight range",    "value": "12–24h","context": "12h45 in Copenhagen end; 24h continuous in Svalbard"},
    ],
    "season_notes": ("Mid-August into early September is the trip's narrow window. "
                     "Svalbard's last reliable boat-tour week is the third week of August "
                     "(the operators wind down by early September). Lofoten weather "
                     "transitions from August's reliable sun to September's first real "
                     "rain. By Copenhagen on Day 22, the days are 13 hours of light and "
                     "the evenings cool to 12°C — the trip's last summer evenings."),
    "packing_implications": [
        "Real coat (down or shell + wool layers) for Svalbard — 2°C wind is the cold reality, not the air temp",
        "Layered hiking shoes good through wet for Lofoten + Bergen — leather boots are too warm, runners too thin",
        "Light city outerwear for the Baltic capitals — late August evenings cool fast but rarely cross 12°C",
        "Swimsuit + microfiber towel for Sørenga Sjøbad in Oslo, Löyly in Helsinki, and the Reine cabin pier",
    ],
}


# ============================================================================
# HISTORY
# ============================================================================

HISTORY = {
    "intro_lede": ("Five capitals across five countries that have spent the last "
                   "thousand years rearranging which of them belonged to which of the "
                   "others. The condensed version is below — by country, by era, with "
                   "the present-day artefacts each chapter left behind."),
    "vignettes": [
        # Norway
        {"title": "Norway · from Vikings to oil",
         "era_slug": "viking",
         "lede": ("Norway's recorded history starts with the Vikings (793 CE raid on Lindisfarne) and ends — for "
                  "narrative purposes — with the 1969 Ekofisk oil discovery. Everything in between is somebody "
                  "else ruling."),
         "deep": ("The first unified Norway came together under Harald Fairhair around 872; the country lost its "
                  "independence to a personal union with Denmark in 1380 and then Sweden in 1814, regaining full "
                  "sovereignty only in 1905 with the dissolution of the Sweden-Norway union. The wealth that "
                  "shaped present-day Oslo — the Opera House, the Munch, the rebuilt waterfront — is the second-"
                  "order consequence of the Ekofisk discovery and the sovereign wealth fund that followed. The "
                  "Viking Ship Museum's ships (Oseberg 834 CE, Gokstad 890 CE) are the country's most-visited "
                  "objects and were found in burial mounds along the Oslofjord in the 1880s and 1900s by farmers "
                  "ploughing fields."),
         "consequence": "The waterfront you walk in Oslo is 2008-onwards and oil-funded; the Viking ships were "
                        "found by farmers.",
         "dig_deeper": {
             "title": "How the oil fund actually works",
             "body": ("The Government Pension Fund Global was set up in 1990 to hold Norway's North Sea revenues; "
                      "it now manages roughly $1.5 trillion — about $275,000 per Norwegian citizen, around 1.5% of "
                      "all listed equities globally. Two design choices made it durable. First, every krone is "
                      "invested abroad — domestic spending of oil money would inflate the currency and crush "
                      "non-oil exports (the Dutch-disease lesson from the 1970s Netherlands). Second, the "
                      "handlingsregel fiscal rule caps annual government drawdown at ~3% of the fund's market "
                      "value, treating oil as a permanent endowment rather than a windfall. A separate Council on "
                      "Ethics excludes tobacco, coal, controversial weapons, and companies systematically "
                      "violating human rights, publishing each exclusion with its reasoning.")
         }},
        # Svalbard
        {"title": "Svalbard · treaty island",
         "era_slug": "modern",
         "lede": ("Svalbard was a no-man's-land until the 1920 Svalbard Treaty made it Norwegian territory open "
                  "to all signatory states' citizens — the reason the Russian, Thai, and Filipino-origin residents "
                  "of Longyearbyen are running shops on the main street."),
         "deep": ("Willem Barentsz reached Svalbard in 1596 looking for the Northeast Passage and named it "
                  "Spitsbergen ('pointed mountains'). For 300 years no nation claimed it — the whalers (Dutch, "
                  "English, Norwegian, Russian) worked from seasonal camps and left when ice came. The 1920 treaty "
                  "(part of the Versailles negotiation) gave Norway sovereignty but kept commercial access open. "
                  "The Russian coal-mining settlement at Barentsburg, 90 km south of Longyearbyen, still operates "
                  "under that treaty provision. The Global Seed Vault (2008) is the most quietly serious "
                  "demonstration that the treaty's openness is permanent."),
         "consequence": "The town has a permanent Russian neighbour at Barentsburg and the world keeps its "
                        "agricultural backup in a mountain you can walk to.",
         "dig_deeper": {
             "title": "What is actually in the Global Seed Vault",
             "body": ("The vault opened in February 2008 at Platåberget, 130 metres into a sandstone mountain "
                      "above Longyearbyen, kept at −18°C by the surrounding permafrost. It holds backup copies "
                      "of seed samples deposited by 80+ national and regional gene banks — over 1.3 million "
                      "distinct varieties, including 150,000+ wheat and rice cultivars. The vault is a *backup* "
                      "repository: depositing banks retain ownership, can withdraw their samples at any time, and "
                      "have done so in earnest exactly once — Syria's ICARDA gene bank, displaced by the civil "
                      "war, withdrew samples in 2015 to reseed at facilities in Lebanon and Morocco. A 2017 "
                      "entrance-tunnel flood from melting permafrost prompted a $20M climate-resilience rebuild.")
         }},
        # Finland
        {"title": "Finland · between two empires",
         "era_slug": "early-modern",
         "lede": ("Finland was Swedish for 600 years (1249–1809), then Russian for 108 years (1809–1917), then "
                  "independent — and the result is a country that is culturally Lutheran-Swedish but politically "
                  "shaped by its century of Russian-empire administration."),
         "deep": ("Helsinki was a fishing village until 1812 when Tsar Alexander I promoted it to capital of the "
                  "Grand Duchy of Finland — Stockholm was too close to the Swedish border. The German architect "
                  "C. L. Engel was hired to design the new capital in neoclassical Russian-imperial style; the "
                  "Senate Square ensemble (Cathedral, Senate, University) is his work, completed by 1852. "
                  "Independence came on December 6, 1917, as Russia collapsed. The 1939–40 Winter War and "
                  "1941–44 Continuation War kept Finland out of the Soviet sphere; the price was 11% of "
                  "pre-war territory ceded to the USSR (Karelia)."),
         "consequence": "Helsinki's monumental centre is Russian-imperial neoclassicism; the rest of the city "
                        "is what an independent Finland chose to add.",
         "dig_deeper": {
             "title": "Why Alexander I moved the capital from Turku to Helsinki",
             "body": ("Turku had been the Finnish capital since the 14th century — older, larger, tied to Swedish-"
                      "administrative tradition. Alexander I moved it in 1812 for two strategic reasons. First, "
                      "distance: Helsinki sat 250 km further from the Swedish border than Turku, making any "
                      "Swedish revanchism a much harder operation to support. Second, proximity to St Petersburg "
                      "and the Russian naval base at Kronstadt — Helsinki was reachable from the imperial capital "
                      "in days, not weeks. The 1827 Great Fire of Turku later destroyed two-thirds of the old "
                      "capital, removing the option to reverse the decision. Alexander's German architect C. L. "
                      "Engel was hired in 1816 and spent the next thirty years building the Senate-Square "
                      "ensemble in St-Petersburg neoclassical style.")
         }},
        # Estonia
        {"title": "Estonia · medieval to digital",
         "era_slug": "medieval",
         "lede": ("Tallinn's old town walls and merchant houses date from a 13th–15th-century Hanseatic League "
                  "membership. The country's 1991 independence from the Soviet Union has been the most rapid "
                  "modernisation of any of the post-Soviet states — Skype was Estonian, e-residency was Estonian, "
                  "and the digital-state architecture is studied in policy schools."),
         "deep": ("Estonia entered the Hanseatic League in 1284 (Tallinn was Reval to its Hanse trading partners) "
                  "and the old town's red-roof complex is the league's surviving northern-Europe artefact — "
                  "more complete than Bergen's Bryggen or Lübeck's Holstentor. The 1561–1710 Swedish period and "
                  "the 1710–1918 Russian-imperial period built the Toompea-hill Lutheran-and-Orthodox layered "
                  "complex you climb on Day 19. The 1918 independence lasted 22 years until the 1940 Soviet "
                  "occupation; the 1991 re-independence has been the country's longest sovereign run since "
                  "1561."),
         "consequence": "The old-town walls are medieval Hanseatic; the digital state is the most recent layer.",
         "dig_deeper": {
             "title": "How X-Road and the digital state actually work",
             "body": ("Estonia's digital state runs on X-Road — a federated data-exchange layer first deployed in "
                      "2001 that lets government services request data from each other (and from authorised "
                      "private parties) without building a central database. Each citizen has one digital ID "
                      "backed by public-key cryptography; once you log in, every service knows it is you. Tax "
                      "returns are pre-filled and take about 3 minutes; prescriptions are issued digitally "
                      "directly to pharmacies; the company-formation system can register an LLC in under an "
                      "hour. Every data lookup is logged to an immutable KSI blockchain ledger the citizen can "
                      "audit — the architecture's most important property is that you can see, at any time, "
                      "exactly which agency looked up your records and why.")
         }},
        # Sweden + Denmark
        {"title": "Sweden + Denmark · the imperial neighbours",
         "era_slug": "early-modern",
         "lede": ("Sweden and Denmark were the two imperial powers of the Baltic for most of the modern era — "
                  "Sweden's 1611–1721 'great power' century and Denmark's longer 1397–1814 hegemony. The Vasa "
                  "in Stockholm and the Tivoli in Copenhagen are the artefacts of each."),
         "deep": ("Sweden's brief great-power century (Stormaktstiden) is the moment the Vasa was built — a "
                  "1628 royal warship that sank ten minutes into its maiden voyage in Stockholm harbour, "
                  "recovered in 1961, now in a single museum room. The country's 19th-century industrialisation "
                  "(Nobel's dynamite 1867, the early Volvo and Saab 1920s) sits on the imperial-era foundation. "
                  "Denmark's longer hegemony spanned the Kalmar Union (1397–1523, ruling Sweden, Norway, "
                  "Iceland, the Faroes) and the loss of Norway (to Sweden, 1814) and the Schleswig wars with "
                  "Prussia (1848, 1864). The Tivoli (1843, Christian VIII's grant) and the Carlsberg brewery "
                  "(1847) are the early-industrial Copenhagen artefacts that survived into the present."),
         "consequence": "Stockholm's Vasa is the only intact warship of the 17th century anywhere; the Tivoli "
                        "is the direct ancestor of Disneyland (Walt visited in 1951).",
         "dig_deeper": {
             "title": "Why the Vasa sank",
             "body": ("The Vasa's sinking has three immediate causes and one structural one. The hull cross-section "
                      "was too narrow for the second gun deck Gustav II Adolf demanded mid-construction, putting "
                      "cannons higher above the waterline than the hull could counterweight. Ballast was "
                      "insufficient: shipwrights kept reducing the stone load because adding it lowered the "
                      "gun-port sills toward sea level. A stability test was run in harbour before launch — 30 "
                      "men running back and forth across the deck — and abandoned after three passes because the "
                      "ship was clearly listing past safe limits; the launch went ahead anyway. The structural "
                      "cause: the king was at war in Poland, demanded immediate launch, and 17th-century "
                      "shipwrights had no formal stability theory to push back with quantitatively.")
         }},
    ],
    "phrase_table": [
        {"row": ["English",        "Norwegian",   "Finnish",        "Estonian",      "Swedish",     "Danish"]},
        {"row": ["Hello",          "Hei",         "Hei / Moi",       "Tere",          "Hej",         "Hej"]},
        {"row": ["Please",         "Vær så snill","Olkaa hyvä",      "Palun",         "Snälla",      "Venligst"]},
        {"row": ["Thank you",      "Takk",        "Kiitos",          "Aitäh",         "Tack",        "Tak"]},
        {"row": ["Excuse me",      "Unnskyld",    "Anteeksi",        "Vabandage",     "Ursäkta",     "Undskyld"]},
        {"row": ["Do you speak English?","Snakker du engelsk?","Puhutko englantia?","Kas räägite inglise keelt?","Talar du engelska?","Taler du engelsk?"]},
        {"row": ["Yes / No",       "Ja / Nei",     "Kyllä / Ei",      "Jah / Ei",      "Ja / Nej",    "Ja / Nej"]},
        {"row": ["1 / 2 / 3",      "én / to / tre","yksi / kaksi / kolme","üks / kaks / kolm","en / två / tre","en / to / tre"]},
        {"row": ["Cheers",         "Skål",         "Kippis",          "Terviseks",     "Skål",        "Skål"]},
    ],
}


# ============================================================================
# FUN FACTS
# ============================================================================

FUN_FACTS = {
    "intro_lede": ("Five-country trivia stitched by national borders — what you'll "
                   "be curious about at dinner and what you actually need to know."),
    "trivia_groups": [
        {"label": "Norway",
         "items": [
             "Norway has more tunnels than any other country per capita — 1,200 road tunnels, including the world's longest (Lærdal, 24.5 km, on the Bergen route).",
             "The sovereign wealth fund (Statens pensjonsfond utland) holds ~$1.5T, about 1.5% of all listed equities globally.",
             "Norwegians vote on Wikipedia's most-edited article every February — *fårikål* (mutton-cabbage stew) is the national dish.",
             "The Svalbard reindeer is a separate subspecies — shorter legs, half the size of mainland reindeer.",
         ]},
        {"label": "Finland",
         "items": [
             "Finland has 188,000 lakes (3 million saunas, by some counts) — more saunas than cars.",
             "*Sisu* is the cultural-export word — stoic perseverance, especially in cold or adversity.",
             "Finland's 'baby box' — a cardboard box of newborn supplies given by the state since 1938 — became the original cardboard-box-as-crib.",
             "The world's first dedicated heavy-metal kindergarten is in Helsinki (Hevisaurus).",
         ]},
        {"label": "Estonia",
         "items": [
             "Estonia issued the world's first e-residency programme (2014) — anyone in the world can establish an EU-resident digital business identity.",
             "Skype was developed in Tallinn (2003) — the four original engineers were Estonian and the early product was built in a cellar near the Old Town.",
             "Estonian uses 'sina' (you, singular) without honorifics — there is no formal-you in everyday speech (unlike Finnish, Swedish, German).",
             "The 1989 Baltic Way human chain — 2 million people linking Tallinn, Riga, and Vilnius — was the largest peaceful protest of the 20th century.",
         ]},
        {"label": "Sweden",
         "items": [
             "The 1628 Vasa sank because Gustav II ordered an extra gun deck added late in construction; the ship was top-heavy. The shipwright drowned in the same harbour eight days later.",
             "The right-hand-drive switch (Dagen H, September 3, 1967) is the largest single-day infrastructure swap any country has done.",
             "Swedish parental leave: 480 days per child, 90 of which are reserved for the second parent (the 'daddy quota').",
             "ABBA is the third-best-selling music act of all time (after the Beatles and Elvis), per RIAA-certified units.",
         ]},
        {"label": "Denmark",
         "items": [
             "Denmark has the world's oldest continuously operating amusement park — Bakken (1583, north of Copenhagen) — and the second-oldest, Tivoli (1843).",
             "Lego was invented in Billund in 1949 — the name is *leg godt*, 'play well.'",
             "The Danish flag (Dannebrog) is, by tradition, the world's oldest national flag still in use — adopted 1219.",
             "Walt Disney visited Tivoli in 1951 and 1956; Disneyland (1955) is the architectural and conceptual descendant.",
         ]},
    ],
    "practical_tips_groups": [
        {"label": "Money",
         "items": [
             "Norway, Sweden, Denmark each have their own krone — DKK, NOK, SEK — not interchangeable.",
             "Finland and Estonia use the Euro.",
             "Card payments are universal; cash is rare. Apple Pay / Google Pay work everywhere.",
             "Tipping: round up (5–10%) for good service; 15–20% is American, not Scandinavian.",
         ]},
        {"label": "Transit + connectivity",
         "items": [
             "eSIM: Airalo or Nomad with a 30-day Scandinavia plan covers all five countries on one number.",
             "Norwegian Vy (trains), Finnish VR, Swedish SJ, Danish DSB — all in English. The Eurail Scandinavia pass is worth it for ≥4 train days.",
             "Helsinki, Tallinn, Stockholm, Copenhagen all use city transit apps (HSL, Pilet, SL, Rejseplanen) — buy single tickets in-app, no queue.",
             "Plug type F (European Schuko) everywhere — same adapter the whole trip. 230V/50Hz.",
         ]},
        {"label": "Etiquette",
         "items": [
             "Take off your outdoor shoes inside any home or smaller hotel — universal in Scandinavia and Estonia.",
             "Do not make small talk on transit — public space silence is the cultural default.",
             "The 'allemansrätten' (right to roam) means you can hike or camp on uncultivated land — extends to Norway, Sweden, Finland.",
             "Sauna in Finland is co-ed-naked among friends/family — towel-wrapped is the international-traveler concession.",
         ]},
    ],
}


# ============================================================================
# FOOD
# ============================================================================

FOOD = {
    "intro_lede": ("Five food cultures with overlapping fish and bread DNA and very "
                   "different feelings about everything else — Norwegian dried-cod "
                   "stoicism, Finnish fermented-rye health-food rigour, Estonian "
                   "Hanseatic-meets-Nordic, Swedish fika ceremony, Danish smørrebrød "
                   "open-faced theatre."),
    "things_to_try": [
        {"name": "Rakfisk", "local": "rakfisk", "region": "Norway", "tag": "dish",
         "body": "Fermented trout served raw with flatbread, onions, sour cream. "
                 "Strong smell, mild taste, mountainous-Norway specialty."},
        {"name": "Stockfish (dried cod)", "local": "tørrfisk", "region": "Norway", "tag": "dish",
         "body": "The Lofoten staple — cod air-dried on wooden racks for 3 months. "
                 "Reconstituted in lutefisk preparations or eaten as a salty snack."},
        {"name": "Brunost", "local": "brunost", "region": "Norway", "tag": "dish",
         "body": "Sweet caramelised brown whey-cheese — slice thin on bread with butter. "
                 "Tastes like cheese-and-dulce-de-leche. The supermarket basic."},
        {"name": "Cloudberry", "local": "molte", "region": "Norway / Finland", "tag": "dish",
         "body": "Arctic-tundra berry, orange-amber, available only in late August. "
                 "Eaten as a jam with cheese or as a dessert with whipped cream."},
        {"name": "Karjalanpiirakka", "local": "karjalanpiirakka", "region": "Finland", "tag": "breakfast",
         "body": "Rye-crust hand-pie filled with rice porridge — Karelian, eaten with "
                 "egg butter (munavoi) on top. Every Finnish breakfast buffet has it."},
        {"name": "Mustikkapiirakka", "local": "mustikkapiirakka", "region": "Finland", "tag": "dessert",
         "body": "Wild-blueberry pie with vanilla custard — the Finnish-coffee-shop "
                 "default. Café Regatta in Helsinki does the canonical version."},
        {"name": "Verivorst", "local": "verivorst", "region": "Estonia", "tag": "dish",
         "body": "Estonian blood sausage with cranberry compote — winter holiday food but "
                 "available year-round. Rich, peppery, requires the cranberry."},
        {"name": "Kohuke", "local": "kohuke", "region": "Estonia", "tag": "snack",
         "body": "Soviet-era chocolate-covered sweet quark bar — Estonia's beloved "
                 "shame-food. The vanilla one is the original; gas-station ubiquitous."},
        {"name": "Köttbullar", "local": "köttbullar", "region": "Sweden", "tag": "dish",
         "body": "Pork-and-beef meatballs with cream gravy, lingonberry jam, mashed "
                 "potato. The IKEA version is not wrong; Pelikan's is the canonical."},
        {"name": "Toast Skagen", "local": "toast Skagen", "region": "Sweden", "tag": "snack",
         "body": "Mayo-bound shrimp salad on butter-fried bread with dill and a wedge "
                 "of lemon. The aperitif-hour default at any half-decent Stockholm "
                 "restaurant."},
        {"name": "Smørrebrød", "local": "smørrebrød", "region": "Denmark", "tag": "dish",
         "body": "Open-faced rye-bread sandwich — herring, pâté, roast beef, egg-and-"
                 "shrimp the four canonical toppings. Torvehallerne's Hallernes does "
                 "the proper version."},
        {"name": "Æbleskiver", "local": "æbleskiver", "region": "Denmark", "tag": "dessert",
         "body": "Pancake-puff balls (despite the apple in the name, the modern "
                 "version usually has no apple). Christmas-market food now year-round; "
                 "dusted with sugar, served with raspberry jam."},
    ],
    "opinion": ("If you eat one fish meal that you remember from this trip, make it "
                "Anita's Sjømat in Sakrisøy on Lofoten Day 10. Stockfish burger, "
                "salmon sashimi from the morning boat, family running the place since "
                "the 1970s. The window-counter operation is the antithesis of every "
                "white-tablecloth fish restaurant you'll eat at on the same trip — "
                "and the cod will be better."),
    "where_to_eat": [
        {"tier": "Splurge",
         "label": "Splurge · big-night meals",
         "entries": [
             {"name": "Maaemo", "venue_key": "Maaemo", "city": "Oslo",
              "body": "Three-Michelin-star, seasonal Norwegian, books out 90 days ahead",
              "tag": "tasting · 3⭐", "booked": True},
             {"name": "Noma", "venue_key": "Noma", "city": "Copenhagen",
              "body": "Bjarke-Ingels greenhouse complex on Refshaleøen — fauna/sea/forest "
                      "seasonal menus; four-month-ahead booking", "tag": "tasting · 3⭐"},
             {"name": "Geranium", "venue_key": "Geranium", "city": "Copenhagen",
              "body": "Eighth-floor 50/50 vegetable-and-seafood — the other Copenhagen "
                      "three-star, easier to book", "tag": "tasting · 3⭐"},
             {"name": "Olo", "venue_key": "Olo Restaurant", "city": "Helsinki",
              "body": "Harbourside Finnish modern; the chef-counter seats are the bookable "
                      "highlight", "tag": "tasting · 1⭐", "booked": True},
             {"name": "Lysverket", "venue_key": "Lysverket", "city": "Bergen",
              "body": "Sea-led tasting in KODE 4's old electrical-substation; kitchen "
                      "counter when available", "tag": "tasting"},
         ]},
        {"tier": "Sit-down",
         "label": "Sit-down · real dinner",
         "entries": [
             {"name": "Huset", "venue_key": "Huset", "city": "Longyearbyen",
              "body": "Old miners' mess; the four-course tasting + a 1000-bottle wine cellar "
                      "(treaty-zero-tax)", "tag": "fjord", "booked": True},
             {"name": "Fiskekompaniet", "venue_key": "Fiskekompaniet", "city": "Tromsø",
              "body": "Harbourside fish house; day's catch grilled, brown butter",
              "tag": "seafood", "booked": True},
             {"name": "Rataskaevu 16", "venue_key": "Rataskaevu 16", "city": "Tallinn",
              "body": "14th-century cellar, modern-Estonian; the elderflower granita "
                      "tableside-finish", "tag": "Estonian", "booked": True},
             {"name": "Pelikan", "venue_key": "Pelikan", "city": "Stockholm",
              "body": "1733 Söder beer hall; köttbullar + akvavit flight + dark wood",
              "tag": "Swedish classic", "booked": True},
             {"name": "Apollo Bar", "venue_key": "Apollo Bar", "city": "Copenhagen",
              "body": "Charlottenborg academy courtyard; market-driven, daily chalkboard",
              "tag": "Danish modern", "booked": True},
         ]},
        {"tier": "Casual",
         "label": "Casual · weekday lunch",
         "entries": [
             {"name": "Mathallen Oslo", "venue_key": "Mathallen Oslo", "city": "Oslo",
              "body": "Indoor food hall, Vulkan complex; Solsiden cured-fish board the "
                      "standout", "tag": "food hall"},
             {"name": "Old Market Hall", "venue_key": "Old Market Hall", "city": "Helsinki",
              "body": "1889 red-brick Vanha Kauppahalli; salmon-soup stall is the lunch",
              "tag": "market hall"},
             {"name": "Torvehallerne", "venue_key": "Torvehallerne", "city": "Copenhagen",
              "body": "Two-glass-hall market north of Nørreport; Hallernes Smørrebrød + "
                      "Coffee Collective", "tag": "food hall"},
             {"name": "Östermalms Saluhall", "venue_key": "Östermalms Saluhall", "city": "Stockholm",
              "body": "1888 covered market, recently restored; Lisa Elmqvist for shrimp",
              "tag": "market hall"},
         ]},
        {"tier": "Street + markets",
         "label": "Street + markets · quick bites",
         "entries": [
             {"name": "Anita's Sjømat", "venue_key": "Anita's Sjømat", "city": "Lofoten",
              "body": "Window-counter fish-shack in Sakrisøy; stockfish burger, sashimi",
              "tag": "fish counter"},
             {"name": "Reffen", "city": "Copenhagen",
              "body": "Refshaleøen street-food market; 16 stalls, Vietnamese-Danish fusion "
                      "the standout", "tag": "street food"},
             {"name": "Fish Market Bergen", "venue_key": "Fish Market", "city": "Bergen",
              "body": "Outdoor + covered hall; smoked-salmon flight + the whale-meat "
                      "sample for the curious", "tag": "fish market"},
             {"name": "Café Regatta", "venue_key": "Café Regatta", "city": "Helsinki",
              "body": "Red-cabin seaside coffee + cinnamon-bun bench; the queue is part "
                      "of it", "tag": "café"},
         ]},
    ],
}


# ============================================================================
# SOURCES + GO-DEEPER CARDS
# ============================================================================

SOURCES_NOTE = ("Sources for this guide. Norwegian history draws on Hans Sigurd Jensen's "
                "<i>A History of the Norwegian Vikings</i> and the Visit Norway tourism "
                "board for current rail / ferry data. Svalbard wildlife draws on Norwegian "
                "Polar Institute fact sheets. Helsinki and Tallinn historical context "
                "draws on Pasi Saukkonen's <i>Erik XIV and the Baltic</i>. Copenhagen "
                "food scene draws on the Politiken restaurant section. Weather data: "
                "yr.no (Norwegian Met Office), fetched 2026-06-27. Opinion is marked in "
                "the prose; sources for individual claims are linked in the &lsquo;Sources "
                "&amp; further reading&rsquo; section at the foot.")
TRIP_META["sources_note"] = SOURCES_NOTE

GO_DEEPER = {
    # Per-section 4-card asides at Deep tier
    "day_by_day": [
        {"kind": "Book", "title": "The Snow Tourist", "url": "https://www.bloomsbury.com/uk/snow-tourist-9780747597551/",
         "annotation": "Charlie English's travel memoir hits Norway and Lofoten with the right kind of attentive boredom — slow, observational, willing to spend a paragraph on a single fish."},
        {"kind": "Podcast", "title": "The Daily Stoic — Svalbard episodes", "url": "https://thedailystoic.com/podcast/",
         "annotation": "Ryan Holiday's interviews with polar explorers — uneven, but the Svalbard-specific ones are interesting on what isolation does to attention."},
        {"kind": "Film", "title": "Trollhunter (2010)", "url": "https://www.imdb.com/title/tt1740707/",
         "annotation": "André Øvredal's mock-doc about a Norwegian government troll-hunter — for the unironic Norwegian landscape cinematography across Lofoten and the Hardangervidda."},
        {"kind": "Local voice", "title": "Visit Norway editorial", "url": "https://www.visitnorway.com/",
         "annotation": "The official board, but the editorial section under 'Inspiration' is genuinely well-written and current — not the marketing fluff you'd expect from a tourism authority."},
    ],
    "field_guide": [
        {"kind": "Book", "title": "Birds of the Western Palearctic", "url": "https://www.oxfordreference.com/display/10.1093/acref/9780198549499.001.0001/acref-9780198549499",
         "annotation": "The reference identification guide — overkill for a casual trip but the one to own if you'll do this region again. Compact concise edition is fine."},
        {"kind": "Podcast", "title": "Outside/In — Arctic episodes", "url": "https://www.nhpr.org/podcast/outside-in",
         "annotation": "NHPR's environmental reporting podcast; the climate-affected-Arctic episodes set the context the field guides don't."},
        {"kind": "Film", "title": "Encounters at the End of the World (2007)", "url": "https://www.imdb.com/title/tt1093824/",
         "annotation": "Werner Herzog's Antarctic doc — not Svalbard but the closest cinematic analogue to what 24-hour daylight does to people."},
        {"kind": "Local voice", "title": "Norwegian Polar Institute", "url": "https://www.npolar.no/en/",
         "annotation": "Government polar research arm; the species fact sheets are public-facing, current, and not dumbed down."},
    ],
    "history": [
        {"kind": "Book", "title": "The Northmen's Fury", "url": "https://www.harpercollins.com/products/the-northmens-fury-philip-parker",
         "annotation": "Philip Parker's one-volume Viking history — narrative-driven, dates and names where it matters, the standard popular entry."},
        {"kind": "Podcast", "title": "Hardcore History — Wrath of the Khans (Scandinavian intersection episodes)", "url": "https://www.dancarlin.com/hardcore-history-series/",
         "annotation": "Dan Carlin's series touches the Norse-Mongol diplomatic threads that most popular histories skip."},
        {"kind": "Film", "title": "The Last King (2016)", "url": "https://www.imdb.com/title/tt4995864/",
         "annotation": "Norwegian medieval drama about the 1206 birch-leg infant-king crossing the mountains in winter. Historically loose, visually convincing about the era's geography."},
        {"kind": "Local voice", "title": "ScandiKitchen newsletter", "url": "https://www.scandikitchen.co.uk/",
         "annotation": "London-based Scandinavian food shop; their newsletter is the most current English-language pulse on Nordic food culture I've found."},
    ],
    "food": [
        {"kind": "Book", "title": "Noma: Time and Place in Nordic Cuisine", "url": "https://www.phaidon.com/store/food-cook/noma-time-and-place-in-nordic-cuisine-9780714859033/",
         "annotation": "René Redzepi's manifesto cookbook — for the philosophy of New Nordic, not the actual recipes (most are unrepeatable at home)."},
        {"kind": "Podcast", "title": "Eat to Live with Joel Fuhrman (Nordic-diet episodes)", "url": "https://www.drfuhrman.com/library/podcasts",
         "annotation": "Not a food-tourism podcast — a nutrition one that takes the Nordic-diet research seriously."},
        {"kind": "Film", "title": "The Apartment (1960 with Lemmon)", "url": "https://www.imdb.com/title/tt0053604/",
         "annotation": "Not on-topic but watch it before Copenhagen — the Christmas-light shot of the apartment is what every Nyhavn-restaurant interior aspires to."},
        {"kind": "Local voice", "title": "Andreas Viestad (Norwegian food writer)", "url": "https://www.andreasviestad.no/",
         "annotation": "Long-form Norwegian food writing in English; his Lofoten-fish-economics essay is the canonical short read."},
    ],
}

BIBLIOGRAPHY = [
    {"group": "On the history",
     "entries": [
         {"title": "The Northmen's Fury", "url": "https://www.harpercollins.com/products/the-northmens-fury-philip-parker",
          "author": "Philip Parker", "year": "2014",
          "annotation": "One-volume Viking history; narrative-driven, the standard popular entry."},
         {"title": "A History of the Norwegian Vikings", "url": "https://www.cambridge.org/core/books/cambridge-history-of-scandinavia/",
          "author": "Hans Sigurd Jensen", "year": "2018",
          "annotation": "Academic but readable; the Lofoten-cod-trade chapter explains why the islands matter."},
         {"title": "Estonia: A Short History", "url": "https://www.routledge.com/Estonia-A-Short-History/",
          "author": "Mart Laar", "year": "2019",
          "annotation": "Former Estonian prime minister; biased toward his political project but the medieval-through-Soviet narrative is solid."},
     ]},
    {"group": "On the wildlife",
     "entries": [
         {"title": "Polar Bears: Ecology and Conservation", "url": "https://www.uchicago.edu/research/center/polar-bears/",
          "author": "Andrew Derocher", "year": "2012",
          "annotation": "The canonical species monograph; chapters on Svalbard-specific populations are the relevant reading."},
         {"title": "Norwegian Polar Institute fact sheets", "url": "https://www.npolar.no/en/species/",
          "author": "Norwegian Polar Institute",
          "annotation": "Free public PDFs on every Svalbard species; updated annually."},
     ]},
    {"group": "On the food",
     "entries": [
         {"title": "Noma: Time and Place in Nordic Cuisine", "url": "https://www.phaidon.com/store/food-cook/noma-time-and-place-in-nordic-cuisine-9780714859033/",
          "author": "René Redzepi", "year": "2010",
          "annotation": "The manifesto cookbook; the philosophy is the point, not the recipes."},
         {"title": "Mat: A Nordic Cooking Annual", "url": "https://www.matarchive.com/",
          "author": "Andreas Viestad et al.", "year": "annual",
          "annotation": "Bilingual Norwegian-English food annual; the Lofoten-fish essays are the canonical short reads."},
     ]},
    {"group": "On the practical stuff",
     "entries": [
         {"title": "yr.no — Norwegian Meteorological Institute", "url": "https://www.yr.no/",
          "author": "Norwegian Met Office",
          "annotation": "The most accurate weather forecast for the region — Norwegian state service, free, in English."},
         {"title": "Visit Norway editorial", "url": "https://www.visitnorway.com/",
          "author": "Innovation Norway",
          "annotation": "Better than most tourism boards; the 'Inspiration' section is genuinely current."},
         {"title": "Rome2Rio for regional routing", "url": "https://www.rome2rio.com/",
          "author": "Rome2Rio Pty Ltd",
          "annotation": "Best aggregator for ferry/train/bus options across Scandinavia — the planning step before you book direct."},
     ]},
]


# ============================================================================
# COMPOSE — emit each section  (helpers now imported from src.guide_emit)
# ============================================================================


def emit_day_by_day(hotels: List[Dict], venue_coords: Dict[str, Tuple[float, float]],
                    venue_relevance: Dict[str, Optional[float]],
                    gaps_by_date: Dict[date, HotelNightGap]) -> Tuple[str, str]:
    intro_body = ("Twenty-three days, six modes of transport, eleven hotels. The intros "
                  "set the day's frame; the cards run in time order and carry the practical "
                  "load. Walking-distance chips show distance from <i>tonight's hotel</i> "
                  "— transit days with no hotel skip the chip.")
    out = []
    body_for_rt = intro_body
    out.append(f'<p class="lede">{intro_body}</p>')
    for i, day in enumerate(DAY_BY_DAY, start=1):
        d = day["date"]
        hotel = resolve_hotel_for_night(hotels, d)
        date_label = d.strftime('%a %b %-d')
        out.append(f'<div class="daymark">')
        out.append(f'  <div class="daynum">Day {i:02d} · {esc(date_label)} · {esc(day["country"])}</div>')
        out.append(f'  <h3 class="dayname">{esc(day["city"])}</h3>')
        out.append(f'  <div class="daymeta">{day["meta"]}</div>')
        out.append(f'  <p class="dayintro">{esc(day["intro"])}</p>')
        body_for_rt += day["intro"]
        if day.get("intro_deep"):
            out.append(f'  <div class="deep"><p class="dayintro-deep">{esc(day["intro_deep"])}</p></div>')
            body_for_rt += day["intro_deep"]
        if d in gaps_by_date:
            gap = gaps_by_date[d]
            out.append(f'  <div class="data-check-note">{esc(gap.reason)}</div>')
            body_for_rt += " " + gap.reason
        for card in day["cards"]:
            time_label = esc(card["time"])
            cat = category_color(card["category"])
            # Venue name in h5 — wrap with practical_link if venue_key resolves
            name = card["name"]
            venue_key = card.get("venue_key")
            if venue_key:
                # Get the city for the practical link
                city = day["city"].split(",")[0] if "," in day["city"] else day["city"]
                if city in ("In flight", "Oslo (transit)", "Copenhagen → home"):
                    city = day["city"]
                link_html = emit_practical_link(venue_key, city, name)
            else:
                link_html = esc(name)
            out.append(f'    <div class="site-card">')
            out.append(f'      <div class="site-card-head">')
            out.append(f'        <span class="time-badge {cat}">{time_label}</span>')
            out.append(f'        <h5>{link_html}</h5>')
            out.append(f'      </div>')
            out.append(f'      <p>{esc(card["body"])}</p>')
            body_for_rt += card["body"]
            if card.get("notes"):
                out.append(f'      <div class="opnote">{esc(card["notes"])}</div>')
            # Tags row: travelpill if present, walkchip if applicable
            tag_parts = []
            if card.get("travelpill"):
                tag_parts.append(f'<span class="travelpill">{esc(card["travelpill"])}</span>')
            chip = emit_walking_chip(card.get("venue_key"), hotel, venue_coords, venue_relevance)
            if chip:
                tag_parts.append(chip)
            if tag_parts:
                out.append(f'      <div class="tags">{" ".join(tag_parts)}</div>')
            out.append(f'    </div>')
        out.append(f'</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="days", label="Day by day", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("day_by_day", [])),
        slug_label="timeline",
    )
    return ("days", "Day by day"), section_html


def emit_field_guide() -> Tuple[str, str]:
    fg = FIELD_GUIDE
    body_text = fg["intro_lede"]
    out = [f'<p class="lede">{esc(fg["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    out.append('<input type="search" id="fg-search" class="fg-search" placeholder="Search field guide…">')
    chip_parts = ['<button class="fg-chip active" data-region="all">All</button>']
    for region in fg["regions"]:
        chip_parts.append(
            f'<button class="fg-chip" data-region="{esc(region["slug"])}">{esc(region["label"])}</button>'
        )
    out.append(f'<div class="fg-chips">{"".join(chip_parts)}</div>')
    for region in fg["regions"]:
        out.append(f'<div class="fg-region-h">{esc(region["label"])}</div>')
        out.append('<div class="fg-grid">')
        for entry in region["entries"]:
            tags_str = " ".join(entry["tags"]) + " " + region["slug"]
            name = entry["name"]
            # Wrap landmark names in practical-link (skip for wildlife — no Maps target per spec)
            is_wildlife = "wildlife" in entry["tags"]
            if not is_wildlife:
                # Use the region's primary city as the Maps query qualifier
                city = (entry["tags"] and {"oslo": "Oslo", "longyearbyen-town": "Longyearbyen, Svalbard",
                                          "norway": "Norway", "bergen": "Bergen, Norway",
                                          "lofoten": "Lofoten, Norway", "transit": "Norway",
                                          "finland": "Finland", "helsinki": "Helsinki, Finland",
                                          "estonia": "Estonia", "tallinn": "Tallinn, Estonia",
                                          "sweden": "Sweden", "stockholm": "Stockholm, Sweden",
                                          "denmark": "Denmark", "copenhagen": "Copenhagen, Denmark"}.get(
                    entry["tags"][-1] if len(entry["tags"]) > 1 else "", "Scandinavia"))
                link = emit_practical_link(name, city, name)
            else:
                link = esc(name)
            out.append(f'  <article class="fg-card" data-tags="{esc(tags_str)}">')
            out.append(f'    <h5>{link}</h5>')
            if entry.get("latin"):
                out.append(f'    <div class="latin">{esc(entry["latin"])}</div>')
            out.append(f'    <div class="likely">{esc(entry["likelihood"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += entry["body"]
            out.append(f'    <div class="fg-tags">')
            for tag in entry["tags"]:
                out.append(f'      <span class="fg-tag">{esc(tag)}</span>')
            out.append(f'    </div>')
            out.append(f'  </article>')
        out.append('</div>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="field-guide", label="Field guide", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("field_guide", [])),
        slug_label="field guide",
    )
    return ("field-guide", "Field guide"), section_html


def emit_things_to_do(is_single_hotel: bool) -> Tuple[str, str]:
    """Emit things_to_do — chips SKIPPED entirely on multi-hotel trips per spec."""
    ttd = THINGS_TO_DO
    body_text = ttd["intro_lede"]
    out = [f'<p class="lede">{esc(ttd["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    # If multi-hotel, add an explanatory note
    if not is_single_hotel:
        out.append('<p style="font-size: 0.88em; color: var(--ink-soft); font-style: italic; margin-bottom: 24px;">'
                  'Walking-distance chips are omitted in this section — this is a multi-hotel trip and the '
                  'right anchor varies by which city you\'re in. Read the neighborhood and judge for yourself.</p>')
    for group in ttd["groups"]:
        out.append(f'<div class="ttd-group">')
        out.append(f'  <h4>{esc(group["label"])}</h4>')
        if group.get("opinion"):
            out.append(f'  <p class="opinion">{esc(group["opinion"])}</p>')
            body_text += group["opinion"]
        for entry in group["entries"]:
            city = entry["neighborhood"]
            venue_key = entry.get("venue_key")
            if venue_key:
                # Pull city from group label (e.g. "Oslo · half-day picks" → "Oslo")
                group_city = group["label"].split("·")[0].strip()
                link = emit_practical_link(venue_key, group_city, entry["name"])
            else:
                link = esc(entry["name"])
            out.append(f'  <div class="ttd-entry">')
            out.append(f'    <h5>{link}</h5>')
            out.append(f'    <div class="neighborhood">{esc(entry["neighborhood"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += entry["body"]
            # NO walkchip — multi-hotel trip
            out.append(f'  </div>')
        out.append(f'</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="things-to-do", label="Things to do", kind="atmospheric",
        body_html="".join(out),
        slug_label="off-itinerary",
    )
    return ("things-to-do", "Things to do"), section_html


def emit_weather() -> Tuple[str, str]:
    w = WEATHER
    body_text = w["intro_lede"] + w["season_notes"]
    out = [f'<p class="lede">{esc(w["intro_lede"])}</p>']
    out.append('<div class="weather-grid">')
    for stat in w["stat_grid"]:
        out.append(f'''  <div class="weather-stat">
    <div class="label">{esc(stat["label"])}</div>
    <div class="value">{esc(stat["value"])}</div>
    <div class="context">{esc(stat["context"])}</div>
  </div>''')
    out.append('</div>')
    out.append(f'<div class="deep">')
    out.append(f'  <p>{esc(w["season_notes"])}</p>')
    out.append(f'  <h4>Packing implications</h4>')
    out.append('  <ul>')
    for item in w["packing_implications"]:
        out.append(f'    <li>{esc(item)}</li>')
        body_text += item
    out.append('  </ul>')
    out.append('</div>')
    out.append('<p class="live-data">Weather data: yr.no (Norwegian Met Office), fetched 2026-06-27.</p>')
    section_html = emit_section_wrapper(
        slug="weather", label="Weather", kind="practical",
        body_html="".join(out),
        slug_label="climate",
    )
    return ("weather", "Weather"), section_html


def emit_history() -> Tuple[str, str]:
    h = HISTORY
    body_text = h["intro_lede"]
    out = [f'<p class="lede">{esc(h["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    for v in h["vignettes"]:
        out.append(f'  <article class="history-vignette era-{esc(v["era_slug"])}">')
        out.append(f'    <h4>{esc(v["title"])}</h4>')
        era_label = next((e["label"] for e in ERAS if e["slug"] == v["era_slug"]), "—")
        out.append(f'    <span class="era-chip">{esc(era_label)}</span>')
        out.append(f'    <p class="lede">{esc(v["lede"])}</p>')
        body_text += v["lede"]
        out.append(f'    <p>{esc(v["deep"])}</p>')
        body_text += v["deep"]
        out.append(f'    <div class="consequence">Today: {esc(v["consequence"])}</div>')
        body_text += v["consequence"]
        if "dig_deeper" in v:
            dd = v["dig_deeper"]
            out.append(f'    <aside class="dig-deeper">')
            out.append(f'      <h5>Dig deeper · {esc(dd["title"])}</h5>')
            out.append(f'      <p>{esc(dd["body"])}</p>')
            out.append(f'    </aside>')
            body_text += " " + dd["title"] + " " + dd["body"]
        out.append(f'  </article>')
    out.append(f'  <h4>Phrase table</h4>')
    out.append('  <table class="phrase-table">')
    for i, row in enumerate(h["phrase_table"]):
        cells = row["row"]
        if i == 0:
            out.append('    <tr>' + "".join(f'<th>{esc(c)}</th>' for c in cells) + '</tr>')
        else:
            out.append('    <tr>' + "".join(f'<td>{esc(c)}</td>' for c in cells) + '</tr>')
    out.append('  </table>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="history", label="History", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("history", [])),
        slug_label="history",
    )
    return ("history", "History"), section_html


def emit_fun_facts() -> Tuple[str, str]:
    ff = FUN_FACTS
    body_text = ff["intro_lede"]
    out = [f'<p class="lede">{esc(ff["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    out.append('<div class="facts-layout">')
    # Left column: trivia
    out.append('<div>')
    out.append('<h4>Trivia by country</h4>')
    for grp in ff["trivia_groups"]:
        out.append(f'  <div class="fact-group">')
        out.append(f'    <h4 class="fg-loc">{esc(grp["label"])}</h4>')
        out.append('    <ul>')
        for item in grp["items"]:
            out.append(f'      <li>{esc(item)}</li>')
            body_text += item
        out.append('    </ul>')
        out.append(f'  </div>')
    out.append('</div>')
    # Right column: tips
    out.append('<div>')
    out.append('<h4>Practical tips</h4>')
    for grp in ff["practical_tips_groups"]:
        out.append(f'  <div class="fact-group">')
        out.append(f'    <h4 class="fg-loc">{esc(grp["label"])}</h4>')
        out.append('    <ul>')
        for item in grp["items"]:
            out.append(f'      <li>{esc(item)}</li>')
            body_text += item
        out.append('    </ul>')
        out.append(f'  </div>')
    out.append('</div>')
    out.append('</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="fun-facts", label="Fun facts & tips", kind="atmospheric",
        body_html="".join(out),
        slug_label="trivia",
    )
    return ("fun-facts", "Fun facts & tips"), section_html


def emit_food() -> Tuple[str, str]:
    fd = FOOD
    body_text = fd["intro_lede"]
    out = [f'<p class="lede">{esc(fd["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    out.append(f'<h4>Things to try</h4>')
    out.append('<div class="food-grid">')
    for item in fd["things_to_try"]:
        out.append(f'  <div class="food-card">')
        out.append(f'    <h5>{esc(item["name"])}</h5>')
        if item.get("local"):
            out.append(f'    <div class="local">{esc(item["local"])}</div>')
        out.append(f'    <div class="region">{esc(item["region"])}</div>')
        out.append(f'    <p>{esc(item["body"])}</p>')
        body_text += item["body"]
        if item.get("tag"):
            out.append(f'    <span class="food-tag">{esc(item["tag"])}</span>')
        out.append(f'  </div>')
    out.append('</div>')
    if fd.get("opinion"):
        out.append(f'<p class="opinion">{esc(fd["opinion"])}</p>')
        body_text += fd["opinion"]
    out.append(f'<h4>Where to eat</h4>')
    for tier in fd["where_to_eat"]:
        out.append(f'<div class="tier-block">')
        out.append(f'  <h4>{esc(tier["label"])}</h4>')
        for entry in tier["entries"]:
            venue_key = entry.get("venue_key")
            if venue_key:
                link = emit_practical_link(venue_key, entry["city"], entry["name"])
            else:
                link = esc(entry["name"])
            out.append(f'  <div class="tier-entry">')
            out.append(f'    <h5>{link}</h5>')
            out.append(f'    <div class="city">{esc(entry["city"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += entry["body"]
            out.append(f'    <div class="tag-row">')
            if entry.get("tag"):
                out.append(f'      <span class="tag">{esc(entry["tag"])}</span>')
            if entry.get("booked"):
                out.append(f'      <span class="booked-tag">✓ you\'ve booked</span>')
            out.append(f'    </div>')
            out.append(f'  </div>')
        out.append(f'</div>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="food", label="Food", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("food", [])),
        slug_label="meals",
    )
    return ("food", "Food"), section_html


def emit_beer() -> Tuple[str, str]:
    """Themed bonus section — beer + breweries grouped by city."""
    b = BEER
    body_text = b["intro_lede"]
    out = [f'<p class="lede">{esc(b["intro_lede"])}</p>']
    out.append(f'<div class="deep">')
    if b.get("opinion"):
        out.append(f'<p class="opinion">{esc(b["opinion"])}</p>')
        body_text += b["opinion"]
    for grp in b["groups"]:
        out.append(f'<div class="ttd-group">')
        out.append(f'  <h4>{esc(grp["city"])}</h4>')
        if grp.get("intro"):
            out.append(f'  <p style="color: var(--ink-soft); font-size: 0.95em; margin: 0 0 14px 0;">{esc(grp["intro"])}</p>')
            body_text += grp["intro"]
        for v in grp["venues"]:
            venue_key = v.get("venue_key")
            city_name = grp["city"].split("·")[0].strip()
            if venue_key:
                link = emit_practical_link(venue_key, city_name, v["name"])
            else:
                link = esc(v["name"])
            out.append(f'  <div class="ttd-entry">')
            out.append(f'    <h5>{link}</h5>')
            out.append(f'    <div class="neighborhood">{esc(v["style"])}</div>')
            out.append(f'    <p>{esc(v["body"])}</p>')
            body_text += v["body"]
            out.append(f'  </div>')
        out.append(f'</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="beer", label="Beer & breweries", kind="atmospheric",
        body_html="".join(out),
        slug_label="breweries",
    )
    return ("beer", "Beer & breweries"), section_html


def emit_sources() -> Tuple[str, str]:
    body_text = "Sources and further reading"
    out = [f'<p class="lede">Books, podcasts, films, and people whose work informed this guide. Every entry links to its canonical source.</p>']
    for grp in BIBLIOGRAPHY:
        out.append(f'<div class="biblio-group">')
        out.append(f'  <h4>{esc(grp["group"])}</h4>')
        out.append('  <ul>')
        for e in grp["entries"]:
            link = f'<a class="practical-link" href="{esc(e["url"])}" rel="noopener" target="_blank"><b>{esc(e["title"])}</b></a>'
            ay = f'<span class="ay">— {esc(e.get("author", ""))}'
            if e.get("year"):
                ay += f' <i>({esc(e["year"])})</i>'
            ay += '.</span>'
            out.append(f'    <li>{link}{ay} {esc(e["annotation"])}</li>')
            body_text += e["annotation"]
        out.append('  </ul>')
        out.append(f'</div>')
    section_html = emit_section_wrapper(
        slug="sources", label="Sources & further reading", kind="practical",
        body_html="".join(out),
        slug_label="sources",
    )
    return ("sources", "Sources & further reading"), section_html


# ============================================================================
# MAIN COMPOSE
# ============================================================================

def compose(venue_coords: Dict[str, Tuple[float, float]],
            venue_relevance: Dict[str, Optional[float]],
            hotels: List[Dict],
            gaps_by_date: Dict[date, HotelNightGap]) -> str:
    is_single_hotel = len(set((h["lat"], h["lng"]) for h in hotels)) == 1
    sections = [
        emit_day_by_day(hotels, venue_coords, venue_relevance, gaps_by_date),
        emit_field_guide(),
        emit_things_to_do(is_single_hotel),
        emit_weather(),
        emit_history(),
        emit_food(),
        emit_beer(),
        emit_fun_facts(),
        emit_sources(),
    ]
    toc_slugs = [(slug, label) for (slug, label), _html in sections]
    sections_html = "".join(html for _s, html in sections)

    body = f"""
<a class="skip-link" href="#main">Skip to content</a>
<div id="vp-progress"></div>

<div class="topbar">
  <div class="crumb">Trip guide<span class="crumb-rest"> · <b>{esc(TRIP_META['title'])}</b> · Oslo → Copenhagen</span></div>
  <div class="spacer"></div>
  <div class="mode-toggle" role="radiogroup" aria-label="Reading depth">
    <button data-mode="skim" aria-pressed="false">Skim</button>
    <button data-mode="standard" aria-pressed="true">Standard</button>
    <button data-mode="deep" aria-pressed="false">Deep</button>
  </div>
  <button id="print-btn" class="print-btn">Save as PDF</button>
</div>

{emit_hero(TRIP_META, PALETTE["name"])}

<div class="toc-wrap">
  {emit_toc(toc_slugs)}
  <main id="main">
{sections_html}
  </main>
</div>

<footer class="guide-footer">
  Trip {TRIP_ID} · generated {GEN_DATE_STR} · palette <span class="palette-name">{esc(PALETTE['name'])}</span>
</footer>
"""

    css = emit_css(PALETTE, ERAS)
    js = emit_js()

    fonts_url = (f"https://fonts.googleapis.com/css2?"
                 f"family=Fraunces:opsz,wght@9..144,400;9..144,600&"
                 f"family=Inter:wght@400;500;600&"
                 f"family=JetBrains+Mono:wght@400;500&display=swap")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(TRIP_META['title'])} · {esc(', '.join(TRIP_META['countries']))} · Aug 14 → Sep 5 2026</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="{fonts_url}" rel="stylesheet">
  <style>{css}</style>
</head>
<body data-mode="standard">
{body}
<script>
{js}
</script>
</body>
</html>
"""
    return html


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("Trip 2 Scandinavia '26 — Deep tier compose")
    print("=" * 70)
    print("\n[1/4] Geocoding venues...")
    venue_coords, venue_relevance = geocode_all_venues()
    print(f"  Got coords for {len(venue_coords)} of {len(NAMED_VENUES)} venues")
    low_conf = sum(1 for r in venue_relevance.values() if r is not None and r < 0.7)
    print(f"  Low-confidence venues (relevance < 0.7): {low_conf}")

    print("\n[2/4] Loading hotels + scanning for data gaps...")
    hotels = load_hotels()
    print(f"  {len(hotels)} hotels loaded, all geocoded: {all(h['lat'] for h in hotels)}")
    is_single_hotel = len(set((h["lat"], h["lng"]) for h in hotels)) == 1
    print(f"  Single-hotel trip: {is_single_hotel}")
    with app.app_context():
        all_bookings = Booking.query.filter_by(trip_id=TRIP_ID).all()
        itinerary = ItineraryItem.query.filter_by(trip_id=TRIP_ID).all()
        gaps = find_hotel_night_gaps(all_bookings, itinerary,
                                     TRIP_META["start_date"], TRIP_META["end_date"])
    gaps_by_date = {g.day_date: g for g in gaps}
    print(f"  Data-check gaps detected: {len(gaps)}")
    for g in gaps:
        print(f"    - Day {g.day_number} ({g.day_date}): {g.reason}")

    print("\n[3/4] Composing HTML...")
    with app.app_context():
        html = compose(venue_coords, venue_relevance, hotels, gaps_by_date)
    print(f"  HTML composed: {len(html):,} chars")

    print("\n[4/4] Saving via save_guide...")
    with app.app_context():
        path = guide_builder.save_guide(TRIP_ID, html)
    print(f"  Saved: {path}")

    # Quick markup audit
    print("\n--- Markup audit ---")
    pl_count = html.count('class="practical-link"')
    wc_count = html.count('class="walkchip"')
    print(f"  practical-link instances: {pl_count}")
    print(f"  walkchip instances:       {wc_count}")
    dc_count = html.count('date-chip')
    gd_count = html.count('go-deeper')
    era_count = html.count('era-chip')
    dcn_count = html.count('data-check-note')
    print(f"  date-chip instances:      {dc_count}")
    print(f"  go-deeper card sections:  {gd_count}")
    print(f"  data-check-note callouts: {dcn_count}")
    print(f"  era-chip instances:       {era_count}")

    # Share URL
    share_token = "1f1ad0d2-0c8a-4dfd-83cf-bfd5e8a7e7e0"  # known existing
    with app.app_context():
        from models import Trip
        trip = db.session.get(Trip, TRIP_ID)
        token = trip.guide_share_token if trip else None
    if token:
        print(f"\n  Gated URL:  http://localhost:5002/trips/{TRIP_ID}/guide")
        print(f"  Share URL:  http://localhost:5002/guides/share/{token}")


if __name__ == "__main__":
    main()

