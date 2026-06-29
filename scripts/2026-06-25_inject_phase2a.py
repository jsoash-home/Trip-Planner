"""One-shot validation script: inject Phase 2a wrappers into trip 4's guide.

Reads data/guides/4.html, adds CSS for practical-link + walkchip, wraps
named venue titles in <a class="practical-link">, and emits walkchip
spans on day_by_day site cards where hotel_for_night + venue coords
resolve. Saves via guide_builder.save_guide (atomic + .bak rotation).

Intentionally scoped to one trip — this is a Phase 2a editorial-spine
validation pass, not a reusable composer rewrite. Captures observations
for the Phase 2b plan seed.
"""

from __future__ import annotations

import os
import logging
import sys
from datetime import date

# Quiet noisy migration warnings; we don't care about them for this run.
logging.basicConfig(level=logging.INFO)
logging.getLogger("app").setLevel(logging.ERROR)

# Resolve project-root vacation.db (see SKILL.md Step 2).
os.environ.pop("DATABASE_URL", None)

# Make project root importable.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from app import app, db                                  # noqa: E402
from models import Booking                                # noqa: E402
from src import guide_builder                             # noqa: E402
from src.geocoding import geocode_with_cache              # noqa: E402
from src.place_links import practical_link, maps_url      # noqa: E402
from src.walking_distance import walking_chip             # noqa: E402
from src.trip_helpers import hotel_for_night              # noqa: E402

TRIP_ID = 4

# CSS to inject — Phase 2a practical-link + walkchip styling.
CSS_INJECT = """
/* Practical hyperlinks (Phase 2a) */
a.practical-link{
  color:var(--ink);
  text-decoration-color:var(--hairline);
  text-decoration-thickness:1px;
  text-underline-offset:2px;
  transition:color 120ms, text-decoration-color 120ms, text-decoration-thickness 120ms;
}
a.practical-link:hover, a.practical-link:focus-visible{
  color:var(--accent);
  text-decoration-color:var(--accent);
  text-decoration-thickness:2px;
}

/* Walking-distance chips (Phase 2a) */
.walkchip{
  display:inline-block;
  font-family:var(--font-mono);
  font-size:11px;
  letter-spacing:0.02em;
  color:var(--ink-soft);
  background:var(--surface);
  border:1px solid var(--hairline);
  padding:2px 8px;
  border-radius:10px;
}
@media print{
  a.practical-link{text-decoration:none;color:var(--ink)}
  .walkchip{display:none}
}
"""


# Venue catalog: name → (city, optional override coords).
# Coords here are used for walkchip math when the venue isn't already
# in the GeocodeCache. None = let the geocoder try.
EXTRA_VENUES = [
    ("The Pump House", "Rock Hill, SC"),
    ("Old Town Kitchen & Cocktails", "Rock Hill, SC"),
    ("Tattooed Brews", "Rock Hill, SC"),
    ("The Dixie Pig", "Rock Hill, SC"),
    ("Off The Tracks Brewing", "Rock Hill, SC"),
    ("Rock Hill Brewing Company", "Rock Hill, SC"),
    ("Dust Off Brewing", "Rock Hill, SC"),
    ("Middle James Brewing", "Rock Hill, SC"),
    ("Birdsong Brewing Company", "Charlotte, NC"),
    ("Resident Culture Brewing", "Charlotte, NC"),
    ("Knowledge Perk Coffee", "Rock Hill, SC"),
    ("Cracker Barrel", "Rock Hill, SC"),
    ("JV Rock Hill", "Rock Hill, SC"),
    ("Catawba Cultural Center", "Catawba, SC"),
    ("Friendship Nine marker", "Rock Hill, SC"),
    ("Mint Museum Uptown", "Charlotte, NC"),
    ("NASCAR Hall of Fame", "Charlotte, NC"),
    ("Discovery Place Science", "Charlotte, NC"),
    ("River Park Rock Hill", "Rock Hill, SC"),
    ("Bank of America Stadium", "Charlotte, NC"),
    ("Galleria Mall", "Rock Hill, SC"),
    ("Publix Galleria Plaza", "Rock Hill, SC"),
    ("Piedmont Medical Center", "Rock Hill, SC"),
    ("Adidas 3SSB", "Rock Hill, SC"),
]


def main() -> int:
    token = os.environ.get("MAPBOX_TOKEN", "").strip()
    if not token:
        print("MAPBOX_TOKEN missing — chip rendering will be skipped.")
        return 1

    with app.app_context():
        # 1. Fill missing venue coords via GeocodeCache.
        venue_coords: dict[str, tuple[float, float]] = {}
        for name, city in EXTRA_VENUES:
            r = geocode_with_cache(text=f"{name}, {city}", db_session=db.session, token=token)
            if r is not None:
                venue_coords[name] = (r.lat, r.lng)
        db.session.commit()

        # 2. Hotel anchor — from the Booking row's geocoded_lat/lng.
        bookings = Booking.query.filter_by(trip_id=TRIP_ID).all()
        hotel = next((b for b in bookings if b.type == "hotel"), None)
        assert hotel and hotel.geocoded_lat and hotel.geocoded_lng
        hotel_coords = (hotel.geocoded_lat, hotel.geocoded_lng)
        hotel_name = hotel.title

        # 3. Activity venue (3SSB Sports & Event Center) — from booking row too.
        sports_booking = next(
            (b for b in bookings if b.type == "activity" and b.geocoded_lat),
            None,
        )
        if sports_booking:
            venue_coords["Rock Hill Sports & Event Center"] = (
                sports_booking.geocoded_lat,
                sports_booking.geocoded_lng,
            )

        # 4. Load existing HTML.
        html = guide_builder.read_guide(TRIP_ID).decode("utf-8")
        original_len = len(html)

        # 5. Inject CSS just before the </style> close tag.
        marker = "/* Register split */"
        assert marker in html, "register-split CSS marker not found"
        html = html.replace(marker, CSS_INJECT.rstrip() + "\n\n" + marker, 1)

        # 6. Venue replacements: each (old_text, replacement_html, expected_count).
        # We construct old_text to be exact (no regex) — typically the full
        # `<h5>Name</h5>` or `<h4>Name</h4>` or `<b>Name</b>` etc.
        #
        # The substitutions wrap the venue NAME ONLY with practical_link(),
        # preserving the surrounding tags. Replacements are one-shot per
        # match — if a venue title appears in two places (e.g. day_by_day
        # h5 AND food where-to-eat <b>), we list both forms.

        def link(name: str, city: str = "Rock Hill, SC") -> str:
            return practical_link(name, city)

        # Day-by-day h5 site-card titles
        day_repls: list[tuple[str, str]] = [
            # Day 1
            ('<h5>Depart MSP on Delta DL → CLT</h5>',
             f'<h5>Depart MSP on Delta → {link("Charlotte Douglas International Airport", "Charlotte, NC")}</h5>'),
            ('<h5>Arrive Charlotte Douglas (CLT)</h5>',
             f'<h5>Arrive {link("Charlotte Douglas International Airport", "Charlotte, NC")} (CLT)</h5>'),
            ('<h5>Check in: Holiday Inn Rock Hill</h5>',
             f'<h5>Check in: {link("Holiday Inn Rock Hill")}</h5>'),
            # Day 2
            ('<h5>3SSB Girls Finals · Game 1</h5>',
             f'<h5>{link("Rock Hill Sports & Event Center")} · Game 1</h5>'),
            ('<h5>Lunch break — go to Main Street</h5>',
             '<h5>Lunch break — go to Main Street</h5>'),  # no link (generic)
            ('<h5>3SSB Girls Finals · Game 2 (likely)</h5>',
             f'<h5>{link("Rock Hill Sports & Event Center")} · Game 2 (likely)</h5>'),
            ('<h5>Dinner: The Pump House</h5>',
             f'<h5>Dinner: {link("The Pump House")}</h5>'),
            # Day 3
            ('<h5>Pool play games</h5>',
             f'<h5>Pool play games · {link("Rock Hill Sports & Event Center")}</h5>'),
            ('<h5>Lunch: Tattooed Brews or food court</h5>',
             f'<h5>Lunch: {link("Tattooed Brews")} or food court</h5>'),
            ('<h5>If she\'s eliminated: Glencairn Garden</h5>',
             f'<h5>If she\'s eliminated: {link("Glencairn Garden")}</h5>'),
            ('<h5>Dinner: The Dixie Pig (early!)</h5>',
             f'<h5>Dinner: {link("The Dixie Pig")} (early!)</h5>'),
            # Day 4
            ('<h5>Bracket game (round of 16 or quarterfinals)</h5>',
             f'<h5>Bracket game · {link("Rock Hill Sports & Event Center")}</h5>'),
            ('<h5>Free afternoon (between games or post-elimination)</h5>',
             f'<h5>Free afternoon · {link("Catawba River Trail")}</h5>'),
            ('<h5>Dinner: Off The Tracks Brewing</h5>',
             f'<h5>Dinner: {link("Off The Tracks Brewing")}</h5>'),
            # Day 5
            ('<h5>Bracket games — semifinals &amp; finals</h5>',
             f'<h5>{link("Rock Hill Sports & Event Center")} · semifinals &amp; finals</h5>'),
            ('<h5>Drive to CLT, fly home</h5>',
             f'<h5>Drive to {link("Charlotte Douglas International Airport", "Charlotte, NC")}, fly home</h5>'),
        ]

        # Things-to-do h4 venue cards
        things_repls: list[tuple[str, str]] = [
            ('<h4>Catawba Riverwalk Trail</h4>',
             f'<h4>{link("Catawba River Trail")}</h4>'),
            ('<h4>Glencairn Garden</h4>',
             f'<h4>{link("Glencairn Garden")}</h4>'),
            ('<h4>Old Town Rock Hill (Main Street)</h4>',
             f'<h4>{link("Old Town Rock Hill", "Rock Hill, SC")}</h4>'),
            ('<h4>Friendship Nine marker</h4>',
             f'<h4>{link("Friendship Nine marker")}</h4>'),
            ('<h4>River Park &amp; Rock Hill Outdoor Center</h4>',
             f'<h4>{link("River Park Rock Hill")}</h4>'),
            ('<h4>Catawba Cultural Center</h4>',
             f'<h4>{link("Catawba Cultural Center", "Catawba, SC")}</h4>'),
            ('<h4>U.S. National Whitewater Center</h4>',
             f'<h4>{link("U.S. National Whitewater Center", "Charlotte, NC")}</h4>'),
            ('<h4>Carowinds</h4>',
             f'<h4>{link("Carolina Place Mall", "Pineville, NC")}</h4>'.replace("Carolina Place Mall", "Carowinds")),
            ('<h4>NASCAR Hall of Fame</h4>',
             f'<h4>{link("NASCAR Hall of Fame", "Charlotte, NC")}</h4>'),
            ('<h4>Mint Museum Uptown</h4>',
             f'<h4>{link("Mint Museum Uptown", "Charlotte, NC")}</h4>'),
            ('<h4>Freedom Park</h4>',
             f'<h4>{link("Freedom Park", "Charlotte, NC")}</h4>'),
            ('<h4>Discovery Place Science</h4>',
             f'<h4>{link("Discovery Place Science", "Charlotte, NC")}</h4>'),
        ]

        # Food where-to-eat <b> names
        food_repls: list[tuple[str, str]] = [
            ('<b>The Pump House</b>',
             f'<b>{link("The Pump House")}</b>'),
            ('<b>Old Town Kitchen &amp; Cocktails</b>',
             f'<b>{link("Old Town Kitchen & Cocktails")}</b>'),
            ('<b>The Dixie Pig</b>',
             f'<b>{link("The Dixie Pig")}</b>'),
            ('<b>Tattooed Brews</b>',
             f'<b>{link("Tattooed Brews")}</b>'),
            ('<b>Off The Tracks Brewing</b>',
             f'<b>{link("Off The Tracks Brewing")}</b>'),
            ('<b>JV Rock Hill</b>',
             f'<b>{link("JV Rock Hill")}</b>'),
            ('<b>Knowledge Perk Coffee</b>',
             f'<b>{link("Knowledge Perk Coffee")}</b>'),
            ('<b>Cracker Barrel · Springsteen Rd</b>',
             f'<b>{link("Cracker Barrel")} · Springsteen Rd</b>'),
            ('<b>Galleria Mall food court</b>',
             f'<b>{link("Galleria Mall")} food court</b>'),
            ('<b>Publix · Galleria Plaza</b>',
             f'<b>{link("Publix Galleria Plaza")} · Galleria Plaza</b>'),
            ('<b>Sports &amp; Event Center food court</b>',
             f'<b>{link("Rock Hill Sports & Event Center")} food court</b>'),
        ]

        # Beer brewery h5 titles
        beer_repls: list[tuple[str, str]] = [
            ('<h5>Legal Remedy Brewing</h5>',
             f'<h5>{link("Legal Remedy Brewing")}</h5>'),
            ('<h5>Slow Play Brewing</h5>',
             f'<h5>{link("Slow Play Brewing")}</h5>'),
            ('<h5>Off The Tracks Brewing</h5>',
             f'<h5>{link("Off The Tracks Brewing")}</h5>'),
            ('<h5>Rock Hill Brewing Company</h5>',
             f'<h5>{link("Rock Hill Brewing Company")}</h5>'),
            ('<h5>Dust Off Brewing</h5>',
             f'<h5>{link("Dust Off Brewing")}</h5>'),
            ('<h5>Middle James Brewing</h5>',
             f'<h5>{link("Middle James Brewing")}</h5>'),
            ('<h5>NoDa Brewing Company</h5>',
             f'<h5>{link("NoDa Brewing", "Charlotte, NC")}</h5>'.replace("NoDa Brewing", "NoDa Brewing Company")),
            ('<h5>Wooden Robot Brewery</h5>',
             f'<h5>{link("Wooden Robot Brewery", "Charlotte, NC")}</h5>'),
            ('<h5>Olde Mecklenburg Brewery</h5>',
             f'<h5>{link("Olde Mecklenburg Brewery", "Charlotte, NC")}</h5>'),
            ('<h5>Birdsong Brewing Company</h5>',
             f'<h5>{link("Birdsong Brewing Company", "Charlotte, NC")}</h5>'),
            ('<h5>Resident Culture Brewing</h5>',
             f'<h5>{link("Resident Culture Brewing", "Charlotte, NC")}</h5>'),
        ]

        # Source bibliography <b> titles (Phase 2a — links to canonical URLs)
        sources_repls: list[tuple[str, str]] = [
            ('<b>Adidas 3SSB official schedule</b>',
             '<b><a class="practical-link" href="https://adidas3ssb.com" rel="noopener" target="_blank">Adidas 3SSB official schedule</a></b>'),
            ('<b>Rock Hill Sports &amp; Event Center facility page</b>',
             f'<b><a class="practical-link" href="{maps_url("Rock Hill Sports & Event Center", "Rock Hill, SC")}" rel="noopener" target="_blank">Rock Hill Sports &amp; Event Center facility page</a></b>'),
            ('<b>Visit York County</b>',
             '<b><a class="practical-link" href="https://www.visityorkcounty.com" rel="noopener" target="_blank">Visit York County</a></b>'),
            ('<b>Discover South Carolina · Rock Hill articles</b>',
             '<b><a class="practical-link" href="https://www.discoversouthcarolina.com" rel="noopener" target="_blank">Discover South Carolina · Rock Hill articles</a></b>'),
            ('<b>NOAA Climate Normals · Rock Hill, SC (1991–2020)</b>',
             '<b><a class="practical-link" href="https://www.ncei.noaa.gov/products/land-based-station/us-climate-normals" rel="noopener" target="_blank">NOAA Climate Normals · Rock Hill, SC (1991–2020)</a></b>'),
            ('<b>The Catawba Nation</b>',
             '<b><a class="practical-link" href="https://catawba.com" rel="noopener" target="_blank">The Catawba Nation</a></b>'),
            ('<b>Untappd</b>',
             '<b><a class="practical-link" href="https://untappd.com" rel="noopener" target="_blank">Untappd</a></b>'),
            ('<b>Charlotte\'s Got A Lot · NoDa Craft Beer Trail</b>',
             '<b><a class="practical-link" href="https://www.charlottesgotalot.com" rel="noopener" target="_blank">Charlotte\'s Got A Lot · NoDa Craft Beer Trail</a></b>'),
            ('<b>Rock Hill Insider · Complete list of breweries in Rock Hill, SC</b>',
             '<b><a class="practical-link" href="https://rockhillinsider.com" rel="noopener" target="_blank">Rock Hill Insider · Complete list of breweries in Rock Hill, SC</a></b>'),
        ]

        # Hotel-at-a-glance table — wrap the hotel address cell in a link.
        hotel_addr_repl = (
            '<td class="addr">503 Galleria Blvd<br>Rock Hill, SC 29730<br>'
            '<button class="copy-btn"',
            f'<td class="addr"><a class="practical-link" href="{maps_url(hotel_name, "Rock Hill, SC")}" '
            'rel="noopener" target="_blank">503 Galleria Blvd<br>Rock Hill, SC 29730</a><br>'
            '<button class="copy-btn"',
        )

        all_repls = (
            day_repls + things_repls + food_repls + beer_repls + sources_repls
            + [hotel_addr_repl]
        )

        hit, miss = 0, []
        for old, new in all_repls:
            if old in html:
                html = html.replace(old, new, 1)
                hit += 1
            else:
                miss.append(old[:60])
        print(f"venue/source replacements: {hit} hit, {len(miss)} missed")
        for m in miss:
            print(f"  MISS: {m!r}")

        # 7. Walking chips — emit on day_by_day site cards where coords + hotel night both resolve.
        # We add a chip into the .tags row of selected site cards. If the card
        # has no existing .tags row, we add one.
        #
        # Helper: build a chip + targeted insertion via a sentinel string.
        # We use the venue-coord lookup from Step 1.
        def chip(venue_name: str, day_d: date) -> str:
            v = venue_coords.get(venue_name)
            if v is None:
                return ""
            h = hotel_for_night(bookings, day_d)
            if h is None or h.geocoded_lat is None:
                return ""
            return walking_chip(v, (h.geocoded_lat, h.geocoded_lng), h.title)

        d2 = date(2026, 7, 24)
        d3 = date(2026, 7, 25)
        d4 = date(2026, 7, 26)

        # Walkchip injections — find the exact <p>...</p> ending block of each
        # site card and insert a <div class="tags"><span class="walkchip">...</span></div>
        # right after it. The card's existing closing </div> stays.
        chip_repls: list[tuple[str, str]] = []

        # Day 2 Game 1 (Sports & Event Center)
        c = chip("Rock Hill Sports & Event Center", d2)
        if c:
            chip_repls.append((
                '<div class="opnote">Bring a charged phone — score keepers post the bracket to the tournament app live as games end.</div>',
                f'<div class="opnote">Bring a charged phone — score keepers post the bracket to the tournament app live as games end.</div>\n      <div class="tags">{c}</div>',
            ))

        # Day 2 Pump House — has existing <div class="tags"><span class="tag cat">Riverwalk · 4 mi from hotel</span></div>
        c = chip("The Pump House", d2)
        if c:
            chip_repls.append((
                '<div class="tags"><span class="tag cat">Riverwalk · 4 mi from hotel</span></div>',
                f'<div class="tags"><span class="tag cat">Riverwalk · 4 mi from hotel</span> {c}</div>',
            ))

        # Day 2 Game 2 (Sports & Event Center) — same as Game 1 venue
        c = chip("Rock Hill Sports & Event Center", d2)
        if c:
            chip_repls.append((
                '<p>Pool play continues. Friday usually closes out two games per team before 7 pm.</p>',
                f'<p>Pool play continues. Friday usually closes out two games per team before 7 pm.</p>\n      <div class="tags">{c}</div>',
            ))

        # Day 3 Pool play (Sports & Event Center)
        c = chip("Rock Hill Sports & Event Center", d3)
        if c:
            chip_repls.append((
                '<p>Schedule is set by Friday night\'s results. Check the app or the printed sheet at the check-in table when you arrive.</p>',
                f'<p>Schedule is set by Friday night\'s results. Check the app or the printed sheet at the check-in table when you arrive.</p>\n      <div class="tags">{c}</div>',
            ))

        # Day 3 Glencairn — has existing tags
        c = chip("Glencairn Garden", d3)
        if c:
            chip_repls.append((
                '<div class="tags"><span class="tag cat">Downtown · 10 min from gym</span></div>',
                f'<div class="tags"><span class="tag cat">Downtown · 10 min from gym</span> {c}</div>',
            ))

        # Day 3 Dixie Pig
        c = chip("The Dixie Pig", d3)
        if c:
            chip_repls.append((
                '<p>The Carolina BBQ stop. The Dixie Pig on Cherry Road has been smoking pork and chicken in Rock Hill since the 1950s. They sell out — be there by 6:30 if you want the full menu. Mustard-based Carolina sauce is the local default; the hash and rice is a regional dish worth ordering at least once.</p>',
                f'<p>The Carolina BBQ stop. The Dixie Pig on Cherry Road has been smoking pork and chicken in Rock Hill since the 1950s. They sell out — be there by 6:30 if you want the full menu. Mustard-based Carolina sauce is the local default; the hash and rice is a regional dish worth ordering at least once.</p>\n      <div class="tags">{c}</div>',
            ))

        # Day 4 Bracket game (Sports)
        c = chip("Rock Hill Sports & Event Center", d4)
        if c:
            chip_repls.append((
                '<p>Confirm tip time the night before. Sunday games tend to spread across fewer courts to concentrate the recruiter audience.</p>',
                f'<p>Confirm tip time the night before. Sunday games tend to spread across fewer courts to concentrate the recruiter audience.</p>\n      <div class="tags">{c}</div>',
            ))

        # Day 4 Free afternoon (Riverwalk)
        c = chip("Catawba River Trail", d4)
        if c:
            chip_repls.append((
                '<div class="tags"><span class="tag cat">Riverwalk · 4 mi from gym</span></div>',
                f'<div class="tags"><span class="tag cat">Riverwalk · 4 mi from gym</span> {c}</div>',
            ))

        # Day 4 Off The Tracks dinner
        c = chip("Off The Tracks Brewing", d4)
        if c:
            chip_repls.append((
                '<p>If the team is still alive, dinner gets simpler — early, mild, and high-carb. Off The Tracks Brewing off Main Street has a big patio and the kitchen does BBQ nachos and brisket plates. If she\'s been eliminated, dinner is whatever celebration the team chooses; the Pump House rooftop bar is the photogenic version.</p>',
                f'<p>If the team is still alive, dinner gets simpler — early, mild, and high-carb. Off The Tracks Brewing off Main Street has a big patio and the kitchen does BBQ nachos and brisket plates. If she\'s been eliminated, dinner is whatever celebration the team chooses; the Pump House rooftop bar is the photogenic version.</p>\n      <div class="tags">{c}</div>',
            ))

        chip_hits = 0
        for old, new in chip_repls:
            if old in html:
                html = html.replace(old, new, 1)
                chip_hits += 1
            else:
                print(f"  CHIP MISS: {old[:80]!r}")
        print(f"walkchip insertions: {chip_hits}")

        # 8. Save via helper (atomic + .bak rotation + last_generated_at bump).
        path = guide_builder.save_guide(TRIP_ID, html)
        print(f"saved: {path}")
        print(f"size: {original_len} → {len(html)} chars (+{len(html) - original_len})")
        return 0


if __name__ == "__main__":
    sys.exit(main())
