# Trip Guide Skill — Design

**Date:** 2026-06-19
**Status:** Approved, ready for implementation plan
**Scope:** New Claude Code skill + `src/guide_builder.py` helper + 2 Flask routes + 1 DB column + 1 template partial + a small CSS/JS hookup. No changes to bookings, itinerary, packing, sharing, or countdown logic.

## Problem

The user has been hand-building beautiful per-trip HTML reference documents (e.g. `~/Downloads/galapagos-wildlife-guide.html` — a 1,112-line filterable wildlife encyclopedia with sticky search and bespoke palette; `~/Downloads/Galapagos_Field_Log_Mar27-Apr3_2027.html` — a 455-line day-by-day editorial field log). They're high-quality souvenir-grade artifacts.

Two pain points:

1. The work is one-off and manual. Each new trip needs the same kind of artifact built from scratch in claude.ai — copying in dates, bookings, itinerary by hand. The Vacation Planner app already holds this data; the artifact should be sourced from it.
2. The finished artifact lives in Downloads, disconnected from the trip. The user wants the guide to appear *inside* the trip page in Vacation Planner as a prominent hero link.

## Goals

1. From Claude Code in this project, run a skill that generates a single-file HTML trip guide and saves it where the Vacation Planner app can serve it.
2. The guide uses the user's actual bookings and itinerary from `vacation.db` as the spine — no copy/paste.
3. The guide supports a modular section catalog the user picks from per trip.
4. The visual quality matches the Galápagos benchmarks: bespoke palette per destination, custom typography, print-friendly, offline-capable, mobile-responsive.
5. The trip overview page in Vacation Planner displays a hero card linking to the guide when one exists.
6. Optionally, the user can mint a public shareable link they send to friends without making the friend a collaborator.
7. The skill requires no Anthropic API key — research runs through Claude Code itself.

## Non-goals (v1)

- **In-app guide-generation UI.** No button in Vacation Planner that triggers generation. The skill is the only way to produce a guide.
- **In-app share-token management UI.** All share token operations go through the skill, not the website.
- **Partial regeneration.** "Regenerate just the weather section" is not supported. Regen is whole-file.
- **Multi-version history.** Only one "current" guide per trip plus one rolling `.bak` of the previous version. No timestamped archives.
- **Templated layout via Jinja.** Each guide's HTML is hand-crafted by Claude in one pass. Templating would dilute the bespoke feel.
- **Auto-deletion of the guide file when a trip is deleted.** Orphans linger harmlessly in `data/guides/`; cleanup is a future polish.
- **Image generation, image hosting, or embedded photos.** Inline SVG / CSS only.

## Decisions (locked during brainstorming)

| Question | Choice |
|---|---|
| Artifact shape | Modular — user picks sections per trip |
| Trip data source | Skill reads `vacation.db` directly via `src/guide_builder.py` |
| Output storage (today) | Filesystem: `data/guides/<trip_id>.html` |
| Output storage (cloud-hosted future) | DB column, behind a `GUIDE_STORAGE` env-var dispatch |
| Section selection mechanism | Interactive picker on first run; cached in JSON sidecar |
| Visual style | Bespoke palette per trip |
| Section catalog | 7 sections — day-by-day, field guide, things-to-do, weather, history, fun facts + practical tips, food + drink |
| Default access | `/trips/<id>/guide`, gated by `require_trip_access` |
| Optional sharing | UUID share token on Trip → `/guides/share/<token>` |
| Code split | Skill orchestrates creative work; `src/guide_builder.py` owns plumbing with unit tests |

## 1. Architecture & file layout

**New files:**

- `.claude/skills/trip-guide/SKILL.md` — project-local skill. Frontmatter `name: trip-guide`, `description: Generate a bespoke HTML trip guide for a vacation-planner trip. Reads bookings + itinerary from vacation.db and writes the guide where the app can serve it.`
- `src/guide_builder.py` — typed, tested helpers. ~150–200 lines.
- `tests/test_guide_builder.py` — one test file mirroring the helper module.
- `templates/_guide_hero.html` — Jinja partial rendering the hero card on the trip overview.
- `scripts/2026-06-19_add_guide_share_token.py` — one-time migration: `ALTER TABLE trip ADD COLUMN guide_share_token VARCHAR(36); CREATE INDEX ix_trip_guide_share_token ON trip (guide_share_token);`.

**Modified files:**

- `app.py` — two new routes (`/trips/<id>/guide`, `/guides/share/<token>`); extension to the trip-overview view context with `guide_exists`, `share_url`, `last_generated_at`.
- `models.py` — adds `guide_share_token = db.Column(db.String(36), unique=True, nullable=True, index=True)` to `Trip`.
- The Jinja file that renders `/trips/<id>` — one `{% include "_guide_hero.html" %}` between the countdown hero and the Today section.
- `static/css/app.css` — `.guide-hero` block (~20 lines).
- `static/js/guide_hero.js` — copy-to-clipboard for the share URL (~15 lines, try/catch around the Clipboard API).
- `.gitignore` — adds `data/guides/`.
- `CLAUDE.md` — new "Trip Guide" subsection documenting the convention.

**New runtime directory:**

- `data/guides/` — gitignored. Holds `<trip_id>.html` (the artifact), `<trip_id>.html.bak` (previous version, single rolling slot), and `<trip_id>.config.json` (section choices + palette + last-generated timestamp).

## 2. Skill contents & invocation flow

**Invocation.** User types `/trip-guide` (or describes the goal in natural language). The skill is project-local so it only surfaces inside this repo.

**Flow inside the skill:**

1. **Resolve the trip.** Skill asks for trip ID or name. For a name, queries `vacation.db` and presents a chooser if multiple match. Echoes the chosen trip back for confirmation.
2. **Load trip data.** Calls `load_trip_data(trip_id)`.
3. **Detect prior run.** Calls `load_or_init_config(trip_id)`. If `last_generated_at` is set, asks: regenerate same sections / change sections / cancel.
4. **Section picker.** Multi-select from the 7-section catalog. Choice written to the JSON sidecar.
5. **Palette proposal.** Skill briefly researches destination feel and proposes a palette archetype with hex codes and a font pairing. User accepts or steers. Saved to config.
6. **Research + compose section by section.** Claude uses its own knowledge plus `WebSearch`/`WebFetch` for content. No Anthropic API key consumed — runs inside Claude Code.
7. **Compose the HTML.** Single-file HTML in one pass: inlined CSS, fonts via Google Fonts CDN, no framework, mobile-responsive, print-friendly, `prefers-reduced-motion` respected. The field guide section ships ~80 lines of vanilla JS for search + chip filters; every other section is static.
8. **Save.** Calls `save_guide(trip_id, html)`. Atomic write. Previous HTML rotated to `.bak`. `last_generated_at` bumped.
9. **Share-token decision.** First run or on-demand: prompt "Generate a shareable public link? (y/n)". If yes, call `set_share_token`. Print both URLs at the end.
10. **Frontend verification (mandatory per `CLAUDE.md`).** Confirm dev server is up; load the guide in headless Chrome via `webapp-testing`; assert zero console errors and visible content; load `/trips/<id>` and assert the hero card renders. Stop on failure.

**Skill markdown tone.** Declarative checklist + a couple of short prose paragraphs describing the quality bar. Explicit pointers (not copies) to `~/Downloads/galapagos-wildlife-guide.html` and `~/Downloads/Galapagos_Field_Log_Mar27-Apr3_2027.html` as anchors.

**Deliberate non-feature.** The skill does NOT auto-detect "nature trip vs city trip" and skip sections. The picker is the source of truth. If you ask for "field guide" on a NYC trip, you get curated museums + restaurants + landmarks — the skill adapts contents, not the section list.

## 3. Section content model

Every guide has a **wrapper** (always present) plus the user-selected **sections**.

### Wrapper (always)

- **Header / hero:** trip title, destination, dates, day count, mono eyebrow. Bespoke palette gradient.
- **Sticky section nav:** only when 2+ sections are included.
- **Footer:** trip ID, last-generated timestamp, palette name.

### Section catalog (7)

**Day-by-day spine.** Per-day editorial section: big day number, date, 1–2 sentence intro, site cards in time order. Each card has a mono time badge, name, 2–3 sentences of context, optional history / fun-fact tags, optional flag for things to know. Inputs: itinerary items grouped by `day_date` (existing `src/itinerary.py:group_items_by_day`) plus bookings overlapping each day. Layout mirrors `Galapagos_Field_Log_Mar27-Apr3_2027.html`. ~150–300 words per day.

**Field guide.** Filterable encyclopedia. Sticky search + filter chips, card grid. Each card: name, optional latin/local-language name, likelihood meter or quality badge, 1–2 line description, "best day to encounter" tags. Vanilla JS for search + chip toggles. Layout mirrors `galapagos-wildlife-guide.html`. Adapts by destination archetype: nature → species; city → museums + landmarks; food-heavy → could collapse into Food + Drink (skill asks).

**Things to do / places to see.** Curated recommendation list — distinct from the field guide (encyclopedia vs picks). No search, no chips. Grouped: morning ideas, evening ideas, half-day, rainy-day fallback. Each entry: name, neighborhood, why, what to pair with, optional cost / time-needed note. Exclude already-booked items (no duplicate suggestions). ~12–25 picks.

**Weather + season notes.** Four-stat grid (high, low, rainfall, daylight) plus a short timing paragraph naming season-tied phenomena (festivals, migrations, monsoon timing, full moon, etc.), plus optional 3–4 bullet packing implications.

**History + cultural context.** Prose-led, 3–5 short headed paragraphs covering compressed history, why-the-place-feels-the-way-it-feels, etiquette norms, and a small phrase table (greeting / please / thank-you / excuse-me / "do you speak English?" / numbers 1–10). ~500–800 words.

**Fun facts + practical tips.** Two-column on desktop, stacked on mobile. Left: 8–12 short trivia bullets. Right: tipping norms, plug type, transit + card, money / ATM tips, scams, emergency numbers, SIM/eSIM tips.

**Food + drink.** Short prose intro on the food culture, then two subsections:
- *Things to try:* card grid, 8–15 entries (dish or drink, optional local-language name in mono, 1–2 line description, optional "best eaten" hint, small tag: dish / drink / street snack / breakfast / dessert).
- *Where to eat:* grouped by four price tiers — Splurge, Sit-down, Casual, Street + markets. 3–5 entries per tier. Each entry: name, neighborhood, signature dish, why, optional logistics tag. **Booked restaurants from the user's trip appear in their correct price tier with a "✓ you've booked" tag** rather than being filtered out — the section doubles as a reminder of commitments.

### Cross-section rules

- One accent color per section, drawn from the trip palette; the sticky nav matches.
- No JS unless needed. Only the field guide ships JS.
- `@media print` shows everything (no sticky nav, no chips, serif body).
- No external images — inline SVG / CSS only.
- Mobile-first responsive; single-column under 600px.

## 4. `src/guide_builder.py` public surface

Pure-ish module. No HTML composition, no Claude calls, no network. Uses SQLAlchemy with a pushed Flask app context so it works against both SQLite and Postgres.

### Constants

- `GUIDES_DIR = Path("data/guides")`
- `CONFIG_SCHEMA_VERSION = 1` — per `CLAUDE.md`'s cache-integrity rule. Bump if the sidecar shape changes.
- `SECTION_KEYS = ("day_by_day", "field_guide", "things_to_do", "weather", "history", "fun_facts", "food")` — canonical lowercase IDs in display order.
- `GUIDE_STORAGE = os.getenv("GUIDE_STORAGE", "filesystem")` — forward-compat dispatch flag.

### Data shape — `GuideConfig` dataclass

```python
@dataclass
class GuideConfig:
    schema_version: int
    trip_id: int
    sections: list[str]                # subset of SECTION_KEYS in display order
    palette: dict                      # {"name": str, "colors": dict, "fonts": dict}
    last_generated_at: Optional[str]   # ISO 8601, None on first init
```

### Public functions

- **`load_trip_data(trip_id: int) -> dict`** — returns `{"trip": {...}, "bookings": [...], "itinerary": [...], "collaborators": [...]}` as plain dicts. Itinerary pre-grouped by `day_date` and sorted via existing `sort_within_day`. Bookings include their `linked_booking_id` itinerary children. Raises `TripNotFound`.
- **`load_or_init_config(trip_id: int) -> GuideConfig`** — reads JSON sidecar; missing / corrupt / schema-mismatch all return a fresh config with a logged warning.
- **`save_config(trip_id: int, config: GuideConfig) -> Path`** — atomic write (temp file + `os.replace`).
- **`save_guide(trip_id: int, html: str) -> Path`** — dispatches on `GUIDE_STORAGE`. Filesystem backend: rotates existing HTML to `.bak`, atomic-writes the new HTML, bumps `last_generated_at`. Returns the written path (or a synthetic path for non-filesystem backends).
- **`read_guide(trip_id: int) -> bytes`** — dispatches on `GUIDE_STORAGE`. Filesystem backend reads from disk. Raises `GuideMissing` if no guide exists. This is what the Flask route calls (NOT `send_file(path)`) — keeps the route storage-agnostic.
- **`guide_path(trip_id: int) -> Path`** — pure path math, filesystem-backend internal use only.
- **`guide_exists(trip_id: int) -> bool`** — dispatches on `GUIDE_STORAGE`. Filesystem backend = `guide_path(trip_id).exists()`. Used by the trip-overview template.
- **`set_share_token(trip_id: int) -> str`** — generates `uuid.uuid4().hex`, writes to `Trip.guide_share_token`, commits. Idempotent — returns existing token if already set.
- **`clear_share_token(trip_id: int) -> None`** — sets to `None`, commits. Idempotent.
- **`trip_by_share_token(token: str) -> Optional[Trip]`** — returns `None` (not raises) for unknown token. Used by the share route.

### Storage backend dispatch

`GUIDE_STORAGE` env var, default `"filesystem"`. The two storage-dependent functions (`save_guide`, `read_guide`, `guide_exists`) branch on it:

```python
if GUIDE_STORAGE == "filesystem":
    # implemented in v1
elif GUIDE_STORAGE == "database":
    # TODO: implement when hosting. Will read/write a TripGuide.html_content column.
    raise NotImplementedError("database backend pending hosted-deployment work")
else:
    raise ValueError(f"unknown GUIDE_STORAGE: {GUIDE_STORAGE!r}")
```

The DB-backend stub deliberately exists in v1 — keeps the dispatch shape visible and protects against silently regressing the abstraction.

### Errors

`class GuideError(Exception)` with subclasses `TripNotFound` and `GuideMissing`. All other errors (`OSError`, `json.JSONDecodeError`) are caught and logged via module-level `logger = logging.getLogger(__name__)`.

### Out of scope for the module

- HTML composition (Claude's creative work)
- Palette selection (Claude's creative work)
- Research / `WebSearch` (Claude's, inside the skill)
- Anything network-bound

## 5. Hero card + Flask routes

### Hero card (templates/_guide_hero.html)

- **Position:** between the countdown hero and the Today section on the trip overview.
- **When it renders:** only when `guide_exists(trip_id)`. Otherwise outputs nothing (silent absence — no "Generate" CTA in v1).
- **Content:**
  - Mono eyebrow: `TRIP GUIDE`
  - Title styled in the trip's emoji-theme color (reuses `emoji_theme()` from `src/trip_helpers.py`).
  - Primary `Open guide` button → `/trips/<id>/guide`.
  - Conditional secondary row (only when `share_url` is set AND viewer is owner): inline "Copy share link" button with the URL in mono next to it. Uses the Clipboard API with a try/catch fallback to a manual-copy hint.
  - Tiny meta line: `Last updated · {{ last_generated_at }}`.
- **No "Regenerate" or "Unshare" button in v1.** Those are skill-side actions.
- **Print:** hidden via `@media print` on the trip overview.

### Route 1 — `GET /trips/<int:trip_id>/guide`

Gated by `require_trip_access(trip_id, "viewer")`. Owner + viewer + editor can reach it.

```python
html = guide_builder.read_guide(trip_id)   # raises GuideMissing if absent
return Response(html, mimetype="text/html")
```

`GuideMissing` is caught and converted to `abort(404)`. The route NEVER touches the filesystem directly — `read_guide` is the only access point. This is what makes the cloud port trivial.

### Route 2 — `GET /guides/share/<token>`

Unauthed. Behavior:

1. `trip = guide_builder.trip_by_share_token(token)`
2. If `trip is None` → `abort(404)` (NOT 403 — don't leak token existence).
3. `html = guide_builder.read_guide(trip.id)` — `GuideMissing` → `abort(404)`.
4. Return `Response(html, mimetype="text/html")`.

The token IS the credential. 32 hex chars = 128 bits of entropy = not enumerable.

### Trip overview context extension

Where the trip overview view composes its template context, add:

```python
guide_exists = guide_builder.guide_exists(trip_id)
share_url = None
if guide_exists and trip.guide_share_token and is_owner(current_user, trip):
    share_url = url_for("guide_share", token=trip.guide_share_token, _external=True)
last_generated_at = None
if guide_exists:
    last_generated_at = guide_builder.load_or_init_config(trip_id).last_generated_at
```

- `share_url` is only populated for the owner — collaborators (even editors) see "Open guide" but not the share URL.
- `load_or_init_config` is only called when the guide exists, so trips without guides pay zero extra cost on overview page load.
- Reuses the existing `is_owner` helper in `src/sharing.py` — no new sharing helpers needed.

## 6. Regeneration, edges, and cloud-hosting forward compat

### Regeneration policy

On re-run, skill detects prior runs via the sidecar's `last_generated_at` and presents three choices:

1. **Regenerate with same sections** — reuses saved sections and palette; re-researches; overwrites.
2. **Change sections** — re-runs the picker (and optionally the palette picker); proceeds.
3. **Cancel.**

No partial regen. Full overwrite is the rule.

### Atomic writes everywhere

Both `save_guide` and `save_config` write to a temp file in the same dir, then `os.replace`. A crash mid-write leaves the previous version intact — never a half-written file.

### Previous-guide retention (`.bak`)

`save_guide`, before writing, copies the existing HTML to `data/guides/<trip_id>.html.bak`. Single slot, overwritten each regen. Cheap escape hatch when a regen goes worse than the previous version.

### Share-token lifecycle

- First-ever generation: skill asks "shareable link? y/n". If yes, `set_share_token` creates one.
- Subsequent regens: token never auto-rotates. Existing links keep working. Skill prints the existing URL at end of regen.
- Explicit rotate: skill offers a "Rotate share token" prompt during regen (calls `clear_share_token` then `set_share_token`).
- No in-app share UI in v1.

### Orphan-file matrix

| State | Behavior |
|---|---|
| Trip exists, HTML missing, sidecar exists | `guide_exists` False; hero hidden; sidecar reused on next regen |
| Trip exists, HTML exists, sidecar missing | Hero renders; "Last updated" shows "—"; next regen re-creates sidecar |
| Trip deleted, files linger | Harmless orphans; no auto-cleanup in v1 |
| Trip deleted, share token still in someone's email | Share route's `first_or_404` returns 404 — link silently stops working |
| Sidecar has old `schema_version` | Returns fresh config + logged warning; skill re-prompts |

### Backup interaction

- `src/backup.py` snapshots `vacation.db` only — guides are deliberately NOT in automatic backups (regeneratable, would bloat backups).
- `guide_share_token` IS in `vacation.db`, so it survives backup restore. The HTML needs regeneration but the share URL resumes working after.

### What's NOT handled

- Concurrent regens (single-user dev tool; last writer wins).
- Disk-full mid-write (atomic write means previous version stays valid; error propagates).
- `uuid4` collisions (effectively zero at single-user scale).

### Forward compatibility — cloud hosting

This is the only design choice that exists specifically to make a later hosted deployment cheap.

**The problem.** Cloud hosts (Railway, Render, Fly) run the app in ephemeral containers. `data/guides/` does not survive container restarts or redeploys. The skill writes the file on the user's laptop; the hosted app needs to find it on its container. Without intervention, the hero card would never render once hosted.

**The chosen migration target.** When hosting goes live, guides move into the database. A new table `TripGuide` (NOT a column on `Trip`, to keep `Trip` queries small):

```
TripGuide:
  trip_id (PK, FK → Trip, ON DELETE CASCADE)
  html_content (TEXT)
  generated_at (DATETIME)
```

**The two changes in v1 that enable the port.**

1. **Storage abstraction.** The Flask routes call `guide_builder.read_guide(trip_id) -> bytes`, never `send_file`. The skill calls `save_guide(trip_id, html)`. Neither knows where the HTML lives.
2. **Dispatch flag.** `GUIDE_STORAGE = os.getenv("GUIDE_STORAGE", "filesystem")`. The storage-dependent helpers branch on it. The `"database"` branch raises `NotImplementedError` in v1 — present-but-unimplemented, so its shape stays visible.

**The port-time work (estimated 2–3 hours).**

1. Add a Flask-SQLAlchemy migration creating the `TripGuide` table.
2. Implement the `"database"` branches in `save_guide`, `read_guide`, `guide_exists`.
3. Write a one-time script that reads every `data/guides/*.html` locally and inserts rows via the hosted app's authenticated API (or directly against the hosted DB with a temporary `DATABASE_URL`).
4. Set `GUIDE_STORAGE=database` on the cloud host.

**The skill-run question once hosted** (defer to port time). Two viable patterns:
- Set `DATABASE_URL` on your laptop shell to the cloud Postgres connection string. Skill writes directly to the hosted DB. Same code path as today.
- Keep skill local-only; add an authenticated `POST /trips/<id>/guide/upload` endpoint that the skill calls after generation.

The first is simpler for a single-user side project; the second is more disciplined. No decision required in v1.

## 7. Testing strategy + implementation phasing

### What's tested

**`tests/test_guide_builder.py`** — one test file mirroring the helper module. Runs against the in-memory DB fixture in `tests/conftest.py`. Covers:

- `load_trip_data`: happy path with seeded Trip + Bookings + ItineraryItems; `TripNotFound` for unknown ID; grouping + sorting; collaborators present.
- `load_or_init_config`: missing file → fresh; valid file → parsed; corrupt JSON → fresh + warning; schema-version mismatch → fresh + warning.
- `save_config`: writes file; atomic-write rename verified by mocking `os.replace` to raise mid-write (existing file untouched).
- `save_guide`: writes HTML; `.bak` rotation; bumps `last_generated_at`; creates `data/guides/` if missing.
- `read_guide`: returns bytes; raises `GuideMissing` when absent.
- `guide_path` / `guide_exists`: path math; both branches.
- `set_share_token`: hex token; idempotent on re-call; persists to Trip.
- `clear_share_token`: clears; idempotent.
- `trip_by_share_token`: finds correct Trip; `None` for unknown; case-sensitive.
- `GUIDE_STORAGE = "database"` raises `NotImplementedError` (regression guard).

**Route tests in `tests/test_routes.py`** (extending the existing file):

- `GET /trips/<id>/guide`: owner 200; viewer 200; non-collaborator 403 from auth guard; missing file 404.
- `GET /guides/share/<token>`: valid token 200; unknown token 404; token-on-deleted-trip 404; token-without-file 404.
- Trip-overview context: when guide exists + owner + token → partial renders with share URL; when editor (not owner) → share URL omitted.

### What's NOT tested

- Generated HTML content quality (Claude's creative work — no static contract).
- The skill markdown itself.
- Palette selection quality.
- Section-content quality (e.g. "the food section is interesting and accurate").

### Frontend verification (mandatory per CLAUDE.md)

Every task that touches `templates/`, `static/css/`, or `static/js/` ends with a headless-Chrome check via the `webapp-testing` skill: zero console errors + the visible affordance present. Plan-level checklist item inside each frontend-touching task.

### Implementation phasing

Three phases, ~17 tasks total. Fits in one plan, tight. If plan-writing exceeds the cap, Phase 3 splits into a follow-up plan.

**Phase 1 — Data layer.** DB column + migration script + `src/guide_builder.py` (all helpers, including the `"database"` stub) + `tests/test_guide_builder.py`. No user-facing change. ~6–7 tasks.

**Phase 2 — Routes + hero card.** Two Flask routes + `_guide_hero.html` partial + CSS + clipboard JS + trip-overview context dict + route tests. After this phase, manually dropping a hand-written HTML into `data/guides/<id>.html` makes the hero card render and routes work. ~6–7 tasks.

**Phase 3 — The skill.** `.claude/skills/trip-guide/SKILL.md` + `CLAUDE.md` doc update + manual end-to-end test against a real trip. ~3–4 tasks.

### Phasing rationale

Phases 1 and 2 are pure code + tests — fully testable without Claude in the loop. Phase 3 is where Claude's creative work meets the plumbing. Doing it last means by the time the user is tuning skill prompts, all the boring infrastructure works.

### Honest risk flags

- **Skill output quality is the make-or-break — and it's only judged at Phase 3 runtime.** No automated check catches "the day-by-day section is generic and boring." First few runs will need prompt iteration. Plan a follow-up "tune the skill" session after Phase 3 with two or three test trips.
- **Atomic-write tests require mocking `os.replace`** — slightly fiddly. If they prove flaky, dropping them is acceptable; atomic write is defensive, not a feature.
- **The migration touches `vacation.db`.** Per the project's data-safety rules, the migration plan must: confirm with user before running; take a manual snapshot first; document rollback (`ALTER TABLE trip DROP COLUMN guide_share_token`).
- **`GUIDE_STORAGE="database"` stub is intentionally unimplemented.** Setting it accidentally will break the app. Mitigated by the unit test that asserts the `NotImplementedError`. Considered acceptable.

## Open questions (none blocking implementation)

- **Phase 3 follow-up cadence:** how many "tune the skill" sessions to budget. Suggest 1–2.
- **Cloud-hosting timeline:** unknown. The v1 abstraction is forward-compatible; no commitment needed now.
- **Whether to include "things to try" cards as inline SVG illustrations** (for example, a stylized iguana silhouette next to "marine iguana"). Skipped in v1 — pure typographic treatment matches the Galápagos files.
