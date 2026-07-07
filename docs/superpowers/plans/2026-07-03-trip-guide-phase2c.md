# Trip-Guide Phase 2c Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract shared HTML/CSS emit helpers from `scripts/2026-06-27_compose_trip2.py`
into `src/guide_emit.py`, retrofit the trip-2 composer to import from it, and update
SKILL.md Step 7 to teach the two-track pattern for future composes.

**Architecture:** Free-function module (`src/guide_emit.py`) exposes ~14 pure emit helpers
that take palette / eras / trip_meta / prose-data as explicit args and return HTML/CSS
strings. Per-trip composers live under a new `compose/` package (starting with
`compose/trip_2.py`) and import from the shared module. No DB migration, no schema
change, no storage-abstraction touch — renderer-only refactor.

**Tech Stack:** Python 3.9, pytest, Flask-SQLAlchemy (only inside `compose/trip_2.py`
for DB reads; `src/guide_emit.py` is I/O-free).

**Design spec:** [../specs/2026-07-03-trip-guide-phase2c-design.md](../specs/2026-07-03-trip-guide-phase2c-design.md) — approved 2026-07-03.

---

## Background

Trip-2's compose script (`scripts/2026-06-27_compose_trip2.py`, 3,612 LOC) already
runs a two-track pattern internally: prose data in Python dicts at top; emit functions
render them. But every helper — from `esc` to the ~800-line `emit_css` — lives inside
the script. Nothing reuses across trips. SKILL.md Step 7 still tells Claude to
"Write the complete single-file HTML in one pass", so the next compose starts from
a blank editor.

Phase 2b's plan explicitly parked this refactor for Phase 2c ("Two-track compose
refactor" → out of scope). Tests currently at 1,010 passing.

Related prior work:

- [2026-06-27-trip-guide-phase2a-validation.md](../notes/2026-06-27-trip-guide-phase2a-validation.md) — Obs 5 named this refactor
- [2026-06-29-trip-guide-phase2b.md](2026-06-29-trip-guide-phase2b.md) — parked Obs 5 for Phase 2c
- [2026-07-03-trip-guide-phase2c-design.md](../specs/2026-07-03-trip-guide-phase2c-design.md) — this plan's authoritative spec

## File Map

| File | State | Responsibility |
|---|---|---|
| `src/guide_emit.py` | Create | Shared emit helpers: tier-1 primitives, palette-aware scaffolding, frame helper. No I/O. |
| `tests/test_guide_emit.py` | Create | Unit tests for each helper in `guide_emit`. ~35 tests. |
| `compose/__init__.py` | Create | Empty package marker so `python -m compose.trip_2` works. |
| `compose/trip_2.py` | Rename from `scripts/2026-06-27_compose_trip2.py` + retrofit | Live trip-2 composer. Prose dicts + per-section emitters + `compose()` driver. |
| `.claude/skills/trip-guide/SKILL.md` | Modify | Rewrite Step 7 for two-track pattern; add "Composer file conventions" subsection; two cross-ref notes. |

---

## Tasks

### Task 1 — Pre-retrofit audit snapshot

**Why:** Capture the reference chip counts + word count + banned-word hits from the
current compose. Task 4 diffs against these to prove the retrofit preserved output.

**Files:** none (data capture)

**Steps:**

- [ ] Run `.venv/bin/python scripts/2026-06-27_compose_trip2.py`
- [ ] From stdout, record the audit counts printed at the end: `practical-link`,
  `walkchip`, `era-chip`, `go-deeper`, `data-check-note`, banned-word grep hits,
  body word count
- [ ] Paste the captured audit output into this file's "Audit reference block" below

**Audit reference block** (captured 2026-07-03 08:33 from
`scripts/2026-06-27_compose_trip2.py` at HEAD `8ad15b0`, before the retrofit):

```
Trip 2 Scandinavia '26 — Deep tier compose

[1/4] Geocoding venues...
  Got coords for 86 of 86 venues
  Low-confidence venues (relevance < 0.7): 0

[2/4] Loading hotels + scanning for data gaps...
  11 hotels loaded, all geocoded: True
  Single-hotel trip: False
  Data-check gaps detected: 0

[3/4] Composing HTML...
  HTML composed: 200,594 chars

[4/4] Saving via save_guide...
  Saved: data/guides/2.html

--- Markup audit ---
  practical-link instances: 145
  walkchip instances:       53
  date-chip instances:      1
  go-deeper card sections:  6
  data-check-note callouts: 2
  era-chip instances:       6
```

**Companion metrics** (separately computed from `data/guides/2.html`, not part of
the script's built-in audit):

- HTML bytes: 201,906
- Body word count (post-`<script>`/`<style>`/quoted-material strip): 14,951
- Banned-word hits (SKILL.md Step 10 list, case-insensitive word-boundary grep): 0

**Preserved reference file** (for Task 3's byte-identity check):
`/private/tmp/claude-501/-Users-jeff-s-Projects-Vacation-Planner/88f92fde-7292-4958-82bf-080576803522/scratchpad/2.html.pre-retrofit`

**Numbers to preserve through Task 4** — any drift here is a bug:
practical-link 145, walkchip 53, date-chip 1, go-deeper 6, data-check-note 2,
era-chip 6, banned-word hits 0, HTML bytes ~200k, body words ~14,950
(whitespace-tolerant ±5 words is acceptable; count deltas are not).

**Verify:** stdout printed cleanly; numbers copied into the reference block.

**Tests:** none

**Commit:** none — data capture only.

---

### Task 2 — Build `src/guide_emit.py` + `tests/test_guide_emit.py`

**Why:** Ship the shared module and its tests before touching the composer. Once
this task is committed, the retrofit in Task 4 is an isolated change with a
green baseline.

**Files:**

- Create: `src/guide_emit.py`
- Create: `tests/test_guide_emit.py`

**Public surface** (verbatim from design spec):

```python
"""guide_emit — shared HTML/CSS emit helpers for trip-guide composers.

Pure rendering. No DB I/O, no filesystem, no module-level mutable state.
Each function takes the data it needs as args and returns HTML/CSS strings.
Per-trip composers (compose/trip_<id>.py) import from here.
"""
from typing import Any, Dict, List, Literal, Optional, Tuple

def esc(s: str) -> str: ...
def reading_time(text: str) -> int: ...
def permalink(slug: str, label: str) -> str: ...
def reading_time_chip(text: str, slug_label: str) -> str: ...
def emit_h2(slug: str, label: str, slug_label: str, body_text: str) -> str: ...
def category_color(cat: str) -> str: ...

def emit_practical_link(name: str, city: str, full_text: Optional[str] = None) -> str: ...
def emit_walking_chip(
    venue_key: Optional[str],
    hotel: Optional[Dict[str, Any]],
    venue_coords: Dict[str, Tuple[float, float]],
    venue_relevance: Dict[str, Optional[float]],
) -> str: ...

def emit_css(palette: Dict[str, Any], eras: List[Dict[str, str]]) -> str: ...
def emit_js() -> str: ...
def emit_hero(trip_meta: Dict[str, Any], palette_name: str) -> str: ...
def emit_toc(slugs: List[Tuple[str, str]]) -> str: ...
def emit_go_deeper(cards: List[Dict[str, str]]) -> str: ...

def emit_section_wrapper(
    slug: str,
    label: str,
    kind: Literal["atmospheric", "practical"],
    body_html: str,
    *,
    go_deeper_html: str = "",
    slug_label: Optional[str] = None,
) -> str: ...
```

**Implementation source:** copy each function body from
`scripts/2026-06-27_compose_trip2.py`. Line ranges per design spec's What-moves table:

| Function | Copy from lines | Signature change |
|---|---|---|
| `esc`, `reading_time`, `permalink`, `reading_time_chip`, `emit_h2`, `category_color` | ~1975–2041 | None |
| `emit_practical_link` | ~2002–2007 | None |
| `emit_walking_chip` | New body, lifting logic from `emit_walking_chip_for_card` (~2010–2030) | Takes `venue_key` + `hotel` dict directly (not `card["venue_key"]`) |
| `emit_css` | ~2047–2862 | Takes `palette: dict, eras: list` args instead of reading module globals |
| `emit_js` | ~2867–2971 | None |
| `emit_hero` | ~2976–3029 | Takes `(trip_meta, palette_name)`; renders `trip_meta.get("route_svg", "")` verbatim (composer supplies the SVG) |
| `emit_toc` | ~3032–3043 | None |
| `emit_go_deeper` | ~3046–3066 | Takes `cards: list` directly (not `section_key: str` + module `GO_DEEPER` dict) |
| `emit_section_wrapper` | NEW | Combines `emit_h2` + `<section class="section--{atmospheric|practical}">` wrapper + `body_html` + optional trailing `go_deeper_html` |

**Input-shape docstring block** at the top of `guide_emit.py` (verbatim from spec):

```python
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
```

**Test list** (names only, ~35 tests):

- `test_esc_escapes_html_special_chars`
- `test_esc_quote_mode_on`
- `test_reading_time_words_over_220_wpm_ceil`
- `test_reading_time_strips_html_tags`
- `test_reading_time_returns_at_least_one`
- `test_permalink_produces_anchor_with_hash_slug`
- `test_permalink_escapes_label_in_aria`
- `test_reading_time_chip_contains_minutes_and_slug_label`
- `test_emit_h2_contains_slug_id_reading_time_chip_permalink`
- `test_emit_h2_escapes_label`
- `test_category_color_known_categories_map_correctly`
- `test_category_color_unknown_falls_back_to_other`
- `test_emit_practical_link_url_encodes_name_and_city`
- `test_emit_practical_link_sets_rel_noopener_target_blank`
- `test_emit_practical_link_uses_full_text_when_passed`
- `test_emit_walking_chip_empty_when_venue_key_none`
- `test_emit_walking_chip_empty_when_hotel_none`
- `test_emit_walking_chip_empty_when_coords_missing`
- `test_emit_walking_chip_empty_when_hotel_missing_lat`
- `test_emit_walking_chip_delegates_confidence_to_walking_distance` (via monkeypatch or spy)
- `test_emit_walking_chip_passes_hotel_title_through`
- `test_emit_css_palette_colors_emitted_as_root_vars`
- `test_emit_css_era_slugs_emitted_as_variables_and_class_rules`
- `test_emit_css_fonts_substituted`
- `test_emit_css_empty_eras_produces_no_era_css_no_crash`
- `test_emit_js_returns_non_empty_string`
- `test_emit_js_contains_mode_toggle_iife_marker`
- `test_emit_hero_contains_trip_title_and_palette_name_eyebrow`
- `test_emit_hero_route_svg_inserted_verbatim`
- `test_emit_hero_absent_route_svg_omits_element`
- `test_emit_hero_escapes_user_supplied_strings`
- `test_emit_toc_produces_anchor_per_slug`
- `test_emit_toc_escapes_label`
- `test_emit_go_deeper_empty_card_list_returns_empty_string`
- `test_emit_go_deeper_n_cards_produce_n_articles`
- `test_emit_section_wrapper_atmospheric_kind_class`
- `test_emit_section_wrapper_practical_kind_class`
- `test_emit_section_wrapper_slug_becomes_section_id`
- `test_emit_section_wrapper_body_html_spliced_inside`
- `test_emit_section_wrapper_go_deeper_appended_when_non_empty`
- `test_emit_section_wrapper_no_trailing_aside_when_go_deeper_empty`
- `test_emit_section_wrapper_slug_label_falls_back_to_label`

Total: 42 test names. All pure-Python string checks; no fixtures, no DB, no Flask.

**Verify:**

- [ ] `.venv/bin/pytest tests/test_guide_emit.py -q` → all new tests pass
- [ ] `.venv/bin/pytest tests/ -q` → existing 1,010 still green (module addition can't
  break anything not imported yet)

**Commit:** `feat(guide_emit): extract shared trip-guide emit helpers to src module`

---

### Task 3 — Rename + move the composer to `compose/`

**Why:** Establish the new package layout before doing any code changes. Isolating
the rename in its own commit keeps `git log --follow` clean over the retrofit diff.

**Files:**

- Create: `compose/__init__.py` (empty file, single newline)
- Rename: `scripts/2026-06-27_compose_trip2.py` → `compose/trip_2.py`

**Steps:**

- [ ] Write `compose/__init__.py` as an empty file (single newline)
- [ ] Run: `git mv scripts/2026-06-27_compose_trip2.py compose/trip_2.py`
- [ ] Fix the module's shebang / `if __name__ == "__main__":` block if needed so
  `python -m compose.trip_2` runs. The existing `main()` invocation pattern should
  work as-is; verify.
- [ ] Run: `.venv/bin/python -m compose.trip_2` — should complete a compose end-to-end
  exactly as before (all helpers are still defined locally at this point; nothing
  imports from `guide_emit` yet)
- [ ] Diff the freshly-generated `data/guides/2.html` against the pre-rename version
  (from Task 1). Byte-identical is the pass bar — the code is unchanged; only the
  file path moved.

**Note on import compatibility:** the existing script does `from app import app` and
similar top-level imports. These still work from `compose/trip_2.py` because the
project root stays on `sys.path` for the `-m` form. No import changes needed here.

**Verify:**

- [ ] `python -m compose.trip_2` succeeds
- [ ] `diff` of `data/guides/2.html` vs pre-rename snapshot is empty (or whitespace-only)
- [ ] `git log --follow compose/trip_2.py` shows the full history back through
  `scripts/2026-06-27_compose_trip2.py`

**Tests:** existing 1,010 stay green: `.venv/bin/pytest tests/ -q`.

**Commit:** `chore(trip-guide): move trip-2 composer to compose/ package`

---

### Task 4 — Retrofit `compose/trip_2.py` to import from `src.guide_emit`

**Why:** Land the two-track split. Composer file drops ~1,100 LOC (the helpers now
live in `src/guide_emit.py`); per-section emitters simplify via `emit_section_wrapper`;
`compose()` unpacks `((slug, label), html)` tuples.

**Files:**

- Modify: `compose/trip_2.py`

**Changes** (in order, so partial in-progress state stays runnable):

1. **Add the import block.** Near the existing imports:

```python
from src.guide_emit import (
    esc, emit_h2, emit_practical_link, emit_walking_chip, category_color,
    emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper,
    emit_section_wrapper,
)
```

2. **Delete local helper defs that now duplicate imports.** Function-by-function,
delete the local `def` block and confirm compose still runs after each delete
(`.venv/bin/python -m compose.trip_2 > /dev/null`). Order — same order as spec's
What-moves table:

   - `esc`, `reading_time`, `permalink`, `reading_time_chip`, `emit_h2`, `category_color`
   - `emit_practical_link`
   - `emit_walking_chip_for_card` — replace all callsites with `emit_walking_chip(card.get("venue_key"), hotel, venue_coords, venue_relevance)` before deleting; grep the file for `emit_walking_chip_for_card` to enumerate callsites
   - `emit_css` — update the one callsite in `compose()` to pass `(PALETTE, ERAS)` explicitly
   - `emit_js`
   - `emit_hero` — hero currently reads globals `PALETTE`, `TRIP_META`, and inlines the route SVG. Before deleting: (a) lift the inlined route SVG string into `TRIP_META["route_svg"]`; (b) change the callsite in `compose()` to `emit_hero(TRIP_META, PALETTE["name"])`
   - `emit_toc`
   - `emit_go_deeper` — replace callsites: was `emit_go_deeper("day_by_day")`, becomes `emit_go_deeper(GO_DEEPER["day_by_day"])`; grep for callsites, ~9 of them (one per section that has a go-deeper row — currently day_by_day, field_guide, history, food)

3. **Rewrite per-section emitters.** Each of `emit_day_by_day`, `emit_field_guide`,
`emit_things_to_do`, `emit_weather`, `emit_history`, `emit_fun_facts`, `emit_food`,
`emit_beer`, `emit_sources` follows this shape after change:

```python
def emit_day_by_day(hotels, venue_coords, venue_relevance, gaps_by_date):
    """Returns ((slug, label), section_html)."""
    body_parts = []
    for day in DAY_BY_DAY:
        # ...existing day-card build logic — unchanged
        body_parts.append(day_html)
    body_html = "\n".join(body_parts)
    section_html = emit_section_wrapper(
        slug="days", label="Day by day", kind="atmospheric",
        body_html=body_html,
        go_deeper_html=emit_go_deeper(GO_DEEPER.get("day_by_day", [])),
    )
    return ("days", "Day by day"), section_html
```

Section slug + label + kind reference table (fill in during retrofit):

| Emitter | slug | label | kind |
|---|---|---|---|
| `emit_day_by_day` | `days` | `Day by day` | atmospheric |
| `emit_field_guide` | `field-guide` | `Field guide` | atmospheric |
| `emit_things_to_do` | `things-to-do` | `Things to do` | atmospheric |
| `emit_weather` | `weather` | `Weather` | practical |
| `emit_history` | `history` | `History` | atmospheric |
| `emit_fun_facts` | `fun-facts` | `Fun facts` | practical |
| `emit_food` | `food` | `Food` | atmospheric |
| `emit_beer` | `beer` | `Beer & breweries` | atmospheric |
| `emit_sources` | `sources` | `Sources & further reading` | practical |

*(Copy actual slug/label from the current emit's `<h2 id="…">` and text; correct
during retrofit if any diverge from the table.)*

4. **Rewrite `compose()`** to unpack the new tuple returns:

```python
def compose(venue_coords, venue_relevance, hotels, is_single_hotel, gaps_by_date):
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
```

Existing `compose()` builds the same structure inline; the change is the tuple
unpacking + explicit `(PALETTE, ERAS)` / `PALETTE["name"]` args.

**Verify (the retrofit's own safety net):**

- [ ] `.venv/bin/python -m compose.trip_2` succeeds
- [ ] Audit output printed at end of run matches Task 1's snapshot **exactly**:
  `practical-link`, `walkchip`, `era-chip`, `go-deeper`, `data-check-note`
  counts identical; body word count within ±5 words; banned-word hits = 0
- [ ] Any audit-count drift is a bug — trace it before commit. Common causes:
  missed callsite for `emit_walking_chip_for_card` → `emit_walking_chip`, or
  `emit_go_deeper` callsite not updated to pass the card list.
- [ ] `.venv/bin/pytest tests/ -q` — all 1,010 + 42 = 1,052 tests green

**Commit:** `refactor(compose/trip_2): use src.guide_emit for shared rendering`

---

### Task 5 — Frontend verification (mandatory per CLAUDE.md)

**Why:** CLAUDE.md's frontend-verification rule: tests-pass ≠ page-works. A
subtle whitespace glitch or a stray `data-mode` change wouldn't show up in unit
tests but would break the browser experience.

**Files:** none (verification only)

**Steps:**

- [ ] Confirm dev server is running: `curl -s http://localhost:5002/ | head -5`.
  If not: `scripts/dev.sh` (or `.venv/bin/python app.py`) in a background terminal.
- [ ] Load `http://localhost:5002/trips/2/guide?v=phase2c` via the `webapp-testing`
  skill (or Chrome MCP; use `open http://localhost:5002/...` not the `127.0.0.1` form
  per CLAUDE.md's OAuth note).
- [ ] Assert **zero** browser console errors. A JS SyntaxError would silently kill
  the mode toggle + TOC scroll-spy + field-guide filter.
- [ ] Assert visible affordances:
  - Hero eyebrow reads "Trip guide · nordlys"
  - Trip title present
  - Sticky TOC has ≥ 8 anchors (matches 2026-06-27 count post-beer)
  - Sections `#days`, `#field-guide`, `#things-to-do`, `#weather`, `#history`,
    `#food`, `#beer`, `#fun-facts`, `#sources` all present in the DOM
  - Mode toggle (Skim / Standard / Deep) buttons present and clickable; clicking
    each toggles `data-mode` on `<body>` correctly
  - "Save as PDF" button present at top-right (injected by `guide_builder`)
- [ ] Print-preview check: browser print-preview shows all `.deep` content
  (mode-toggle hides ignored under `@media print`)
- [ ] `preview_resize` to 600px width — mobile single-column layout intact

If any assert fails: do not commit. Trace to the retrofit and fix.

**Tests:** none — this is browser-side.

**Commit:** none — verification only.

---

### Task 6 — SKILL.md updates

**Why:** Without updating SKILL.md, the next `/trip-guide` invocation would still
follow the old "write HTML in one pass" instruction and re-implement all the helpers
inline. This task teaches the pattern.

**Files:**

- Modify: `.claude/skills/trip-guide/SKILL.md`

**Edit 1 — Replace Step 7 body.** Grep for `### 7. Compose the HTML` and replace
the entire step (roughly 15 lines today) with the following:

```markdown
### 7. Compose the HTML

Build the guide as `compose/trip_<id>.py` following the two-track pattern:
**Track 1 (top of file):** Python dicts + lists holding prose data and configuration
(PALETTE, ERAS, TRIP_META, GO_DEEPER, plus one dict/list per section — DAY_BY_DAY,
FIELD_GUIDE, and so on).
**Track 2 (below):** per-section emitter functions that iterate track-1 data and
return HTML, plus a `compose()` driver that concatenates them.

All shared rendering — CSS, JS, hero, TOC, go-deeper card rows, section wrappers,
practical links, walking chips, text primitives — lives in `src/guide_emit.py`.
Import what you need:

```python
from src.guide_emit import (
    esc, emit_h2, emit_practical_link, emit_walking_chip, category_color,
    emit_css, emit_js, emit_hero, emit_toc, emit_go_deeper, emit_section_wrapper,
)
```

**Canonical worked example:** [`compose/trip_2.py`](../../compose/trip_2.py) is the
reference implementation. Copy its structure — imports, prose-data ordering,
per-section emitter pattern, and the way `compose()` returns `((slug, label), html_str)`
tuples from each section emitter so the TOC stays in lock-step with the section list.

Requirements (unchanged):

- Inlined CSS via `emit_css(PALETTE, ERAS)` — no external stylesheet
- Fonts via Google Fonts CDN only
- Vanilla JS via `emit_js()` — no framework
- Mobile-responsive (single-column under 600px)
- `@media print` coverage
- `prefers-reduced-motion: reduce` respected
- Field-guide section: interactive search + chip filters (JS lives in `emit_js()`)
- No external images

Save via `guide_builder.save_guide(trip_id, html)` — see Step 8.
```

**Edit 2 — Add "Composer file conventions" subsection.** Insert this ~30-line block
between the end of the 10-step flow (after Step 10 wrap-up) and the beginning of
"## Section content model":

```markdown
## Composer file conventions

**File name.** One composer per trip, `compose/trip_<id>.py`. Versioned in git.
Never re-use a trip's composer across trips — copy and adapt.

**File section ordering** (top to bottom):

1. Imports (stdlib → third-party → `app` / `models` / `src`)
2. Trip-wide constants: `TRIP_ID`, `PALETTE`, `ERAS`, `TRIP_META`, `GO_DEEPER`,
   `SOURCES_NOTE`
3. Per-section prose dicts: `DAY_BY_DAY`, `FIELD_GUIDE`, `THINGS_TO_DO`, `WEATHER`,
   `HISTORY`, `FUN_FACTS`, `FOOD`, plus any themed-bonus dicts
4. Per-section emitters (one function per section)
5. `compose(...)` driver
6. `main()` — geocoding, gap detection, compose, save, audit-print

**Per-section emitter return convention.** Every per-section emitter returns a
`((slug: str, label: str), html: str)` tuple. The compose driver unpacks these:
slugs feed `emit_toc`; html strings concatenate into the page body. This keeps
the TOC in lock-step with the section list — a future edit can't add a section
without adding a TOC entry.

**Input-shape source of truth.** The docstrings in `src/guide_emit.py` document
the exact shapes for `palette`, `eras`, `hotel`, `trip_meta`, `go-deeper cards`.
The composer's dicts conform to those shapes.

**Route SVG.** `emit_hero` renders `trip_meta["route_svg"]` verbatim; the composer
builds the SVG string itself (each trip has its own geometry) and puts it into
`TRIP_META["route_svg"]` before calling `compose()`. Absent key → no SVG in hero.
```

**Edit 3 — Add cross-reference notes in existing sections.**

- In `## Walking-distance chips` → `### Helper invocation`, append one line after
  the existing example:

```markdown
Composers call the wrapper `emit_walking_chip(venue_key, hotel, venue_coords,
venue_relevance)` from `src.guide_emit`, which threads the composer-facing shape
into `walking_distance.walking_chip`'s positional call.
```

- In `## Practical hyperlinks` → `### Helper invocation`, append one line after
  the existing example:

```markdown
Composers call `emit_practical_link(name, city, full_text=None)` from
`src.guide_emit` — same behaviour, thin adapter around `place_links.practical_link`.
```

**Verify:**

- [ ] Grep the modified SKILL.md for `2026-06-27_compose_trip2` — should be zero
  hits (the old script path is gone from the guidance)
- [ ] Grep for `src.guide_emit` — should show hits in Step 7, in the composer-conventions
  subsection, and in the two cross-references
- [ ] Read the diff end-to-end for internal consistency

**Tests:** none.

**Commit:** `docs(trip-guide): document two-track compose pattern in SKILL.md`

---

## Self-Review

**Spec coverage:**

- Design § Architecture (module layout, what moves) → File Map + Task 2 ✓
- Design § Public surface → Task 2 (verbatim block) ✓
- Design § Per-trip composer shape → Task 4 (per-section emitter pattern + tuple returns) ✓
- Design § SKILL.md updates (edits 1/2/3 + cross-refs) → Task 6 ✓
- Design § Tests (~35 unit tests + audit-count regression) → Task 2 (42 tests) + Task 4 (audit diff) ✓
- Design § Migration path (6 steps → 4 commits) → Tasks 1-6 map 1:1 ✓
- Design § Non-goals (no dataclasses, no schema change) → nothing in the plan touches them ✓

**Type consistency:**

- `emit_section_wrapper(slug, label, kind, body_html, *, go_deeper_html="", slug_label=None)`
  in Task 2 matches call-site pattern in Task 4 per-section emitters ✓
- `emit_walking_chip(venue_key, hotel, venue_coords, venue_relevance)` in Task 2
  matches callsite update instruction in Task 4 step 2 ✓
- Per-section emitter return `((slug, label), html)` in Task 4 step 3 matches
  `compose()` unpack in Task 4 step 4 ✓
- `emit_hero(trip_meta, palette_name)` in Task 2 matches call `emit_hero(TRIP_META,
  PALETTE["name"])` in Task 4 step 4 ✓
- `emit_go_deeper(cards)` in Task 2 matches callsite update in Task 4 step 2
  (`emit_go_deeper(GO_DEEPER["day_by_day"])`) ✓
- `emit_css(palette, eras)` in Task 2 matches `emit_css(PALETTE, ERAS)` in Task 4 ✓

**Placeholder scan:** no "TBD", "TODO", "handle edge cases", "add appropriate
error handling", "similar to Task N", "implement later" in the plan. Task 1
intentionally leaves an "Audit reference block" placeholder that gets filled
during execution — that's data capture, not a spec gap.

**Scope check:** 6 tasks, ~450 lines. Under the project caps (17 tasks, 1,000
lines). Non-goals from the design spec (dataclasses, trip-1/trip-3 composers,
schema changes) are absent from the plan by construction.

---

## Out of scope (deferred to future phases)

- Formal dataclasses for section content shapes — YAGNI until ≥ 2 trips converge
  on the same shape.
- Migrating trip-1 and trip-3 (and future) composers to `compose/trip_<id>.py`.
  Each is its own compose run; the retrofit here proves the shared module works.
- New visual primitives, palette rules, content-model changes — Phase 2c is a
  renderer refactor, not a content-spec change.
- ~~Storage-backend work (`GUIDE_STORAGE=database`) — still `NotImplementedError`;
  Phase 2c doesn't touch it.~~ Shipped 2026-07-07 —
  see [../plans/2026-07-07-guide-storage-db-backend.md](2026-07-07-guide-storage-db-backend.md).
