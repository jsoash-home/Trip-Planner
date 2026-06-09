# Home-Currency Budget Totals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll up multi-currency booking totals into a single
target currency on the budget page. Add `User.home_currency` as
the default target, a new `ExchangeRateCache` table for daily
rates from exchangerate.host, and a `Show in: [USD ▼]` toggle on
the budget hero that lets the user spot-check other currencies or
fall back to "Mixed (no conversion)".

**Architecture:** One new nullable column (`User.home_currency`,
default `'USD'`), one new model (`ExchangeRateCache`), one new
module (`src/exchange_rates.py`) with pure helpers + cache-first
`get_rates_for`, one new pure function (`convert_totals` in
`src/budget.py`). The `/settings` page from B1 grows a second
fieldset; the `trip_budget` route reads `?show_as=` and converts
each category's `totals_by_currency` before rendering. Booking
rows are unchanged.

**Tech Stack:** Python 3.9, Flask, SQLAlchemy, `requests` (already
present from B1 / geocoding). **No new Python packages.** External
service: `exchangerate.host` — free, no key, same posture as
Open-Meteo (B1) and `timezonefinder` (B2).

---

## Spec

Full design: [docs/superpowers/specs/2026-06-09-home-currency-budget-design.md](../specs/2026-06-09-home-currency-budget-design.md)

Read it first. This plan executes that spec.

## Background reading

Before starting, read these to put the patterns in head:

- [src/weather.py](../../../src/weather.py) — the closest existing
  analog. Cache-first `get_forecast_for_day` matches the shape of
  `get_rates_for` here.
- [models.py:24](../../../models.py) — `User` model where
  `home_currency` lands; weather_units is the template to follow.
- [src/budget.py](../../../src/budget.py) — the module that grows
  `convert_totals`. Reuse `format_money` rounding rules via
  `format_money_totals`.
- [src/currency.py](../../../src/currency.py) —
  `SUPPORTED_CURRENCIES`, `SUPPORTED_CURRENCY_CODES`,
  `is_valid_currency`. All already there; just import.
- [app.py:846](../../../app.py) — current `/settings` route. T4
  extends it; the existing weather_units handling stays.
- [app.py:2593](../../../app.py) — current `trip_budget` route. T5
  extends it.
- [app.py:302](../../../app.py) — `_run_safe_alters` for the
  additive `ALTER TABLE` pattern (T1).
- [templates/settings.html](../../../templates/settings.html) and
  [templates/trip_budget.html](../../../templates/trip_budget.html)
  — the two templates extended by T4 and T5.

---

## File map

**Create:**

- `src/exchange_rates.py` — `RateBundle` dataclass + pure helpers
  (`is_rate_fresh`, `cache_key_for`, `cross_rates_via_usd`) +
  impure `fetch_latest_rates` and `get_rates_for`.
- `tests/test_exchange_rates.py` — unit tests for everything in
  the new module.

**Modify:**

- `models.py` — add `home_currency` column on `User`; add
  `ExchangeRateCache` model.
- `app.py` — `_run_safe_alters` ALTER for `user.home_currency`;
  extend `/settings` route and `/trips/<id>/budget` route.
- `src/budget.py` — add `convert_totals`.
- `tests/test_budget.py` — add unit tests for `convert_totals`.
- `tests/test_routes.py` — append integration tests for the
  settings round-trip and the budget page in mixed + converted
  modes.
- `templates/settings.html` — new home-currency fieldset.
- `templates/trip_budget.html` — toggle, disclaimer, unconverted
  footnote.
- `docs/PHASE_3_ROADMAP.md` — flip B3 row to ✓ shipped with plan
  link (final task).

**Do not modify:**

- `src/currency.py`. `SUPPORTED_CURRENCIES` is the canonical list
  — extend the list there if a new code is ever needed, but not in
  this feature.
- `src/booking_helpers.py`. Per-booking display is unchanged.
- Existing weather_units handling on `/settings` or its template
  — it stays alongside the new field.
- `static/js/*`. No client-side JS needed — toggle uses a plain
  `<form method="get">` with `onchange="this.form.submit()"`.

---

## Task 1: Schema — `User.home_currency` + `ExchangeRateCache` + migration

**Files:**

- Modify: `models.py`
- Modify: `app.py` (the `_run_safe_alters` block)

**Schema (one shot, hard to recover — be careful):**

`User.home_currency` —
`db.Column(db.String(3), nullable=False, default="USD")`.

Placed in the `User` model immediately after `weather_units`.

`ExchangeRateCache` — new model:

| Field | Type | Notes |
|---|---|---|
| `id` | `db.Integer`, primary key | |
| `base_currency` | `db.String(3)`, nullable=False | always `'USD'` in v1 |
| `target_currency` | `db.String(3)`, nullable=False | |
| `rate` | `db.Float`, nullable=False | how many target per one base |
| `rate_date` | `db.Date`, nullable=False | |
| `fetched_at` | `db.DateTime`, nullable=False, default `datetime.utcnow` | TTL anchor |
| `__table_args__` | `(db.UniqueConstraint("base_currency", "target_currency", "rate_date", name="uq_rate_cache_pair_date"),)` | |

**`_run_safe_alters` addition:**

```python
"ALTER TABLE user ADD COLUMN home_currency VARCHAR(3) NOT NULL DEFAULT 'USD'",
```

Wrap in the existing `try/except OperationalError: pass` pattern.

**No new tests for this task.** The B1 / B2 schema-add tasks both
ran without a dedicated test — the model surface is exercised by
later tasks. Smoke:

- App starts cleanly.
- `sqlite3 vacation.db ".schema user"` shows
  `home_currency VARCHAR(3) NOT NULL DEFAULT 'USD'`.
- `sqlite3 vacation.db ".schema exchange_rate_cache"` shows the
  five fields + the unique index.

**Commit:** `feat: home_currency column + ExchangeRateCache model`

---

## Task 2: `src/exchange_rates.py` — module + tests

**Files:**

- Create: `src/exchange_rates.py`
- Create: `tests/test_exchange_rates.py`

**Public surface:**

```python
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, Mapping, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS: int = 24 * 60 * 60
DEFAULT_BASE: str = "USD"
API_URL: str = "https://api.exchangerate.host/latest"
API_TIMEOUT_SECONDS: int = 5


@dataclass
class RateBundle:
    base: str
    rates: Dict[str, float]            # {"EUR": 1.10, "GBP": 1.27, ...}
    rate_date: date
    fetched_at: datetime


# Pure helpers

def is_rate_fresh(fetched_at: datetime, now: datetime) -> bool: ...
def cache_key_for(base: str, target: str, d: date) -> Tuple[str, str, date]: ...
def cross_rates_via_usd(
    usd_rates: Mapping[str, float],     # {currency: how many of currency per USD}
    target: str,
) -> Dict[str, float]:                  # {source_currency: how many target per one source}
    ...


# Impure (mocked in tests)

def fetch_latest_rates(base: str = DEFAULT_BASE) -> Optional[RateBundle]: ...

def get_rates_for(
    base: str,
    targets: Iterable[str],
    *,
    db_session,
    now: Optional[datetime] = None,
) -> Dict[str, float]: ...
```

**Implementation notes:**

- `is_rate_fresh(fetched_at, now)`:
  `fetched_at + timedelta(seconds=CACHE_TTL_SECONDS) > now`.
- `cache_key_for(base, target, d)`: `(base.upper(), target.upper(), d)`.
- `cross_rates_via_usd(usd_rates, target)`: `target = target.upper()`;
  if `target not in usd_rates and target != "USD"`: return `{}`.
  `rate_target = usd_rates.get(target, 1.0)`. Result builds
  `{src: rate_target / usd_rates[src]}` for every src in `usd_rates`
  plus `{"USD": rate_target}` if `target != "USD"`. The target
  itself is included with rate `1.0` so callers don't need to
  special-case same-currency in `convert_totals`.
- `fetch_latest_rates(base)`: GET `API_URL?base={base}` with
  timeout `API_TIMEOUT_SECONDS`. Catch `requests.RequestException`
  → log warning → return None. On 200, parse JSON; check
  `response.get("success", True)` truthy (exchangerate.host
  sometimes omits the field on success); if not, log + None. Build
  `RateBundle` with `rates` filtered to numeric values only (skip
  non-floats / nulls). `rate_date = date.fromisoformat(json["date"])`
  (fall back to today on parse failure).
- `get_rates_for(base, targets, *, db_session, now=None)`:
  - `now = now or datetime.utcnow()` — parameter kept for tests.
  - Normalize: `base = base.upper()`, `targets = {t.upper() for t in targets}`.
  - Query `ExchangeRateCache` for rows matching `(base, target ∈ targets)`
    where `is_rate_fresh(row.fetched_at, now)`. Collect into a
    `{target: rate}` dict.
  - If every requested target is already in the dict: return it.
  - Otherwise call `fetch_latest_rates(base)`. If None: return
    what we have from cache (graceful degradation).
  - For each target in the freshly-fetched bundle that's in
    `targets`: upsert the cache row (delete-by-key + insert is
    fine; or query + update). Commit.
  - Return `{target: rate}` for every target now available
    (cache + fresh fetch combined).
  - Defensive: wrap the cache query in `try/except` catching
    `sqlalchemy.exc.OperationalError` (table missing on a
    fresh deploy before `db.create_all()` ran) and treat as
    "no cache". Don't raise.

**Test list (~16):**

`is_rate_fresh` (~3):
- `test_is_rate_fresh_just_fetched`
- `test_is_rate_fresh_within_window`
- `test_is_rate_fresh_past_ttl`

`cache_key_for` (~2):
- `test_cache_key_for_uppercases_codes`
- `test_cache_key_for_passes_date_through`

`cross_rates_via_usd` (~5):
- `test_cross_rates_target_usd_returns_passthrough` (target=USD →
  result is the input rates unchanged + USD=1.0)
- `test_cross_rates_target_in_input` (target=EUR, input has EUR
  rate → cross-rates correct via division, USD included)
- `test_cross_rates_target_missing_returns_empty`
- `test_cross_rates_source_with_implicit_rate_one` (target's own
  rate appears as `1.0` in the result)
- `test_cross_rates_numeric_precision` (input `{"EUR": 1.10}`,
  target=EUR → `USD ≈ 0.909`)

`fetch_latest_rates` (~4, with `requests.get` mocked):
- `test_fetch_latest_rates_success_returns_bundle`
- `test_fetch_latest_rates_api_success_false_returns_none`
- `test_fetch_latest_rates_5xx_returns_none`
- `test_fetch_latest_rates_network_error_returns_none`

`get_rates_for` (~5, with cache + API mocked):
- `test_get_rates_for_cache_miss_calls_api_and_writes_cache`
- `test_get_rates_for_cache_hit_skips_api`
- `test_get_rates_for_stale_rows_trigger_refetch`
- `test_get_rates_for_api_failure_returns_partial_from_cache`
- `test_get_rates_for_missing_cache_table_returns_empty`
  (`OperationalError` defensive path)

**Verify:** `pytest tests/test_exchange_rates.py -v` all pass.

**Commit:** `feat: src/exchange_rates.py module + 16 tests`

---

## Task 3: `convert_totals` in `src/budget.py` + tests

**Files:**

- Modify: `src/budget.py`
- Modify: `tests/test_budget.py`

**Public surface:**

```python
def convert_totals(
    totals_by_currency: Mapping[str, float],
    target_currency: str,
    rates: Mapping[str, float],
) -> Dict[str, float]:
    """
    Collapse per-currency totals into the target currency using rates.

    `rates` is keyed by source currency; value is "how many
    target_currency per one source_currency". The target itself
    is treated as having implicit rate 1.0 even if absent.

    Source currencies whose rate is missing pass through unchanged
    — they appear in the result keyed by their original code,
    alongside the (single) target_currency entry.
    """
```

**Implementation notes:**

- Normalize `target_currency = target_currency.upper()`.
- `out: Dict[str, float] = {}`.
- Build a local `effective_rates = {**rates, target_currency: 1.0}`
  so same-currency passes through with no special case.
- For each `(code, amount)` in `totals_by_currency.items()`:
  - `code_upper = code.upper()`.
  - If `code_upper in effective_rates`:
    - `converted = amount * effective_rates[code_upper]`
    - `out[target_currency] = out.get(target_currency, 0.0) + converted`
  - Else: `out[code_upper] = out.get(code_upper, 0.0) + amount`
    (pass-through).
- Return `out`.

The rate semantics here ("target per source") match what
`cross_rates_via_usd` returns. Keep the convention rigid; the spec
calls it out explicitly.

**Test list (~7):**

- `test_convert_totals_empty_input_returns_empty`
- `test_convert_totals_same_currency_passthrough` (input has only
  the target currency; no rates needed)
- `test_convert_totals_single_foreign_converts`
- `test_convert_totals_multiple_foreign_sum_to_target`
- `test_convert_totals_mixed_target_and_foreign` (input has target +
  foreign; both fold into one target entry)
- `test_convert_totals_missing_rate_passes_through` (input has 3
  codes; rate map covers 2; result has 1 target entry + 1
  unconverted entry)
- `test_convert_totals_negative_amounts_handled` (no sign-special-
  casing — verify `-100 EUR @ 1.10` → `-110 USD`)

**Verify:** `pytest tests/test_budget.py -v` green (existing tests
plus 7 new).

**Commit:** `feat: convert_totals helper + 7 tests`

---

## Task 4: `/settings` extension — home_currency field

**Files:**

- Modify: `app.py` (the `settings` view at line 846)
- Modify: `templates/settings.html`
- Modify: `tests/test_routes.py`

**Route changes:**

- Import `SUPPORTED_CURRENCIES`, `is_valid_currency` from
  `src.currency`.
- On GET: pass `supported_currencies=SUPPORTED_CURRENCIES` to
  `render_template`.
- On POST: read both `weather_units` and `home_currency` (upper-
  cased + stripped). Validate independently — accumulate errors;
  if any error, flash all of them as `danger` and re-render
  without saving either field. If clean: assign both and commit;
  flash `"Settings updated."` and redirect.

**Implementation note:** the existing route currently re-renders
on its own validation error — keep that posture but expand the
validation to cover the new field. Do NOT save weather_units when
home_currency is invalid (atomic semantics); the spec calls this
out.

**Template change:** add a `<fieldset>` for "Home currency" after
the existing temperature units fieldset, before the Save button.
Markup follows the spec — a single `<select>` populated from
`supported_currencies`, with the user's current code selected.
Short help text above the select describing what it's used for.

No new CSS needed.

**Test list (~4):**

- `test_settings_get_renders_home_currency_field` (body contains
  `name="home_currency"` and the user's current code is selected)
- `test_settings_post_saves_both_units_and_home_currency` (POST
  both fields → row updated, redirect)
- `test_settings_post_rejects_invalid_home_currency` (POST `XYZ`
  → neither field saved, form re-renders, danger flash)
- `test_settings_post_rejects_invalid_units_even_when_currency_valid`
  (atomic — bad units + good currency → neither saved)

**Verify:** `pytest tests/test_routes.py -k settings -v` green;
full suite green. Manual smoke:

- Visit `/settings`. New "Home currency" fieldset appears with the
  user's current home currency selected (USD on a fresh DB).
- Change to EUR + units to imperial; Save. Reload — both stick.
- Submit `XYZ` via DevTools-edited form value → both flash errors;
  neither field changes on the row.

**Commit:** `feat: /settings — home currency selector with atomic save`

---

## Task 5: `trip_budget` route + template — conversion + toggle + disclaimer

**Files:**

- Modify: `app.py` (the `trip_budget` view at line 2593)
- Modify: `templates/trip_budget.html`
- Modify: `tests/test_routes.py`

**Route changes:**

Imports needed:

```python
from src.budget import convert_totals       # (existing imports above)
from src.exchange_rates import get_rates_for, cross_rates_via_usd
from src.currency import SUPPORTED_CURRENCIES, SUPPORTED_CURRENCY_CODES
from datetime import date
```

Behavior (high level — the spec's snippet is the canonical
reference):

1. Parse `show_as = (request.args.get("show_as") or "").upper()`.
   - If `show_as == "MIXED"`: `convert_mode = False`; target irrelevant.
   - Elif `show_as in SUPPORTED_CURRENCY_CODES`: `convert_mode = True`; `target = show_as`.
   - Else: `convert_mode = True`; `target = current_user.home_currency`.
   - The "Show in:" dropdown's `selected` reflects this resolved
     value (so an invalid querystring shows the home currency as
     selected, not "MIXED").
2. Compute `categories = rollup_bookings_by_category(bookings, primary_currency=trip.primary_currency)`
   as today.
3. If `convert_mode` and `categories`:
   - Collect `sources = {c for cat in categories for c in cat["totals_by_currency"]}`.
   - Call `usd_rates = get_rates_for("USD", sources | {target}, db_session=db.session)`.
   - `cross = cross_rates_via_usd(usd_rates, target)`.
   - If `cross` is empty (target rate missing → can't convert
     anything): set `rate_disclaimer = None` and a separate
     `convert_warning = "Couldn't fetch rates — showing per-currency totals."`;
     skip the per-category mutation (page falls back to mixed
     display).
   - Else: for each cat, replace `cat["totals_by_currency"]` with
     `convert_totals(cat["totals_by_currency"], target, cross)`;
     replace `cat["primary_total"]` with
     `converted.get(target, 0.0)`; collect any non-target keys
     in `converted` into `unconverted_codes`. Recompute every
     `cat["share_fraction"]` off the new primary totals.
   - `rate_disclaimer = f"≈ rates as of {date.today().isoformat()} via exchangerate.host"`
     (computed once; the date matches the cache fill day, which is
     today for v1).
4. Build `grand_totals` and `grand_total_label` as today.
5. Pass new context vars to `render_template`:
   `show_as_resolved` (the dropdown's selected value: `"MIXED"` or
   a code), `convert_mode`, `supported_currencies`,
   `rate_disclaimer`, `convert_warning`, `unconverted_codes`
   (sorted list).

**Implementation note:** the existing route is short — keep the
new logic linear, no new helpers in `app.py`. The disclaimer date
is purposely *today's date* in v1; we don't surface the
exchangerate.host `rate_date` because cache freshness is the user-
visible signal. If you ever want to surface the bundle's
`rate_date`, plumb it back from `get_rates_for` (out of scope).

**Template changes:** see spec for canonical markup. Summary:

- Hero card left column: add `{% if rate_disclaimer %}` and
  `{% if convert_warning %}` and `{% if unconverted_codes %}`
  blocks under the grand total amount (each `text-muted small`).
- Hero card right column: wrap the booking-count block in the
  new `<form method="get">` that contains the "Show in:" select.
  The form auto-submits on change.
- The existing "Currencies aren't converted — totals are kept
  separate per currency." line is shown only when
  `convert_mode is False` (so the Mixed mode keeps today's
  messaging). Reword to "Showing original currencies." for
  consistency with the toggle copy.
- Category share bars: render the bar when
  `cat.share_fraction > 0` *and either* `convert_mode is True`
  (any category with a non-zero converted primary_total) *or* the
  existing condition (single-currency category). The template
  already gates on `cat.share_fraction` so the existing
  `{% if cat.share_fraction and cat.share_fraction > 0 %}` keeps
  working — recomputation in the route is what makes the bar
  meaningful under conversion.

No new CSS needed — `form-select-sm`, `text-muted small`, and
the existing budget hero classes cover the layout.

**Test list (~7):**

- `test_budget_default_show_as_uses_home_currency` — mixed-currency
  bookings + user `home_currency=USD` + `get_rates_for` mocked to
  return `{"EUR": 1.10}`. Body contains a USD total with both
  source currencies folded in.
- `test_budget_show_as_mixed_disables_conversion` — `?show_as=MIXED`
  → multi-currency total in body, no `rate_disclaimer` line, no
  unconverted footnote.
- `test_budget_show_as_specific_currency_overrides_home` —
  `?show_as=EUR` → body shows EUR total even with `home_currency=USD`.
- `test_budget_invalid_show_as_falls_back_to_home` — `?show_as=ZZZ`
  → resolves to home currency; dropdown shows home selected.
- `test_budget_unconverted_codes_listed_when_rate_missing` — mock
  `get_rates_for` to return rates for EUR but not BRL; body
  contains "(BRL not converted — rate unavailable)" and the BRL
  amount is still visible in mixed form.
- `test_budget_api_down_falls_back_to_mixed_with_note` — mock
  `get_rates_for` to return `{}` so `cross_rates_via_usd` returns
  `{}` → body still 200s; per-currency totals shown; "Couldn't
  fetch rates" line present; no disclaimer.
- `test_budget_no_categories_skips_toggle_and_disclaimer` — trip
  with zero bookings → empty-state nudge renders; no toggle form,
  no disclaimer.

**Verify:** `pytest tests/test_routes.py -k budget -v` (+ ~7);
full suite green. Manual smoke:

- Visit a trip with bookings in two currencies → totals show in
  home currency with disclaimer.
- Toggle to JPY → page reloads with JPY totals (whole yen, no
  decimals — verifies `format_money` rounding kicks in).
- Toggle to Mixed → multi-currency totals; no disclaimer.
- DevTools-rewrite the querystring to `?show_as=ZZZ` → renders in
  home currency.
- Stop the dev server's network egress (disable wifi) and reload
  → cache hits still convert if rates fetched today; otherwise
  the "Couldn't fetch rates" line shows. No crash.
- Visit the bookings list — original currencies unchanged.

**Commit:** `feat: budget — Show in: toggle, home-currency conversion`

---

## Task 6: Update roadmap + close out

**Files:**

- Modify: `docs/PHASE_3_ROADMAP.md`

**Change:**

- Flip the B3 status row to ✓ shipped.
- Link plan and spec in the same format as A1 / A2 / A3 / B1 / B2.
- Phase 3 status block (if present near the top) — update
  remaining count; B3 is the last Phase 3 row.

**No tests.**

**Commit:** `docs: mark home-currency budget (B3) shipped + add spec/plan`

---

## Phase boundary checkpoints

After each task, verify before moving on. Stop here if anything is red.

| After task | Verify |
|---|---|
| T1 | App starts; `sqlite3 vacation.db ".schema user"` shows `home_currency`; `.schema exchange_rate_cache` shows the new table. |
| T2 | `pytest tests/test_exchange_rates.py -v` all pass (~16). Full suite green. |
| T3 | `pytest tests/test_budget.py -v` (+7 new). Full suite green. |
| T4 | `pytest tests/test_routes.py -k settings -v` (+4 new). Full suite green. Manual: `/settings` saves home currency. |
| T5 | `pytest tests/test_routes.py -k budget -v` (+7 new). Full suite green. Manual: budget page toggle works; mixed/converted/missing-rate paths all visible. |
| T6 | Roadmap reflects shipped status; Phase 3 row completion noted. |

---

## Done when

- 6 tasks committed (one commit per task).
- `pytest` green; new test count ≈ **34** (~16 exchange_rates + ~7
  budget + ~4 settings integration + ~7 budget integration).
  Suite lands ~637.
- Manual smoke checklists for T4–T5 completed.
- `docs/PHASE_3_ROADMAP.md` B3 row → ✓ shipped, plan + spec links
  populated.
- Phase 3 is complete (A1 ✓, A2 ✓, A3 ✓, B1 ✓, B2 ✓, B3 ✓).
