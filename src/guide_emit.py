"""guide_emit — shared HTML/CSS emit helpers for trip-guide composers.

Pure rendering. No DB I/O, no filesystem, no module-level mutable state.
Each function takes the data it needs as args and returns HTML/CSS strings.
Per-trip composers (compose/trip_<id>.py) import from here.

Input shapes (documented, not schema-enforced):

    # palette dict:
    #   {"name": str, "colors": {bg,surface,ink,ink_soft,ink_display,accent,accent_2,
    #    muted,hairline,warning: hex}, "fonts": {display,body,mono: str}}
    # eras list:
    #   [{"slug": str, "label": str, "hex": hex, "year_range": str}, ...]
    # hotel dict (emit_walking_chip):
    #   {"lat": float, "lng": float, "title": str, ...}
    # go-deeper card dict (emit_go_deeper):
    #   {"kind": "Book"|"Podcast"|"Film"|"Local voice", "title": str,
    #    "url": str, "annotation": str}
    # trip_meta dict (emit_hero):
    #   {"title", "subtitle", "narrator_dek", "start_date", "end_date",
    #    "countries", "route_svg" (optional str), ...}
"""

import html as html_mod
import logging
import math
import re
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.place_links import maps_url
from src.walking_distance import walking_chip

logger = logging.getLogger(__name__)


# ── Tier 1: text primitives ────────────────────────────────────────────────

def esc(s: str) -> str:
    """HTML-escape a string with quote-mode on (attribute-safe)."""
    return html_mod.escape(s, quote=True)


def reading_time(text: str) -> int:
    """Words / 220 wpm, ceil. Strip HTML tags first. Floor at 1 minute."""
    plain = re.sub(r'<[^>]+>', '', text)
    words = len(plain.split())
    return max(1, math.ceil(words / 220))


def permalink(slug: str, label: str) -> str:
    """Return the `<a class="permalink">¶</a>` anchor for a section heading."""
    return (f'<a class="permalink" href="#{slug}" '
            f'aria-label="Permalink to {esc(label)}">¶</a>')


def reading_time_chip(text: str, slug_label: str) -> str:
    """Return the reading-time chip HTML for a body of text."""
    m = reading_time(text)
    return f'<span class="reading-time">{m} min · {esc(slug_label)}</span>'


def emit_h2(slug: str, label: str, slug_label: str, body_text: str) -> str:
    """Emit an `<h2 id="slug">` with a reading-time chip and permalink."""
    rt = reading_time_chip(body_text, slug_label)
    pl = permalink(slug, label)
    return f'<h2 id="{slug}">{esc(label)}{rt}{pl}</h2>'


def category_color(cat: str) -> str:
    """Map itinerary category to a tag color CSS class."""
    return {
        "transit": "transit",
        "meal": "meal",
        "sightseeing": "sight",
        "other": "other",
    }.get(cat, "other")


# ── Tier 1: link + chip helpers ────────────────────────────────────────────

def emit_practical_link(name: str, city: str, full_text: Optional[str] = None) -> str:
    """Wrap a venue name in `<a class="practical-link">` linking to Google Maps."""
    text = full_text or name
    url = maps_url(name, city)
    return (f'<a class="practical-link" href="{esc(url)}" '
            f'rel="noopener" target="_blank">{esc(text)}</a>')


def emit_walking_chip(
    venue_key: Optional[str],
    hotel: Optional[Dict[str, Any]],
    venue_coords: Dict[str, Tuple[float, float]],
    venue_relevance: Dict[str, Optional[float]],
) -> str:
    """Emit a walkchip if both venue and hotel resolve; else ''.

    Skips when venue_relevance is known and below the default 0.7 threshold —
    those are usually Mapbox city-centroid fallbacks where the distance would
    be misleading. Thin adapter that unpacks the composer-facing shape
    (venue_key + hotel dict + coord dicts) into the positional
    `walking_distance.walking_chip(...)` call.
    """
    if not venue_key or not hotel or not hotel.get("lat"):
        return ""
    vc = venue_coords.get(venue_key.lower())
    if not vc:
        return ""
    return walking_chip(
        venue_coords=vc,
        hotel_coords=(hotel["lat"], hotel["lng"]),
        hotel_name=hotel["title"],
        venue_confidence=venue_relevance.get(venue_key.lower()),
    )


# ── Tier 2: palette-aware scaffolding ──────────────────────────────────────

def emit_css(palette: Dict[str, Any], eras: List[Dict[str, str]]) -> str:
    """Return the full CSS block for the guide, parameterised by palette + eras."""
    colors = palette["colors"]
    fonts = palette["fonts"]
    era_css = "\n".join(f'  --era-{e["slug"]}: {e["hex"]};' for e in eras)
    era_class_css = "\n".join(
        f'.era-{e["slug"]} {{ --era: var(--era-{e["slug"]}); }}'
        for e in eras
    )
    return f"""
:root {{
  --bg: {colors["bg"]};
  --surface: {colors["surface"]};
  --ink: {colors["ink"]};
  --ink-soft: {colors["ink_soft"]};
  --ink-display: {colors["ink_display"]};
  --accent: {colors["accent"]};
  --accent-2: {colors["accent_2"]};
  --muted: {colors["muted"]};
  --hairline: {colors["hairline"]};
  --warning: {colors["warning"]};
{era_css}
  --font-display: '{fonts["display"]}', Georgia, serif;
  --font-body:    '{fonts["body"]}', -apple-system, BlinkMacSystemFont, sans-serif;
  --font-mono:    '{fonts["mono"]}', SFMono-Regular, Consolas, monospace;
  --font-sans:    var(--font-body);
  --font-serif:   var(--font-display);
}}

* {{ box-sizing: border-box; }}
html {{ scroll-behavior: smooth; }}
body {{
  margin: 0; padding: 0;
  background: var(--bg); color: var(--ink);
  font-family: var(--font-body);
  font-size: 17px; line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
img, svg {{ max-width: 100%; }}
a {{ color: var(--accent); }}

/* Skip link */
.skip-link {{
  position: absolute; left: -9999px; top: 0;
  background: var(--accent); color: var(--bg);
  padding: 8px 12px; z-index: 999; text-decoration: none;
  font-family: var(--font-mono); font-size: 0.85em;
}}
.skip-link:focus {{ left: 8px; top: 8px; }}

/* Focus styles */
*:focus-visible {{
  outline: 2.5px solid var(--accent);
  outline-offset: 3px;
}}

/* Top progress bar */
#vp-progress {{
  position: fixed; top: 0; left: 0; height: 3px; width: 0%;
  background: var(--accent); z-index: 100;
  transition: width 80ms linear;
}}

/* Top sticky nav bar */
.topbar {{
  position: sticky; top: 0; z-index: 50;
  background: rgba(14, 19, 26, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--hairline);
  padding: 14px 24px;
  display: flex; align-items: center; gap: 24px;
  font-family: var(--font-mono); font-size: 0.78em;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--ink-soft);
}}
.topbar .crumb {{ color: var(--ink-soft); }}
.topbar .crumb b {{ color: var(--ink); }}
.topbar .spacer {{ flex: 1; }}

.mode-toggle {{
  display: inline-flex; gap: 0;
  border: 1px solid var(--hairline); border-radius: 6px;
  overflow: hidden;
}}
.mode-toggle button {{
  background: transparent; color: var(--ink-soft);
  border: 0; padding: 6px 12px;
  font-family: var(--font-mono); font-size: 0.85em;
  text-transform: uppercase; letter-spacing: 0.05em;
  cursor: pointer;
}}
.mode-toggle button[aria-pressed="true"] {{
  background: var(--accent); color: var(--bg);
}}

.print-btn {{
  background: transparent; color: var(--ink-soft);
  border: 1px solid var(--hairline); border-radius: 6px;
  padding: 6px 12px; cursor: pointer;
  font-family: var(--font-mono); font-size: 0.85em;
  text-transform: uppercase; letter-spacing: 0.05em;
}}
.print-btn:hover {{ color: var(--ink); border-color: var(--accent); }}

/* Hero */
.hero {{
  position: relative;
  padding: 100px 24px 80px;
  max-width: 1080px; margin: 0 auto;
  border-bottom: 2px solid var(--accent);
  overflow: hidden;
}}
.hero::before {{
  content: "";
  position: absolute; top: -200px; left: -150px;
  width: 700px; height: 700px;
  background: radial-gradient(circle, var(--accent) 0%, transparent 60%);
  opacity: 0.10; z-index: 0;
}}
.hero::after {{
  content: "";
  position: absolute; bottom: -2px; left: 0; right: 0;
  height: 1px; background: var(--accent-2);
  opacity: 0.6;
}}
.hero > * {{ position: relative; z-index: 1; }}
.hero .eyebrow {{
  font-family: var(--font-mono); font-size: 0.78em;
  text-transform: uppercase; letter-spacing: 0.18em;
  color: var(--accent); margin-bottom: 24px;
}}
.hero h1 {{
  font-family: var(--font-display); color: var(--ink-display);
  font-size: clamp(56px, 9vw, 110px); line-height: 0.96;
  margin: 0 0 20px 0; letter-spacing: -0.02em;
  font-weight: 600;
}}
.hero .narrator-dek {{
  font-family: var(--font-display); font-style: italic;
  font-size: 1.2em; color: var(--ink-soft);
  margin: 0 0 28px 0; max-width: 56ch;
}}
.hero .subtitle {{
  font-family: var(--font-body);
  font-size: 1.15em; line-height: 1.55;
  max-width: 62ch; color: var(--ink);
  margin: 0 0 36px 0;
}}
.hero .meta-row {{
  display: flex; flex-wrap: wrap; gap: 28px;
  font-family: var(--font-mono); font-size: 0.85em;
  color: var(--ink-soft);
}}
.hero .meta-row .meta b {{ color: var(--ink); margin-left: 4px; }}
.hero .meta-row .meta {{
  border-left: 2px solid var(--accent);
  padding-left: 12px;
  text-transform: uppercase; letter-spacing: 0.08em;
}}

/* Route SVG */
.route-svg {{
  margin: 36px 0 0 0;
  width: 100%; height: auto;
  max-height: 120px;
}}

/* Sticky TOC */
.toc-wrap {{
  max-width: 1080px; margin: 0 auto;
  padding: 36px 24px;
  display: grid; grid-template-columns: 220px 1fr;
  gap: 60px;
}}
.vp-toc {{
  position: sticky; top: 90px;
  font-family: var(--font-mono); font-size: 0.82em;
  text-transform: uppercase; letter-spacing: 0.06em;
  max-height: calc(100vh - 100px); overflow-y: auto;
}}
.vp-toc h3 {{
  font-size: 0.95em; color: var(--ink-soft);
  margin: 0 0 16px 0; text-transform: uppercase;
  letter-spacing: 0.1em;
}}
.vp-toc a {{
  display: block; padding: 6px 0;
  color: var(--ink-soft); text-decoration: none;
  border-left: 2px solid transparent; padding-left: 12px;
  margin-left: -14px;
}}
.vp-toc a:hover {{ color: var(--ink); border-color: var(--hairline); }}
.vp-toc a.active {{
  color: var(--accent); font-weight: 600;
  border-color: var(--accent);
}}
.vp-toc a.active::before {{ content: "▸ "; }}

/* Main content */
main {{ max-width: none; padding: 0; }}
main section[id] {{
  scroll-margin-top: 90px;
  padding: 60px 0 80px;
  border-bottom: 1px solid var(--hairline);
}}
main section[id]:last-child {{ border-bottom: none; }}

/* Section register classes */
.section--practical {{ font-family: var(--font-sans); max-width: 52ch; }}
.section--practical p {{ margin: 0.6em 0; }}
.section--practical ul {{ padding-left: 1.2em; }}
.section--atmospheric {{ font-family: var(--font-serif); max-width: 62ch; }}
.section--atmospheric p {{ margin: 1em 0; text-indent: 0; }}
.section--atmospheric p + p {{ text-indent: 1.5em; }}

/* Section headings */
h2 {{
  font-family: var(--font-display); color: var(--ink-display);
  font-size: clamp(36px, 5vw, 56px); line-height: 1.05;
  margin: 0 0 32px 0; font-weight: 600; letter-spacing: -0.01em;
}}
h3 {{
  font-family: var(--font-display); color: var(--ink-display);
  font-size: 1.7em; line-height: 1.2;
  margin: 36px 0 16px 0; font-weight: 600;
}}
h4 {{
  font-family: var(--font-display); color: var(--ink);
  font-size: 1.3em; margin: 28px 0 12px 0;
}}
h5 {{
  font-family: var(--font-body); color: var(--ink-display);
  font-size: 1.05em; font-weight: 600;
  margin: 0 0 6px 0;
}}

/* Reading-time chip */
.reading-time {{
  display: inline-block; font-family: var(--font-mono);
  font-size: 0.6em; color: var(--ink-soft);
  margin-left: 16px; padding: 3px 8px;
  border: 1px solid var(--hairline); border-radius: 3px;
  text-transform: uppercase; letter-spacing: 0.08em;
  vertical-align: middle;
}}

/* Permalink anchor */
.permalink {{
  opacity: 0; margin-left: 0.4em; color: var(--ink-soft);
  text-decoration: none; transition: opacity 120ms;
  font-size: 0.6em; vertical-align: middle;
}}
h2:hover .permalink, h3:hover .permalink {{ opacity: 0.6; }}
.permalink:hover {{ opacity: 1 !important; color: var(--accent); }}

/* Lede / .deep two-track */
.lede {{
  font-weight: 600;
  font-size: 1.06em; line-height: 1.5;
  margin: 0 0 1em 0;
  color: var(--ink);
}}
.deep {{
  font-size: 0.96em; line-height: 1.65;
  color: var(--ink-soft);
}}
.deep p:first-child {{ margin-top: 0; }}

/* Mode-toggle visibility rules */
body[data-mode="skim"] .deep,
body[data-mode="skim"] .dig-deeper,
body[data-mode="skim"] .sidenote-content,
body[data-mode="skim"] .endnotes {{ display: none; }}

body[data-mode="standard"] .dig-deeper,
body[data-mode="standard"] .sidenote-content {{ display: none; }}

/* Section content wrappers */
section .content-block {{ margin: 0 24px; }}
@media (min-width: 760px) {{
  section .content-block {{ margin: 0; }}
}}

/* Practical links */
a.practical-link {{
  color: var(--ink);
  text-decoration-color: var(--ink-soft);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
  transition: color 120ms, text-decoration-color 120ms, text-decoration-thickness 120ms;
}}
a.practical-link:hover, a.practical-link:focus-visible {{
  color: var(--accent);
  text-decoration-color: var(--accent);
  text-decoration-thickness: 2px;
}}

/* Sources note */
details.sources-note {{
  margin: 36px 0;
  padding: 16px 20px;
  background: var(--surface);
  border-left: 3px solid var(--accent-2);
  border-radius: 0 6px 6px 0;
  font-size: 0.92em;
}}
details.sources-note summary {{
  cursor: pointer; font-family: var(--font-mono);
  text-transform: uppercase; letter-spacing: 0.08em;
  font-size: 0.85em; color: var(--ink-soft);
}}
details.sources-note p {{ margin: 12px 0 0 0; color: var(--ink); }}

/* Data check callout */
.data-check {{
  margin: 24px 0;
  padding: 18px 22px;
  background: rgba(224, 124, 91, 0.10);
  border-left: 3px solid var(--warning);
  border-radius: 0 6px 6px 0;
  font-family: var(--font-body); font-size: 0.95em;
}}
.data-check .label {{
  font-family: var(--font-mono); font-size: 0.78em;
  text-transform: uppercase; letter-spacing: 0.1em;
  color: var(--warning); margin-bottom: 8px;
}}

/* Day-by-day */
.daymark {{
  margin: 60px 0 24px 0;
  padding-top: 24px;
  border-top: 1px dashed var(--hairline);
}}
.daymark:first-of-type {{ border-top: none; }}
.daynum {{
  font-family: var(--font-mono); font-size: 0.85em;
  color: var(--accent); text-transform: uppercase;
  letter-spacing: 0.12em; margin-bottom: 6px;
}}
.dayname {{
  font-family: var(--font-display); color: var(--ink-display);
  font-size: 2em; line-height: 1.1; margin: 0 0 4px 0;
  font-weight: 600;
}}
.daymeta {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--ink-soft); margin: 0 0 24px 0;
  text-transform: uppercase; letter-spacing: 0.06em;
}}
.daymeta b {{ color: var(--accent); }}
.dayintro {{
  font-family: var(--font-display); font-size: 1.1em;
  line-height: 1.55; max-width: 62ch;
  margin: 0 0 12px 0; color: var(--ink);
  font-style: italic;
}}
.dayintro-deep {{
  font-size: 0.95em; line-height: 1.65;
  max-width: 62ch; color: var(--ink-soft);
  margin: 0 0 24px 0;
}}

/* Site cards */
.site-card {{
  background: var(--surface);
  border-radius: 8px;
  padding: 18px 22px;
  margin: 14px 0;
  border-left: 3px solid var(--hairline);
}}
.site-card-head {{
  display: flex; align-items: baseline; gap: 14px;
  margin-bottom: 8px;
}}
.site-card h5 {{
  margin: 0; flex: 1; font-size: 1.05em;
}}
.time-badge {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--accent); padding: 2px 8px;
  border: 1px solid var(--accent);
  border-radius: 3px;
  text-transform: uppercase; letter-spacing: 0.06em;
  white-space: nowrap;
}}
.time-badge.transit {{ color: var(--accent-2); border-color: var(--accent-2); }}
.time-badge.meal {{ color: var(--warning); border-color: var(--warning); }}
.time-badge.other {{ color: var(--muted); border-color: var(--muted); }}
.site-card p {{ margin: 6px 0; font-size: 0.96em; }}
.site-card .opnote {{
  margin: 10px 0 4px 0;
  padding-left: 12px;
  border-left: 2px solid var(--accent-2);
  font-style: italic; color: var(--ink-soft);
  font-size: 0.93em;
}}

/* Data-check callout — surfaces bookings-data inconsistencies (gap nights) */
.data-check-note {{
  margin: 14px 0 18px 0;
  padding: 10px 14px;
  background: rgba(212, 162, 76, 0.08);
  border-left: 3px solid #d4a24c;
  font-family: var(--font-mono);
  font-size: 0.85em;
  color: var(--ink-soft);
  border-radius: 0 4px 4px 0;
}}
.data-check-note::before {{
  content: "⚠ Data check · ";
  color: #d4a24c;
  font-weight: 600;
}}
.site-card .tags {{
  display: flex; flex-wrap: wrap; gap: 6px;
  margin-top: 12px;
}}
.walkchip {{
  display: inline-block;
  font-family: var(--font-mono); font-size: 0.72em;
  color: var(--ink-soft); background: var(--bg);
  padding: 2px 8px; border-radius: 10px;
  border: 1px solid var(--hairline);
}}
.travelpill {{
  display: inline-block;
  font-family: var(--font-mono); font-size: 0.72em;
  color: var(--accent-2); background: var(--bg);
  padding: 2px 8px; border-radius: 10px;
  border: 1px solid var(--accent-2);
}}
.tag {{
  display: inline-block;
  font-family: var(--font-mono); font-size: 0.72em;
  color: var(--ink-soft); background: var(--bg);
  padding: 2px 8px; border-radius: 10px;
  border: 1px solid var(--hairline);
}}

/* Field guide */
.fg-search {{
  margin: 0 0 24px 0;
  padding: 12px 16px;
  width: 100%; max-width: 460px;
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-radius: 6px;
  color: var(--ink); font-size: 1em;
  font-family: var(--font-body);
}}
.fg-chips {{
  display: flex; flex-wrap: wrap; gap: 8px;
  margin: 0 0 24px 0;
}}
.fg-chip {{
  font-family: var(--font-mono); font-size: 0.8em;
  padding: 6px 14px;
  background: transparent; border: 1px solid var(--hairline);
  border-radius: 20px; color: var(--ink-soft);
  cursor: pointer;
  text-transform: uppercase; letter-spacing: 0.06em;
}}
.fg-chip:hover {{ color: var(--ink); border-color: var(--accent); }}
.fg-chip.active {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
.fg-grid {{
  display: grid; gap: 18px;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
}}
.fg-card {{
  background: var(--surface);
  padding: 18px 20px; border-radius: 8px;
  border-left: 3px solid var(--accent);
}}
.fg-card h5 {{ margin: 0 0 4px 0; font-size: 1.05em; }}
.fg-card .latin {{
  font-style: italic; font-size: 0.92em;
  color: var(--ink-soft); margin: 0 0 8px 0;
}}
.fg-card .likely {{
  font-family: var(--font-mono); font-size: 0.75em;
  color: var(--accent-2); margin: 0 0 8px 0;
  text-transform: uppercase; letter-spacing: 0.06em;
}}
.fg-card p {{ font-size: 0.93em; margin: 8px 0 0 0; }}
.fg-card .fg-tags {{
  display: flex; flex-wrap: wrap; gap: 4px;
  margin-top: 12px;
}}
.fg-card .fg-tag {{
  font-family: var(--font-mono); font-size: 0.68em;
  background: var(--bg); color: var(--ink-soft);
  padding: 2px 7px; border-radius: 10px;
  border: 1px solid var(--hairline);
}}
.fg-region-h {{
  font-family: var(--font-mono); font-size: 0.85em;
  color: var(--accent-2); text-transform: uppercase;
  letter-spacing: 0.1em; margin: 32px 0 12px 0;
}}

/* Things to do */
.ttd-group {{ margin: 40px 0; }}
.ttd-group h4 {{ color: var(--accent); margin: 0 0 16px 0; }}
.ttd-entry {{
  margin: 14px 0; padding: 14px 18px;
  background: var(--surface); border-radius: 6px;
  border-left: 2px solid var(--hairline);
}}
.ttd-entry h5 {{ margin: 0 0 4px 0; }}
.ttd-entry .neighborhood {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--accent-2); margin: 0 0 6px 0;
}}
.ttd-entry p {{ margin: 6px 0 0 0; font-size: 0.95em; }}

/* Opinion */
.opinion {{
  border-left: 3px solid var(--accent);
  padding: 14px 18px;
  margin: 24px 0;
  font-style: italic; color: var(--ink-soft);
  font-size: 0.98em;
}}

/* Weather */
.weather-grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px; margin: 24px 0;
}}
.weather-stat {{
  background: var(--surface); padding: 18px;
  border-radius: 8px; border-top: 2px solid var(--accent);
}}
.weather-stat .label {{
  font-family: var(--font-mono); font-size: 0.75em;
  color: var(--ink-soft); text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 8px;
}}
.weather-stat .value {{
  font-family: var(--font-display); font-size: 1.9em;
  color: var(--ink-display); margin-bottom: 6px;
  font-weight: 600;
}}
.weather-stat .context {{
  font-size: 0.85em; color: var(--ink-soft);
  font-family: var(--font-body);
}}

/* History */
.history-vignette {{
  margin: 40px 0; padding: 22px 26px;
  background: var(--surface); border-radius: 8px;
  border-left: 4px solid var(--era, var(--accent));
}}
.history-vignette h4 {{ margin: 0 0 6px 0; color: var(--ink-display); }}
.history-vignette .era-chip {{
  display: inline-block; margin-bottom: 14px;
  background: var(--era); color: white;
  padding: 2px 8px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 0.75em;
  text-transform: uppercase; letter-spacing: 0.08em;
}}
.history-vignette .consequence {{
  margin-top: 16px; padding-top: 12px;
  border-top: 1px dashed var(--hairline);
  font-size: 0.92em; color: var(--ink-soft);
  font-style: italic;
}}
{era_class_css}

.date-chip {{
  background: var(--era, var(--accent));
  color: white;
  padding: 1px 6px; border-radius: 3px;
  font-family: var(--font-mono); font-size: 0.88em;
  letter-spacing: 0.02em;
}}

/* Phrase table */
.phrase-table {{
  width: 100%; margin: 28px 0;
  border-collapse: collapse; font-size: 0.9em;
}}
.phrase-table th, .phrase-table td {{
  padding: 8px 12px; text-align: left;
  border-bottom: 1px solid var(--hairline);
}}
.phrase-table th {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--accent); text-transform: uppercase;
  letter-spacing: 0.06em;
}}
.phrase-table tr:first-child td {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--accent); text-transform: uppercase;
  letter-spacing: 0.06em; border-bottom: 2px solid var(--accent);
}}

/* Fun facts */
.facts-layout {{
  display: grid; gap: 32px;
  grid-template-columns: 1fr;
}}
@media (min-width: 760px) {{
  .facts-layout {{ grid-template-columns: 1fr 1fr; }}
}}
.fact-group {{ margin: 0 0 24px 0; }}
.fg-loc {{
  font-family: var(--font-mono); font-size: 0.85em;
  color: var(--accent); text-transform: uppercase;
  letter-spacing: 0.08em; margin: 0 0 10px 0;
  padding-bottom: 6px; border-bottom: 1px solid var(--hairline);
}}
.fact-group ul {{ margin: 0; padding: 0; list-style: none; }}
.fact-group li {{
  position: relative;
  padding: 8px 0 8px 22px;
  border-bottom: 1px dashed var(--hairline);
  font-size: 0.95em; line-height: 1.5;
}}
.fact-group li::before {{
  content: "•"; color: var(--accent);
  position: absolute; left: 6px; top: 6px;
  font-weight: bold;
}}
.fact-group li:last-child {{ border-bottom: none; }}

/* Food */
.food-grid {{
  display: grid; gap: 16px;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  margin: 24px 0;
}}
.food-card {{
  background: var(--surface); padding: 16px 18px;
  border-radius: 6px; border-left: 2px solid var(--accent-2);
}}
.food-card h5 {{ margin: 0 0 2px 0; }}
.food-card .local {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--ink-soft); font-style: italic;
  margin: 0 0 4px 0;
}}
.food-card .region {{
  font-family: var(--font-mono); font-size: 0.7em;
  color: var(--accent-2); margin: 0 0 8px 0;
  text-transform: uppercase; letter-spacing: 0.06em;
}}
.food-card p {{ font-size: 0.92em; margin: 6px 0 0 0; }}
.food-card .food-tag {{
  display: inline-block; margin-top: 8px;
  font-family: var(--font-mono); font-size: 0.7em;
  background: var(--bg); color: var(--ink-soft);
  padding: 1px 6px; border-radius: 8px;
}}

.tier-block {{ margin: 24px 0; }}
.tier-block h4 {{ color: var(--accent); margin: 0 0 14px 0; }}
.tier-entry {{
  margin: 10px 0; padding: 12px 16px;
  background: var(--surface); border-radius: 6px;
  border-left: 2px solid var(--hairline);
}}
.tier-entry h5 {{ margin: 0 0 4px 0; font-size: 0.98em; }}
.tier-entry p {{ font-size: 0.9em; margin: 4px 0 0 0; }}
.tier-entry .city {{
  font-family: var(--font-mono); font-size: 0.72em;
  color: var(--accent-2); margin: 0 0 4px 0;
  text-transform: uppercase; letter-spacing: 0.06em;
}}
.tier-entry .tag-row {{
  display: flex; gap: 6px; margin-top: 8px;
}}
.booked-tag {{
  font-family: var(--font-mono); font-size: 0.7em;
  background: var(--accent); color: var(--bg);
  padding: 1px 8px; border-radius: 8px;
}}

/* Dig-deeper — Deep-mode-only supplementary inset */
aside.dig-deeper {{
  margin: 24px 0 8px 0;
  padding: 16px 20px;
  background: rgba(126, 200, 177, 0.06);
  border-left: 3px solid var(--accent);
  border-radius: 0 6px 6px 0;
}}
aside.dig-deeper > h5 {{
  margin: 0 0 8px 0;
  font-family: var(--font-mono);
  font-size: 0.78em;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--accent);
}}
aside.dig-deeper > p {{
  margin: 0;
  font-size: 0.95em;
  color: var(--ink-soft);
  line-height: 1.6;
}}

/* Go-deeper */
.go-deeper {{
  margin: 36px 0 0 0;
  padding: 24px 0 0 0;
  border-top: 1px solid var(--hairline);
}}
.go-deeper > h4 {{
  margin: 0 0 16px 0; color: var(--accent-2);
  font-family: var(--font-mono); font-size: 0.95em;
  text-transform: uppercase; letter-spacing: 0.08em;
}}
.gd-grid {{
  display: grid; gap: 12px;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}}
.gd-card {{
  background: var(--surface); padding: 14px 16px;
  border-radius: 6px; border-top: 2px solid var(--accent-2);
}}
.gd-kind {{
  font-family: var(--font-mono); font-size: 0.7em;
  color: var(--accent-2); text-transform: uppercase;
  letter-spacing: 0.08em; margin-bottom: 6px;
  display: block;
}}
.gd-card h5 {{ margin: 0 0 6px 0; font-size: 0.95em; }}
.gd-card p {{ font-size: 0.85em; margin: 6px 0 0 0; color: var(--ink-soft); }}

/* Bibliography */
.biblio-group {{ margin: 28px 0; }}
.biblio-group h4 {{
  font-family: var(--font-mono); font-size: 0.85em;
  text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--accent); margin: 0 0 12px 0;
  border-bottom: 1px solid var(--hairline); padding-bottom: 6px;
}}
.biblio-group ul {{ padding-left: 0; list-style: none; }}
.biblio-group li {{
  padding: 10px 0; border-bottom: 1px dashed var(--hairline);
}}
.biblio-group li b {{ font-weight: 600; }}
.biblio-group li .ay {{
  font-family: var(--font-mono); font-size: 0.85em;
  color: var(--ink-soft); margin: 0 6px;
}}

/* Live-data callout */
.live-data {{
  font-family: var(--font-mono); font-size: 0.78em;
  color: var(--ink-soft); margin-top: 24px;
  padding-top: 10px;
  border-top: 1px dashed var(--hairline);
}}

/* Footer */
footer.guide-footer {{
  padding: 40px 24px; text-align: center;
  font-family: var(--font-mono); font-size: 0.8em;
  color: var(--ink-soft); border-top: 1px solid var(--hairline);
}}
footer.guide-footer .palette-name {{
  color: var(--accent); letter-spacing: 0.1em;
  text-transform: uppercase;
}}

/* Hotels at a glance */
.hotels-table {{
  width: 100%; border-collapse: collapse;
  margin: 24px 0; font-size: 0.92em;
}}
.hotels-table th, .hotels-table td {{
  padding: 10px 14px; text-align: left;
  border-bottom: 1px solid var(--hairline);
}}
.hotels-table th {{
  font-family: var(--font-mono); font-size: 0.78em;
  text-transform: uppercase; letter-spacing: 0.06em;
  color: var(--accent);
}}

/* Responsive */
@media (max-width: 920px) {{
  .topbar .crumb .crumb-rest {{ display: none; }}
}}
@media (max-width: 760px) {{
  .toc-wrap {{ grid-template-columns: 1fr; gap: 24px; padding: 24px 18px; }}
  .vp-toc {{ position: static; max-height: none; }}
  .hero {{ padding: 60px 18px 50px; }}
  main section[id] {{ padding: 40px 0 60px; }}
  section .content-block {{ margin: 0 18px; }}
  .topbar {{ padding: 10px 14px; gap: 14px; flex-wrap: wrap; }}
  .topbar .crumb {{ display: none; }}
  .gd-grid {{ grid-template-columns: 1fr; }}
}}

/* Print */
@media print {{
  .deep, .dig-deeper, .sidenote-content {{ display: block !important; }}
  .mode-toggle, .print-btn, #vp-progress, .vp-toc, .skip-link {{ display: none !important; }}
  .topbar {{ position: static; }}
  body {{ background: white; color: black; font-size: 11pt; }}
  a {{ color: black; text-decoration: underline; }}
  .walkchip, .tag, .travelpill {{ display: none; }}
}}

@media (prefers-reduced-motion: reduce) {{
  html {{ scroll-behavior: auto; }}
  * {{ transition: none !important; animation: none !important; }}
}}
"""


def emit_js() -> str:
    """Return the vanilla JS bundle for the guide (progress bar, scroll-spy,
    mode toggle, field-guide search + chip filter, print button)."""
    return """
window.VPGuide = window.VPGuide || {};

(function(VPGuide){
  function initProgressBar(){
    try {
      var bar = document.getElementById("vp-progress");
      if (!bar) return;
      window.addEventListener("scroll", function(){
        var h = document.documentElement;
        var pct = (h.scrollTop / (h.scrollHeight - h.clientHeight)) * 100;
        bar.style.width = pct + "%";
      }, { passive: true });
    } catch(e){ console.warn("progress bar init failed", e); }
  }

  function initScrollSpy(){
    try {
      var links = document.querySelectorAll(".vp-toc a[href^='#']");
      if (!links.length || !("IntersectionObserver" in window)) return;
      var byId = {};
      links.forEach(function(a){ byId[a.getAttribute("href").slice(1)] = a; });
      var obs = new IntersectionObserver(function(entries){
        entries.forEach(function(e){
          var a = byId[e.target.id];
          if (!a) return;
          if (e.isIntersecting) {
            links.forEach(function(l){ l.classList.remove("active"); });
            a.classList.add("active");
          }
        });
      }, { rootMargin: "-40% 0px -55% 0px" });
      document.querySelectorAll("main section[id]").forEach(function(s){ obs.observe(s); });
    } catch(e){ console.warn("scroll-spy init failed", e); }
  }

  function initModeToggle(){
    try {
      var KEY = "vp.guide.mode";
      var saved = null;
      try { saved = localStorage.getItem(KEY); } catch(e) {}
      var mode = saved || "standard";
      document.body.setAttribute("data-mode", mode);
      var buttons = document.querySelectorAll(".mode-toggle [data-mode]");
      buttons.forEach(function(btn){
        btn.setAttribute("aria-pressed", btn.dataset.mode === mode ? "true" : "false");
        btn.addEventListener("click", function(){
          var next = btn.dataset.mode;
          document.body.setAttribute("data-mode", next);
          buttons.forEach(function(b){
            b.setAttribute("aria-pressed", b.dataset.mode === next ? "true" : "false");
          });
          try { localStorage.setItem(KEY, next); } catch(e){}
        });
      });
    } catch(e){ console.warn("mode toggle init failed", e); }
  }

  function initFieldGuide(){
    try {
      var search = document.getElementById("fg-search");
      var chips = document.querySelectorAll(".fg-chip");
      var cards = document.querySelectorAll(".fg-card");
      if (!cards.length) return;
      var activeRegion = "all";
      function apply(){
        var q = (search && search.value || "").toLowerCase().trim();
        cards.forEach(function(c){
          var matchesQ = !q || c.textContent.toLowerCase().indexOf(q) !== -1;
          var matchesR = activeRegion === "all" || (c.dataset.tags || "").indexOf(activeRegion) !== -1;
          c.style.display = (matchesQ && matchesR) ? "" : "none";
        });
      }
      if (search) search.addEventListener("input", apply);
      chips.forEach(function(ch){
        ch.addEventListener("click", function(){
          activeRegion = ch.dataset.region || "all";
          chips.forEach(function(c){ c.classList.remove("active"); });
          ch.classList.add("active");
          apply();
        });
      });
    } catch(e){ console.warn("field guide init failed", e); }
  }

  function initPrint(){
    try {
      var btn = document.getElementById("print-btn");
      if (btn) btn.addEventListener("click", function(){ window.print(); });
    } catch(e){}
  }

  VPGuide.initWayfinding = function(){
    initProgressBar();
    initScrollSpy();
    initModeToggle();
    initFieldGuide();
    initPrint();
  };
  document.addEventListener("DOMContentLoaded", VPGuide.initWayfinding);
})(window.VPGuide);
"""


def emit_hero(trip_meta: Dict[str, Any], palette_name: str) -> str:
    """Emit the hero section + sources-note details block.

    `palette_name` surfaces in the "Trip guide · {name}" eyebrow.
    `trip_meta["route_svg"]` (optional) is inserted verbatim into the hero.
    Absent → no SVG element in the hero.
    `trip_meta["sources_note"]` (optional) is inserted verbatim — caller is
    responsible for supplying safe HTML (may contain <i>, <a>, &lsquo;, etc.).
    Absent or empty → no sources block.
    """
    start = trip_meta["start_date"]
    end = trip_meta["end_date"]
    days = (end - start).days + 1
    date_str = f"{start.strftime('%b %-d')} → {end.strftime('%b %-d')} · {start.year}"
    nights = trip_meta.get("nights", days - 1)
    countries_count = trip_meta.get("countries_count", len(trip_meta.get("countries", [])))
    bookings_count = trip_meta.get("bookings_count", "")
    route_svg = trip_meta.get("route_svg", "")
    sources_note = trip_meta.get("sources_note", "")
    sources_block = ""
    if sources_note:
        sources_block = f"""

<details class="sources-note">
  <summary>A note on sources</summary>
  <p>{sources_note}</p>
</details>
"""
    return f"""
<section id="hero" class="hero">
  <div class="eyebrow">Trip guide · {esc(palette_name)}</div>
  <h1>{esc(trip_meta['title'])}</h1>
  <div class="narrator-dek">{esc(trip_meta['narrator_dek'])}</div>
  <p class="subtitle">{esc(trip_meta['subtitle'])}</p>
  <div class="meta-row">
    <div class="meta">When<b>{esc(date_str)}</b></div>
    <div class="meta">Length<b>{days} days · {nights} nights</b></div>
    <div class="meta">Countries<b>{countries_count}</b></div>
    <div class="meta">Bookings<b>{bookings_count}</b></div>
  </div>
  {route_svg}
</section>{sources_block}
"""


def emit_toc(slugs: List[Tuple[str, str]]) -> str:
    """Return an `<aside class="vp-toc">` nav block with one anchor per (slug, label) pair."""
    items = "\n".join(
        f'    <a href="#{slug}">{esc(label)}</a>'
        for slug, label in slugs
    )
    return f"""
<aside class="vp-toc" role="navigation" aria-label="Section navigation">
  <h3>Sections</h3>
{items}
</aside>
"""


def emit_go_deeper(cards: List[Dict[str, str]]) -> str:
    """Emit the "Go deeper on this" card grid. Empty cards list → ''."""
    if not cards:
        return ""
    card_html = "\n".join(
        f'''    <article class="gd-card">
      <span class="gd-kind">{esc(c["kind"])}</span>
      <h5><a class="practical-link" href="{esc(c["url"])}" rel="noopener" target="_blank">{esc(c["title"])}</a></h5>
      <p>{esc(c["annotation"])}</p>
    </article>'''
        for c in cards
    )
    return f"""
<aside class="go-deeper">
  <h4>Go deeper on this</h4>
  <div class="gd-grid">
{card_html}
  </div>
</aside>
"""


# ── Frame helper ───────────────────────────────────────────────────────────

def emit_section_wrapper(
    slug: str,
    label: str,
    kind: Literal["atmospheric", "practical"],
    body_html: str,
    *,
    go_deeper_html: str = "",
    slug_label: Optional[str] = None,
) -> str:
    """Wrap a section's body in `<section class="section--<kind>">` with h2 + content-block.

    Produces the same shape as the per-section emitters in the Trip-2 compose
    script produce inline today. Reading-time chip uses body_html + go_deeper_html
    as the text source. slug_label defaults to label.
    """
    label_for_chip = slug_label if slug_label is not None else label
    rt_source = body_html + (go_deeper_html or "")
    h2 = emit_h2(slug, label, label_for_chip, rt_source)
    trailing = go_deeper_html if go_deeper_html else ""
    return (
        f'<section id="{slug}" class="section--{kind}">'
        f'{h2}<div class="content-block">{body_html}{trailing}</div></section>'
    )
