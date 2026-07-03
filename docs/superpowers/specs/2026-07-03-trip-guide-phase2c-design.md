# Trip-Guide Phase 2c — Two-Track Compose Refactor (Design)

**Date:** 2026-07-03
**Status:** Design — awaits implementation plan
**Predecessor:** [Phase 2b plan](../plans/2026-06-29-trip-guide-phase2b.md) (shipped)
**Predecessor note:** [Phase 2a validation Obs 5](../notes/2026-06-27-trip-guide-phase2a-validation.md#5-the-compose-script-as-skill-runner-pattern-is-excellent-for-validation)

## Goal

Formalise the two-track compose pattern the Trip-2 validation script proved out.
Extract reusable HTML/CSS emit helpers from
`scripts/2026-06-27_compose_trip2.py` into a shared `src/guide_emit.py`
module, then retrofit the Trip-2 composer to import from it. Update
`.claude/skills/trip-guide/SKILL.md` Step 7 to teach the pattern for future
composes.

## Non-goals

- Introducing formal dataclasses for section content shapes (YAGNI — Trip-2's
  beer-section addition proved that sections vary trip-to-trip).
- Adding new visual primitives, palette rules, or content-model changes.
- Migrating trip-1 or trip-3 composes — those are future work.
- Any DB schema change, migration, or `vacation.db` write.
- Changing the storage abstraction (`GUIDE_STORAGE` env var, `save_guide`,
  `.bak` rotation) — Phase 2c is renderer-only.

## Context

`scripts/2026-06-27_compose_trip2.py` is a 3,612-line one-shot compose script
that already runs a two-track pattern internally: prose data lives in Python
dicts/lists at the top of the file (`DAY_BY_DAY`, `FIELD_GUIDE`, `BEER`, ...);
emit functions render those dicts to HTML. But every helper — from `esc` to
the ~800-line `emit_css` — lives inside the script. Nothing is reusable
across trips. The SKILL.md Step 7 still tells Claude to "Write the complete
single-file HTML in one pass", which means the next compose (trip-3, or a
Trip-2 regen after a spec change) starts from a blank editor.

The Phase 2b plan explicitly parked this refactor for Phase 2c after Phase 2b
(the smaller editorial-spine seeds) shipped. Tests sit at 1,010 passing.

## Design decisions (locked at brainstorm)

1. **Scope:** extract helpers into `src/guide_emit.py` **and** retrofit
   Trip-2's composer to use them. Proves the helpers are actually reusable
   and leaves a working reference for future composes.
2. **Depth:** medium. Extract tier-1 primitives (text/link/chip helpers) +
   tier-2 palette-aware scaffolding (CSS, JS, hero, TOC, go-deeper) + a
   small handful of tier-3 frame helpers (`emit_section_wrapper`). Per-section
   emitters (day-by-day, field-guide, etc.) stay in the per-trip composer
   because they iterate trip-specific data shapes.
3. **Location:** new top-level `compose/` package. Trip-2's composer moves
   to `compose/trip_2.py`. `scripts/` keeps one-shot migrations + dev tooling.
4. **API shape:** free functions. Palette + eras are passed as explicit args
   to the two functions that actually need them (`emit_css`, `emit_hero`).
   No module-level state; no `Renderer` class; no `GuideContext` dataclass.

## Architecture

### Module layout after refactor

- **`src/guide_emit.py`** *(new)* — the shared renderer. Free functions, no
  module-level mutable state, no I/O. ~1,050 LOC, dominated by the CSS block
  inside `emit_css(palette, eras)`.
- **`tests/test_guide_emit.py`** *(new)* — one test file per `src/` module
  per project convention.
- **`compose/__init__.py`** *(new, empty)* — makes the folder a package so
  `python -m compose.trip_2` works.
- **`compose/trip_2.py`** *(renamed from `scripts/2026-06-27_compose_trip2.py`)*
  — the live composer for Trip-2. Holds Trip-2's prose dicts, per-section
  emitters, and the `compose()` driver. ~2,500 LOC after retrofit (mostly
  prose).

### What moves to `src/guide_emit.py`

| From compose script (line range) | New home | Notes |
|---|---|---|
| `esc`, `reading_time`, `permalink`, `reading_time_chip`, `emit_h2`, `emit_practical_link`, `category_color` (~1975–2041) | `guide_emit.py` — tier-1 primitives | Pure, palette-free. ~65 LOC lifted with unchanged signatures. |
| `emit_walking_chip_for_card` (2010–2030) | `guide_emit.py` as `emit_walking_chip(venue_key, hotel, venue_coords, venue_relevance)` | Signature change: takes venue_key directly instead of `card["venue_key"]`. Decouples helper from card shape so composers can call it from anywhere (day-by-day cards today; things-to-do entries tomorrow if desired). |
| `emit_css` (2047–2862) | `guide_emit.py` as `emit_css(palette, eras)` | The ~800-line CSS block. Now takes palette + eras as explicit args instead of reading module globals. Era CSS variables emitted from the eras list; palette color + font variables emitted from the palette dict. |
| `emit_js` (2867–2971) | `guide_emit.py` | Vanilla JS bundle (field-guide filter, TOC scroll-spy, Skim/Standard/Deep mode toggle). No palette dependency. |
| `emit_hero` (2976–3029) | `guide_emit.py` as `emit_hero(trip_meta, palette_name)` | Palette name surfaces in the "Trip guide · {name}" eyebrow; passed explicitly rather than read from a global. **Route SVG contract:** `emit_hero` never generates the SVG itself — it renders `trip_meta.get("route_svg", "")` verbatim into the hero. The composer builds its own route SVG (Trip-2's is a hand-tuned 5-country geometry) and puts the SVG string into `trip_meta["route_svg"]` before calling. Absent key → no SVG element in the hero. |
| `emit_toc` (3032–3043) | `guide_emit.py` | Already pure; lifts straight over. |
| `emit_go_deeper` (3046–3066) | `guide_emit.py` as `emit_go_deeper(cards)` | Signature change: takes the card list directly instead of a `section_key` + a `GO_DEEPER` dict. Caller looks up the key in its own dict and passes the list. |
| **NEW:** `emit_section_wrapper(slug, label, kind, body_html, *, go_deeper_html="", slug_label=None)` | `guide_emit.py` — frame helper | Emits `<h2>` via `emit_h2` + `<section class="section--atmospheric">` or `section--practical` wrapper + `body_html` inside + optional `<aside class="go-deeper">` trailing. Removes ~10 lines of boilerplate from every per-section emitter. |

### What stays in `compose/trip_2.py`

- All prose data dicts and constants: `PALETTE`, `ERAS`, `TRIP_META`, `GO_DEEPER`,
  `SOURCES_NOTE`, `DAY_BY_DAY`, `FIELD_GUIDE`, `THINGS_TO_DO`, `WEATHER`,
  `HISTORY`, `FUN_FACTS`, `FOOD`, `BEER`.
- All per-section emitters (`emit_day_by_day`, `emit_field_guide`,
  `emit_things_to_do`, `emit_weather`, `emit_history`, `emit_fun_facts`,
  `emit_food`, `emit_beer`, `emit_sources`) — these iterate Trip-2's specific
  data shapes. Each internally becomes: build body HTML, call
  `emit_section_wrapper(...)` once at the end.
- `compose()` and `main()` driver.
- Any Trip-2-specific SVG (route map) and Trip-2-specific WebSearch-sourced
  bibliography.

### What `scripts/` keeps

`2026-06-19_add_guide_share_token.py` (one-shot migration),
`2026-06-25_inject_phase2a.py` + `2026-06-25_verify_phase2a.py` (validation
one-shots, frozen), `backfill_auto_kind.py`, `backup_db.sh`, `dev.sh`,
`load_scandinavia.py`. The retrofit moves only the one file that is
actually a re-runnable composer.

## Public surface of `src/guide_emit.py`

Every function is a free function. Type hints on all signatures. Docstrings
document input shapes. No module-level state beyond constants.

```python
"""guide_emit — shared HTML/CSS emit helpers for trip-guide composers.

Pure rendering. No DB I/O, no filesystem, no module-level mutable state.
Each function takes the data it needs as args and returns a string of HTML
or CSS. Per-trip composers (compose/trip_<id>.py) import from here.
"""

# ── Tier 1: text primitives ────────────────────────────────────────────────
def esc(s: str) -> str: ...
def reading_time(text: str) -> int: ...                       # words / 220 wpm, ceil
def permalink(slug: str, label: str) -> str: ...
def reading_time_chip(text: str, slug_label: str) -> str: ...
def emit_h2(slug: str, label: str, slug_label: str, body_text: str) -> str: ...
def category_color(cat: str) -> str: ...

# ── Tier 1: link + chip helpers ────────────────────────────────────────────
def emit_practical_link(name: str, city: str, full_text: Optional[str] = None) -> str: ...
def emit_walking_chip(
    venue_key: Optional[str],
    hotel: Optional[Dict[str, Any]],            # expects 'lat','lng','title' keys
    venue_coords: Dict[str, Tuple[float, float]],
    venue_relevance: Dict[str, Optional[float]],
) -> str: ...

# ── Tier 2: palette-aware scaffolding ──────────────────────────────────────
def emit_css(palette: Dict[str, Any], eras: List[Dict[str, str]]) -> str: ...
def emit_js() -> str: ...                                     # static; no palette
def emit_hero(trip_meta: Dict[str, Any], palette_name: str) -> str: ...
def emit_toc(slugs: List[Tuple[str, str]]) -> str: ...
def emit_go_deeper(cards: List[Dict[str, str]]) -> str: ...

# ── Frame helper (the new one) ─────────────────────────────────────────────
def emit_section_wrapper(
    slug: str,
    label: str,
    kind: Literal["atmospheric", "practical"],
    body_html: str,
    *,
    go_deeper_html: str = "",
    slug_label: Optional[str] = None,           # falls back to `label` for the reading-time chip
) -> str: ...
```

### Input shapes (documented, not schema-enforced)

```python
# palette dict
{
  "name": "nordlys",
  "colors": {"bg": "#...", "surface": "#...", "ink": "#...", "ink_soft": "#...",
             "ink_display": "#...", "accent": "#...", "accent_2": "#...",
             "muted": "#...", "hairline": "#...", "warning": "#..."},
  "fonts":  {"display": "...", "body": "...", "mono": "..."},
}

# eras list (per ERA_COLORS palette pattern in SKILL.md)
[{"slug": "imperial", "label": "Imperial", "hex": "#b45309", "year_range": "..."}, ...]

# hotel dict (consumed by emit_walking_chip)
{"lat": float, "lng": float, "title": str}    # composer may carry extra keys

# go-deeper card dict
{"kind": "Book"|"Podcast"|"Film"|"Local voice", "title": str, "url": str, "annotation": str}

# trip_meta dict (consumed by emit_hero)
{"title": str, "subtitle": str, "narrator_dek": str, "start_date": date,
 "end_date": date, "countries": List[str],
 "route_svg": Optional[str],    # inserted verbatim into the hero; empty/absent → no SVG
 ...}    # composer may add extra keys
```

Dicts (not dataclasses) match what's already in `compose_trip2.py`. A future
trip with a slightly different section shape can iterate its own dicts and
call the helpers without a schema migration. Dataclasses can come later if
multiple trips converge on the same shape.

### What is NOT in `guide_emit.py`

- No per-section emitters (`emit_day_by_day`, `emit_field_guide`, ...) —
  those iterate trip-specific data shapes.
- No prose constants.
- No I/O — `save_guide` stays in `guide_builder.py`.
- No `GO_DEEPER` lookup logic — composer owns its own dict.

## Per-trip composer shape

After retrofit, `compose/trip_2.py` reads top-to-bottom as: **imports →
prose data → per-section emitters → `compose()` driver → `main()`**.

```python
"""compose/trip_2.py — live composer for Trip 2 (Scandinavia '26)."""

from datetime import date
from typing import Any, Dict, List, Optional, Tuple
from app import app, db
from src import guide_builder
from src.geocoding import ensure_geocoded, geocode_with_cache
from src.trip_helpers import hotel_for_night
from src.data_check import find_hotel_night_gaps
from src.guide_emit import (
    esc, emit_h2, emit_practical_link, emit_walking_chip, category_color,
    emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper,
    emit_section_wrapper,
)

TRIP_ID = 2

# ── prose data (unchanged from today) ──────────────────────────────────────
PALETTE = { "name": "nordlys", "colors": {...}, "fonts": {...} }
ERAS = [ ... ]
TRIP_META = { "title": "...", "narrator_dek": "...", "start_date": date(2026,8,14), ... }
GO_DEEPER = { "day_by_day": [...], "field_guide": [...], "history": [...], "food": [...] }
SOURCES_NOTE = "..."
DAY_BY_DAY = [ ... ]
FIELD_GUIDE = { ... }
THINGS_TO_DO = { ... }
WEATHER = { ... }
HISTORY = { ... }
FUN_FACTS = { ... }
FOOD = { ... }
BEER = { ... }

# ── trip-specific per-section emitters ─────────────────────────────────────
def emit_day_by_day(hotels, venue_coords, venue_relevance, gaps_by_date):
    """Iterate DAY_BY_DAY; build body HTML; wrap via emit_section_wrapper.
    Returns ((slug, label), section_html)."""
    body_parts = []
    for day in DAY_BY_DAY:
        # build day-card HTML using emit_practical_link, emit_walking_chip, ...
        body_parts.append(day_html)
    body_html = "\n".join(body_parts)
    section_html = emit_section_wrapper(
        slug="days", label="Day by day", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER["day_by_day"]),
    )
    return ("days", "Day by day"), section_html

def emit_field_guide(): ...
def emit_things_to_do(is_single_hotel): ...
def emit_weather(): ...
def emit_history(): ...
def emit_fun_facts(): ...
def emit_food(): ...
def emit_beer(): ...
def emit_sources(): ...

# ── driver ──────────────────────────────────────────────────────────────────
def compose(venue_coords, venue_relevance, hotels, is_single_hotel, gaps_by_date) -> str:
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
    slugs = [(slug, label) for (slug, label), _html in sections]
    body_html = "\n".join(html for _s, html in sections)
    return f"""<!doctype html>
<html><head><style>{emit_css(PALETTE, ERAS)}</style></head>
<body data-mode="standard">
{emit_hero(TRIP_META, PALETTE["name"])}
{emit_toc(slugs)}
<main>
{body_html}
</main>
<script>{emit_js()}</script>
</body></html>"""

def main(): ...   # geocoding + gap detection + compose + save_guide + audit
```

### Section-emitter return convention

Each per-section emitter returns `((slug, label), html_str)`. The compose
driver unpacks the tuple: the slug/label list drives `emit_toc`; the html
strings concatenate into the page body. This keeps the TOC in lock-step
with the section list — a future edit can't add a section without adding a
TOC entry.

### Composer file line-count estimate after retrofit

- Was: ~3,612 LOC
- After: ~2,500 LOC in `compose/trip_2.py` + ~1,050 LOC in `src/guide_emit.py`
- The 1,100-LOC drop from the composer maps to: CSS (~800) + JS (~105) +
  tier-1 primitives (~65) + hero/toc/go-deeper (~90) + section-wrapper
  boilerplate saved across 9 sections (~40).

### How future composes work

Next trip is `compose/trip_3.py`. It defines its own PALETTE / ERAS /
prose dicts and its own per-section emitters (which may have different
structure — e.g. no beer section, but a coffee section). It imports the
same helpers from `src.guide_emit`. Trip-3's per-section emitters won't be
identical to Trip-2's, but the frame + CSS + JS are shared for free.

## SKILL.md updates

Two targeted edits, both localised to Step 7 and its supporting content.

### Edit 1 — Step 7 replaced

Current single line ("Write the complete single-file HTML in one pass.
Requirements: ...") becomes:

> ### 7. Compose the HTML
>
> Build the guide as `compose/trip_<id>.py` following the two-track pattern:
> **Track 1 (top of file):** Python dicts + lists holding prose data and
> configuration (PALETTE, ERAS, TRIP_META, GO_DEEPER, plus one dict/list per
> section — DAY_BY_DAY, FIELD_GUIDE, and so on).
> **Track 2 (below):** per-section emitter functions that iterate track-1
> data and return HTML, plus a `compose()` driver that concatenates them.
>
> All shared rendering — CSS, JS, hero, TOC, go-deeper card rows, section
> wrappers, practical links, walking chips, text primitives — lives in
> `src/guide_emit.py`. Import what you need:
>
> ```python
> from src.guide_emit import (
>     esc, emit_h2, emit_practical_link, emit_walking_chip, category_color,
>     emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper, emit_section_wrapper,
> )
> ```
>
> **Canonical worked example:** [`compose/trip_2.py`](../../compose/trip_2.py)
> is the reference implementation. Copy its structure — imports, prose-data
> ordering, per-section emitter pattern, and the way `compose()` returns
> `((slug, label), html_str)` tuples from each section emitter so the TOC
> stays in lock-step with the section list.
>
> Requirements (unchanged):
>
> - Inlined CSS via `emit_css(PALETTE, ERAS)` — no external stylesheet
> - Fonts via Google Fonts CDN only
> - Vanilla JS via `emit_js()` — no framework
> - Mobile-responsive (single-column under 600px)
> - `@media print` coverage
> - `prefers-reduced-motion: reduce` respected
> - Field-guide section: interactive search + chip filters (JS lives in `emit_js()`)
> - No external images
>
> Save via `guide_builder.save_guide(trip_id, html)` — see Step 8.

### Edit 2 — new "Composer file conventions" subsection

A short new subsection (~30 lines) after the 10-step flow documenting:

- File name: `compose/trip_<id>.py` — one file per trip, versioned in git
- Section ordering inside the file: imports → prose dicts (PALETTE / ERAS /
  TRIP_META / GO_DEEPER first, then section-specific dicts) → per-section
  emitters → `compose()` → `main()`
- Convention that each per-section emitter returns `((slug, label), html_str)`
- Convention that trip-specific dicts follow the shapes documented in
  `src/guide_emit.py`'s docstrings — the emit helpers are the source of
  truth for input shapes, the composer conforms

### Cross-reference notes

- `## Walking-distance chips` → `## Helper invocation`: add one-line note
  that composers call `emit_walking_chip` from `src.guide_emit`, which
  wraps `walking_distance.walking_chip` with the venue-key + hotel-dict
  plumbing.
- `## Practical hyperlinks` → `## Helper invocation`: add one-line note
  that composers call `emit_practical_link` from `src.guide_emit`.

### What does NOT change in SKILL.md

- Editorial voice rules (banned phrases, named-particulars density, history
  claim triad, sensory opener) — the composer applies these to prose;
  unaffected by where the HTML is emitted from.
- Depth tiers, archetypes, palette proposal, geocoding, source disclosure,
  practical hyperlinks, walking-distance chips — content spec is unchanged.
- Step 10 verification asserts — the browser-side + grep-side checks are
  the same regardless of how the HTML got built.

## Tests

New file: `tests/test_guide_emit.py`. Coverage per helper:

**Tier-1 primitives:**

- `esc`: HTML-special-char escape → correct output; quote-mode on
- `reading_time`: word-count / 220 wpm ceil; strips HTML tags; ≥1 min floor
- `permalink`: produces `<a class="permalink" href="#slug">¶</a>`; label escaped in aria
- `emit_h2`: contains slug id, reading-time chip, permalink; label escaped
- `emit_practical_link`: URL-encodes name and city; sets `rel="noopener" target="_blank"`; falls back to `full_text` when passed
- `category_color`: known categories map to known classes; unknown → `"other"`

**Chip / walking-distance wiring:**

- `emit_walking_chip`: returns `""` on missing venue_key, missing hotel, missing venue_coords entry, or hotel with no lat; when all inputs resolve, delegates to `walking_distance.walking_chip(venue_coords=..., hotel_coords=..., hotel_name=..., venue_confidence=...)` — the confidence-threshold + haversine math lives there (unchanged by Phase 2c). `emit_walking_chip` is a thin adapter that unpacks the composer-facing shape (venue_key + hotel dict + coord dicts) into that positional call. Tests cover both skip paths and the passthrough.

**Palette-aware helpers:**

- `emit_css`: palette colors appear as `--bg`, `--accent`, etc. in `:root`; era slugs appear as `--era-<slug>` variables; era class rules emitted; fonts substituted into `--font-display` etc.; empty ERAS list produces no era CSS (no crash)
- `emit_js`: returns non-empty string (smoke); contains the mode-toggle IIFE marker; deterministic across calls
- `emit_hero`: contains trip title, palette name in eyebrow, narrator dek, date range formatted; escapes all user-supplied strings
- `emit_toc`: produces one `<a>` per slug; anchor href is `#slug`; label is escaped
- `emit_go_deeper`: empty card list → returns `""`; N cards → N `<article class="gd-card">`; card title wrapped in `practical-link` anchor to the card's URL

**Frame helper:**

- `emit_section_wrapper`: `kind="atmospheric"` produces `<section class="section--atmospheric">`; `kind="practical"` produces `<section class="section--practical">`; slug becomes the section id; label appears in the h2; body_html spliced inside the wrapper; go_deeper_html appended after body when non-empty; nothing appended when go_deeper_html is empty; slug_label falls back to label when not supplied

**Count:** ~35 tests. Every test is a plain-Python string check on the return
value of a pure function — no fixtures, no DB, no Flask. Runs in well under
a second.

**Existing test suite (1,010 tests):** stays green. `src/walking_distance.py`,
`src/place_links.py`, `src/geocoding.py`, `src/trip_helpers.py`,
`src/data_check.py`, `guide_builder.py` — none of their signatures change.

**Regression harness for the retrofit:** the Trip-2 guide is the end-to-end
check. Snapshot the audit output — `practical-link` (145), `walkchip` (53),
`era-chip` (5), `go-deeper` (4), `data-check-note` (≥1), banned-word grep
(0), body word count (~13,977) — from a pre-retrofit compose. After
retrofit, re-run `python -m compose.trip_2` and diff. Audit counts must be
identical; whitespace-only HTML byte-diffs are acceptable.

## Migration path

Six ordered steps producing four commits. Steps 1 and 5 are verification-only
(no commit). Each step leaves the tree working before moving on.

### Step 1 — Pre-retrofit audit snapshot

Run the current script, capture: word count, banned-word hits (should be 0),
`practical-link` / `walkchip` / `era-chip` / `go-deeper` / `data-check-note`
counts. Save numbers as expected values for step 5. No code change; no
commit. Notes go in the plan file.

### Step 2 — Add `src/guide_emit.py` + tests

Create the module. Copy the helpers over with their new signatures
(`emit_css(palette, eras)`, `emit_walking_chip(venue_key, hotel, ...)`,
`emit_hero(trip_meta, palette_name)`, `emit_go_deeper(cards)`, plus the new
`emit_section_wrapper`). Write `tests/test_guide_emit.py`. Run `pytest
tests/ -q` — new tests pass, existing 1,010 stay green. The old compose
script is unchanged and still works via its own local defs.

**Commit:** `feat(guide_emit): extract shared trip-guide emit helpers to src module`

### Step 3 — Rename + move the composer

Create empty `compose/__init__.py`. `git mv
scripts/2026-06-27_compose_trip2.py compose/trip_2.py`. No code changes yet
— the rename is its own commit so `git log --follow` stays readable.

**Commit:** `chore(trip-guide): move trip-2 composer to compose/ package`

### Step 4 — Retrofit `compose/trip_2.py` to use `src.guide_emit`

At the top of the file, replace the old direct helper defs with `from
src.guide_emit import ...`. Delete the now-duplicate function bodies for
`esc`, `reading_time`, `permalink`, `reading_time_chip`, `emit_h2`,
`emit_practical_link`, `emit_walking_chip_for_card` (replaced by
`emit_walking_chip`), `category_color`, `emit_css`, `emit_js`, `emit_hero`,
`emit_toc`, `emit_go_deeper`. Update the ~9 per-section emitters to build
a body_html string and call `emit_section_wrapper(...)` once instead of
building the h2 + wrapper inline. Rewrite `compose()` to consume the new
`((slug, label), html)` tuple returns.

Run `python -m compose.trip_2`. Confirm audit output matches step 1's
snapshot exactly (chip counts, word count, banned-word hits). Any drift is
a bug — fix before commit.

**Commit:** `refactor(compose/trip_2): use src.guide_emit for shared rendering`

### Step 5 — Frontend verification

Load the regenerated guide via `webapp-testing` per CLAUDE.md's
frontend-verification rule. Zero console errors. Visible content on `#hero`,
`#days`, `#field-guide`, `#food`, `#beer`, `#sources`. Mode toggle
(Skim/Standard/Deep) works. Print preview honors `@media print`.

No commit — verification-only.

### Step 6 — Update SKILL.md

Apply the Step 7 rewrite + new "Composer file conventions" subsection + the
two cross-reference notes in Practical hyperlinks + Walking-distance chips
sections. Human-eyeball read of the diff.

**Commit:** `docs(trip-guide): document two-track compose pattern in SKILL.md`

## Risk / recovery

- Between step 3 and step 4, the composer is a renamed but not-yet-refactored
  copy. Running `python -m compose.trip_2` still works because all helpers
  are still defined locally. If step 4 goes sideways, `git revert` on step 4
  puts us back at "renamed but not refactored" which is fine.
- Step 4's diff will be large — it deletes ~1,100 LOC and rewrites 9 section
  emitters. The audit-snapshot diff is the safety net. If audit counts
  drift, the retrofit missed something.
- No DB migration, no schema change, no OAuth touch, no `vacation.db` write.
  Trip-2's guide file gets overwritten during verification runs;
  `save_guide` handles the `.bak` rotation.

## Estimated totals

- **Commits:** 4 (feat guide_emit + chore rename + refactor + docs SKILL.md).
- **LOC delta:** +~1,050 in `src/guide_emit.py`, −~1,100 in composer file,
  +~200 tests, +~50 SKILL.md.
- **Test count delta:** +~35 (1,010 → ~1,045).

## Out of scope

- Formal dataclasses for section content shapes — YAGNI until 2+ trips
  converge on the same shape.
- Trip-1 or trip-3 composers — future work.
- New visual primitives, palette rules, content-model changes.
- DB / storage-abstraction / `save_guide` changes.
