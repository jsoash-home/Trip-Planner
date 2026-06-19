---
name: trip-guide
description: Generate a bespoke single-file HTML trip guide for a Vacation Planner trip. Reads bookings + itinerary from vacation.db and writes the guide to data/guides/<trip_id>.html. Use when the user asks to build, generate, regenerate, or share a trip guide. Requires no Anthropic API key — runs entirely in Claude Code.
---

# Trip Guide Generator

Builds a souvenir-grade, single-file HTML trip guide sourced from the user's
actual bookings and itinerary in `vacation.db`. The visual quality bar is set
by two benchmark files (see below). Each guide earns its own bespoke palette
and editorial voice — never templated, never generic.

## When to use this skill

Trigger on any of:
- "build a trip guide" / "generate a guide for [trip]"
- "regenerate the Iceland guide" / "redo the guide"
- "share my trip guide with [person]" (implies guide may need minting or a share token)
- Any natural-language request involving HTML guides for trips in this project

## Quality bar — read the benchmarks first

Before composing HTML for any new destination, read both benchmark files:

- `~/Downloads/galapagos-wildlife-guide.html` — 1,112 lines. Filterable wildlife
  encyclopedia: sticky search + chip filters, bespoke palette, custom typography,
  card grid, vanilla JS throughout. Study the palette discipline and card structure.
- `~/Downloads/Galapagos_Field_Log_Mar27-Apr3_2027.html` — 455 lines. Day-by-day
  editorial field log: per-day island sections, timed site cards, history/fact tags,
  life-list footer, serif body text, strong editorial voice.

Match: typographic polish, palette discipline, editorial voice, single-file HTML
approach, `@media print` coverage, mobile-responsive layout, `prefers-reduced-motion`
respect. Each destination should feel custom-designed, not like a template fill-in.

---

## The 10-step flow

Work through these in order. Do not skip a step. Check off each one before advancing.

### 1. Resolve the trip

Ask the user for a trip ID or trip name. If a name is given, query `vacation.db`
to find matches (multiple results → present a numbered chooser). Confirm back before
proceeding:

> "Iceland, Aug 17–24 2026 · 7 days · 3 bookings · 12 itinerary items — right?"

### 2. Load trip data

```python
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///vacation.db")
from app import app
from src import guide_builder
with app.app_context():
    data = guide_builder.load_trip_data(trip_id)
    # data = {"trip": {...}, "bookings": [...], "itinerary": [...], "collaborators": [...]}
```

Itinerary is pre-grouped by `day_date` and sorted via `sort_within_day`.
Bookings include their `linked_booking_id` itinerary children.

### 3. Detect prior run

```python
with app.app_context():
    cfg = guide_builder.load_or_init_config(trip_id)
```

If `cfg.last_generated_at` is set, present three options and wait for user choice:

1. Regenerate with same sections (reuse saved sections + palette; re-research; overwrite)
2. Change sections (re-run the picker; optionally re-pick palette)
3. Cancel

Never auto-regenerate without asking.

### 4. Section picker

Present a multi-select from the 7-section catalog. The user picks a subset.
Save their choice immediately via `guide_builder.save_config(trip_id, cfg)`.

| Key | Section |
|---|---|
| `day_by_day` | Editorial timeline from itinerary + bookings |
| `field_guide` | Filterable encyclopedia (wildlife / museums / landmarks) |
| `things_to_do` | Curated picks, distinct from field guide |
| `weather` | 4-stat grid + season notes + packing implications |
| `history` | Prose + phrase table |
| `fun_facts` | 2-col trivia + practical tips |
| `food` | "Things to try" cards + "where to eat" by price tier |

All 7 can be included. Any subset is valid. The picker is the source of truth —
the skill does NOT auto-detect "nature trip" and skip sections.

### 5. Palette proposal

Research the destination's feel: climate, landscape, cultural mood, time of year.
Propose a palette archetype with concrete hex codes and a font pairing. For example:

> "Iceland: basalt-black (#1a1a1e) + aurora-green (#47d58a) + glacier-white (#f2f5f9),
> display: Bricolage Grotesque (Google Fonts), body: Spectral"

User accepts, steers, or substitutes. Save the agreed palette to `cfg.palette`,
then call `save_config`. Never reuse a previous trip's palette wholesale.

### 6. Research + compose section by section

Use Claude's built-in knowledge as the primary source. Use `WebSearch` / `WebFetch`
for current information (festival dates, recent restaurant openings, transport specifics).
No Anthropic API key consumed — research runs inside Claude Code.

Work through each selected section in order: draft, then refine. Aim for editorial
quality: specific names, actual context, useful detail. No placeholders, no filler.
Each section should feel like it was written by someone who has been there.

### 7. Compose the HTML

Write the complete single-file HTML in one pass. Requirements:

- Inlined CSS — no external stylesheet
- Fonts via Google Fonts CDN only (no other external assets)
- No JS framework — vanilla JS only
- Mobile-responsive — single-column under 600px
- Print-friendly — `@media print` shows all content, hides sticky nav + chips, uses serif body
- `prefers-reduced-motion: reduce` respected (skip transitions/animations)
- The `field_guide` section ships ~80 lines of vanilla JS for search + chip filters
- Every other section is static HTML + CSS
- No external images — inline SVG / CSS only

Always present: wrapper header (trip title, dates, destination, day count, mono eyebrow),
sticky section nav (when 2+ sections), and footer (trip ID, last-generated timestamp,
palette name).

### 8. Save

```python
with app.app_context():
    path = guide_builder.save_guide(trip_id, html)
```

`save_guide` handles: atomic write (temp file + `os.replace`), `.bak` rotation of
previous guide, `last_generated_at` bump. Do NOT write the HTML file directly to
`data/guides/` — always call `save_guide`.

### 9. Share-token decision

On first run (or when the user asks on-demand), prompt:

> "Generate a shareable public link? (y/n)"

If yes:

```python
with app.app_context():
    token = guide_builder.set_share_token(trip_id)
```

If the trip already has a token, `set_share_token` is idempotent — returns the
existing token. Print both URLs at the end of the run:

- Gated: `http://localhost:5002/trips/<id>/guide`
- Public (only when token minted): `http://localhost:5002/guides/share/<token>`

On regeneration, never auto-rotate the token — existing links keep working.

### 10. Frontend verification (mandatory per CLAUDE.md)

This step is not optional. Do it before claiming success.

1. Confirm dev server is running: `curl -s http://localhost:5002/ | head -5`
   — must return something. If not, stop and report.

2. Load the generated guide via the `webapp-testing` skill. Assert:
   - Zero browser console errors (a JS SyntaxError will silently kill the page)
   - Visible content: look for "Day 1", section headings, or the trip name

3. Load `/trips/<id>` via the `webapp-testing` skill. Assert:
   - Hero card is visible with the "TRIP GUIDE" eyebrow and "Open guide" button

If either check fails, surface the console error or missing element and stop.
Do not smooth over failures with "probably fine."

---

## Section content model

### day_by_day

Editorial timeline. Per-day section: large day number + date, 1–2 sentence intro,
site cards in time order. Each card: mono time badge, name, 2–3 sentences of context,
optional history / fun-fact tags. Inputs: itinerary items grouped by `day_date`
via existing `src/itinerary.py:group_items_by_day`, plus bookings overlapping each
day. ~150–300 words per day. Layout mirrors `Galapagos_Field_Log_Mar27-Apr3_2027.html`.

### field_guide

Filterable encyclopedia. Sticky search bar + filter chips, card grid. Each card:
name, optional latin / local-language name, likelihood or quality badge, 1–2 line
description, "best day to encounter" tags. Vanilla JS for search + chip toggles.
Adapts by destination: nature trip → species; city → museums + landmarks. Layout
mirrors `galapagos-wildlife-guide.html`.

### things_to_do

Curated picks — distinct from field guide (encyclopedia vs editorial recommendations).
No search, no chips. Grouped: morning ideas, evening ideas, half-day excursions,
rainy-day fallbacks. Each entry: name, neighborhood, why it's worth it, what to
pair with it, optional cost / time-needed note. ~12–25 picks. Exclude items the
user has already booked — no redundant suggestions.

### weather

Four-stat grid (daily high, daily low, rainfall, daylight hours). Short timing
paragraph: season-tied phenomena (festivals, migrations, monsoon windows, full-moon
events). Optional 3–4 bullet packing implications (e.g. "layers essential — mornings
can be 10°C colder than noon").

### history

Prose-led. 3–5 short headed paragraphs: compressed history, why the place feels
the way it feels, etiquette norms. Closes with a small phrase table: greeting /
please / thank you / excuse me / "do you speak English?" / numbers 1–10. ~500–800
words total.

### fun_facts

Two-column on desktop, stacked on mobile. Left column: 8–12 short trivia bullets.
Right column: tipping norms, plug type, transit + card tips, money / ATM tips,
common scams, emergency numbers, SIM / eSIM advice.

### food

Short prose intro on the food culture, then two subsections:

- **Things to try** — card grid, 8–15 entries. Each: dish or drink name, optional
  local-language name in mono, 1–2 line description, optional "best eaten" hint,
  small tag (dish / drink / street snack / breakfast / dessert).

- **Where to eat** — grouped by four price tiers: Splurge, Sit-down, Casual,
  Street + markets. 3–5 entries per tier. Each: name, neighborhood, signature dish,
  why, optional logistics tag. **Booked restaurants from the user's trip appear in
  their correct price tier with a "✓ you've booked" tag** — do not filter them out.

---

## Helper invocation pattern

Always push a Flask app context before any helper call. Template:

```python
import os
os.environ.setdefault("DATABASE_URL", "sqlite:///vacation.db")
from app import app
from src import guide_builder

trip_id = 7  # replace with actual ID

with app.app_context():
    data = guide_builder.load_trip_data(trip_id)
    cfg = guide_builder.load_or_init_config(trip_id)

    # After picking sections and palette:
    cfg.sections = ["day_by_day", "food", "weather"]
    cfg.palette = {"name": "basalt-aurora", "colors": {"bg": "#1a1a1e", ...}, "fonts": {...}}
    guide_builder.save_config(trip_id, cfg)

    # After composing html:
    path = guide_builder.save_guide(trip_id, html)

    # Optionally mint a share token:
    token = guide_builder.set_share_token(trip_id)
```

Available helpers:

| Function | Purpose |
|---|---|
| `load_trip_data(trip_id)` | Returns `{trip, bookings, itinerary, collaborators}` as plain dicts |
| `load_or_init_config(trip_id)` | Reads JSON sidecar; missing / corrupt → fresh config + logged warning |
| `save_config(trip_id, cfg)` | Atomic write of `GuideConfig` to `data/guides/<id>.config.json` |
| `save_guide(trip_id, html)` | Rotates `.bak`, atomic-writes HTML, bumps `last_generated_at` |
| `read_guide(trip_id)` | Returns HTML bytes; raises `GuideMissing` if absent |
| `guide_exists(trip_id)` | `True` if `data/guides/<id>.html` exists |
| `set_share_token(trip_id)` | Mints UUID token; idempotent if already set |
| `clear_share_token(trip_id)` | Clears the token; idempotent |
| `trip_by_share_token(token)` | Returns `Trip` or `None` (never raises) |

---

## Anti-patterns

**Do NOT:**

- Generate placeholder content: no "Lorem ipsum", "Day intro TBD", "TODO: research this".
  If you don't have enough to fill a section well, say so and ask the user.
- Skip the frontend verification step (step 10). Tests passing is not the same as the
  page working. A JS `SyntaxError` at line 1 silently kills the entire file.
- Write to `vacation.db` directly. The only permitted DB writes are `set_share_token`
  and `clear_share_token`, called through the helper.
- Embed images from external URLs. Inline SVG / CSS gradients only.
- Reuse a previous trip's palette — each trip earns its own.
- Auto-regenerate without asking (step 3). Existing guides represent real work.
- Bypass the storage abstraction. Always call `save_guide` / `read_guide`. Never
  open `data/guides/<id>.html` directly in the skill.

---

## First-run handoff format

After successful generation, print a concise summary:

```
Trip:      Iceland · Aug 17–24 2026 · 7 days
Sections:  day_by_day, field_guide, weather, food
Palette:   basalt-aurora (#1a1a1e · #47d58a · #f2f5f9)
File:      data/guides/7.html
Gated URL: http://localhost:5002/trips/7/guide
Share URL: http://localhost:5002/guides/share/a3f9... (if minted)
```

Close with 1–2 honest observations about what's strong and what could be expanded
in a follow-up pass. For example: "the History section is brief — period-specific
research would strengthen it" or "the field guide has 22 entries; filtering by
day works well."
