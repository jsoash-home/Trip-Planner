# Fun Countdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Source of truth:** [`docs/superpowers/specs/2026-05-25-fun-countdown-design.md`](../specs/2026-05-25-fun-countdown-design.md). If a step here conflicts with the spec, the spec wins — flag it and stop.

**Goal:** Replace the small countdown chip with a delightful countdown experience: a live-ticking hero on the trip overview page, milestone confetti at 30/14/7/3/1 days, a progress ring on dashboard cards, emoji-themed phrasing, and a "Days · Sleeps" unit toggle.

**Architecture:** Three new pure helpers in `src/trip_helpers.py` (`progress_fraction`, `emoji_theme`, `themed_countdown_label`) drive the templates. One vanilla JS module `static/js/countdown.js` ticks the hero, applies the unit toggle, and fires milestone confetti. State is client-side only: unit choice + milestone dedup in `localStorage`. No DB changes.

**Tech Stack:** Python 3.9, Flask, Jinja2, Bootstrap 5, vanilla JS, `canvas-confetti` via CDN (~6 KB), pytest.

---

## Background (read this first)

Read these so the patterns are in your head:

- [src/trip_helpers.py](../../../src/trip_helpers.py) — the pure-helper style. Note `countdown_label` (lines 100–135) and `days_until` (line 48). The new helpers go in the same file.
- [tests/test_trip_helpers.py](../../../tests/test_trip_helpers.py) — the test style.
- [templates/_trip_card.html](../../../templates/_trip_card.html) — the dashboard card that currently renders the countdown chip.
- [templates/trip_overview.html](../../../templates/trip_overview.html) — the trip detail page where the hero goes (top, after the breadcrumb, before the existing "Today" section).
- [templates/base.html](../../../templates/base.html) — the shared layout. The toggle goes in the navbar; the countdown JS gets loaded here.
- [static/css/app.css](../../../static/css/app.css) — existing patterns for animations (note `prefers-reduced-motion` gates around line 940+) and trip-card styles (line 151+).

Two existing conventions to follow:
1. **All CSS animations gated by `@media (prefers-reduced-motion: no-preference)`** — see existing `[data-just-synced]` pulse for the pattern.
2. **JS lives inline in `base.html` or as a small static file loaded with `defer`** — see the auto-dismiss flash handler around line 73.

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `src/trip_helpers.py` | Modify | Add `progress_fraction`, `emoji_theme`, `themed_countdown_label`. |
| `tests/test_trip_helpers.py` | Modify | Unit tests for the three new helpers. |
| `templates/_trip_card.html` | Modify | Swap the chip for an SVG progress ring on upcoming trips; add themed phrase below; render both unit forms. |
| `templates/_countdown_hero.html` | Create | Hero block for the trip overview page (upcoming + completed states). |
| `templates/trip_overview.html` | Modify | Include the hero partial below the breadcrumb. |
| `templates/base.html` | Modify | Add the navbar unit toggle, the `countdown.js` script tag, and the `canvas-confetti` CDN script tag. |
| `static/js/countdown.js` | Create | Apply unit on load, handle toggle clicks, tick the hero, fire milestone confetti. |
| `static/css/app.css` | Modify | Styles for the unit toggle, progress ring, hero block, milestone celebration. |

---

## Task 1: `progress_fraction` helper (TDD)

A pure helper used by the dashboard ring. Returns a float in `[0.0, 1.0]` representing how close `today` is to `start`, within a fixed window.

**Files:**
- Modify: `src/trip_helpers.py`
- Modify: `tests/test_trip_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trip_helpers.py`:

```python
from datetime import date

from src.trip_helpers import progress_fraction


def test_progress_fraction_at_start_returns_one():
    # Day-of trip → ring fully filled.
    assert progress_fraction(date(2026, 8, 17), date(2026, 8, 17)) == 1.0


def test_progress_fraction_after_start_clamps_to_one():
    # Mid-trip → ring stays full (we don't represent overshoot).
    assert progress_fraction(date(2026, 8, 17), date(2026, 8, 20)) == 1.0


def test_progress_fraction_at_window_boundary_returns_zero():
    # 90 days out → ring empty.
    assert progress_fraction(date(2026, 8, 17), date(2026, 5, 19)) == 0.0


def test_progress_fraction_beyond_window_clamps_to_zero():
    # 200 days out → still 0.0, not negative.
    assert progress_fraction(date(2026, 8, 17), date(2026, 1, 1)) == 0.0


def test_progress_fraction_mid_window():
    # 45 days out → halfway through the 90-day window.
    result = progress_fraction(date(2026, 8, 17), date(2026, 7, 3))
    assert abs(result - 0.5) < 0.01


def test_progress_fraction_close_to_start():
    # 9 days out → 90% filled.
    result = progress_fraction(date(2026, 8, 17), date(2026, 8, 8))
    assert abs(result - 0.9) < 0.01


def test_progress_fraction_custom_window():
    # 30-day window, 15 days out → 50%.
    result = progress_fraction(date(2026, 8, 17), date(2026, 8, 2), window_days=30)
    assert abs(result - 0.5) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k progress_fraction`
Expected: 7 FAIL with `ImportError: cannot import name 'progress_fraction'`.

- [ ] **Step 3: Write the implementation**

Append to `src/trip_helpers.py`:

```python
def progress_fraction(start: date, today: date, window_days: int = 90) -> float:
    """
    How close today is to `start`, expressed as a 0.0–1.0 fraction.

    A `window_days` window before the start date is the "runway"; `today`
    at the start of that window returns 0.0 and `today == start` (or
    later) returns 1.0. Clamps both ways so callers never see a value
    outside [0.0, 1.0].

    Used by the dashboard progress ring.
    """
    if today >= start:
        return 1.0
    days_out = (start - today).days
    if days_out >= window_days:
        return 0.0
    return 1.0 - (days_out / window_days)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k progress_fraction`
Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trip_helpers.py tests/test_trip_helpers.py
git commit -m "feat: progress_fraction helper for dashboard countdown ring"
```

---

## Task 2: `emoji_theme` helper (TDD)

A pure lookup helper that maps a trip's cover emoji to a short theme phrase fragment (e.g., `"🏝️" → "the beach"`). Returns `None` for unknown emojis, the default `🧳`, and `None` input.

**Files:**
- Modify: `src/trip_helpers.py`
- Modify: `tests/test_trip_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trip_helpers.py`:

```python
from src.trip_helpers import emoji_theme


def test_emoji_theme_beach_emojis():
    assert emoji_theme("🏝️") == "the beach"
    assert emoji_theme("🌴") == "the beach"
    assert emoji_theme("🌊") == "the beach"


def test_emoji_theme_takeoff():
    assert emoji_theme("✈️") == "takeoff"


def test_emoji_theme_mountains():
    assert emoji_theme("🏔️") == "the mountains"
    assert emoji_theme("⛷️") == "the mountains"


def test_emoji_theme_food():
    assert emoji_theme("🍝") == "the next great meal"
    assert emoji_theme("🍜") == "the next great meal"


def test_emoji_theme_history():
    assert emoji_theme("🏛️") == "history"


def test_emoji_theme_road():
    assert emoji_theme("🚗") == "the open road"


def test_emoji_theme_hotel():
    assert emoji_theme("🏨") == "check-in"


def test_emoji_theme_city():
    assert emoji_theme("🗽") == "the city"


def test_emoji_theme_default_suitcase_returns_none():
    # 🧳 is the default fallback emoji — keep it unthemed.
    assert emoji_theme("🧳") is None


def test_emoji_theme_unknown_returns_none():
    assert emoji_theme("🎉") is None


def test_emoji_theme_none_returns_none():
    assert emoji_theme(None) is None


def test_emoji_theme_empty_string_returns_none():
    assert emoji_theme("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k emoji_theme`
Expected: 12 FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

Append to `src/trip_helpers.py`:

```python
# Emoji → theme phrase fragment used by themed_countdown_label.
# Returning None means "use plain copy" — applies to unknown emojis and
# the default 🧳 suitcase.
_EMOJI_THEME_MAP: Dict[str, str] = {
    "🏝️": "the beach",
    "🌴": "the beach",
    "🌊": "the beach",
    "✈️": "takeoff",
    "🏔️": "the mountains",
    "⛷️": "the mountains",
    "🍝": "the next great meal",
    "🍜": "the next great meal",
    "🏛️": "history",
    "🚗": "the open road",
    "🏨": "check-in",
    "🗽": "the city",
}


def emoji_theme(emoji: Optional[str]) -> Optional[str]:
    """
    Map a trip's cover emoji to a theme phrase fragment.

    Returns None for unknown emojis, the default 🧳, None, and empty
    strings — the caller should fall back to plain copy in those cases.
    """
    if not emoji:
        return None
    return _EMOJI_THEME_MAP.get(emoji)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k emoji_theme`
Expected: 12 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trip_helpers.py tests/test_trip_helpers.py
git commit -m "feat: emoji_theme lookup for themed countdown phrasing"
```

---

## Task 3: `themed_countdown_label` helper (TDD)

Wraps `countdown_label`. When `today` is in the "N days to go" state (upcoming, N ≥ 2) AND the emoji has a theme, returns the themed variant in the requested unit (`days` or `sleeps`). All other states pass through `countdown_label` unchanged.

**Files:**
- Modify: `src/trip_helpers.py`
- Modify: `tests/test_trip_helpers.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_trip_helpers.py`:

```python
from src.trip_helpers import themed_countdown_label


def test_themed_label_upcoming_themed_days():
    # 23 days out, beach emoji, days unit → themed phrasing.
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 7, 25),
        emoji="🏝️", unit="days",
    )
    assert result == "23 days until the beach"


def test_themed_label_upcoming_themed_sleeps():
    # Same trip, sleeps unit.
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 7, 25),
        emoji="🏝️", unit="sleeps",
    )
    assert result == "23 sleeps until the beach"


def test_themed_label_upcoming_unthemed_days_falls_back_to_default():
    # No theme → plain "23 days to go".
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 7, 25),
        emoji="🧳", unit="days",
    )
    assert result == "23 days to go"


def test_themed_label_upcoming_unthemed_sleeps():
    # No theme + sleeps → "23 sleeps to go".
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 7, 25),
        emoji=None, unit="sleeps",
    )
    assert result == "23 sleeps to go"


def test_themed_label_tomorrow_passes_through_unchanged():
    # "Tomorrow!" state stays as-is regardless of theme or unit.
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 8, 16),
        emoji="🏝️", unit="sleeps",
    )
    assert result == "Tomorrow!"


def test_themed_label_today_passes_through():
    # First day of trip — pass through to countdown_label's output.
    # countdown_label returns "Today!" for today == start when start != end.
    from src.trip_helpers import countdown_label
    expected = countdown_label(date(2026, 8, 17), date(2026, 8, 27), date(2026, 8, 17))
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 8, 17),
        emoji="🏝️", unit="sleeps",
    )
    assert result == expected


def test_themed_label_mid_trip_passes_through():
    # On day 3 of 7 → unchanged.
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 23), date(2026, 8, 19),
        emoji="🏝️", unit="sleeps",
    )
    assert result == "On day 3 of 7"


def test_themed_label_last_day_passes_through():
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 23), date(2026, 8, 23),
        emoji="🏝️", unit="days",
    )
    assert result == "Last day"


def test_themed_label_recent_past_passes_through():
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 23), date(2026, 8, 25),
        emoji="🏝️", unit="sleeps",
    )
    assert result == "Ended 2 days ago"


def test_themed_label_invalid_unit_defaults_to_days():
    # Defensive: if a caller passes something weird, treat as days.
    result = themed_countdown_label(
        date(2026, 8, 17), date(2026, 8, 27), date(2026, 7, 25),
        emoji="🏝️", unit="bogus",
    )
    assert result == "23 days until the beach"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k themed_label`
Expected: 10 FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

Append to `src/trip_helpers.py`:

```python
def themed_countdown_label(
    start: date,
    end: date,
    today: date,
    emoji: Optional[str] = None,
    unit: str = "days",
) -> str:
    """
    Like countdown_label but with optional themed phrasing and a unit choice.

    Only the "N days to go" upcoming state (N ≥ 2) gets themed. All other
    states (Tomorrow!, Today!, On day X of Y, Last day, Ended …) pass
    through countdown_label unchanged — themed phrasing only makes sense
    when there's a number to attach a unit to.

    `unit` may be "days" or "sleeps". Anything else is treated as "days".
    `emoji` is looked up via emoji_theme(); None / unknown emoji / 🧳
    fall back to the plain "N days/sleeps to go" phrasing.
    """
    if today >= start:
        return countdown_label(start, end, today)

    days_out = days_until(start, today)
    if days_out <= 1:
        # "Tomorrow!" — leave alone.
        return countdown_label(start, end, today)

    unit_word = "sleeps" if unit == "sleeps" else "days"
    theme = emoji_theme(emoji)
    if theme:
        return f"{days_out} {unit_word} until {theme}"
    return f"{days_out} {unit_word} to go"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v -k themed_label`
Expected: 10 PASS.

- [ ] **Step 5: Run the full helpers test file**

Run: `.venv/bin/pytest tests/test_trip_helpers.py -v`
Expected: every test passes (existing tests untouched + 29 new tests).

- [ ] **Step 6: Commit**

```bash
git add src/trip_helpers.py tests/test_trip_helpers.py
git commit -m "feat: themed_countdown_label adds emoji + sleeps phrasing"
```

---

## Task 4: Progress ring on dashboard cards

Replace the text countdown chip on upcoming-trip cards with an SVG progress ring showing the days-remaining number in the middle. Active and past cards keep the existing chip. This task ships with a plain "days" label inside the ring; the unit toggle wires up in Task 6.

**Files:**
- Modify: `templates/_trip_card.html`
- Modify: `static/css/app.css`
- Modify: `app.py` (expose helpers to the Jinja context — verify first if already exposed)

- [ ] **Step 1: Verify which helpers are exposed to templates**

The trip card template calls `countdown_label(...)` directly, which means helpers are exposed via Jinja's globals. Search `app.py` for how this happens:

```bash
grep -nE "countdown_label|jinja_env\.globals|app\.jinja_env" "/Users/jeff_s/Projects/Vacation Planner/app.py"
```

Expected: you'll find a block where helpers are registered as Jinja globals. **You must add `progress_fraction`, `emoji_theme`, `themed_countdown_label`, and `days_until` to that block.** (Add only the ones not already there.)

Example of what the registration looks like (your actual block may differ — match the existing style):

```python
app.jinja_env.globals.update(
    countdown_label=countdown_label,
    derive_status=derive_status,
    days_until=days_until,                       # may already be registered
    progress_fraction=progress_fraction,         # add
    emoji_theme=emoji_theme,                     # add
    themed_countdown_label=themed_countdown_label,  # add
)
```

Also confirm the import line near the top of `app.py` imports these names from `src.trip_helpers`.

- [ ] **Step 2: Edit `templates/_trip_card.html`**

Replace the existing `<span class="trip-card-countdown">…</span>` line with a conditional block that picks ring vs. chip based on status:

```jinja
{% set status = derive_status(trip.start_date, trip.end_date, today) %}
{% set countdown = countdown_label(trip.start_date, trip.end_date, today) %}
{% set countdown_cls = ('is-active' if status == 'in_progress' else ('is-past' if status == 'completed' else '')) %}
```

Find that block (it already exists at the top of the macro) and leave it as-is. Then below, find:

```jinja
<span class="trip-card-countdown {{ countdown_cls }}">{{ countdown }}</span>
```

Replace it with:

```jinja
{% if status == 'planning' %}
  {% set frac = progress_fraction(trip.start_date, today) %}
  {% set d = days_until(trip.start_date, today) %}
  <div class="trip-card-ring-wrap" aria-label="{{ d }} days until trip">
    <svg class="trip-card-ring" viewBox="0 0 36 36" aria-hidden="true">
      <circle class="trip-card-ring-bg" cx="18" cy="18" r="15.915"/>
      <circle class="trip-card-ring-fg" cx="18" cy="18" r="15.915"
              stroke-dasharray="100 100"
              stroke-dashoffset="{{ '%.2f' | format(100 - (frac * 100)) }}"/>
    </svg>
    <span class="trip-card-ring-number">{{ d }}</span>
    <span class="trip-card-ring-unit">{% if d == 1 %}day{% else %}days{% endif %}</span>
  </div>
{% else %}
  <span class="trip-card-countdown {{ countdown_cls }}">{{ countdown }}</span>
{% endif %}
```

- [ ] **Step 3: Add the ring styles to `static/css/app.css`**

Append (near the existing `.trip-card-countdown` styles around line 187):

```css
/* ───── Dashboard progress ring (upcoming trips) ───── */
.trip-card-ring-wrap {
  position: relative;
  width: 84px;
  height: 84px;
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.trip-card-ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}

.trip-card-ring-bg {
  fill: none;
  stroke: var(--bs-gray-200, #e9ecef);
  stroke-width: 3;
}

.trip-card-ring-fg {
  fill: none;
  stroke: var(--bs-primary, #0d6efd);
  stroke-width: 3;
  stroke-linecap: round;
  transition: stroke-dashoffset 600ms ease-out;
}

@media (prefers-reduced-motion: reduce) {
  .trip-card-ring-fg { transition: none; }
}

.trip-card-ring-number {
  position: relative;
  z-index: 1;
  font-weight: 700;
  font-size: 1.5rem;
  line-height: 1;
  color: var(--bs-body-color, #212529);
}

.trip-card-ring-unit {
  position: absolute;
  bottom: 14px;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--bs-secondary, #6c757d);
}
```

- [ ] **Step 4: Smoke-test in a browser**

Start the dev server:

```bash
python app.py
```

Open `http://localhost:5002`, log in. The dashboard should show:
- Upcoming trip cards with a circular ring and a number in the middle (e.g., 23). The ring fills proportionally — a trip 80+ days out shows nearly empty; a trip 5 days out shows nearly full.
- Active and past trip cards still show the text chip ("On day 3 of 7" / "Ended yesterday").

If you don't have a trip in `planning` state, edit one in the DB or the UI so its start date is 30+ days away.

Stop the server.

- [ ] **Step 5: Commit**

```bash
git add templates/_trip_card.html static/css/app.css app.py
git commit -m "feat: progress ring on dashboard cards for upcoming trips"
```

---

## Task 5: Themed copy in dashboard cards (renders both unit forms)

Add a themed phrase below the ring. Render both `days` and `sleeps` forms in the DOM so Task 6's toggle can flip them. The `sleeps` form starts hidden — the JS will unhide it if the user's stored preference is `sleeps`.

**Files:**
- Modify: `templates/_trip_card.html`

- [ ] **Step 1: Add the themed phrase span**

In `templates/_trip_card.html`, inside the `{% if status == 'planning' %}` block (the one we added in Task 4), append after the `</div>` closing the `.trip-card-ring-wrap`:

```jinja
  <span class="trip-card-themed" data-countdown-unit>
    <span data-countdown-form="days">{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='days') }}</span>
    <span data-countdown-form="sleeps" hidden>{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='sleeps') }}</span>
  </span>
```

The whole `{% if status == 'planning' %}` block should now look like:

```jinja
{% if status == 'planning' %}
  {% set frac = progress_fraction(trip.start_date, today) %}
  {% set d = days_until(trip.start_date, today) %}
  <div class="trip-card-ring-wrap" aria-label="{{ d }} days until trip">
    <svg class="trip-card-ring" viewBox="0 0 36 36" aria-hidden="true">
      <circle class="trip-card-ring-bg" cx="18" cy="18" r="15.915"/>
      <circle class="trip-card-ring-fg" cx="18" cy="18" r="15.915"
              stroke-dasharray="100 100"
              stroke-dashoffset="{{ '%.2f' | format(100 - (frac * 100)) }}"/>
    </svg>
    <span class="trip-card-ring-number">{{ d }}</span>
    <span class="trip-card-ring-unit">{% if d == 1 %}day{% else %}days{% endif %}</span>
  </div>
  <span class="trip-card-themed" data-countdown-unit>
    <span data-countdown-form="days">{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='days') }}</span>
    <span data-countdown-form="sleeps" hidden>{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='sleeps') }}</span>
  </span>
{% else %}
  <span class="trip-card-countdown {{ countdown_cls }}">{{ countdown }}</span>
{% endif %}
```

- [ ] **Step 2: Add CSS for the themed phrase**

Append to `static/css/app.css` (after the ring styles from Task 4):

```css
.trip-card-themed {
  display: block;
  margin-top: 0.4rem;
  font-size: 0.85rem;
  color: var(--bs-secondary, #6c757d);
  font-style: italic;
}
```

- [ ] **Step 3: Smoke-test**

Start the dev server. Reload the dashboard.

Expected:
- Upcoming trip with a themed emoji (e.g., `🏝️`) shows "23 days until the beach" below the ring.
- Upcoming trip with the default `🧳` or an untracked emoji shows "23 days to go".
- The `sleeps` span is present in the DOM (inspect with DevTools) but `hidden`.

Stop the server.

- [ ] **Step 4: Commit**

```bash
git add templates/_trip_card.html static/css/app.css
git commit -m "feat: themed countdown phrasing below dashboard ring"
```

---

## Task 6: `countdown.js` module + Days/Sleeps toggle in navbar

Create the JS module that reads the unit from `localStorage`, applies it to every `[data-countdown-unit]` wrapper by toggling the `hidden` attribute on `[data-countdown-form]` children. Add the segmented-control toggle to the navbar.

**Files:**
- Create: `static/js/countdown.js`
- Modify: `templates/base.html`
- Modify: `static/css/app.css`

- [ ] **Step 1: Create `static/js/countdown.js`**

```javascript
/**
 * countdown.js — countdown unit toggle, ticker, and milestone celebrations.
 *
 * State (in localStorage):
 *   vp.countdown.unit            "days" | "sleeps"   (default "days")
 *   vp.celebrated.<id>.<thresh>  any value           (presence = celebrated)
 *
 * DOM convention:
 *   <span data-countdown-unit>
 *     <span data-countdown-form="days">…</span>
 *     <span data-countdown-form="sleeps" hidden>…</span>
 *   </span>
 *
 * Toggle:
 *   <button data-countdown-toggle="days"   aria-pressed="…">…</button>
 *   <button data-countdown-toggle="sleeps" aria-pressed="…">…</button>
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'vp.countdown.unit';
  var VALID_UNITS = ['days', 'sleeps'];

  function readUnit() {
    try {
      var v = window.localStorage.getItem(STORAGE_KEY);
      if (VALID_UNITS.indexOf(v) !== -1) return v;
    } catch (e) {
      // localStorage blocked (e.g., private browsing) — fall through.
    }
    return 'days';
  }

  function writeUnit(unit) {
    try {
      window.localStorage.setItem(STORAGE_KEY, unit);
    } catch (e) {
      // Best-effort; toggle still works for the current page.
    }
  }

  function applyUnit(unit) {
    document.querySelectorAll('[data-countdown-unit]').forEach(function (wrap) {
      wrap.querySelectorAll('[data-countdown-form]').forEach(function (form) {
        var matches = form.getAttribute('data-countdown-form') === unit;
        form.hidden = !matches;
      });
    });
    document.querySelectorAll('[data-countdown-toggle]').forEach(function (btn) {
      var matches = btn.getAttribute('data-countdown-toggle') === unit;
      btn.setAttribute('aria-pressed', matches ? 'true' : 'false');
    });
  }

  function wireToggle() {
    document.querySelectorAll('[data-countdown-toggle]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var unit = btn.getAttribute('data-countdown-toggle');
        if (VALID_UNITS.indexOf(unit) === -1) return;
        writeUnit(unit);
        applyUnit(unit);
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    applyUnit(readUnit());
    wireToggle();
  });
})();
```

- [ ] **Step 2: Add toggle markup + script tag in `templates/base.html`**

Find the `.vp-user ms-auto` div in the navbar (around line 43–53). Add the toggle as a sibling, just before `.vp-user`:

```jinja
        <div class="vp-unit-toggle ms-auto me-3" role="group" aria-label="Countdown unit">
          <button type="button" class="vp-unit-btn" data-countdown-toggle="days" aria-pressed="true">Days</button>
          <button type="button" class="vp-unit-btn" data-countdown-toggle="sleeps" aria-pressed="false">Sleeps</button>
        </div>

        <div class="vp-user">
```

(Notice the `ms-auto` moves from `.vp-user` to the new `.vp-unit-toggle` — otherwise both elements compete for the auto margin. Keep `.vp-user` as a plain `<div class="vp-user">` after this change.)

Then near the bottom of `base.html`, just below the Bootstrap bundle script tag (around line 72):

```html
<script src="{{ url_for('static', filename='js/countdown.js') }}" defer></script>
```

- [ ] **Step 3: Style the toggle**

Append to `static/css/app.css`:

```css
/* ───── Days / Sleeps unit toggle (navbar) ───── */
.vp-unit-toggle {
  display: inline-flex;
  background: var(--bs-gray-100, #f8f9fa);
  border-radius: 999px;
  padding: 2px;
  gap: 2px;
}

.vp-unit-btn {
  background: transparent;
  border: 0;
  border-radius: 999px;
  padding: 4px 12px;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--bs-secondary, #6c757d);
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.vp-unit-btn[aria-pressed="true"] {
  background: var(--bs-white, #fff);
  color: var(--bs-body-color, #212529);
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
}

.vp-unit-btn:focus-visible {
  outline: 2px solid var(--bs-primary, #0d6efd);
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .vp-unit-btn { transition: none; }
}
```

- [ ] **Step 4: Smoke-test**

Start the dev server. Reload the dashboard.

Expected:
- The navbar shows a "Days · Sleeps" segmented control. Days is highlighted by default.
- Click "Sleeps" — every dashboard card's themed phrase swaps to the sleeps form ("23 sleeps until the beach" / "23 sleeps to go"). No page reload.
- Reload the page — the toggle remembers "Sleeps" was active.
- Click "Days" — phrases swap back.
- Open DevTools, run `localStorage.removeItem('vp.countdown.unit')`, reload — defaults back to Days.
- Open in a Private/Incognito window — toggle still works for the current session, just doesn't persist.

Stop the server.

- [ ] **Step 5: Commit**

```bash
git add static/js/countdown.js templates/base.html static/css/app.css
git commit -m "feat: Days/Sleeps unit toggle with localStorage persistence"
```

---

## Task 7: Hero countdown on trip overview (with live ticker)

Add a hero block at the top of the trip overview page. Renders three states:
- **Upcoming** (`today < start`): big days number + live-ticking hours/minutes/seconds + themed phrase
- **Completed** (`today > end`): static "Welcomed home N days ago"
- **In-progress**: nothing — the existing "Today" section is already the hero

The ticker is added to `countdown.js` and runs only on pages with a `[data-countdown-target]` element.

**Files:**
- Create: `templates/_countdown_hero.html`
- Modify: `templates/trip_overview.html`
- Modify: `static/js/countdown.js`
- Modify: `static/css/app.css`

- [ ] **Step 1: Create `templates/_countdown_hero.html`**

```jinja
{# Hero countdown block for the trip overview page.
   Renders nothing while the trip is in progress (the Today section is the hero). #}
{% set _status = derive_status(trip.start_date, trip.end_date, today) %}

{% if _status == 'planning' %}
  {% set _d = days_until(trip.start_date, today) %}
  <section class="countdown-hero" aria-label="Countdown to trip"
           data-countdown-hero
           data-trip-id="{{ trip.id }}"
           data-countdown-target="{{ trip.start_date.isoformat() }}T00:00:00">
    <div class="countdown-hero-number">
      <span class="countdown-hero-days" data-countdown-days>{{ _d }}</span>
      <span class="countdown-hero-days-label">{% if _d == 1 %}day{% else %}days{% endif %}</span>
    </div>
    <div class="countdown-hero-ticker" aria-hidden="true">
      <span data-countdown-h>—</span>h
      <span data-countdown-m>—</span>m
      <span data-countdown-s>—</span>s
    </div>
    <div class="countdown-hero-themed" data-countdown-unit>
      <span data-countdown-form="days">{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='days') }}</span>
      <span data-countdown-form="sleeps" hidden>{{ themed_countdown_label(trip.start_date, trip.end_date, today, emoji=trip.cover_emoji, unit='sleeps') }}</span>
    </div>
  </section>
{% elif _status == 'completed' %}
  {% set _ago = (today - trip.end_date).days %}
  <section class="countdown-hero countdown-hero--past" aria-label="Trip recap">
    <div class="countdown-hero-past-text">
      Welcomed home {{ _ago }} day{% if _ago != 1 %}s{% endif %} ago
    </div>
  </section>
{% endif %}
```

- [ ] **Step 2: Include the partial in `trip_overview.html`**

In `templates/trip_overview.html`, find the breadcrumb block at the top (lines 6–9). Just after it, before the `<div class="trip-overview-header">`, add:

```jinja
{% set today = today_date %}
{% include "_countdown_hero.html" %}
```

(The route passes the date as `today_date`, but the partial — and the helpers it calls — expects `today`. The `{% set %}` aliases it for the include.)

- [ ] **Step 3: Add the hero styles**

Append to `static/css/app.css`:

```css
/* ───── Countdown hero (trip overview page) ───── */
.countdown-hero {
  background: linear-gradient(135deg, var(--bs-primary, #0d6efd) 0%, #6610f2 100%);
  color: #fff;
  border-radius: 1rem;
  padding: 2rem 1.5rem;
  margin-bottom: 1.5rem;
  text-align: center;
  box-shadow: 0 4px 16px rgba(13, 110, 253, 0.15);
}

.countdown-hero--past {
  background: var(--bs-gray-100, #f8f9fa);
  color: var(--bs-secondary, #6c757d);
  box-shadow: none;
}

.countdown-hero-number {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.countdown-hero-days {
  font-size: 4rem;
  font-weight: 800;
  line-height: 1;
}

.countdown-hero-days-label {
  font-size: 1.25rem;
  font-weight: 500;
  opacity: 0.85;
}

.countdown-hero-ticker {
  font-size: 1rem;
  font-weight: 500;
  letter-spacing: 0.05em;
  opacity: 0.9;
  font-variant-numeric: tabular-nums;
  margin-bottom: 0.75rem;
}

.countdown-hero-ticker span {
  display: inline-block;
  min-width: 1.5em;
  text-align: right;
}

.countdown-hero-themed {
  font-size: 1.1rem;
  font-weight: 500;
}

.countdown-hero-past-text {
  font-size: 1.25rem;
  font-weight: 500;
}
```

- [ ] **Step 4: Add the ticker to `countdown.js`**

In `static/js/countdown.js`, before the closing `})();`, add:

```javascript
  function pad2(n) {
    return n < 10 ? '0' + n : '' + n;
  }

  function tickHero(hero) {
    var target = new Date(hero.getAttribute('data-countdown-target'));
    if (isNaN(target.getTime())) return;
    var now = new Date();
    var diffMs = target - now;
    if (diffMs <= 0) {
      // Trip started — page will refresh and switch to in-progress UI on next visit.
      return;
    }
    var totalSeconds = Math.floor(diffMs / 1000);
    var days = Math.floor(totalSeconds / 86400);
    var hours = Math.floor((totalSeconds % 86400) / 3600);
    var minutes = Math.floor((totalSeconds % 3600) / 60);
    var seconds = totalSeconds % 60;

    var daysEl = hero.querySelector('[data-countdown-days]');
    if (daysEl) daysEl.textContent = days;
    var hEl = hero.querySelector('[data-countdown-h]');
    if (hEl) hEl.textContent = pad2(hours);
    var mEl = hero.querySelector('[data-countdown-m]');
    if (mEl) mEl.textContent = pad2(minutes);
    var sEl = hero.querySelector('[data-countdown-s]');
    if (sEl) sEl.textContent = pad2(seconds);
  }

  function startTickers() {
    var heroes = document.querySelectorAll('[data-countdown-hero][data-countdown-target]');
    if (!heroes.length) return;
    heroes.forEach(tickHero);
    setInterval(function () {
      heroes.forEach(tickHero);
    }, 1000);
  }
```

Then update the `DOMContentLoaded` handler near the bottom of the file to call `startTickers()`:

```javascript
  document.addEventListener('DOMContentLoaded', function () {
    applyUnit(readUnit());
    wireToggle();
    startTickers();
  });
```

- [ ] **Step 5: Smoke-test**

Start the dev server. Open an upcoming trip's overview page.

Expected:
- A purple/blue gradient hero block at the top showing big "23 days" + ticking "4h 12m 07s" + the themed phrase below.
- Seconds tick visibly.
- Click "Sleeps" in the navbar — the themed phrase changes ("23 sleeps until the beach"). The big number stays the same.
- Visit an in-progress trip overview — no hero block.
- Visit a completed trip overview — gray hero block showing "Welcomed home N days ago".

Stop the server.

- [ ] **Step 6: Commit**

```bash
git add templates/_countdown_hero.html templates/trip_overview.html static/js/countdown.js static/css/app.css
git commit -m "feat: live-ticking countdown hero on trip overview page"
```

---

## Task 8: Milestone celebrations with confetti

At thresholds 30, 14, 7, 3, 1 days out, swap the hero copy to celebratory text and fire a confetti burst — but only the first time the user sees that milestone for that trip. Dedup via `localStorage`. Honor `prefers-reduced-motion: reduce` by skipping the confetti (copy still swaps).

**Files:**
- Modify: `templates/base.html`
- Modify: `static/js/countdown.js`
- Modify: `static/css/app.css`

- [ ] **Step 1: Add the canvas-confetti CDN script tag in `templates/base.html`**

Just below the existing `countdown.js` script tag added in Task 6:

```html
<script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.9.3/dist/confetti.browser.min.js" defer></script>
```

- [ ] **Step 2: Add milestone logic to `countdown.js`**

Before the closing `})();`, add:

```javascript
  var MILESTONES = [30, 14, 7, 3, 1];

  var MILESTONE_COPY = {
    30: '🎉 One month to go!',
    14: '🧳 Two weeks!',
    7: '⏰ One week!',
    3: '✨ Just three days!',
    1: '🛫 Tomorrow!'
  };

  function celebratedKey(tripId, threshold) {
    return 'vp.celebrated.' + tripId + '.' + threshold;
  }

  function alreadyCelebrated(tripId, threshold) {
    try {
      return window.localStorage.getItem(celebratedKey(tripId, threshold)) !== null;
    } catch (e) {
      return true;  // pretend we already did, to avoid re-firing on every reload
    }
  }

  function markCelebrated(tripId, threshold) {
    try {
      window.localStorage.setItem(celebratedKey(tripId, threshold), '1');
    } catch (e) {
      // best-effort
    }
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function fireConfetti() {
    if (prefersReducedMotion()) return;
    if (typeof window.confetti !== 'function') return;
    window.confetti({
      particleCount: 120,
      spread: 70,
      origin: { y: 0.3 }
    });
  }

  function showMilestoneOverlay(hero, copy) {
    var overlay = document.createElement('div');
    overlay.className = 'countdown-hero-milestone';
    overlay.textContent = copy;
    hero.appendChild(overlay);
    // Slide it out after 4s so the regular hero shows again.
    setTimeout(function () {
      overlay.classList.add('countdown-hero-milestone--dismissing');
    }, 4000);
    setTimeout(function () {
      overlay.remove();
    }, 4600);
  }

  function checkMilestones() {
    var heroes = document.querySelectorAll('[data-countdown-hero][data-trip-id][data-countdown-target]');
    heroes.forEach(function (hero) {
      var tripId = hero.getAttribute('data-trip-id');
      var target = new Date(hero.getAttribute('data-countdown-target'));
      if (isNaN(target.getTime())) return;
      var now = new Date();
      var diffMs = target - now;
      if (diffMs <= 0) return;
      var totalDays = Math.ceil(diffMs / 86400000);
      for (var i = 0; i < MILESTONES.length; i++) {
        var t = MILESTONES[i];
        if (totalDays === t && !alreadyCelebrated(tripId, t)) {
          showMilestoneOverlay(hero, MILESTONE_COPY[t]);
          fireConfetti();
          markCelebrated(tripId, t);
          break;
        }
      }
    });
  }
```

Update the `DOMContentLoaded` handler:

```javascript
  document.addEventListener('DOMContentLoaded', function () {
    applyUnit(readUnit());
    wireToggle();
    startTickers();
    checkMilestones();
  });
```

- [ ] **Step 3: Style the milestone overlay**

Append to `static/css/app.css`:

```css
.countdown-hero { position: relative; overflow: hidden; }

.countdown-hero-milestone {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.95);
  color: var(--bs-primary, #0d6efd);
  font-size: 1.75rem;
  font-weight: 700;
  text-align: center;
  padding: 1rem;
  opacity: 1;
  transition: opacity 600ms ease-out;
}

.countdown-hero-milestone--dismissing { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .countdown-hero-milestone { transition: none; }
}
```

- [ ] **Step 4: Smoke-test the happy path**

Start the dev server. Edit a trip in the DB (or via the UI) so its start date is exactly 7 days from today.

```bash
sqlite3 vacation.db
> UPDATE trip SET start_date = date('now', '+7 days'), end_date = date('now', '+14 days') WHERE id = <YOUR_TRIP_ID>;
> .exit
```

Reload the trip overview page.

Expected:
- A white overlay slides over the hero showing "⏰ One week!"
- Confetti fires from the top of the page.
- After ~4 seconds the overlay fades out and the normal hero shows again.

Reload again.

Expected:
- No overlay, no confetti — `localStorage` remembers you already celebrated this milestone.
- In DevTools: `localStorage.getItem('vp.celebrated.<trip_id>.7')` returns `"1"`.

- [ ] **Step 5: Smoke-test reduced motion**

In your OS settings, enable "Reduce motion" (macOS: System Settings → Accessibility → Display → Reduce motion). Clear the dedup key:

In DevTools console:
```javascript
localStorage.removeItem('vp.celebrated.<trip_id>.7');
```

Reload.

Expected:
- The milestone overlay still shows ("⏰ One week!").
- **No** confetti fires.

Turn off Reduce motion when done.

- [ ] **Step 6: Smoke-test other thresholds**

Repeat Step 4 for trips at 30, 14, 3, and 1 days out. Each should fire its own copy + confetti once.

For "🛫 Tomorrow!" (1 day): note this overlaps with `countdown_label`'s existing "Tomorrow!" — that's fine; the milestone copy shows briefly over the hero, then fades to reveal the regular hero copy.

Stop the server.

- [ ] **Step 7: Commit**

```bash
git add templates/base.html static/js/countdown.js static/css/app.css
git commit -m "feat: milestone confetti celebrations at 30/14/7/3/1 days"
```

---

## Final verification

- [ ] **Run the full test suite**

```bash
.venv/bin/pytest -v
```

Expected: every test passes. The new tests in `tests/test_trip_helpers.py` add 29 tests (7 progress_fraction + 12 emoji_theme + 10 themed_countdown_label).

- [ ] **Manual end-to-end walkthrough**

1. Dashboard — upcoming trip cards show progress rings; active/past keep chips.
2. Toggle "Sleeps" — themed phrases swap; reload, choice persists.
3. Open an upcoming trip — purple hero with live ticker.
4. Switch back to Days — hero phrase swaps without page reload.
5. Set a trip to 7 days out → confetti fires once; reload → no re-fire.
6. Set a trip with `cover_emoji="🍝"` → "23 days until the next great meal".
7. Set a trip with `cover_emoji="🧳"` (default) → plain "23 days to go".

- [ ] **No commit needed for verification.** If anything is off, fix in a follow-up commit with a clear message.

---

## Done. What ships in this plan

- Live-ticking purple hero countdown on every upcoming trip's overview page
- Static "Welcomed home" hero on completed trips
- SVG progress rings on dashboard cards for upcoming trips
- Emoji-themed countdown copy ("23 days until the beach", "until takeoff", etc.)
- Days · Sleeps unit toggle in the navbar that persists across sessions and works on every page
- One-time confetti celebrations at 30/14/7/3/1 days, with `prefers-reduced-motion` respected
- Three new pure helpers in `src/trip_helpers.py` with 29 unit tests
- One small vanilla JS module (no build step, no npm)

---

## What's intentionally NOT in this plan

- **Per-user server-side preference for unit choice.** `localStorage` is enough — it's per-browser, which is what most users expect anyway.
- **Animations on the dashboard ring filling up over time.** Static snapshot is enough; the value comes from the at-a-glance comparison across cards.
- **Destination keyword matching.** Emoji-only — if a user wants the beach phrasing they pick a beach emoji.
- **Sound effects on milestone celebrations.** Visual + confetti is enough.
- **Sharing milestone screenshots.** Not a real ask yet.
- **Custom theme phrases per user.** The built-in table is enough for v1.
- **Wrap-around for the "Tomorrow!" milestone showing "1 sleep!".** "Tomorrow!" stays as-is in sleeps mode for simplicity.
