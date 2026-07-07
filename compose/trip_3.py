"""
Compose Trip 3 (Galápagos SB '27) Souvenir-grade trip guide.

Source of truth for content:
  - ~/Downloads/Galapagos_Cruise_Log_Mar27-Apr3_2027_1.md
  - ~/Downloads/Galapagos_Field_Log_Mar27-Apr3_2027_2.html

Extra sections (field guide, history, things to do, food, photography, fun
facts) are written from general Galápagos + Ecuador knowledge — not from
external research.

Author: Claude Code session 2026-07-07
"""

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("compose_trip3")

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
from src.geocoding import geocode_with_cache
from src.guide_emit import (
    esc, emit_h2, emit_practical_link, category_color,
    emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper,
    emit_section_wrapper,
)

TRIP_ID = 3
MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()
GEN_DATE_STR = "2026-07-07"

# ============================================================================
# PALETTE + ERAS
# ============================================================================
# Palette identity: teal-deep + gold, echoing the source field-log's expedition
# aesthetic, adapted to the dark-mode surface that the shared emit_css scaffold
# assumes (topbar backdrop is hard-coded rgba on the dark bg).

PALETTE = {
    "name": "Encantadas expedition",
    "colors": {
        "bg":          "#0e1e20",
        "surface":     "#153538",
        "ink":         "#eaf2f0",
        "ink_soft":    "#a8c4c1",
        "ink_display": "#ffffff",
        "accent":      "#c6952f",
        "accent_2":    "#e7c87f",
        "muted":       "#6b8280",
        "hairline":    "#1c3f43",
        "warning":     "#d97757",
    },
    "fonts": {
        "display": "Bricolage Grotesque",
        "body":    "Spectral",
        "mono":    "Space Mono",
    },
}

# Wildlife archetype: no era palette (per trip-guide skill's "When to skip" rule).
ERAS: List[Dict[str, str]] = []

# ============================================================================
# NAMED VENUES (for practical-link geocoding)
# ============================================================================

NAMED_VENUES = [
    # Cruise stops — mostly wilderness, but the ports get Maps queries
    ("Puerto Baquerizo Moreno", "San Cristóbal, Galápagos, Ecuador"),
    ("Kicker Rock", "San Cristóbal, Galápagos, Ecuador"),
    ("Interpretation Center", "Puerto Baquerizo Moreno, Galápagos, Ecuador"),
    ("Cerro Tijeretas", "San Cristóbal, Galápagos, Ecuador"),
    ("Puerto Ayora", "Santa Cruz, Galápagos, Ecuador"),
    ("Charles Darwin Research Station", "Puerto Ayora, Galápagos, Ecuador"),
    # Pre/post-cruise picks — Guayaquil
    ("Parque Histórico Guayaquil", "Guayaquil, Ecuador"),
    ("Malecón 2000", "Guayaquil, Ecuador"),
    ("Las Peñas", "Guayaquil, Ecuador"),
    ("Cerro Santa Ana", "Guayaquil, Ecuador"),
    ("Iguanas Park (Parque Seminario)", "Guayaquil, Ecuador"),
    # Pre/post-cruise picks — Quito
    ("Quito Old Town", "Quito, Ecuador"),
    ("La Compañía de Jesús", "Quito, Ecuador"),
    ("Basílica del Voto Nacional", "Quito, Ecuador"),
    ("TelefériQo", "Quito, Ecuador"),
    ("Mitad del Mundo", "Quito, Ecuador"),
    # Where to eat — Guayaquil / Quito
    ("Riviera Ristorante", "Guayaquil, Ecuador"),
    ("Sambo Casa del Cangrejo", "Guayaquil, Ecuador"),
    ("Lo Nuestro", "Guayaquil, Ecuador"),
    ("Cyrano bakery", "Guayaquil, Ecuador"),
    ("Zazu", "Quito, Ecuador"),
    ("Casa Gangotena", "Quito, Ecuador"),
    ("La Ronda", "Quito, Ecuador"),
    ("Vista Hermosa", "Quito, Ecuador"),
    # Where to eat — Puerto Ayora / Baquerizo
    ("Isla Grill", "Puerto Ayora, Galápagos, Ecuador"),
    ("Almar", "Puerto Ayora, Galápagos, Ecuador"),
    ("Muyu Bistro", "Puerto Baquerizo Moreno, Galápagos, Ecuador"),
    ("Calle de los Kioskos", "Puerto Ayora, Galápagos, Ecuador"),
]


def geocode_all_venues() -> Tuple[Dict[str, Tuple[float, float]], Dict[str, Optional[float]]]:
    coords: Dict[str, Tuple[float, float]] = {}
    relevance: Dict[str, Optional[float]] = {}
    if not MAPBOX_TOKEN:
        return coords, relevance
    with app.app_context():
        for name, city in NAMED_VENUES:
            key = name.lower()
            result = geocode_with_cache(
                text=f"{name}, {city}",
                db_session=db.session,
                token=MAPBOX_TOKEN,
            )
            if result is not None:
                coords[key] = (result.lat, result.lng)
                relevance[key] = result.relevance
        db.session.commit()
    return coords, relevance


# ============================================================================
# TRIP META + ROUTE SVG
# ============================================================================
# Route arc: mainland Ecuador → San Cristóbal → Genovesa (north spike) →
# Santiago/N.Seymour → Isabela+Fernandina (west spike) → Santa Cruz →
# Española (south) → back to San Cristóbal.

ROUTE_SVG = """
<svg class="route-svg" viewBox="0 0 600 140" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Route: mainland Ecuador to San Cristóbal, then loop north to Genovesa, west to Isabela/Fernandina, south to Española, back to San Cristóbal">
  <line x1="30" y1="80" x2="140" y2="80" stroke="var(--accent-2)" stroke-width="1" stroke-dasharray="3,3"/>
  <line x1="140" y1="80" x2="220" y2="30" stroke="var(--accent)" stroke-width="1"/>
  <line x1="220" y1="30" x2="300" y2="70" stroke="var(--accent)" stroke-width="1"/>
  <line x1="300" y1="70" x2="360" y2="90" stroke="var(--accent)" stroke-width="1"/>
  <line x1="360" y1="90" x2="420" y2="80" stroke="var(--accent)" stroke-width="1"/>
  <line x1="420" y1="80" x2="480" y2="115" stroke="var(--accent)" stroke-width="1"/>
  <line x1="480" y1="115" x2="540" y2="80" stroke="var(--accent)" stroke-width="1"/>
  <line x1="540" y1="80" x2="570" y2="80" stroke="var(--accent-2)" stroke-width="1" stroke-dasharray="3,3"/>
  <circle cx="30" cy="80" r="5" fill="var(--accent-2)"/>
  <circle cx="140" cy="80" r="6" fill="var(--accent)" stroke="var(--ink-display)" stroke-width="1"/>
  <circle cx="220" cy="30" r="4" fill="var(--accent)"/>
  <circle cx="300" cy="70" r="4" fill="var(--accent)"/>
  <circle cx="360" cy="90" r="7" fill="var(--accent-2)" stroke="var(--accent)" stroke-width="2"/>
  <circle cx="420" cy="80" r="4" fill="var(--accent)"/>
  <circle cx="480" cy="115" r="4" fill="var(--accent)"/>
  <circle cx="540" cy="80" r="6" fill="var(--accent)" stroke="var(--ink-display)" stroke-width="1"/>
  <circle cx="570" cy="80" r="5" fill="var(--accent-2)"/>
  <text x="30" y="102" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Guayaquil</text>
  <text x="140" y="102" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">S.Cristóbal</text>
  <text x="220" y="22" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Genovesa</text>
  <text x="300" y="62" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Santiago</text>
  <text x="360" y="108" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Isabela/Fernandina</text>
  <text x="420" y="72" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">S.Cruz</text>
  <text x="480" y="132" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">Española</text>
  <text x="540" y="102" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">S.Cristóbal</text>
  <text x="570" y="102" fill="var(--ink-soft)" font-family="var(--font-mono)" font-size="9" text-anchor="middle">home</text>
</svg>
"""

SOURCES_NOTE = (
    "This guide is built from the field log the traveller assembled with Claude "
    "in April 2026, cross-checked against Galápagos National Park site rotations "
    "and long-standing naturalist literature (David Steadman on birds; John Kricher "
    "on the archipelago's ecology; Henry Nicholls on the giant tortoises). The "
    "cruise route follows a standard San Cristóbal round-trip; specific stop "
    "assignments rotate every fortnight — <b>the cruise director's nightly briefing "
    "is the authority</b>. Live figures for weather and species timing are seasonal "
    "reference points, not real-time data."
)

TRIP_META = {
    "title": "Galápagos SB '27",
    "subtitle": ("Eight days at sea, four biogeographic corners of the archipelago: "
                 "bird-dense Genovesa in the north, the cold-water Bolívar Channel "
                 "in the west, Santa Cruz's tortoise highlands, and Española's "
                 "waved albatross in the south — a round-trip from San Cristóbal, "
                 "where Darwin first came ashore in 1835."),
    "narrator_dek": "For the first-time Galápagos naturalist — read the wildlife, geology, and Darwin at once.",
    "start_date": date(2027, 3, 25),
    "end_date": date(2027, 4, 4),
    "countries": ["Ecuador"],
    "nights": 10,
    "countries_count": 1,
    "bookings_count": 1,
    "route_svg": ROUTE_SVG,
    "sources_note": SOURCES_NOTE,
}

# ============================================================================
# CAPTAIN'S NOTES — the three honest flags from the source HTML
# ============================================================================

CAPTAINS_NOTES = [
    {
        "kind": "warn",
        "label": "Timing",
        "body": ("Your Española day (April 1) sits at the very front edge of "
                 "waved-albatross season. The colony arrives late March into April. "
                 "You'll likely see some — soaring on the cliff updrafts, earliest "
                 "arrivals settling in — but not the full clattering courtship "
                 "spectacle, which peaks late April into May. If the albatross was "
                 "a top reason for these dates, you're a few weeks early for the peak."),
    },
    {
        "kind": "info",
        "label": "Weather",
        "body": ("Late March is the rainiest month of the year in the Galápagos — "
                 "and that's a feature here. It's also the warmest water (~77°F / "
                 "25°C), the clearest visibility, and the calmest seas of the year, "
                 "with lush green highlands. Expect short afternoon showers that "
                 "clear fast. Snorkeling conditions are at their annual best."),
    },
    {
        "kind": "info",
        "label": "Route",
        "body": ("A genuine best-of loop with no weak days. Day 4 in the Bolívar "
                 "Channel is the rare-endemics highlight — flightless cormorant, "
                 "equatorial penguins, the most productive water in the archipelago. "
                 "If albatross timing disappoints, reframe Day 4 as your headline day."),
    },
]

# 4-stat weather grid pulled from the source HTML's Season strip.
SEASON_STRIP = [
    {"label": "Water",   "value": "~77°F / 25°C",   "context": "warmest, clearest of year"},
    {"label": "Seas",    "value": "Calmest",        "context": "good for far crossings"},
    {"label": "Sky",     "value": "Brief showers",  "context": "then sun; green highlands"},
    {"label": "Wetsuit", "value": "Optional",       "context": "2–3mm shorty for comfort"},
]

# ============================================================================
# DAY-BY-DAY — sourced verbatim in spirit from the field log
# ============================================================================
# Card shape:
#   {"time": "HH:MM", "name": str, "venue_key": Optional[str],
#    "body": str, "category": str, "notes": Optional[str],
#    "travelpill": Optional[str]}
# Day shape:
#   {"date": date, "city": str, "meta": str, "intro": str, "intro_deep": str,
#    "cards": [...]}

DAY_BY_DAY: List[Dict[str, Any]] = [
    # ── Buffer: Thu Mar 25 · Fly to Ecuador ─────────────────────────────────
    {
        "date": date(2027, 3, 25), "city": "MSP → Ecuador",
        "meta": "<b>~9h flight</b> · en route · gateway either Quito (UIO) or Guayaquil (GYE)",
        "intro": ("The trip starts in the buffer day, not the cruise. Quito sits at "
                  "2,850m — a bad city to land into and immediately embark from; "
                  "Guayaquil at sea level is friendlier to a same-day continuation "
                  "but you skip the Old Town. Most Silversea itineraries stage in "
                  "Guayaquil the night before the LATAM flight to Baltra or San "
                  "Cristóbal — check your operator's pre-cruise instructions."),
        "intro_deep": ("The Galápagos are two hours ahead of Ecuador mainland time "
                       "in the Southern-Hemisphere winter (GMT-6 mainland, GMT-6 "
                       "islands — same on your dates in March). Bring the usual "
                       "Latin-America items: proof of yellow-fever vaccine isn't "
                       "required for Galápagos-only entry from a low-risk country, "
                       "but airlines occasionally ask; keep the card with your passport."),
        "cards": [
            {"time": "TBD", "name": "Fly MSP → Ecuador (placeholder)", "category": "transit",
             "body": "Flight details not yet booked in the app — add via the Bookings tab. "
                     "Common routings: MSP → ATL → UIO/GYE (Delta), or via Miami on American.",
             "travelpill": "Flight · overnight"},
        ],
    },
    # ── Buffer: Fri Mar 26 · Overnight in Ecuador ──────────────────────────
    {
        "date": date(2027, 3, 26), "city": "Guayaquil or Quito",
        "meta": "<b>28° / 22°C GYE · 20° / 10°C UIO</b> · pre-cruise night",
        "intro": ("A day to reset your body clock and stage for the LATAM hop to "
                  "the islands tomorrow. Silversea usually books this hotel for you "
                  "and includes a mainland tour; independent travellers should book "
                  "same-day check-in near the airport. Sleep, hydrate, and pack the "
                  "cruise duffel — you'll live out of it for eight days."),
        "intro_deep": ("Guayaquil is Ecuador's biggest city, muggy and tropical; "
                       "Quito is colonial and thin-air at 2,850m. If you have the "
                       "day free, walk the Malecón 2000 in Guayaquil (an 2.5km "
                       "riverfront reclamation project from 1999–2002) or the "
                       "Quito Old Town's Calle Ronda after dark — both are covered "
                       "in the Things to Do section."),
        "cards": [
            {"time": "TBD", "name": "Overnight (placeholder)", "category": "other",
             "body": "Hotel details not yet in the app. Silversea's package usually "
                     "includes a Hotel Oro Verde night in Guayaquil or the Wyndham "
                     "at the airport. Confirm which with your travel documents.",
             "notes": "Bring a bag of snacks: LATAM's Galápagos flight is a snack-only 2h hop."},
        ],
    },
    # ── DAY 1 · Sat Mar 27 · San Cristóbal + Kicker Rock ────────────────────
    {
        "date": date(2027, 3, 27), "city": "San Cristóbal (embark)",
        "meta": "<b>28° / 22°C</b> · water 25°C · embarkation day",
        "intro": ("The trip's real day one begins at Puerto Baquerizo Moreno on "
                  "San Cristóbal — the easternmost and geologically oldest of the "
                  "main islands, and the capital of the Galápagos province. It is "
                  "also where Charles Darwin first came ashore on September 17, "
                  "1835, aboard HMS Beagle. Every sea lion sprawled across every "
                  "bench in town is a descendant of populations he watched."),
        "intro_deep": ("San Cristóbal is roughly 2.4 million years old — young by "
                       "the standards of continents, ancient by the standards of "
                       "oceanic islands. It is one of the very few Galápagos islands "
                       "with permanent fresh water (El Junco crater lake in the "
                       "highlands, worth a mention if you have time before boarding). "
                       "Embarkation is usually mid-afternoon; the ship pushes off "
                       "toward Kicker Rock at golden hour on its way north."),
        "cards": [
            {"time": "12:00", "name": "Embark · Puerto Baquerizo Moreno",
             "venue_key": "Puerto Baquerizo Moreno", "category": "transit",
             "body": "The town is one long malecón along the harbour, sea lions on "
                     "every step, frigatebirds wheeling overhead. Take a slow walk "
                     "before boarding — you won't be back in a town for a week.",
             "notes": "You'll board Silversea by tender or panga; keep your passport in your hand luggage."},
            {"time": "17:00", "name": "Kicker Rock (León Dormido) cruise-by",
             "venue_key": "Kicker Rock", "category": "sightseeing",
             "body": "Two sheer vertical rock towers rising ~490 ft (150m) straight "
                     "out of the ocean, split by a narrow channel — the eroded "
                     "remnant of a vertical tuff cone. No landing; the ship threads "
                     "the channel at sunset. Two names, one profile: Spanish León "
                     "Dormido (\"sleeping lion\") for the silhouette; English "
                     "\"Kicker Rock\" for the boot shape.",
             "notes": "If your operator offers a channel snorkel this evening or on the return leg, take it — the channel is a shark corridor (Galápagos sharks, white-tips, seasonal hammerheads) with rays and turtles. Late-March water clarity is at its annual best.",
             "travelpill": "Panga cruise · 90 min"},
        ],
    },
    # ── DAY 2 · Sun Mar 28 · Genovesa (Bird Island) ────────────────────────
    {
        "date": date(2027, 3, 28), "city": "Genovesa · Bird Island",
        "meta": "<b>27° / 22°C</b> · water 25°C · far north crossing",
        "intro": ("Genovesa sits by itself in the northern archipelago, well off "
                  "the standard tourist circuit. The overnight sail is why it stays "
                  "so pristine — and so bird-dense. The whole island is a collapsed "
                  "caldera whose southern rim fell into the sea; you literally sail "
                  "into the flooded crater to reach the landings. Nothing here "
                  "learned to fear anything, and it shows."),
        "intro_deep": ("Genovesa never had land reptiles worth speaking of and "
                       "never had large mammalian predators. The birds nest at eye "
                       "level and on the ground because there was never a reason "
                       "not to. This is \"Bird Island\" for a reason — the standard "
                       "guide checklist for a morning here runs to seven or eight "
                       "seabird species most naturalists count as lifers."),
        "cards": [
            {"time": "08:00", "name": "Prince Philip's Steps",
             "category": "sightseeing",
             "body": "A steep natural rock stairway (~25m) climbing the cliff on "
                     "the NE side of Darwin Bay, named for Prince Philip, Duke of "
                     "Edinburgh, who visited Genovesa in 1965 and again in 1981. "
                     "The clifftop plateau is a seabird metropolis: Nazca boobies, "
                     "red-footed boobies (Genovesa hosts one of the world's largest "
                     "colonies), great frigatebirds, and hundreds of thousands of "
                     "storm petrels swirling overhead.",
             "notes": "Watch the palo santo forest for the Galápagos short-eared owl hunting storm petrels by day — one of the only places on Earth you can reliably see this behaviour."},
            {"time": "12:00", "name": "Darwin Bay beach",
             "category": "sightseeing",
             "body": "The coral-sand beach inside the caldera itself. Red-footed "
                     "boobies nest in the mangroves (the only booby that nests in "
                     "trees, with prehensile feet to grip branches). Great "
                     "frigatebirds display crimson throat pouches, fully inflated "
                     "— courtship peaks December through May, so you are in the "
                     "sweet spot. Swallow-tailed gulls stalk the shoreline: the "
                     "world's only nocturnal gull, with the huge night-adapted eyes to match.",
             "notes": "Snorkel from the wet landing here — sea lions, sea turtles, hammerheads occasionally cruise the drop-off."},
        ],
    },
    # ── DAY 3 · Mon Mar 29 · North Seymour + Santiago ───────────────────────
    {
        "date": date(2027, 3, 29), "city": "North Seymour + Santiago",
        "meta": "<b>28° / 23°C</b> · water 25°C · uplifted seabed + young lava",
        "intro": ("Two geological opposites in one day. North Seymour is dead flat "
                  "— not a volcano at all, but uplifted ancient seabed thrust above "
                  "the waterline by tectonics. Sullivan Bay on Santiago is the "
                  "opposite: black glassy pahoehoe lava from an 1897 eruption, one "
                  "of the youngest walkable lava fields on Earth. Between them, "
                  "you've read the archipelago's two dominant creation stories."),
        "intro_deep": ("North Seymour is a top-three photography stop — the largest "
                       "frigatebird nesting colony on the route (males with balloon-"
                       "red pouches on display) plus prime blue-footed booby "
                       "courtship dances, the comic high-stepping and sky-pointing "
                       "at their peak in late March. Sullivan Bay pairs a lava walk "
                       "with a snorkel across the channel to Bartolomé's Pinnacle Rock."),
        "cards": [
            {"time": "08:00", "name": "North Seymour",
             "category": "sightseeing",
             "body": "A small, flat island just north of Baltra. Land iguanas roam "
                     "the trail — and here's an odd story: they aren't original to "
                     "the island. A 1930s scientific expedition relocated iguanas "
                     "from nearby Baltra to North Seymour. Decades later, when "
                     "Baltra's own population was wiped out (partly by WWII military "
                     "activity at the airfield), the North Seymour transplants were "
                     "used to repopulate Baltra. A 1930s hunch saved a population.",
             "notes": "Peak blue-footed booby courtship dance is active now. Watch for the sky-pointing display — heads back, wings up, whistling. The male in question is not embarrassed."},
            {"time": "12:00", "name": "Sullivan Bay lava walk + Bartolomé snorkel",
             "category": "sightseeing",
             "body": "A jet-black pahoehoe lava flow — ropey, swirled, glassy — "
                     "from an eruption around 1897, making it one of the youngest "
                     "and most pristine lava fields you can walk on. Look for "
                     "hornitos (small spatter cones), collapsed lava bubbles, and "
                     "pioneer life pushing through cracks: the endemic lava cactus "
                     "(Brachycereus) and the succulent Mollugo. The snorkel across "
                     "the channel toward Bartolomé's Pinnacle Rock can turn up "
                     "Galápagos penguins — the only penguin found north of the equator.",
             "notes": "Darwin spent time on Santiago in 1835. Pirates and whalers later devastated it; introduced goats and pigs took over a century to eradicate — complete removal was finally declared around 2006."},
        ],
    },
    # ── DAY 4 · Tue Mar 30 · Western islands (Isabela + Fernandina) ─────────
    {
        "date": date(2027, 3, 30), "city": "The West · Isabela + Fernandina",
        "meta": "<b>26° / 21°C</b> · water 23°C · Cromwell upwelling",
        "intro": ("The western islands sit over the Cromwell Current upwelling — "
                  "cold, nutrient-rich water rising from the deep Pacific, dragged "
                  "up against Isabela's western wall. It is the single most "
                  "biologically productive corner of the archipelago and the reason "
                  "you can see penguins on the equator at all. If the albatross "
                  "day disappoints on timing, this is the day to reframe as the "
                  "headline. The rarest endemics live here."),
        "intro_deep": ("Fernandina, west of Isabela, is the youngest and most "
                       "volcanically active island — and, remarkably, the most "
                       "pristine island ecosystem on Earth's oceanic islands. It "
                       "has never been colonised by an introduced species. No "
                       "rats, no goats, nothing alien. La Cumbre, its main volcano, "
                       "erupts every few years. In 2019 a giant tortoise thought "
                       "extinct — Fernanda — was rediscovered here. She remains "
                       "the only known living member of her species."),
        "cards": [
            {"time": "08:00", "name": "Bolívar Channel cruising",
             "category": "sightseeing",
             "body": "The strait between Isabela and Fernandina is the best place "
                     "in Galápagos for marine mammals. Scan the water constantly: "
                     "Bryde's whales, common and bottlenose dolphins, plus the "
                     "richest concentrations of Galápagos penguins and flightless "
                     "cormorants anywhere. Manta rays and mola mola (ocean sunfish) "
                     "are seasonally possible.",
             "notes": "Bridge and forward decks are the best vantage. Bring binoculars — the whales are often 100–400m off.",
             "travelpill": "Channel cruise · morning"},
            {"time": "12:00", "name": "Punta Mangle, Fernandina",
             "category": "sightseeing",
             "body": "Mangrove-lined coves on Fernandina — where marine iguanas "
                     "are nesting in March. Panga rides and snorkel among the "
                     "mangroves for the marquee species: Galápagos penguins and "
                     "flightless cormorants, the only cormorant in the world that "
                     "lost the ability to fly. Nearly the entire global population "
                     "of ~1,000 flightless cormorants lives here and on western Isabela.",
             "notes": "Marine iguanas here are the dark, larger \"Fernandina race\" — less colourful than Española's but more massive."},
            {"time": "15:00", "name": "Punta Moreno, Isabela",
             "category": "sightseeing",
             "body": "A huge pahoehoe lava field on western Isabela, pocked with "
                     "brackish lagoons that draw greater flamingos, white-cheeked "
                     "pintails, and common gallinules. From the lava you get a "
                     "panorama of three volcanoes: Sierra Negra and Cerro Azul on "
                     "Isabela, plus Fernandina's La Cumbre across the channel. "
                     "Isabela itself is built from six separate volcanoes that "
                     "merged — the largest island in the archipelago, shaped like "
                     "a seahorse.",
             "notes": "Snorkeling here: penguins, sea turtles, rays."},
        ],
    },
    # ── DAY 5 · Wed Mar 31 · Santa Cruz ─────────────────────────────────────
    {
        "date": date(2027, 3, 31), "city": "Santa Cruz · the conservation hub",
        "meta": "<b>27° / 20°C</b> · water 24°C · highlands lush now",
        "intro": ("Santa Cruz is the most populated island in the Galápagos and "
                  "the conservation hub for the whole archipelago. It's also the "
                  "one day of the trip you spend inland — the green, misty highland "
                  "interior at its lushest now in the wet season. You'll see wild "
                  "giant tortoises grazing in pools, and later, back down at sea "
                  "level, you'll see the taxidermied body of Lonesome George at "
                  "the Charles Darwin Research Station."),
        "intro_deep": ("The Fausto Llerena Breeding Center in Puerto Ayora is the "
                       "site of both the biggest single conservation failure and "
                       "the biggest single conservation win in the modern Galápagos "
                       "story. George, the last Pinta tortoise, died in 2012 despite "
                       "40 years of attempts to breed him. Diego, a male Española "
                       "tortoise repatriated from the San Diego Zoo, fathered a "
                       "huge share of the rebuilt Española population over the same "
                       "period, and in 2020 was returned to Española himself. "
                       "George is the warning. Diego is the win."),
        "cards": [
            {"time": "08:00", "name": "Santa Cruz Highlands (El Chato / lava tubes / Los Gemelos)",
             "category": "sightseeing",
             "body": "The morning excursion covers three highland stops. Free-"
                     "roaming giant tortoises at El Chato / Rancho Primicias, "
                     "wallowing in shallow pools — completely different from seeing "
                     "them in a pen. Walkable underground lava tubes, formed when "
                     "a flow's surface cooled while molten lava drained beneath. "
                     "And Los Gemelos, \"the twins\" — two large pit craters "
                     "(technically sinkholes: collapsed magma chambers, not "
                     "eruptive craters) ringed by Scalesia forest, where vermilion "
                     "flycatchers and short-eared owls hunt.",
             "notes": "Bring long pants and closed-toe shoes for the tortoise ranch — mud and mosquitoes in the wet season."},
            {"time": "12:00", "name": "Fausto Llerena Breeding Center",
             "venue_key": "Charles Darwin Research Station", "category": "sightseeing",
             "body": "The giant-tortoise and land-iguana breeding and rearing "
                     "program at the Charles Darwin Research Station in Puerto "
                     "Ayora. Pens hold baby and juvenile tortoises being raised "
                     "for about five years before being repatriated to their home "
                     "islands. Lonesome George's body is displayed in a "
                     "climate-controlled exhibit — the global symbol of extinction "
                     "since he died on June 24, 2012.",
             "notes": "Puerto Ayora's Calle de los Kioskos comes alive in the evening — worth a wander if you have any free time before the ship departs."},
        ],
    },
    # ── DAY 6 · Thu Apr 1 · Española ────────────────────────────────────────
    {
        "date": date(2027, 4, 1), "city": "Española · Hood Island",
        "meta": "<b>27° / 22°C</b> · water 24°C · headline day",
        "intro": ("Española is the oldest of the main islands (~3.5 million years) "
                  "and the most isolated. That combination produced the highest "
                  "rate of unique endemic species in the archipelago. This is why "
                  "it is saved for near the end of the loop. Christmas iguanas, "
                  "waved albatross, and the endemic Española mockingbird will walk "
                  "right up to your boots — the birds here have not learned to be "
                  "cautious."),
        "intro_deep": ("The waved albatross is the largest bird in the Galápagos "
                       "with an eight-foot wingspan, mates for life, and does its "
                       "famous cliff-edge takeoffs and crash-landings at Punta "
                       "Suárez. April 1 sits at the very front edge of their "
                       "arrival window — expect a taste, not the full spectacle. "
                       "The birds are just arriving; the full clattering courtship "
                       "dance peaks late April into May, with eggs laid mid-April "
                       "onward. Manage expectations. If you were coming primarily "
                       "for albatross, you are a few weeks early."),
        "cards": [
            {"time": "08:00", "name": "Gardner Bay",
             "category": "sightseeing",
             "body": "A white coral-sand beach — one of the most beautiful in "
                     "Galápagos. A large, relaxed sea lion colony sprawls along "
                     "the sand, pups included. The bold, endemic Española "
                     "mockingbird will walk right up to your feet — famously "
                     "inquisitive. Marine iguanas here are the most colourful in "
                     "the islands: the red-and-turquoise \"Christmas iguanas,\" "
                     "brightest now in breeding colour through about the end of March.",
             "notes": "Green sea turtle hatching season begins around now — Gardner Bay is one of the documented hatching beaches. Snorkel off Gardner Islet / Tortuga Rock: reef fish, sharks, curious young sea lions."},
            {"time": "12:00", "name": "Punta Suárez",
             "category": "sightseeing",
             "body": "The single most spectacular wildlife walk in the archipelago. "
                     "You'll definitely get: Nazca and blue-footed boobies nesting "
                     "underfoot; the dramatic blowhole that shoots seawater ~80 "
                     "feet up through a lava fissure at the swells' pulse; the "
                     "endemic Española lava lizard; Galápagos hawk; swallow-tailed "
                     "gulls; and the brilliant Christmas marine iguanas. You may "
                     "get the waved albatross — some of the earliest arrivals, "
                     "soaring on the cliff updrafts, occasionally settling in.",
             "notes": "The trail is about 2.5km on lava and gravel with no shade. Bring a hat and water. Punta Suárez is the only breeding colony of the waved albatross on Earth (plus a tiny secondary colony on Isla de la Plata off mainland Ecuador)."},
        ],
    },
    # ── DAY 7 · Fri Apr 2 · Back toward San Cristóbal ───────────────────────
    {
        "date": date(2027, 4, 2), "city": "Back toward San Cristóbal",
        "meta": "<b>28° / 22°C</b> · water 25°C · closing the loop",
        "intro": ("The homeward day of the cruise, closing the loop back toward "
                  "San Cristóbal. Two of the archipelago's easiest sea-lion "
                  "encounters, plus a coral-sand beach with the same look — and "
                  "the same origin — as Gardner Bay yesterday. You end where you "
                  "began: with a view back toward Kicker Rock from a bright white "
                  "beach on San Cristóbal."),
        "intro_deep": ("Cerro Brujo's dazzling white sand is eroded coral, not "
                       "volcanic — unusual in this mostly black-lava archipelago, "
                       "and why the beach reads so brilliantly bright against the "
                       "surrounding tuff cone. From the sand you can look back "
                       "east toward Kicker Rock, closing the visual loop with "
                       "where the trip started at golden hour on Day 1."),
        "cards": [
            {"time": "08:00", "name": "Isla Lobos",
             "category": "sightseeing",
             "body": "A small islet off San Cristóbal whose name means \"Sea Lion "
                     "Island\" (lobos marinos = sea lions). A resident sea lion "
                     "colony sprawls along the rocks, and the sheltered channel "
                     "on the north side is one of the best places in the archipelago "
                     "to snorkel with playful young sea lions, which loop and "
                     "somersault around swimmers. Blue-footed boobies and "
                     "frigatebirds nest on the little island's central plateau.",
             "notes": "The channel snorkel here is a highlight of the whole trip. Bring a GoPro."},
            {"time": "12:00", "name": "Cerro Brujo (Witch Hill)",
             "category": "sightseeing",
             "body": "A gorgeous white coral-sand beach backed by an eroded tuff "
                     "cone. Sea lions, shorebirds, marine iguanas, blue-footed "
                     "boobies, and sometimes flamingos in a small lagoon behind "
                     "the beach. Darwin is said to have explored this stretch of "
                     "coast in 1835 as the Beagle worked the eastern archipelago.",
             "notes": "From the beach you can see Kicker Rock in the distance — a nice symmetry with Day 1."},
        ],
    },
    # ── DAY 8 · Sat Apr 3 · Disembark ──────────────────────────────────────
    {
        "date": date(2027, 4, 3), "city": "San Cristóbal (disembark)",
        "meta": "<b>28° / 22°C</b> · departure day · morning flight to mainland",
        "intro": ("Final morning and departure. Depending on your flight timing, "
                  "expedition vessels typically fit a last short visit before the "
                  "LATAM hop back to Guayaquil or Quito. All three of the common "
                  "options are on-island: the Interpretation Center (excellent on "
                  "the archipelago's human and natural history), Cerro Tijeretas "
                  "(Frigatebird Hill, with a snorkel cove at its base), or a "
                  "highland galapaguera (tortoise reserve). A fitting bookend — "
                  "you finish where Darwin began."),
        "intro_deep": ("The Interpretation Center is the best of the three if you "
                       "have never spent a day thinking about the Galápagos as a "
                       "human-history place rather than a wildlife place. It's "
                       "small, free, and honest about the pirates, whalers, "
                       "penal colonists, and Ecuadorian settlers who came before "
                       "the naturalists arrived. About 90 minutes if you take it "
                       "seriously."),
        "cards": [
            {"time": "08:00", "name": "Disembark · Puerto Baquerizo Moreno",
             "venue_key": "Puerto Baquerizo Moreno", "category": "transit",
             "body": "The tender delivers you back to the malecón. Bags forward. "
                     "The LATAM flight to mainland Ecuador leaves later in the day.",
             "notes": "Tip the cabin staff and naturalists before you disembark — the ship's front desk usually has envelopes ready."},
            {"time": "09:30", "name": "Interpretation Center (optional last visit)",
             "venue_key": "Interpretation Center", "category": "sightseeing",
             "body": "Small, free, and one of the best short museums in Ecuador on "
                     "the archipelago's human history: pirates, whalers, WWII "
                     "airbase on Baltra, the penal colony on Isabela, the "
                     "Ecuadorian settlers, the 1959 national park declaration, "
                     "the conservation battles since.",
             "notes": "You can walk to Cerro Tijeretas from here — a 30-min uphill trail to the frigatebird colony overlook."},
        ],
    },
    # ── Buffer: Sun Apr 4 · Fly home ────────────────────────────────────────
    {
        "date": date(2027, 4, 4), "city": "Ecuador → MSP",
        "meta": "<b>~9h flight</b> · homeward · Guayaquil/Quito → US → MSP",
        "intro": ("The mirror of Day 0 — a long travel day back through mainland "
                  "Ecuador and a US hub to MSP. If your itinerary has a Guayaquil "
                  "or Quito day-room booked, use it to shower and repack; the "
                  "flight home is usually late-evening."),
        "intro_deep": ("Customs paperwork: bring nothing back from the Galápagos "
                       "beyond photos. Shells, sand, feathers, seeds — the park "
                       "will confiscate at exit, and US Customs cares too. If you "
                       "bought anything at the airport in Baltra or San Cristóbal, "
                       "keep the receipt with your carry-on for the mainland transfer."),
        "cards": [
            {"time": "TBD", "name": "Fly Ecuador → MSP (placeholder)", "category": "transit",
             "body": "Flight details not yet booked in the app — add via the Bookings tab.",
             "travelpill": "Flight · overnight"},
        ],
    },
]

# Life list — the source file's footer, kept as-is
LIFE_LIST = [
    "Waved albatross", "Blue-footed booby", "Nazca booby", "Red-footed booby",
    "Great frigatebird", "Magnificent frigatebird", "Galápagos penguin",
    "Flightless cormorant", "Swallow-tailed gull (nocturnal)", "Lava gull",
    "Short-eared owl (day-hunting)", "Vermilion flycatcher", "Darwin's finches",
    "Galápagos hawk", "Wild giant tortoise", "Land iguana", "Marine iguana",
    "\"Christmas\" marine iguana (Española)", "Sea lion + pups",
    "Green sea turtle", "Galápagos shark", "White-tip reef shark",
    "Hammerhead shark", "Eagle / golden / mobula ray", "Bryde's whale",
    "Common + bottlenose dolphin", "Greater flamingo", "Española mockingbird",
    "Endemic lava lizard (each island its own race)", "Palo santo forest",
    "Lava cactus (Brachycereus)", "Scalesia forest",
    "El Junco crater lake water",
]


# ============================================================================
# FIELD GUIDE — Galápagos species encyclopedia
# ============================================================================
# Grouped by region for chip filtering.

FIELD_GUIDE: Dict[str, Any] = {
    "intro_lede": ("A field guide to the archipelago's headline species — the "
                   "ones you have a realistic shot at seeing in eight days on a "
                   "standard San Cristóbal round-trip. Filter by region to focus "
                   "on the day at hand; search for a specific bird or reptile."),
    "regions": [
        {"slug": "birds", "label": "Birds — seabirds & endemics", "entries": [
            {"name": "Waved albatross", "latin": "Phoebastria irrorata",
             "likelihood": "Days 6 (Española) · likely a taste, not peak",
             "body": ("The Galápagos's largest bird — eight-foot wingspan, mates "
                      "for life, does dramatic cliff-edge takeoffs and crash-"
                      "landings that are part of the show. Punta Suárez on "
                      "Española is the only breeding colony on Earth (plus a tiny "
                      "secondary colony on Isla de la Plata). Full courtship "
                      "spectacle peaks late April into May; April 1 sits at the "
                      "very start of arrival — expect some soaring on updrafts, "
                      "earliest arrivals settling in."),
             "tags": ["birds", "espanola"]},
            {"name": "Blue-footed booby", "latin": "Sula nebouxii",
             "likelihood": "Days 3 · Days 6 · Days 7 — courtship dance peak now",
             "body": ("The iconic Galápagos species — bright turquoise feet, comic "
                      "sky-pointing courtship dance, high-stepping strut. Late "
                      "March is peak courtship, so North Seymour on Day 3 is prime "
                      "viewing. Feet colour is a diet signal — brighter blue = "
                      "well-fed male."),
             "tags": ["birds", "n-seymour", "espanola", "s-cristobal"]},
            {"name": "Nazca booby", "latin": "Sula granti",
             "likelihood": "Days 2 · Days 3 · Days 6",
             "body": ("Larger and whiter than the blue-foot, with a black mask "
                      "around the bill. Nests on cliffs (Genovesa) and rocky "
                      "outcrops (Española). Famous for siblicide — the older "
                      "chick usually pushes the younger out of the nest, and the "
                      "parents do not intervene."),
             "tags": ["birds", "genovesa", "espanola"]},
            {"name": "Red-footed booby", "latin": "Sula sula",
             "likelihood": "Day 2 (Genovesa) — biggest colony you'll see",
             "body": ("The only booby that nests in trees, thanks to prehensile "
                      "feet that grip branches. Genovesa hosts one of the world's "
                      "largest red-footed colonies. Two colour morphs (brown and "
                      "white); the brown form dominates here."),
             "tags": ["birds", "genovesa"]},
            {"name": "Great frigatebird", "latin": "Fregata minor",
             "likelihood": "Days 2 · Days 3 — courtship peak Dec–May",
             "body": ("Males inflate crimson throat pouches to soccer-ball size "
                      "during courtship, which peaks December through May — you "
                      "are in the sweet spot. Kleptoparasites: they harass other "
                      "seabirds into dropping their catch in mid-air, then swoop "
                      "the fish before it hits water."),
             "tags": ["birds", "genovesa", "n-seymour"]},
            {"name": "Magnificent frigatebird", "latin": "Fregata magnificens",
             "likelihood": "Days 1 · Day 8 (San Cristóbal town)",
             "body": ("The other frigatebird — same behaviour, subtly different "
                      "plumage. Common over Cerro Tijeretas (\"Frigatebird Hill\") "
                      "above Puerto Baquerizo Moreno. Wingspan reaches 2.4m yet "
                      "the bird weighs only 1.5kg — the lightest bird per square "
                      "metre of wing on Earth."),
             "tags": ["birds", "s-cristobal"]},
            {"name": "Galápagos penguin", "latin": "Spheniscus mendiculus",
             "likelihood": "Day 4 (Bolívar Channel) · possibly Day 3",
             "body": ("The only penguin found north of the equator (a tiny colony "
                      "on northern Isabela sits about 1° N). Global population is "
                      "around 1,200 pairs — one of the world's rarest penguins. "
                      "The Bolívar Channel's Cromwell upwelling drags Antarctic-"
                      "cold, fish-rich water right up to the equator, which is "
                      "the only reason they survive here."),
             "tags": ["birds", "isabela", "santiago"]},
            {"name": "Flightless cormorant", "latin": "Nannopterum harrisi",
             "likelihood": "Day 4 (Fernandina + western Isabela)",
             "body": ("The only cormorant in the world that lost the ability to "
                      "fly — wings shrivelled to useless stubs while the bird "
                      "became a powerful underwater swimmer. Total global "
                      "population: ~1,000 birds, essentially all of them living "
                      "on Fernandina and western Isabela."),
             "tags": ["birds", "fernandina", "isabela"]},
            {"name": "Swallow-tailed gull", "latin": "Creagrus furcatus",
             "likelihood": "Days 2 · Days 3 · Day 6",
             "body": ("The world's only nocturnal gull — huge dark-adapted eyes "
                      "and a bright white spot at the bill's base that chicks peck "
                      "to prompt feeding. Nests on cliff ledges. When you see one "
                      "roosting during the day and looking sleepy, that is the "
                      "correct behaviour."),
             "tags": ["birds", "genovesa", "espanola"]},
            {"name": "Lava gull", "latin": "Leucophaeus fuliginosus",
             "likelihood": "Days 1 · Day 2 · around any harbour",
             "body": ("One of the rarest gulls in the world — global population "
                      "of only about 300–400 pairs, all in the Galápagos. Dark "
                      "sooty grey plumage with a red eye-ring; scavenges around "
                      "harbours and nesting seabird colonies."),
             "tags": ["birds", "s-cristobal", "genovesa"]},
            {"name": "Galápagos short-eared owl", "latin": "Asio flammeus galapagoensis",
             "likelihood": "Day 2 (Genovesa) — day-hunting is diagnostic",
             "body": ("Endemic subspecies. Genovesa is one of the only places on "
                      "Earth where you can reliably see a short-eared owl hunting "
                      "in broad daylight — it targets the island's dense storm "
                      "petrel colony, which the resident Galápagos hawk doesn't "
                      "share. Watch the palo santo forest edges on Prince Philip's Steps."),
             "tags": ["birds", "genovesa"]},
            {"name": "Vermilion flycatcher", "latin": "Pyrocephalus rubinus",
             "likelihood": "Day 5 (Santa Cruz highlands)",
             "body": ("Bright red male, brown female — an unmistakable flash of "
                      "colour in the misty Scalesia forest of Santa Cruz's Los "
                      "Gemelos. Populations have declined on several islands due "
                      "to introduced parasitic flies (Philornis downsi) killing "
                      "chicks in the nest — the highland reserves are the best "
                      "current viewing."),
             "tags": ["birds", "santa-cruz"]},
            {"name": "Darwin's finches (small ground/cactus/warbler)", "latin": "Geospiza spp. / Camarhynchus spp.",
             "likelihood": "Every day, everywhere",
             "body": ("The famous 13-species radiation from a single South-"
                      "American ancestor. Beak size and shape track diet — small "
                      "ground finches on seeds, cactus finches on Opuntia flowers, "
                      "warbler finches on insects, woodpecker finches on grubs "
                      "(they use tools). Distinguishing them in the field takes "
                      "practice; the naturalists on board will help."),
             "tags": ["birds", "any"]},
            {"name": "Galápagos hawk", "latin": "Buteo galapagoensis",
             "likelihood": "Day 6 (Española) · often Day 3 (Santiago)",
             "body": ("The archipelago's apex terrestrial predator — takes lizards, "
                      "young marine iguanas, baby sea turtles, occasionally chicks "
                      "of other seabirds. Absent from Genovesa (which is why the "
                      "short-eared owl fills the raptor niche there). Polyandrous: "
                      "one female often mates with several males who all help raise the brood."),
             "tags": ["birds", "espanola", "santiago"]},
            {"name": "Española mockingbird", "latin": "Mimus macdonaldi",
             "likelihood": "Day 6 (Española) — will approach you",
             "body": ("Endemic to Española. Famously inquisitive — will walk right "
                      "up to your boots, has been observed pecking at water bottles "
                      "for the moisture. Darwin's four Galápagos mockingbird "
                      "species (one per major island group) were actually a "
                      "bigger inspiration for his thinking than the finches at "
                      "the time — the differences between islands hit him harder."),
             "tags": ["birds", "espanola"]},
        ]},
        {"slug": "reptiles", "label": "Reptiles — iguanas & tortoises", "entries": [
            {"name": "Galápagos giant tortoise", "latin": "Chelonoidis niger complex",
             "likelihood": "Day 5 (wild + breeding centre)",
             "body": ("The archipelago's namesake — galápago is the old Spanish "
                      "word for tortoise. About 12 named subspecies, several extinct. "
                      "Two shell shapes: dome-shelled (grazers, wetter islands) and "
                      "saddleback (browsers, drier islands — the arched shell lets "
                      "the neck reach up for Opuntia pads). Lifespan is over 100 "
                      "years; the largest bulls weigh 300+ kg."),
             "tags": ["reptiles", "santa-cruz"]},
            {"name": "Marine iguana", "latin": "Amblyrhynchus cristatus",
             "likelihood": "Every landing, every day",
             "body": ("The only marine lizard in the world. Feeds on submerged "
                      "algae — larger males dive to 20m; smaller females and "
                      "juveniles graze shoreline algae at low tide. \"Sneezes\" "
                      "salt through nasal glands after feeding (you'll see the "
                      "white crust). Each island's race has its own colour "
                      "signature; Española's are the brilliant red-and-"
                      "turquoise \"Christmas iguanas.\""),
             "tags": ["reptiles", "any"]},
            {"name": "Galápagos land iguana", "latin": "Conolophus subcristatus",
             "likelihood": "Day 3 (North Seymour) · Day 4 (western Isabela)",
             "body": ("Yellow-and-brown, larger than the marine iguana, and "
                      "vegetarian — eats Opuntia cactus pads, tolerating the "
                      "spines. North Seymour hosts the transplanted population "
                      "from the 1930s Baltra relocation experiment (later used "
                      "to repopulate Baltra when its own population was wiped out)."),
             "tags": ["reptiles", "n-seymour", "isabela"]},
            {"name": "Endemic lava lizard (species per island)", "latin": "Microlophus spp.",
             "likelihood": "Every landing",
             "body": ("Small ground lizards you'll see on every rock and trail. "
                      "Seven endemic species split across the archipelago — each "
                      "major island has its own species. Females often have red "
                      "throat patches; males do prominent push-up displays to "
                      "hold territory."),
             "tags": ["reptiles", "any"]},
        ]},
        {"slug": "marine", "label": "Marine — sharks, rays, whales, turtles", "entries": [
            {"name": "Galápagos sea lion", "latin": "Zalophus wollebaeki",
             "likelihood": "Every day of the trip",
             "body": ("Endemic to the archipelago (a close relative of the "
                      "Californian sea lion). Colonies on almost every beach; "
                      "young pups are curious and will investigate snorkelers. "
                      "Males are much larger (300+ kg) with a pronounced forehead "
                      "bump; they defend beach territories aggressively during "
                      "the breeding season."),
             "tags": ["marine", "any"]},
            {"name": "Galápagos fur seal", "latin": "Arctocephalus galapagoensis",
             "likelihood": "Occasional — cliffy shorelines, dawn/dusk",
             "body": ("The archipelago's other pinniped — smaller, denser fur, "
                      "and more nocturnal than the sea lion. Prefers rocky, "
                      "shaded shorelines. Nearly extirpated by 19th-century "
                      "sealers; now protected and slowly recovering. Best "
                      "chance: cliffy stretches on Santiago or Isabela."),
             "tags": ["marine", "santiago"]},
            {"name": "Green sea turtle", "latin": "Chelonia mydas",
             "likelihood": "Every snorkel · nesting/hatching on Days 6",
             "body": ("The archipelago's dominant sea turtle. Nesting season "
                      "peaks December–March; early hatching begins around now on "
                      "beaches like Gardner Bay. In the water they're often "
                      "startlingly close — they don't spook easily. The Galápagos "
                      "population has its own genetic signature and some turtles "
                      "have shells nearly black rather than the greenish global norm."),
             "tags": ["marine", "espanola", "any"]},
            {"name": "Galápagos shark", "latin": "Carcharhinus galapagensis",
             "likelihood": "Kicker Rock channel · Bolívar Channel",
             "body": ("The archipelago's namesake shark — grey-brown, up to 3m. "
                      "Common around volcanic pinnacles and clear-water islets. "
                      "Not aggressive toward snorkelers under normal conditions "
                      "but keep the naturalist's briefing in mind: don't chase, "
                      "don't corner."),
             "tags": ["marine", "s-cristobal"]},
            {"name": "White-tip reef shark", "latin": "Triaenodon obesus",
             "likelihood": "Frequent — day-resting under ledges",
             "body": ("The shark you'll most often see resting under ledges by "
                      "day (they hunt at night). Slender, 1.5–2m, with distinctive "
                      "white tips on dorsal and caudal fins. Utterly uninterested "
                      "in snorkelers — you can drift right over one."),
             "tags": ["marine", "any"]},
            {"name": "Hammerhead shark", "latin": "Sphyrna lewini",
             "likelihood": "Kicker Rock channel · seasonal",
             "body": ("Scalloped hammerheads form schools around the archipelago's "
                      "outer islets in season. Kicker Rock's channel is one of the "
                      "reliable sites when the water is warm and clear (which is "
                      "your week). The classic sighting is a school gliding "
                      "below at 15–20m; less often, individuals cross the shallows."),
             "tags": ["marine", "s-cristobal"]},
            {"name": "Manta ray", "latin": "Mobula birostris",
             "likelihood": "Bolívar Channel · offshore transits",
             "body": ("The world's largest ray — wingspan to 7m. Feeds on "
                      "plankton, filter-feeding by cruising with mouth open. "
                      "Most likely on the Bolívar Channel morning; occasionally "
                      "on inter-island crossings. Distinguished from the smaller "
                      "mobula rays by size and the horn-like cephalic fins that "
                      "unfurl in front of the head."),
             "tags": ["marine", "isabela"]},
            {"name": "Spotted eagle ray / golden ray / mobula", "latin": "Aetobatus / Rhinoptera / Mobula spp.",
             "likelihood": "Kicker Rock · Isla Lobos · Gardner Bay",
             "body": ("Three ray genera you'll commonly see: the elegant spotted "
                      "eagle ray with white spots on a dark back; the golden "
                      "cownose ray moving in shimmering schools; and the smaller "
                      "mobulas that jump clear of the water on occasion."),
             "tags": ["marine", "s-cristobal", "espanola"]},
            {"name": "Bryde's whale", "latin": "Balaenoptera edeni",
             "likelihood": "Day 4 (Bolívar Channel) — best chance",
             "body": ("Medium-sized baleen whale (~15m). The Bolívar Channel is "
                      "the archipelago's best cetacean water because the Cromwell "
                      "upwelling concentrates krill and small fish. Bryde's are "
                      "the most consistent sighting; blue whales, sperm whales, "
                      "and orcas are occasional bonuses."),
             "tags": ["marine", "isabela"]},
            {"name": "Common + bottlenose dolphin", "latin": "Delphinus delphis / Tursiops truncatus",
             "likelihood": "Any crossing · bow rides common",
             "body": ("Both species ride the bow of the ship on longer crossings. "
                      "Common dolphins travel in the larger pods (50–500 animals); "
                      "bottlenose in smaller family groups. Best watch: forward "
                      "deck on morning transits between islands."),
             "tags": ["marine", "any"]},
        ]},
        {"slug": "plants-geology", "label": "Plants & geology", "entries": [
            {"name": "Palo santo tree", "latin": "Bursera graveolens",
             "likelihood": "Day 2 (Genovesa) · Day 3 · Day 6",
             "body": ("\"Holy wood\" — a silvery-barked, aromatic tree common on "
                      "the drier islands. Leafless most of the year; leaves out "
                      "briefly during the wet season, which means your late-March "
                      "trip should see it in green. Burnt as incense throughout "
                      "Andean South America; the wood has a citrus-cedar smell."),
             "tags": ["plants-geology", "genovesa", "espanola"]},
            {"name": "Lava cactus", "latin": "Brachycereus nesioticus",
             "likelihood": "Day 3 (Sullivan Bay) — pioneer species",
             "body": ("Endemic — grows only on young pahoehoe and aa lava fields, "
                      "one of the very first plants to colonise fresh flows. "
                      "Small yellow spines, cylindrical stems in clumps. On "
                      "Sullivan Bay's 1897 flow it is the visible \"life is "
                      "starting here\" species."),
             "tags": ["plants-geology", "santiago"]},
            {"name": "Opuntia cactus (giant prickly pear)", "latin": "Opuntia echios / O. galapageia",
             "likelihood": "Days 1 · 3 · 5 · widespread",
             "body": ("Massive prickly-pear cacti, sometimes tree-like with a "
                      "woody trunk. The species and shape varies by island — a "
                      "classic Galápagos speciation example. On islands with "
                      "giant tortoises, the tallest Opuntia hold their pads out "
                      "of reach; on islands without tortoises, the plants stay low."),
             "tags": ["plants-geology", "any"]},
            {"name": "Scalesia forest", "latin": "Scalesia pedunculata",
             "likelihood": "Day 5 (Santa Cruz highlands)",
             "body": ("Endemic — the \"tree daisy\" (Scalesia is in the sunflower "
                      "family). Forms dense cloud forests in the highlands of the "
                      "wetter islands. The Los Gemelos crater rims on Santa Cruz "
                      "are ringed with mature Scalesia forest, dripping in "
                      "epiphytes during the wet season."),
             "tags": ["plants-geology", "santa-cruz"]},
            {"name": "Mangroves (four species)", "latin": "Rhizophora / Avicennia / Laguncularia / Conocarpus",
             "likelihood": "Days 2 · Day 4 · Day 6",
             "body": ("The archipelago has all four New-World mangrove species. "
                      "Look for the red mangrove's stilt roots, white mangrove's "
                      "salt-excreting leaves, black mangrove's finger-like "
                      "pneumatophores rising from the mud, and button mangrove's "
                      "rounder form. Prime habitat for herons, sea turtles, "
                      "reef fish nurseries, and Day 4's flightless cormorants."),
             "tags": ["plants-geology", "genovesa", "isabela"]},
            {"name": "Pahoehoe lava", "latin": "—",
             "likelihood": "Day 3 (Sullivan Bay) · Day 4 (Punta Moreno)",
             "body": ("The ropey, smooth, glassy type of basaltic lava flow — from "
                      "the Hawaiian word for \"unbroken.\" Contrast with aa (rough, "
                      "broken clinker). Sullivan Bay's 1897 flow is a textbook "
                      "pahoehoe field with hornitos (small spatter cones from "
                      "gas escape) and collapsed lava bubbles."),
             "tags": ["plants-geology", "santiago", "isabela"]},
            {"name": "Tuff cone (León Dormido, Cerro Brujo)", "latin": "—",
             "likelihood": "Days 1 · Day 7",
             "body": ("Volcanic ash compacted into rock, then eroded. Kicker "
                      "Rock's twin towers are the eroded remnant of a vertical "
                      "tuff cone; Cerro Brujo is a lower, wider tuff-cone remnant "
                      "on San Cristóbal. Tuff erodes much faster than lava, which "
                      "is why these forms are so sculptural — the sea has been "
                      "chewing them for a long time."),
             "tags": ["plants-geology", "s-cristobal"]},
        ]},
    ],
}


# ============================================================================
# WEATHER
# ============================================================================

WEATHER = {
    "intro_lede": ("Late March in the Galápagos is the warm/wet season at its "
                   "peak: warmest water, clearest visibility, calmest seas, "
                   "brief afternoon showers, lush green highlands. If you were "
                   "picking dates for photography and snorkeling comfort, "
                   "these are the ones."),
    "stat_grid": SEASON_STRIP,
    "season_notes": ("The Galápagos has two seasons, not four: warm/wet "
                     "(December–May) and cool/dry (June–November). Your dates "
                     "are at the tail end of warm/wet, which brings the "
                     "highest sea temperatures (~25°C / 77°F) and clearest "
                     "water of the year, but also the year's peak rainfall — "
                     "usually short afternoon showers rather than sustained "
                     "rain. Seas are calmest now, which matters for the long "
                     "northern crossing to Genovesa and the west-side "
                     "channels."),
    "packing_implications": [
        "Rain jacket that actually breathes — you'll wear it over sun clothing during afternoon showers.",
        "2–3mm shorty wetsuit is comfort, not necessity — water is 25°C. Rash guard is a fine minimum for casual snorkelers.",
        "Reef-safe (mineral) sunscreen — Galápagos National Park rules and coral health both prefer it.",
        "Quick-dry pants + long-sleeve UPF shirts — you'll live in these; cotton stays damp all week.",
        "Closed-toe hiking sandals or grippy water shoes for wet landings on lava; regular sneakers for dry landings and highland walks.",
        "Broad-brim hat with a chinstrap — the equatorial sun is intense even under cloud, and the wind on pangas takes hats fast.",
        "Small dry bag for camera + phone on panga rides — the tenders splash.",
        "US-plug adapter (Ecuador uses Type A/B, same as North America, 110V). No conversion needed for Americans.",
    ],
}


# ============================================================================
# HISTORY
# ============================================================================

HISTORY = {
    "intro_lede": ("The Galápagos have three interlocking histories: geological "
                   "(a hotspot in the Pacific), evolutionary (isolation "
                   "producing radiations Darwin would notice), and human "
                   "(pirates, whalers, penal colonists, and, since 1959, "
                   "conservationists). Each of the three explains something "
                   "you'll see this week."),
    "vignettes": [
        {
            "era_slug": "geology",
            "title": "The hotspot and the age gradient",
            "lede": ("The Galápagos sit over a stationary volcanic hotspot beneath "
                     "the Nazca tectonic plate. The plate is moving east-southeast "
                     "at about 5cm per year, so islands are born in the west "
                     "(Fernandina, ~35,000 years old and still erupting), age as "
                     "they drift east, and eventually erode below the waterline. "
                     "San Cristóbal at the eastern edge is ~2.4 million years old; "
                     "Española is the oldest of the main islands at ~3.5 million."),
            "deep": ("This is why your itinerary reads geologically in a specific "
                     "order: San Cristóbal (old, eroded, tuff cones) at both ends, "
                     "Fernandina (young, pristine, still smoking) in the middle, "
                     "and Española's old rounded slopes in the south. Between the "
                     "oldest and youngest islands you cross ~3.5 million years of "
                     "geology in less than a day's sailing."),
            "consequence": ("Every landscape you walk on this week is a snapshot "
                            "of the hotspot's conveyor belt at a different stage."),
        },
        {
            "era_slug": "geology",
            "title": "Why penguins live on the equator",
            "lede": ("The Cromwell Current (Pacific Equatorial Undercurrent) flows "
                     "east along the equator at depth, then upwells against the "
                     "western wall of Isabela. Cold, nutrient-rich Antarctic-"
                     "origin water rises to the surface. That upwelling is why "
                     "the western channel is Galápagos's cetacean and pinniped "
                     "capital — and why penguins and fur seals live 1° from the equator."),
            "deep": ("The upwelling is seasonal in strength. It peaks in the "
                     "cool/dry season (July–November); your late-March visit "
                     "catches the warm end of it, but the channel is still "
                     "measurably colder than the eastern islands — Day 4's water "
                     "temperature will drop by 2–3°C for the snorkel."),
            "consequence": ("Day 4 is your only equator-cold day. Bring the shorty."),
        },
        {
            "era_slug": "evolution",
            "title": "Darwin, Sept 17 1835, and the mockingbirds",
            "lede": ("HMS Beagle made landfall at San Cristóbal on September 17, "
                     "1835. Darwin spent about five weeks in the archipelago, "
                     "visiting four islands. Contrary to popular retelling, the "
                     "finches did not immediately convince him of anything — he "
                     "mislabelled many specimens by island. It was the "
                     "mockingbirds — four visibly distinct species, one per major "
                     "island group — that first made him question fixity of species."),
            "deep": ("Darwin published On the Origin of Species in 1859, nearly a "
                     "quarter-century after the Galápagos visit. The archipelago "
                     "was only one input among many, but it was foundational for "
                     "the specific idea that isolated populations diverge. Alfred "
                     "Russel Wallace independently reached the same conclusion "
                     "from Southeast Asia; their joint 1858 papers preceded "
                     "the book by a year."),
            "consequence": ("The endemic Española mockingbird that walks up to "
                            "your boots on Day 6 is a direct descendant of what "
                            "Darwin was noticing here."),
        },
        {
            "era_slug": "human",
            "title": "Pirates, whalers, and post office bay",
            "lede": ("For nearly 300 years before naturalists arrived, the "
                     "Galápagos were a resupply stop for pirates raiding the "
                     "Spanish Pacific coast (16th–17th centuries) and, later, "
                     "American and British whalers hunting sperm whales in the "
                     "eastern Pacific (18th–19th centuries). The islands paid "
                     "for it: whalers took an estimated 100,000+ giant tortoises "
                     "as living food stores, and introduced goats, pigs, and rats."),
            "deep": ("Floreana's Post Office Bay barrel is the surviving trace — "
                     "a whaler's improvised mail-drop from around 1793 that still "
                     "works on the honour system today. Your itinerary doesn't "
                     "call at Floreana, but the Interpretation Center in Puerto "
                     "Baquerizo Moreno covers the whaling era well if you have "
                     "time on Day 8."),
            "consequence": ("Every island you visit is quietly recovering from "
                            "the whaling centuries; the goat and pig eradications "
                            "are what made the modern conservation numbers possible."),
        },
        {
            "era_slug": "human",
            "title": "1959, the National Park, and the modern deal",
            "lete": "",
            "lede": ("Ecuador declared the Galápagos a National Park in 1959 — "
                     "the centenary year of On the Origin of Species — and the "
                     "Charles Darwin Research Station opened at Puerto Ayora "
                     "in 1964. The park covers 97% of the archipelago's land "
                     "area; the remaining 3% is settled (Santa Cruz, San "
                     "Cristóbal, Isabela, Floreana). Marine Reserve status "
                     "came in 1998, covering 138,000 km² of surrounding water."),
            "deep": ("The modern deal is a hard trade: strict rules for visitors "
                     "(licensed naturalist guides required, fixed trail routes, "
                     "no touching wildlife, rotating site assignments to prevent "
                     "overuse), a $200 park entrance fee, tight cruise permits. "
                     "In exchange, the archipelago has recovered spectacularly "
                     "from the 20th century's low point — goat-free major islands, "
                     "giant tortoise populations rebuilt on Española, and "
                     "occasional new species discoveries (Fernanda, 2019)."),
            "consequence": ("The reason you can walk right up to a nesting "
                            "blue-footed booby without disturbing it is a "
                            "70-year regulatory experiment that mostly worked."),
        },
    ],
    "phrase_table": [
        {"row": ["English", "Spanish", "Pronunciation"]},
        {"row": ["Hello", "Hola", "OH-lah"]},
        {"row": ["Please", "Por favor", "por fah-VOR"]},
        {"row": ["Thank you", "Gracias", "GRAH-see-ahs"]},
        {"row": ["Excuse me", "Disculpe", "dees-KOOL-peh"]},
        {"row": ["Do you speak English?", "¿Habla inglés?", "AH-blah een-GLESS"]},
        {"row": ["The bill, please", "La cuenta, por favor", "lah KWEN-tah"]},
        {"row": ["One / two / three", "Uno / dos / tres", "OO-noh / dohs / trays"]},
        {"row": ["Four / five / six", "Cuatro / cinco / seis", "KWAH-troh / SEEN-koh / says"]},
        {"row": ["Seven / eight / nine / ten", "Siete / ocho / nueve / diez", "see-EH-teh / OH-choh / NWEH-veh / dee-EZ"]},
    ],
}


# ============================================================================
# THINGS TO DO — pre/post-cruise Quito / Guayaquil / San Cristóbal
# ============================================================================

THINGS_TO_DO = {
    "intro_lede": ("The cruise carries the trip. But most itineraries include a "
                   "buffer night on the mainland — Guayaquil (Silversea's usual "
                   "stage) or Quito (the culturally richer option). Here are "
                   "picks for a half-day in each, plus a short list for Puerto "
                   "Baquerizo Moreno if you land early on embarkation morning."),
    "groups": [
        {
            "label": "Guayaquil · half-day picks",
            "opinion": ("Guayaquil's Malecón is genuinely worth two hours; the "
                        "rest of the city can be safely skipped by a first-time "
                        "visitor. If you have less than a full afternoon, "
                        "prioritise the Malecón → Las Peñas → Cerro Santa Ana "
                        "arc, in that order."),
            "entries": [
                {"name": "Malecón 2000",
                 "venue_key": "Malecón 2000",
                 "neighborhood": "Riverfront · downtown",
                 "body": ("A 2.5km reclaimed riverfront promenade opened in 2000 "
                          "along the Guayas River. Free to enter (there are gate "
                          "checkpoints), well-maintained, safe. Gardens, small "
                          "shops, and the shaded Plaza Cívica with a viewing tower.")},
                {"name": "Las Peñas + Cerro Santa Ana",
                 "venue_key": "Las Peñas",
                 "neighborhood": "Oldest quarter · north end of Malecón",
                 "body": ("Colourful 19th-century houses on a hillside, plus 444 "
                          "steps up Cerro Santa Ana to a small chapel and "
                          "panorama over the river and city. Do the climb in "
                          "the late afternoon when the light is soft. Cafés and "
                          "small galleries line the way up.")},
                {"name": "Parque Seminario (Iguanas Park)",
                 "venue_key": "Iguanas Park (Parque Seminario)",
                 "neighborhood": "City centre · across from cathedral",
                 "body": ("A small downtown park famous for dozens of free-"
                          "roaming green iguanas that lounge on the grass and "
                          "in the trees. Ten minutes, then move on. A useful "
                          "warm-up for the reptile density you're about to see.")},
                {"name": "Parque Histórico Guayaquil",
                 "venue_key": "Parque Histórico Guayaquil",
                 "neighborhood": "Samborondón (north bank, 15 min by taxi)",
                 "body": ("An open-air museum in three zones: a coastal wildlife "
                          "reserve (tapirs, sloths, harpy eagles), a restored "
                          "1900s hacienda, and a colonial Guayaquil urban "
                          "reconstruction. Genuinely well done; needs half a day.")},
            ],
        },
        {
            "label": "Quito · half-day picks",
            "opinion": ("Quito's Old Town is a UNESCO site and the best "
                        "colonial-city walk in Ecuador; if you can arrange a "
                        "Quito stopover instead of Guayaquil, do. Skip the "
                        "Mitad del Mundo monument (the actual equator line is "
                        "500m north of it and the visitor site is a bit forced)."),
            "entries": [
                {"name": "Quito Old Town",
                 "venue_key": "Quito Old Town",
                 "neighborhood": "Historic centre · walkable",
                 "body": ("Cobblestone streets, colonial churches, and Plaza de "
                          "la Independencia. Do a half-day slow walk: Plaza de "
                          "la Independencia → Palacio de Carondelet → La "
                          "Compañía → San Francisco → Calle La Ronda for the "
                          "evening.")},
                {"name": "La Compañía de Jesús",
                 "venue_key": "La Compañía de Jesús",
                 "neighborhood": "Old Town · block from Plaza Grande",
                 "body": ("A Jesuit church whose interior is entirely gilded — "
                          "160 years to build (1605–1765), and the most opulent "
                          "colonial-Baroque interior in South America. Small "
                          "entrance fee, no photos inside. About 45 minutes.")},
                {"name": "Basílica del Voto Nacional",
                 "venue_key": "Basílica del Voto Nacional",
                 "neighborhood": "Old Town · north edge",
                 "body": ("A neo-Gothic basilica whose gargoyles are Galápagos "
                          "iguanas, tortoises, and boobies (a genuine "
                          "peculiarity — the architect substituted local fauna "
                          "in the 1900s design). You can climb the towers for "
                          "the view. Not for those uncomfortable with heights.")},
                {"name": "TelefériQo",
                 "venue_key": "TelefériQo",
                 "neighborhood": "Pichincha · west of city",
                 "body": ("A cable car up the flank of Pichincha volcano to "
                          "4,050m — vast views over Quito and the Andean "
                          "cordillera on a clear morning. Go early; clouds "
                          "close in by 11am most days. Bring a jacket — it is "
                          "genuinely cold at the top.")},
            ],
        },
        {
            "label": "Puerto Baquerizo Moreno · embark or disembark day",
            "opinion": ("If you have 90 minutes on Day 1 before boarding or "
                        "Day 8 after disembarking, the Interpretation Center + "
                        "Cerro Tijeretas walk is the correct answer. Everything "
                        "else in town is coffee and souvenir shopping."),
            "entries": [
                {"name": "Interpretation Center",
                 "venue_key": "Interpretation Center",
                 "neighborhood": "Punta Carola · 15 min walk from harbour",
                 "body": ("A small, free museum on the archipelago's human and "
                          "natural history — pirates, whalers, WWII Baltra "
                          "airbase, the 1959 park declaration. Honest and well-"
                          "curated. About 60 minutes.")},
                {"name": "Cerro Tijeretas (Frigatebird Hill)",
                 "venue_key": "Cerro Tijeretas",
                 "neighborhood": "Behind the Interpretation Center · 30 min trail",
                 "body": ("A gentle trail up a small hill with a frigatebird "
                          "colony overlook at the top and a snorkel cove at the "
                          "bottom. Good for a couple of hours if you brought a "
                          "swimsuit in your day pack.")},
            ],
        },
    ],
}


# ============================================================================
# FOOD — Ecuadorian + Galápagos
# ============================================================================

FOOD = {
    "intro_lede": ("The cruise handles the archipelago's meals — you'll eat "
                   "buffet-style on board with fresh fish and Ecuadorian rice-"
                   "and-beans staples. This section covers the mainland "
                   "brackets: what to try on a Guayaquil or Quito buffer day, "
                   "plus a short list for Puerto Ayora if you have any free "
                   "evening on Day 5."),
    "things_to_try": [
        {"name": "Ceviche (Ecuadorian style)", "local": "ceviche",
         "region": "Coastal Ecuador · everywhere",
         "body": ("Different from Peruvian ceviche — the fish comes in a tomato-"
                  "based broth rather than clear leche de tigre, with popcorn "
                  "or corn nuts on the side. Shrimp ceviche is the coastal "
                  "default; concha (blood cockle) is the more adventurous choice."),
         "tag": "must try"},
        {"name": "Encebollado", "local": "encebollado",
         "region": "Guayaquil breakfast staple",
         "body": ("A tuna and yuca soup with pickled red onion on top — the "
                  "quintessential Guayaquil hangover cure and, more usefully, "
                  "a filling cheap breakfast at any comedor. Comes with "
                  "popcorn and plantain chips.")},
        {"name": "Locro de papa", "local": "locro de papa",
         "region": "Highland / Quito",
         "body": ("A creamy potato-and-cheese soup with avocado on top, staple "
                  "Andean comfort food. Warms you up after a chilly Quito "
                  "morning. The version in most restaurants is enough to be "
                  "a light lunch on its own.")},
        {"name": "Bolón de verde", "local": "bolón",
         "region": "Coastal breakfast",
         "body": ("A ball of mashed green plantain filled with cheese or "
                  "chicharrón, pan-fried until crisp. Common breakfast at "
                  "Guayaquil markets. Pair with a strong coffee.")},
        {"name": "Llapingachos", "local": "llapingachos",
         "region": "Highland",
         "body": ("Pan-fried potato-and-cheese patties, usually served with "
                  "chorizo, avocado, and a peanut sauce. Highland comfort "
                  "food; a staple set-menu almuerzo (lunch) plate.")},
        {"name": "Cuy (roasted guinea pig)", "local": "cuy",
         "region": "Highland — adventurous",
         "body": ("A special-occasion dish in the Andes — roasted whole. Try "
                  "it if you're culturally curious; skip if you'd rather not "
                  "see feet on your plate. Not on the coast; not on Galápagos.")},
        {"name": "Empanadas de viento", "local": "empanadas de viento",
         "region": "Highland",
         "body": ("Puffy fried cheese empanadas dusted with sugar. Airport-"
                  "food-tier ubiquitous in Quito and a legitimately delicious "
                  "cheap snack. Ten minutes to make, five to eat.")},
        {"name": "Encocado", "local": "encocado",
         "region": "Coastal Ecuador",
         "body": ("Fish or shrimp in a coconut-milk sauce, with green plantain "
                  "and rice. An Afro-Ecuadorian coastal staple. Rich but "
                  "not heavy.")},
        {"name": "Colada morada", "local": "colada morada",
         "region": "Highland · Nov 2 traditionally, year-round in some places",
         "body": ("A thick, dark-purple corn-and-blackberry drink served with "
                  "guagua de pan (a person-shaped sweet bread). Ceremonial "
                  "for Day of the Dead but often available on regular menus.")},
        {"name": "Canelazo", "local": "canelazo",
         "region": "Highland warm evening drink",
         "body": ("Hot cinnamon-and-cane-sugar drink spiked with aguardiente "
                  "(sugar-cane spirit) or rum. Ubiquitous in Quito after dark. "
                  "Warms you up on a cool Andean evening.")},
        {"name": "Fritada", "local": "fritada",
         "region": "Highland",
         "body": ("Slow-braised then fried pork, served with mote (hominy), "
                  "toasted corn, tostones, and salsa criolla. Weekend lunch "
                  "food; very filling.")},
        {"name": "Fresh fish, Galápagos", "local": "pescado del día",
         "region": "On board + Puerto Ayora",
         "body": ("Grouper, wahoo, tuna, dorado — whatever came off the boat "
                  "that morning. The archipelago's marine reserve keeps "
                  "sustainable catches viable. On board, the buffet's fish "
                  "will be genuinely local.")},
    ],
    "opinion": ("If you only try three things: (1) shrimp ceviche in "
                "Guayaquil the day you land, (2) a locro de papa in Quito if "
                "you get a highland day, and (3) fresh grilled fish at "
                "Puerto Ayora's Calle de los Kioskos if you have an evening "
                "on Day 5. Everything else is bonus."),
    "where_to_eat": [
        {"label": "Splurge · white-tablecloth", "entries": [
            {"name": "Casa Gangotena",
             "venue_key": "Casa Gangotena",
             "city": "Quito Old Town",
             "body": ("The best colonial-mansion dining room in Ecuador. "
                      "Tasting menu focused on Andean ingredients — cuy, "
                      "quinoa, uvilla — with modernist plating. Reserve well ahead.")},
            {"name": "Zazu",
             "venue_key": "Zazu",
             "city": "Quito · La Floresta",
             "body": ("Widely considered Quito's most consistent fine-dining "
                      "kitchen. Peruvian-Ecuadorian fusion; the ceviche and "
                      "the tiradito are especially good.")},
            {"name": "Lo Nuestro",
             "venue_key": "Lo Nuestro",
             "city": "Guayaquil · Urdesa",
             "body": ("Old-guard Ecuadorian cuisine done well — the encebollado "
                      "at lunch and the corvina Lo Nuestro at dinner. Formal "
                      "but warm.")},
        ]},
        {"label": "Sit-down · reliable", "entries": [
            {"name": "Riviera Ristorante",
             "venue_key": "Riviera Ristorante",
             "city": "Guayaquil · Urdesa",
             "body": ("Wood-oven Italian on the coast side, going strong for "
                      "decades. Not Ecuadorian food, but exactly what you want "
                      "the night you land — familiar, well-executed, quiet.")},
            {"name": "Sambo Casa del Cangrejo",
             "venue_key": "Sambo Casa del Cangrejo",
             "city": "Guayaquil · Urdesa",
             "body": ("Crab specialists — the local mangrove crab (cangrejo "
                      "rojo) done ten ways. Messy, communal, cheap for what "
                      "it is. Bring a change of shirt.")},
            {"name": "Isla Grill",
             "venue_key": "Isla Grill",
             "city": "Puerto Ayora, Santa Cruz",
             "body": ("A reliable grill room a block back from the malecón. "
                      "Local fish, competent grilling, no surprises. "
                      "Convenient if you're in town on Day 5.")},
            {"name": "Almar",
             "venue_key": "Almar",
             "city": "Puerto Ayora",
             "body": ("Seafood-forward Ecuadorian, on the harbour front. Best "
                      "for an early dinner watching the pangas come in.")},
        ]},
        {"label": "Casual · lunch counters + neighborhood spots", "entries": [
            {"name": "La Ronda",
             "venue_key": "La Ronda",
             "city": "Quito Old Town",
             "body": ("A restored colonial lane in Old Town lined with small "
                      "restaurants and canelazo bars, all with musicians in "
                      "the evening. Order a canelazo and empanadas de viento "
                      "and drift.")},
            {"name": "Muyu Bistro",
             "venue_key": "Muyu Bistro",
             "city": "Puerto Baquerizo Moreno, San Cristóbal",
             "body": ("If you get a lunch in town on Day 1 before boarding or "
                      "Day 8 after disembarking, this is the best casual "
                      "kitchen on the malecón. Fresh fish and a good "
                      "vegetarian option.")},
            {"name": "Cyrano bakery",
             "venue_key": "Cyrano bakery",
             "city": "Guayaquil · multiple locations",
             "body": ("Long-running local pastry chain — the almojábanas "
                      "(cheese buns) with morning coffee are the airport-side "
                      "answer to \"I need real food quickly.\"")},
        ]},
        {"label": "Street + markets", "entries": [
            {"name": "Calle de los Kioskos",
             "venue_key": "Calle de los Kioskos",
             "city": "Puerto Ayora, Santa Cruz",
             "body": ("A street of open-air seafood kiosks that come alive "
                      "after dark. Point at your fish or lobster, watch it go "
                      "on the grill, eat at plastic tables under strung "
                      "lights. Cash-first; small bills help.")},
            {"name": "Mercado Central (Guayaquil)",
             "city": "Guayaquil · downtown",
             "body": ("Encebollado at 8am, ceviche at noon — cheap, honest "
                      "cooking under fluorescent lights. Point-and-order the "
                      "menu of the day. Don't drink the water; do drink the naranjilla juice.")},
            {"name": "Mercado Central (Quito Old Town)",
             "city": "Quito Old Town",
             "body": ("Same principle as Guayaquil's version but with locro, "
                      "hornado (roasted pig), and morocho (a hot corn drink). "
                      "Two blocks north of the Plaza de la Independencia.")},
        ]},
    ],
}


# ============================================================================
# PHOTOGRAPHY — themed bonus for a wildlife-first trip
# ============================================================================

PHOTOGRAPHY = {
    "intro_lede": ("The Galápagos is one of the world's easiest wildlife-photo "
                   "destinations — the animals genuinely do not care that you "
                   "are there. That doesn't mean the pictures come easily. "
                   "The equatorial light is harsh, the pangas move, and the "
                   "best moments are usually happening on the far side of the "
                   "boat you can't turn around."),
    "opinion": ("You do not need a 600mm super-telephoto. The animals are "
                "close enough that a 100–400mm zoom (or an APS-C 70–300mm) "
                "does everything you need for wildlife, and a 24–70mm handles "
                "the rest. Bring two bodies if you have them so you're not "
                "changing lenses in salt spray."),
    "groups": [
        {
            "label": "Gear for a Galápagos cruise",
            "entries": [
                {"name": "One long zoom (100–400mm equivalent)",
                 "body": ("Enough reach for boobies, iguanas, sea lions, most "
                          "seabirds. A stabilised full-frame f/4.5–5.6 zoom "
                          "or an APS-C 70–300mm is the sweet spot. Faster "
                          "glass is nice but not necessary in equatorial light.")},
                {"name": "One wide-normal zoom (24–70mm equivalent)",
                 "body": ("For the landscapes — Sullivan Bay's lava, Genovesa's "
                          "cliffs, the pahoehoe wide shots. Also for the "
                          "\"there is a sea lion three feet from my camera\" "
                          "situation that will happen daily.")},
                {"name": "Small underwater camera (GoPro or waterproof compact)",
                 "body": ("The snorkeling is a huge part of the trip and no "
                          "phone case is truly reliable at depth. A GoPro or "
                          "Olympus TG-6 gets the sea-lion-loops-underwater shot.")},
                {"name": "Polarising filter for the wide zoom",
                 "body": ("Cuts glare on wet lava, deepens the sky over the "
                          "ocean, saves highlights in white-sand beach shots.")},
                {"name": "Fast card + spare battery",
                 "body": ("Wildlife bursts fill cards fast. A 64GB+ UHS-II "
                          "SD card and two spare batteries are the "
                          "conservative minimum for a week. Chargers on board.")},
                {"name": "Silica gel + a dry bag",
                 "body": ("Panga rides splash; humidity is high year-round. "
                          "A big Ziploc with a couple of silica packets goes "
                          "in the day pack.")},
            ],
        },
        {
            "label": "Timing + light",
            "entries": [
                {"name": "Golden hour is short",
                 "body": ("You are on the equator: the sun rises fast and sets "
                          "fast, and the truly warm light lasts about 30 "
                          "minutes at each end of the day. Be at your landing "
                          "for the wet-landing 06:30 start on every day you can.")},
                {"name": "Midday sun is brutal",
                 "body": ("11am–2pm is unshaded, contrast-crushing overhead "
                          "light. Not the best for portraits or landscapes. "
                          "Snorkel through the middle of the day; save "
                          "photography for the shoulders.")},
                {"name": "Frigatebird pouches and blue-foot feet",
                 "body": ("Both are colour-critical shots. Aim for underexposure "
                          "of 1/3 to 2/3 stop to keep the reds and cyans saturated. "
                          "A polariser on the frigatebird pouch cuts sheen.")},
                {"name": "The blowhole at Punta Suárez",
                 "body": ("Time the shot to the wave pulse — the spout goes "
                          "up in the ~15-second lull after each set. Frame "
                          "wide with an iguana in the foreground if you can.")},
            ],
        },
        {
            "label": "Ethics + park rules",
            "entries": [
                {"name": "Two-metre distance is required by rule",
                 "body": ("The park requires visitors to stay at least 2m from "
                          "wildlife. The animals will often close that gap "
                          "themselves; you cannot. Longer glass makes the rule "
                          "easier to obey without shrinking the shot.")},
                {"name": "No flash on nesting birds",
                 "body": ("Flash is prohibited on nesting seabirds and "
                          "vulnerable species like the short-eared owl. High "
                          "ISO on modern bodies handles the shady palo santo "
                          "forest just fine.")},
                {"name": "Drones are banned throughout the National Park",
                 "body": ("The Galápagos National Park does not permit drone "
                          "use for tourism. Leave it at home; you will lose "
                          "it at customs if you try to bring it into the park.")},
            ],
        },
    ],
}


# ============================================================================
# FUN FACTS + PRACTICAL TIPS
# ============================================================================

FUN_FACTS = {
    "intro_lede": ("Small pieces of Ecuador and Galápagos knowledge that don't "
                   "fit anywhere else — trivia in the left column, practical "
                   "tips (money, plugs, tipping, the phone situation) in the right."),
    "trivia_groups": [
        {"label": "Galápagos", "items": [
            "The islands are named for the Spanish word for tortoise — galápago — after the saddle-shaped shells the early Spanish sailors mistook for saddles.",
            "\"Encantadas\" (Enchanted Isles) is the older Spanish name — the currents made the islands seem to move, appearing and disappearing in fog.",
            "The archipelago has 13 major islands, 6 smaller islands, and 107 named rocks and islets.",
            "Isabela's Wolf Volcano is home to a population of pink land iguanas — a species only formally described in 2009.",
            "The Galápagos are one of the very few equatorial regions where you can see penguins, fur seals, and albatross in the same week.",
            "Ecuador's four national regions in miniature: coast, highlands, Amazon, and Galápagos. You'll cross the first two on this trip.",
            "Every Galápagos island's tortoise subspecies has (or had) a distinct shell shape — the ones with the tall arched saddleback shells evolved to reach up for Opuntia pads on the drier islands.",
        ]},
        {"label": "Ecuador (mainland)", "items": [
            "Ecuador uses the US dollar as its official currency (since 2000) — you can pay in USD notes everywhere. Coins are a mix of US coinage and Ecuadorian centavos of equal value.",
            "Quito's Old Town was the first UNESCO World Heritage Site, jointly declared with Kraków in 1978.",
            "The country sits astride the equator (mitad del mundo = middle of the world); the actual equator line runs a few hundred metres north of the famous 1979 monument outside Quito.",
            "Bananas are Ecuador's largest export by volume — over 30% of the world's traded bananas come from here.",
            "The country has about 1,600 bird species — roughly twice as many as all of North America, in an area smaller than Colorado.",
        ]},
    ],
    "practical_tips_groups": [
        {"label": "Money", "items": [
            "Ecuador uses the US dollar — no currency exchange needed for US travellers.",
            "ATMs on Santa Cruz and San Cristóbal work but occasionally run dry; withdraw $200–300 on the mainland to be safe.",
            "Credit cards work at the ship, cruise operators, and larger hotels/restaurants. Small kiosks and taxis: cash only.",
            "Cruise tips: $15–25 per guest per day is standard on Silversea and comparable operators. Envelopes provided at the end of the trip.",
        ]},
        {"label": "Plugs, phones, water", "items": [
            "Plugs are Type A/B (US-style, two flat blades / three-prong grounded) at 110V, 60Hz. No adapter needed for US travellers.",
            "Phones: Claro and Movistar are the dominant local carriers. US carriers with international roaming work in port towns. Cruise WiFi is spotty and expensive; treat the week as a digital detox.",
            "Do not drink the tap water anywhere in Ecuador — mainland or islands. Bottled water is universal at restaurants and free on board.",
            "The ship provides reusable water bottles you refill from onboard filtered water. Bring your own if you're picky.",
        ]},
        {"label": "Health + safety", "items": [
            "No yellow-fever vaccine is required for Galápagos-only entry from a low-risk country. If you're routing through the Amazon or Coca, it becomes advisable — check CDC before travel.",
            "Motion sickness: the northern crossing to Genovesa (Day 1 overnight) and the west-side channels (Day 4) are the most likely nights. Scopolamine patches or bonine work; take before you feel it.",
            "Sunburn is the single most common visitor injury. The equator plus a highly reflective sea plus low humidity is a fast burn — reapply every two hours on landing days.",
            "Emergency number in Ecuador: 911 (works nationwide since 2012).",
        ]},
        {"label": "Language + etiquette", "items": [
            "Spanish is universal; Quechua is common in the highlands (you won't need it). English is spoken at the ship and hotels, spotty elsewhere.",
            "Ecuadorian Spanish is spoken clearly, less clipped than Peninsular or Argentinian — a good country to practise if you're learning.",
            "Tipping restaurants: 10% is often included as \"servicio\" on the bill; if not, 10% is customary. Taxis: round up.",
            "Address strangers as usted (formal) rather than tú (informal) unless invited to switch — Ecuador leans formal.",
        ]},
    ],
}


# ============================================================================
# BIBLIOGRAPHY + GO-DEEPER
# ============================================================================

GO_DEEPER: Dict[str, List[Dict[str, str]]] = {
    "day_by_day": [
        {"kind": "Book", "title": "The Voyage of the Beagle",
         "url": "https://www.gutenberg.org/ebooks/944",
         "annotation": "Darwin's own trip log, 1839. Chapters 17–18 cover the Galápagos week."},
        {"kind": "Podcast", "title": "In Our Time — Galápagos",
         "url": "https://www.bbc.co.uk/programmes/b06vpxbp",
         "annotation": "Melvyn Bragg's usual 45-minute deep dive with three university biologists."},
        {"kind": "Film", "title": "Galápagos (BBC / IMAX, 1999)",
         "url": "https://www.bbc.co.uk/programmes/b006mgxg",
         "annotation": "The classic Attenborough treatment, still holds up on the wildlife side."},
        {"kind": "Local voice", "title": "Charles Darwin Foundation news",
         "url": "https://www.darwinfoundation.org/en/",
         "annotation": "The Foundation runs the CDRS in Puerto Ayora and posts current research news."},
    ],
    "field_guide": [
        {"kind": "Book", "title": "A Field Guide to the Birds of the Galápagos",
         "url": "https://www.amazon.com/Field-Guide-Birds-Galapagos/dp/000219898X",
         "annotation": "Michael H. Jackson's compact field guide — the standard on-ship reference for a decade."},
        {"kind": "Book", "title": "Galápagos: A Natural History",
         "url": "https://www.press.uchicago.edu/ucp/books/book/chicago/G/bo3628586.html",
         "annotation": "John Kricher (2006). The best single-volume overview of the archipelago's ecology."},
        {"kind": "Podcast", "title": "The Naturalist's Notebook",
         "url": "https://open.spotify.com/show/6P0YCr9kYmYrTHtV1x2QYw",
         "annotation": "Occasional Galápagos episodes; the biologist hosts do straightforward taxonomic explainers."},
    ],
    "history": [
        {"kind": "Book", "title": "The Galápagos: A Natural History (Kricher)",
         "url": "https://www.press.uchicago.edu/ucp/books/book/chicago/G/bo3628586.html",
         "annotation": "Chapters on hotspot geology and the whaling era do the heavy lifting."},
        {"kind": "Book", "title": "Lonesome George: The Life and Loves of a Conservation Icon",
         "url": "https://www.macmillan.com/books/9780230736177",
         "annotation": "Henry Nicholls (2006). The best single-figure history through George's story."},
        {"kind": "Film", "title": "Galápagos: The Islands That Changed the World (BBC, 2006)",
         "url": "https://www.bbc.co.uk/programmes/b006wp6b",
         "annotation": "A 3-part BBC series stitching geology, evolution, and human history — better than the older IMAX."},
    ],
    "food": [
        {"kind": "Book", "title": "The Ecuadorian Kitchen",
         "url": "https://www.amazon.com/Ecuadorian-Kitchen/dp/1938086376",
         "annotation": "Christian Bravo's regional cookbook — a workable in-country reference."},
        {"kind": "Podcast", "title": "The Splendid Table — Andean episodes",
         "url": "https://www.splendidtable.org/",
         "annotation": "Occasional Ecuadorian episodes when new Andean cookbooks come out."},
    ],
}

BIBLIOGRAPHY: List[Dict[str, Any]] = [
    {
        "group": "On the Galápagos as a place",
        "entries": [
            {"title": "Galápagos: A Natural History",
             "author": "John Kricher",
             "year": "2006",
             "url": "https://www.press.uchicago.edu/ucp/books/book/chicago/G/bo3628586.html",
             "annotation": "The compact standard reference — geology, evolution, ecology, human history in one volume. Read chapter 1 before the trip."},
            {"title": "Evolution's Workshop: God and Science on the Galápagos Islands",
             "author": "Edward J. Larson",
             "year": "2001",
             "url": "https://www.basicbooks.com/titles/edward-j-larson/evolutions-workshop/9780465018970/",
             "annotation": "The century-and-a-half of natural-history science that followed Darwin — expeditions, museums, and the modern institutional story."},
            {"title": "Lonesome George: The Life and Loves of a Conservation Icon",
             "author": "Henry Nicholls",
             "year": "2006",
             "url": "https://www.macmillan.com/books/9780230736177",
             "annotation": "A biography of the last Pinta tortoise that doubles as a history of Galápagos conservation."},
            {"title": "The Beak of the Finch",
             "author": "Jonathan Weiner",
             "year": "1994",
             "url": "https://www.penguinrandomhouse.com/books/167651/the-beak-of-the-finch-by-jonathan-weiner/",
             "annotation": "The Pulitzer-winning account of the Grants' 40-year finch study on Daphne Major — evolution watched in real time."},
        ],
    },
    {
        "group": "On Darwin and the Beagle",
        "entries": [
            {"title": "The Voyage of the Beagle",
             "author": "Charles Darwin",
             "year": "1839",
             "url": "https://www.gutenberg.org/ebooks/944",
             "annotation": "Free on Project Gutenberg. The Galápagos chapters are surprisingly compact — read on the flight down."},
            {"title": "Darwin's Ghosts: The Secret History of Evolution",
             "author": "Rebecca Stott",
             "year": "2012",
             "url": "https://www.spiegelandgrau.com/book/darwins-ghosts-the-secret-history-of-evolution-by-rebecca-stott/",
             "annotation": "The pre-Darwinians who worked toward the same idea for two millennia."},
        ],
    },
    {
        "group": "On the wildlife",
        "entries": [
            {"title": "A Field Guide to the Birds of the Galápagos",
             "author": "Michael H. Jackson",
             "year": "2001",
             "url": "https://www.amazon.com/Field-Guide-Birds-Galapagos/dp/000219898X",
             "annotation": "Compact enough for the day pack. What the naturalists on board will be teaching from."},
            {"title": "The Galápagos: Exploring Darwin's Tapestry",
             "author": "John Hess",
             "year": "2009",
             "url": "https://www.upress.pitt.edu/books/978-0-8262-1858-3",
             "annotation": "A photography-heavy natural history — good coffee-table pre-read to prime what you're looking for."},
        ],
    },
    {
        "group": "On Ecuador (mainland)",
        "entries": [
            {"title": "The Panama Hat Trail",
             "author": "Tom Miller",
             "year": "1986",
             "url": "https://www.amazon.com/Panama-Hat-Trail-Tom-Miller/dp/0873514882",
             "annotation": "A classic travel book that begins as a story about hats and becomes a portrait of coastal Ecuador. Dated but still readable."},
            {"title": "Ecuador: Insight Guides",
             "author": "Insight Guides",
             "year": "current edition",
             "url": "https://www.insightguides.com/destinations/south-america/ecuador",
             "annotation": "The most current practical guidebook — worth a look for the mainland brackets of the trip."},
        ],
    },
]


# ============================================================================
# SECTION EMITTERS
# ============================================================================

def emit_captains_notes() -> Tuple[Tuple[str, str], str]:
    body_text = "Captain's notes"
    out = [f'<p class="lede">Three honest flags to read before you unpack — the '
           'guide behind these comes from a naturalist\'s reading of your exact dates.</p>']
    out.append('<div class="deep">')
    for note in CAPTAINS_NOTES:
        klass = "data-check" if note["kind"] == "warn" else "opinion"
        out.append(f'  <div class="{klass}">')
        out.append(f'    <div class="label">{esc(note["label"])}</div>')
        out.append(f'    <p>{esc(note["body"])}</p>')
        body_text += " " + note["body"]
        out.append(f'  </div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="captains-notes", label="Captain's notes", kind="atmospheric",
        body_html="".join(out),
        slug_label="briefing",
    )
    return ("captains-notes", "Captain's notes"), section_html


def emit_day_by_day(venue_coords: Dict[str, Tuple[float, float]]) -> Tuple[Tuple[str, str], str]:
    intro_body = ("Eleven days from MSP door to MSP door — two travel-buffer days on "
                  "each end and eight days at sea in the archipelago. The intros "
                  "set each day's frame; the cards run in time order and carry "
                  "the practical load. Buffer-day cards are placeholders — flight "
                  "and hotel details are not yet in the app.")
    body_for_rt = intro_body
    out = [f'<p class="lede">{intro_body}</p>']
    out.append('<div class="deep">')
    for i, day in enumerate(DAY_BY_DAY, start=1):
        d = day["date"]
        date_label = d.strftime('%a %b %-d')
        out.append('<div class="daymark">')
        out.append(f'  <div class="daynum">Day {i:02d} · {esc(date_label)}</div>')
        out.append(f'  <h3 class="dayname">{esc(day["city"])}</h3>')
        out.append(f'  <div class="daymeta">{day["meta"]}</div>')
        out.append(f'  <p class="dayintro">{esc(day["intro"])}</p>')
        body_for_rt += " " + day["intro"]
        if day.get("intro_deep"):
            out.append(f'  <p class="dayintro-deep">{esc(day["intro_deep"])}</p>')
            body_for_rt += " " + day["intro_deep"]
        for card in day["cards"]:
            time_label = esc(card["time"])
            cat = category_color(card["category"])
            name = card["name"]
            venue_key = card.get("venue_key")
            if venue_key:
                city = day["city"].split("·")[0].split("→")[0].strip()
                link_html = emit_practical_link(venue_key, city, name)
            else:
                link_html = esc(name)
            out.append('    <div class="site-card">')
            out.append('      <div class="site-card-head">')
            out.append(f'        <span class="time-badge {cat}">{time_label}</span>')
            out.append(f'        <h5>{link_html}</h5>')
            out.append('      </div>')
            out.append(f'      <p>{esc(card["body"])}</p>')
            body_for_rt += " " + card["body"]
            if card.get("notes"):
                out.append(f'      <div class="opnote">{esc(card["notes"])}</div>')
                body_for_rt += " " + card["notes"]
            tag_parts = []
            if card.get("travelpill"):
                tag_parts.append(f'<span class="travelpill">{esc(card["travelpill"])}</span>')
            if tag_parts:
                out.append(f'      <div class="tags">{" ".join(tag_parts)}</div>')
            out.append('    </div>')
        out.append('</div>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="days", label="Day by day", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("day_by_day", [])),
        slug_label="timeline",
    )
    return ("days", "Day by day"), section_html


def emit_field_guide() -> Tuple[Tuple[str, str], str]:
    fg = FIELD_GUIDE
    body_text = fg["intro_lede"]
    out = [f'<p class="lede">{esc(fg["intro_lede"])}</p>']
    out.append('<div class="deep">')
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
            out.append(f'  <article class="fg-card" data-tags="{esc(tags_str)}">')
            out.append(f'    <h5>{esc(name)}</h5>')
            if entry.get("latin") and entry["latin"] != "—":
                out.append(f'    <div class="latin">{esc(entry["latin"])}</div>')
            out.append(f'    <div class="likely">{esc(entry["likelihood"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += " " + entry["body"]
            out.append('    <div class="fg-tags">')
            for tag in entry["tags"]:
                out.append(f'      <span class="fg-tag">{esc(tag)}</span>')
            out.append('    </div>')
            out.append('  </article>')
        out.append('</div>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="field-guide", label="Field guide", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("field_guide", [])),
        slug_label="species",
    )
    return ("field-guide", "Field guide"), section_html


def emit_weather() -> Tuple[Tuple[str, str], str]:
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
    out.append('<div class="deep">')
    out.append(f'  <p>{esc(w["season_notes"])}</p>')
    out.append('  <h4>Packing implications</h4>')
    out.append('  <ul>')
    for item in w["packing_implications"]:
        out.append(f'    <li>{esc(item)}</li>')
        body_text += " " + item
    out.append('  </ul>')
    out.append('</div>')
    out.append('<p class="live-data">Season data: composite from Galápagos National Park meteorological records + Cornell Lab / Charles Darwin Foundation phenology notes.</p>')
    section_html = emit_section_wrapper(
        slug="weather", label="Weather", kind="practical",
        body_html="".join(out),
        slug_label="climate",
    )
    return ("weather", "Weather"), section_html


def emit_history() -> Tuple[Tuple[str, str], str]:
    h = HISTORY
    body_text = h["intro_lede"]
    out = [f'<p class="lede">{esc(h["intro_lede"])}</p>']
    out.append('<div class="deep">')
    for v in h["vignettes"]:
        out.append('  <article class="history-vignette">')
        out.append(f'    <h4>{esc(v["title"])}</h4>')
        out.append(f'    <p class="lede">{esc(v["lede"])}</p>')
        body_text += " " + v["lede"]
        out.append(f'    <p>{esc(v["deep"])}</p>')
        body_text += " " + v["deep"]
        out.append(f'    <div class="consequence">Today: {esc(v["consequence"])}</div>')
        body_text += " " + v["consequence"]
        out.append('  </article>')
    out.append('  <h4>Phrase table (Spanish)</h4>')
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


def emit_things_to_do() -> Tuple[Tuple[str, str], str]:
    ttd = THINGS_TO_DO
    body_text = ttd["intro_lede"]
    out = [f'<p class="lede">{esc(ttd["intro_lede"])}</p>']
    out.append('<div class="deep">')
    out.append('<p style="font-size: 0.88em; color: var(--ink-soft); font-style: italic; margin-bottom: 24px;">'
               'Walking-distance chips are omitted — this trip has no in-app hotel bookings yet to anchor '
               'distances against. Read the neighborhood and judge for yourself.</p>')
    for group in ttd["groups"]:
        out.append('<div class="ttd-group">')
        out.append(f'  <h4>{esc(group["label"])}</h4>')
        if group.get("opinion"):
            out.append(f'  <p class="opinion">{esc(group["opinion"])}</p>')
            body_text += " " + group["opinion"]
        for entry in group["entries"]:
            venue_key = entry.get("venue_key")
            if venue_key:
                group_city = group["label"].split("·")[0].strip()
                link = emit_practical_link(venue_key, group_city, entry["name"])
            else:
                link = esc(entry["name"])
            out.append('  <div class="ttd-entry">')
            out.append(f'    <h5>{link}</h5>')
            out.append(f'    <div class="neighborhood">{esc(entry["neighborhood"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += " " + entry["body"]
            out.append('  </div>')
        out.append('</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="things-to-do", label="Things to do", kind="atmospheric",
        body_html="".join(out),
        slug_label="off-itinerary",
    )
    return ("things-to-do", "Things to do"), section_html


def emit_food() -> Tuple[Tuple[str, str], str]:
    fd = FOOD
    body_text = fd["intro_lede"]
    out = [f'<p class="lede">{esc(fd["intro_lede"])}</p>']
    out.append('<div class="deep">')
    out.append('<h4>Things to try</h4>')
    out.append('<div class="food-grid">')
    for item in fd["things_to_try"]:
        out.append('  <div class="food-card">')
        out.append(f'    <h5>{esc(item["name"])}</h5>')
        if item.get("local"):
            out.append(f'    <div class="local">{esc(item["local"])}</div>')
        out.append(f'    <div class="region">{esc(item["region"])}</div>')
        out.append(f'    <p>{esc(item["body"])}</p>')
        body_text += " " + item["body"]
        if item.get("tag"):
            out.append(f'    <span class="food-tag">{esc(item["tag"])}</span>')
        out.append('  </div>')
    out.append('</div>')
    if fd.get("opinion"):
        out.append(f'<p class="opinion">{esc(fd["opinion"])}</p>')
        body_text += " " + fd["opinion"]
    out.append('<h4>Where to eat</h4>')
    for tier in fd["where_to_eat"]:
        out.append('<div class="tier-block">')
        out.append(f'  <h4>{esc(tier["label"])}</h4>')
        for entry in tier["entries"]:
            venue_key = entry.get("venue_key")
            if venue_key:
                link = emit_practical_link(venue_key, entry["city"], entry["name"])
            else:
                link = esc(entry["name"])
            out.append('  <div class="tier-entry">')
            out.append(f'    <h5>{link}</h5>')
            out.append(f'    <div class="city">{esc(entry["city"])}</div>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += " " + entry["body"]
            out.append('  </div>')
        out.append('</div>')
    out.append('</div>')
    body_html = "".join(out)
    section_html = emit_section_wrapper(
        slug="food", label="Food", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("food", [])),
        slug_label="meals",
    )
    return ("food", "Food"), section_html


def emit_photography() -> Tuple[Tuple[str, str], str]:
    p = PHOTOGRAPHY
    body_text = p["intro_lede"]
    out = [f'<p class="lede">{esc(p["intro_lede"])}</p>']
    out.append('<div class="deep">')
    if p.get("opinion"):
        out.append(f'<p class="opinion">{esc(p["opinion"])}</p>')
        body_text += " " + p["opinion"]
    for group in p["groups"]:
        out.append('<div class="ttd-group">')
        out.append(f'  <h4>{esc(group["label"])}</h4>')
        for entry in group["entries"]:
            out.append('  <div class="ttd-entry">')
            out.append(f'    <h5>{esc(entry["name"])}</h5>')
            out.append(f'    <p>{esc(entry["body"])}</p>')
            body_text += " " + entry["body"]
            out.append('  </div>')
        out.append('</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="photography", label="Photography", kind="atmospheric",
        body_html="".join(out),
        slug_label="camera",
    )
    return ("photography", "Photography"), section_html


def emit_fun_facts() -> Tuple[Tuple[str, str], str]:
    ff = FUN_FACTS
    body_text = ff["intro_lede"]
    out = [f'<p class="lede">{esc(ff["intro_lede"])}</p>']
    out.append('<div class="deep">')
    out.append('<div class="facts-layout">')
    # Left column: trivia
    out.append('<div>')
    out.append('<h4>Trivia</h4>')
    for grp in ff["trivia_groups"]:
        out.append('  <div class="fact-group">')
        out.append(f'    <h4 class="fg-loc">{esc(grp["label"])}</h4>')
        out.append('    <ul>')
        for item in grp["items"]:
            out.append(f'      <li>{esc(item)}</li>')
            body_text += " " + item
        out.append('    </ul>')
        out.append('  </div>')
    out.append('</div>')
    # Right column: practical tips
    out.append('<div>')
    out.append('<h4>Practical tips</h4>')
    for grp in ff["practical_tips_groups"]:
        out.append('  <div class="fact-group">')
        out.append(f'    <h4 class="fg-loc">{esc(grp["label"])}</h4>')
        out.append('    <ul>')
        for item in grp["items"]:
            out.append(f'      <li>{esc(item)}</li>')
            body_text += " " + item
        out.append('    </ul>')
        out.append('  </div>')
    out.append('</div>')
    out.append('</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="fun-facts", label="Fun facts & tips", kind="atmospheric",
        body_html="".join(out),
        slug_label="trivia",
    )
    return ("fun-facts", "Fun facts & tips"), section_html


def emit_life_list() -> Tuple[Tuple[str, str], str]:
    intro = ("A pre-trip mental priming list — species and moments to keep an eye "
             "out for. Not a checklist to complete; a set of hooks that make the "
             "week easier to remember.")
    out = [f'<p class="lede">{esc(intro)}</p>']
    out.append('<div class="deep">')
    out.append('<div class="fg-grid" style="grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));">')
    for item in LIFE_LIST:
        out.append(f'  <div class="fg-card"><h5>☐ {esc(item)}</h5></div>')
    out.append('</div>')
    out.append('</div>')
    section_html = emit_section_wrapper(
        slug="life-list", label="Week's life list", kind="atmospheric",
        body_html="".join(out),
        slug_label="checklist",
    )
    return ("life-list", "Week's life list"), section_html


def emit_sources() -> Tuple[Tuple[str, str], str]:
    intro = "Books, films, and organisations whose work informed this guide."
    out = [f'<p class="lede">{esc(intro)}</p>']
    for grp in BIBLIOGRAPHY:
        out.append('<div class="biblio-group">')
        out.append(f'  <h4>{esc(grp["group"])}</h4>')
        out.append('  <ul>')
        for e in grp["entries"]:
            link = f'<a class="practical-link" href="{esc(e["url"])}" rel="noopener" target="_blank"><b>{esc(e["title"])}</b></a>'
            ay = f'<span class="ay">— {esc(e.get("author", ""))}'
            if e.get("year"):
                ay += f' <i>({esc(e["year"])})</i>'
            ay += '.</span>'
            out.append(f'    <li>{link}{ay} {esc(e["annotation"])}</li>')
        out.append('  </ul>')
        out.append('</div>')
    section_html = emit_section_wrapper(
        slug="sources", label="Sources & further reading", kind="practical",
        body_html="".join(out),
        slug_label="sources",
    )
    return ("sources", "Sources & further reading"), section_html


# ============================================================================
# COMPOSE
# ============================================================================

def compose(venue_coords: Dict[str, Tuple[float, float]]) -> str:
    sections = [
        emit_captains_notes(),
        emit_day_by_day(venue_coords),
        emit_field_guide(),
        emit_weather(),
        emit_history(),
        emit_things_to_do(),
        emit_food(),
        emit_photography(),
        emit_fun_facts(),
        emit_life_list(),
        emit_sources(),
    ]
    toc_slugs = [(slug, label) for (slug, label), _html in sections]
    sections_html = "".join(html for _s, html in sections)

    body = f"""
<a class="skip-link" href="#main">Skip to content</a>
<div id="vp-progress"></div>

<div class="topbar">
  <div class="crumb">Trip guide<span class="crumb-rest"> · <b>{esc(TRIP_META['title'])}</b> · San Cristóbal round-trip</span></div>
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

    fonts_url = ("https://fonts.googleapis.com/css2?"
                 "family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&"
                 "family=Spectral:ital,wght@0,400;0,500;0,600;1,400;1,500&"
                 "family=Space+Mono:wght@400;700&display=swap")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(TRIP_META['title'])} · Galápagos · Mar 27 → Apr 3 2027</title>
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

def main() -> None:
    print("=" * 70)
    print("Trip 3 Galápagos SB '27 — Souvenir-grade compose")
    print("=" * 70)

    print("\n[1/3] Geocoding venues...")
    venue_coords, venue_relevance = geocode_all_venues()
    print(f"  Got coords for {len(venue_coords)} of {len(NAMED_VENUES)} venues")

    print("\n[2/3] Composing HTML...")
    with app.app_context():
        html = compose(venue_coords)
    print(f"  HTML composed: {len(html):,} chars")

    print("\n[3/3] Saving via save_guide...")
    with app.app_context():
        path = guide_builder.save_guide(TRIP_ID, html)
    print(f"  Saved: {path}")

    # Quick markup audit
    print("\n--- Markup audit ---")
    audit = {
        "practical-link":  html.count('class="practical-link"'),
        "walkchip":        html.count('class="walkchip"'),
        "go-deeper cards": html.count('class="gd-card"'),
        "field-guide entries": html.count('class="fg-card"'),
        "history vignettes":   html.count('class="history-vignette"'),
        "life-list items":     html.count('☐ '),
        "sources note block":  html.count('class="sources-note"'),
        "mode-toggle buttons": html.count('mode-toggle') and html.count('data-mode="'),
    }
    for k, v in audit.items():
        print(f"  {k:<22}: {v}")

    # Share URL
    with app.app_context():
        from models import Trip
        trip = db.session.get(Trip, TRIP_ID)
        token = trip.guide_share_token if trip else None
    print(f"\n  Gated URL:  http://localhost:5002/trips/{TRIP_ID}/guide")
    if token:
        print(f"  Share URL:  http://localhost:5002/guides/share/{token}")
    else:
        print("  (No share token yet — mint at end of trip-guide skill flow.)")


if __name__ == "__main__":
    main()
