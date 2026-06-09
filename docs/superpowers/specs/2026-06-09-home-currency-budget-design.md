# Home-Currency Budget Totals — Design Spec

> **Status:** Draft, awaiting review. Phase 3 feature B3 from
> [docs/PHASE_3_ROADMAP.md](../../PHASE_3_ROADMAP.md). Spec captures
> the design decisions made during the 2026-06-09 brainstorm. Third
> feature in the "plan smarter" thread and the final Phase 3 feature;
> A1 / A2 / A3 / B1 / B2 shipped 2026-05-31 through 2026-06-08.

## Goal

Let a user with bookings in mixed currencies see a single grand
total in their home currency on the budget page. A small toggle at
the top of the budget hero ("Show in: [USD ▼]") picks the target
currency or switches to a "Mixed (no conversion)" view.

Per-booking rows on the bookings list still display their original
currency. The conversion applies to **rollup totals only**:

- The grand total in the budget hero card.
- Each category row's total on the right side.
- The category share bars — recomputed off the converted totals so
  the bars represent relative spend in consistent units.

The user's preferred home currency lives on a new
`User.home_currency` column (default `USD`), settable from the
existing `/settings` page introduced by B1.

Rates come from [exchangerate.host](https://exchangerate.host) —
free, no API key, daily granularity. A new `ExchangeRateCache`
table caches one row per `(base_currency, target_currency, date)`
with a 24-hour TTL. The page renders a small disclaimer
("≈ rates as of 2026-06-09 via exchangerate.host") under the grand
total so the user knows the figures are reference, not contractual.

When rates can't be fetched (API down, network error) or a
currency has no rate available, the page degrades silently: the
unrenderable currency stays in its original form alongside the
converted portion, and the disclaimer line notes which currencies
were not converted. No red banner, no error page.

## Background and motivation

Phase 3 roadmap calls this out as the sixth and final "plan
smarter" feature:

> 💰 Estimated total: **$3,427** (≈ rates as of today)

Travel budgets are real-world multi-currency: flights billed in
USD, a hotel in EUR, restaurants in GBP, train tickets in DKK.
Today the budget page lists each currency on its own line ("$1,200
+ €600 + £150") which is *honest* but not *useful* — you can't tell
whether you're under or over plan without doing math.

The conversion is the smallest possible value-add for that pain.
The roadmap deliberately puts B3 last because currency rounding
and rate freshness have the most tradeoffs of the B-thread
features. Now that B1 (`/settings` page) and B2 (`Trip.timezone_iana`
column on the same table) have both shipped, this slots in cleanly.

The cache pattern mirrors `src/geocoding.py` + `GeocodeCache` and
`src/weather.py` + `WeatherCache`: external API + cache table +
freshness check + graceful failure mode. Lazy on page load is fine
— budget pages are infrequent.

## Scope

**In scope:**

- One new SQLAlchemy model `ExchangeRateCache` keyed by
  `(base_currency, target_currency, date)` with a 24-hour TTL.
- One new column `User.home_currency` (`String(3)`, default `'USD'`).
- One new `src/exchange_rates.py` module:
  - Pure helpers: `convert_totals`, `cache_key_for`,
    `is_rate_fresh`.
  - Impure (mocked in tests): `fetch_latest_rates` (exchangerate.host
    client) and `get_rates_for` (cache-first, returns a
    `{currency: rate}` dict).
- Extend `src/budget.py`:
  - New pure function `convert_totals(totals_by_currency,
    target_currency, rates) -> dict` — referenced directly in the
    roadmap.
- Extend the existing `/settings` route + template (built in B1)
  to surface a home-currency dropdown alongside the existing
  temperature-units field. Both fields save in one POST.
- Extend `trip_budget` route + template:
  - Read `?show_as=` querystring; default to
    `current_user.home_currency`. A reserved value `mixed` switches
    off conversion entirely.
  - When converting, replace `totals_by_currency` and the category
    bars with values computed in the target currency.
  - Render a "Show in:" `<select>` in the hero card. Submitting
    reloads the page with the chosen `show_as`.
  - Render an unobtrusive disclaimer line under the grand total
    showing the rates' as-of date and source.
- Unit tests for every pure helper. Integration tests for the
  settings POST round-trip, the budget page render in both modes
  (mixed and converted), the cache hit/miss path (with API
  mocked), and the missing-rate fallback.

**Out of scope (explicit):**

- No per-booking conversion. Booking rows on the bookings list keep
  their original currency. Roadmap is explicit on this.
- No live rate ticker, no intraday refresh. One fetch per day per
  base currency.
- No per-trip home-currency override — the setting is global per
  user. A trip in EUR-land still rolls up in the user's home
  currency.
- No multi-provider fallback. If exchangerate.host is down, no
  conversion that page load.
- No historical-rate lookup ("what was a EUR worth on the day I
  booked?"). v1 always uses today's rates.
- No "spent so far / remaining" budget tracking. The roadmap parks
  this under C3 (quick spend log) for a later phase.
- No editing of cached rates from the UI. They are derived data
  with a 24h TTL; the cache is purely a freshness/performance
  artifact.
- No currency display preference beyond home_currency (no "show
  all rollups in EUR but home_currency is USD"). The toggle on the
  budget page handles one-off views.
- No new currency codes beyond what `SUPPORTED_CURRENCIES`
  already lists (21 codes in `src/currency.py`).

## Decisions baked in

| Decision | Choice | Why / rejected alternative |
|---|---|---|
| Provider | **exchangerate.host** (`https://api.exchangerate.host/latest`) | Free, no API key, commercial use allowed. Roadmap-specified. Same posture as Open-Meteo (B1) — pick the no-friction option. |
| Cache TTL | **24 hours** | Roadmap-specified. Daily rates are stable enough; one fetch per day per base is plenty. |
| Cache key | **`(base_currency, target_currency, date)`** | Roadmap-specified. Direct lookup, no rounding tricks. |
| Pivot currency for fetches | **Always USD** — one API call returns all-vs-USD rates. Cross-pair lookups (e.g. EUR→GBP) go through USD. | Cheapest fetch (one call/day) — exchangerate.host's `/latest?base=USD` returns rates for every supported code in one response. Storing only USD-base rows keeps the cache ~21 rows/day instead of ~441. Cross-rate accuracy is fine at 4-decimal precision. |
| Home currency storage | **`User.home_currency String(3)` default `'USD'`** | Same shape as `Trip.primary_currency`. ISO 4217 code. Validated against `SUPPORTED_CURRENCY_CODES` from `src/currency.py`. |
| Default page view (home set) | **Convert to home_currency on load**. Toggle defaults to user's home_currency. | Roadmap framing ("The budget page can show totals in the user's home currency") reads as the natural default. Mixed-by-default would mean the feature is invisible until users click. |
| Default page view (home = primary_currency) | **Same — show converted view**, even though for a single-currency trip "converted" and "mixed" are visually identical. | Consistency. No special-case branching. |
| Toggle options | **"Mixed (no conversion)" + each supported currency** (21 codes). Reserved value `mixed` in the querystring. | Lets a user spot-check "what is this in JPY?" without changing their home_currency. The "Mixed" option is the escape hatch back to today's behavior. |
| Toggle persistence | **Querystring only — not persisted.** Default re-derives from `home_currency` on each visit. | Conversion is a one-off curiosity; persistence would make the global home_currency setting feel inconsistent. |
| Conversion granularity | **Each `totals_by_currency` dict is converted as a whole**. Mixed-currency totals collapse to a single target-currency total per category. Grand total is the sum of converted category totals. | Mirrors how the page reads today — the rollup is the conversion target. |
| Per-category bars under conversion | **Recompute `share_fraction` off the converted totals.** | Bars represent relative spend; consistent units make the proportions meaningful. The math is identical to today (`primary_total / grand_primary`) with `target_currency` substituted. |
| Missing rate behavior | **Pass-through unconverted.** `convert_totals` returns a dict that includes (a) the target-currency-summed converted portion and (b) any source currencies whose rate was missing, in original form. Template renders these with a small footnote: "(EUR not converted — rate unavailable)". | "No fake numbers" rule (same as B1/B2 silent failure). Better to show partial truth than to drop data. |
| API failure on the page load | **Fall back to mixed display, log a warning, render an inline note** ("Couldn't fetch rates — showing per-currency totals"). | Same posture as B1 weather. Page doesn't break; conversion just doesn't happen. |
| Rate freshness check | **`fetched_at + 24h < utcnow()`** — same TTL pattern as `WeatherCache.fetched_at`. | Established pattern. |
| Rounding | **2 decimal places for all currencies except `JPY` / `KRW`** (no decimals, mirroring `format_money`). | Reuses the existing `format_money` rules — no new rounding logic to invent. |
| Disclaimer copy | **"≈ rates as of YYYY-MM-DD via exchangerate.host"** under the grand total, in `text-muted small`. | Quiet, accurate, gives the user the source. Date is the date of the freshest cached rate row used in the conversion. |
| Settings UX | **Single combined form** — extends the existing B1 form with a new fieldset above (or below) the temperature units. Saves both fields on one POST. | The settings page already has one Save button; staying single-form avoids two-button surface area. |
| Validation | **`is_valid_currency(code)` from `src/currency.py`** | Already exists. Rejects "USDS" before save. |
| Migration | **`_run_safe_alters` adds `user.home_currency`**; `db.create_all()` creates `exchange_rate_cache`. | Same additive pattern as B1's `user.weather_units` and B2's `trip.timezone_iana`. |
| Booking-page behavior | **Unchanged.** No conversion shown on individual booking rows. | Roadmap is explicit; booking rows remain "ground truth" in their original currency. |

## Architecture

```
                  ┌──────────────────────────────────────┐
                  │  exchangerate.host  (no key)         │
                  │  /latest?base=USD                    │
                  └─────────────────▲────────────────────┘
                                    │  (once / day)
                          ┌─────────┴────────────┐
                          │  src/exchange_rates  │
                          │  fetch_latest_rates  │
                          │  get_rates_for       │
                          │  (cache-first)       │
                          └─────────▲────────────┘
                                    │
                          ┌─────────┴────────────┐
                          │  ExchangeRateCache   │
                          │  (base, target, date)│
                          │   TTL 24 hours       │
                          └─────────▲────────────┘
                                    │
                          ┌─────────┴────────────┐
                          │  src/budget          │
                          │  convert_totals(...) │
                          └─────────▲────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                                                       │
        ▼                                                       ▼
┌──────────────────────────┐                  ┌────────────────────────────┐
│ GET /trips/<id>/budget   │                  │ GET / POST /settings       │
│  (Show in: [USD ▼])      │                  │  (home_currency dropdown)  │
└──────────────────────────┘                  └────────────────────────────┘
```

### Data model changes

| Table | Column | Type | Default | Notes |
|---|---|---|---|---|
| `user` | `home_currency` | `String(3)` | `'USD'` | ISO 4217. Validated against `SUPPORTED_CURRENCY_CODES`. |
| `exchange_rate_cache` (new) | `id` | Integer | — | PK |
| `exchange_rate_cache` | `base_currency` | `String(3)` | — | ISO 4217, always `'USD'` in v1 (kept as a column for forward compat). |
| `exchange_rate_cache` | `target_currency` | `String(3)` | — | ISO 4217. |
| `exchange_rate_cache` | `rate` | Float | — | How many `target_currency` per one `base_currency`. e.g. `1.10` for `(USD, EUR)`. |
| `exchange_rate_cache` | `rate_date` | Date | — | The date the rate applies to (exchangerate.host returns the date in the JSON; we use it as the cache key). |
| `exchange_rate_cache` | `fetched_at` | DateTime | `utcnow` | TTL anchor — `fetched_at + 24h < utcnow` → re-fetch. |
| `exchange_rate_cache` | unique index | — | — | `(base_currency, target_currency, rate_date)` unique. |

Migration uses the same additive `_run_safe_alters` pattern as
B1 and B2.

### `src/exchange_rates.py` (new module)

```python
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, Mapping, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 24 * 60 * 60
DEFAULT_BASE = "USD"
API_URL = "https://api.exchangerate.host/latest"
API_TIMEOUT_SECONDS = 5


@dataclass
class RateBundle:
    """A coherent set of rates fetched together — keyed by target currency."""
    base: str                          # always "USD" in v1
    rates: Dict[str, float]            # {"EUR": 1.10, "GBP": 1.27, ...}
    rate_date: date                    # the date the rates apply to
    fetched_at: datetime               # used for TTL freshness


# Pure helpers (no DB, no network)

def is_rate_fresh(fetched_at: datetime, now: datetime) -> bool:
    """True iff fetched_at + 24h > now."""

def cache_key_for(base: str, target: str, d: date) -> Tuple[str, str, date]:
    """(base, target, d) — upper-cased codes."""


# Impure (mocked in tests)

def fetch_latest_rates(base: str = DEFAULT_BASE) -> Optional[RateBundle]:
    """One exchangerate.host call. Returns None on network / 5xx.
    Timeout 5s. Does NOT touch the DB."""

def get_rates_for(
    base: str,
    targets: Iterable[str],
    *,
    db_session,
    now: Optional[datetime] = None,
) -> Dict[str, float]:
    """Cache-first. Returns {target: rate} for every target whose
    rate could be served from cache OR freshly fetched. Targets
    whose rate cannot be obtained are omitted from the dict.

    Side effects: writes ExchangeRateCache rows on a successful
    fetch.
    """
```

`get_rates_for` is the only function the routes call. It hides
both the cache and the API behind a single dict-returning surface.

### `src/budget.py` extension

```python
def convert_totals(
    totals_by_currency: Mapping[str, float],
    target_currency: str,
    rates: Mapping[str, float],
) -> Dict[str, float]:
    """
    Collapse a per-currency totals dict into the target currency
    using the supplied rates.

    `rates` is {source_currency: rate}, where rate = "how many
    target_currency per one source_currency". The same-currency
    pair has implicit rate 1.0 even if not in `rates`.

    Source currencies whose rate is missing pass through unchanged
    — they appear in the result keyed by their original code,
    alongside the (single) target_currency entry.

    Examples:
      convert_totals({"USD": 100, "EUR": 50}, "USD", {"EUR": 1.10})
        -> {"USD": 155.00}

      convert_totals({"EUR": 100, "GBP": 50, "BRL": 200},
                     "USD", {"EUR": 1.10, "GBP": 1.27})
        -> {"USD": 173.50, "BRL": 200}

      convert_totals({}, "USD", {})  -> {}
    """
```

This is the only new function in `src/budget.py`. The existing
`rollup_bookings_by_category` stays untouched — the route layer
post-processes its output by calling `convert_totals` on each
category's `totals_by_currency` dict when conversion is on.

### Route changes — `trip_budget`

```python
@app.route("/trips/<int:trip_id>/budget")
@login_required
def trip_budget(trip_id):
    trip, user_role = _trip_with_access_or_404(trip_id, role="viewer")
    bookings = Booking.query.filter_by(trip_id=trip.id).all()

    show_as = (request.args.get("show_as") or "").upper() or current_user.home_currency
    convert_mode = show_as != "MIXED"

    categories = rollup_bookings_by_category(
        bookings, primary_currency=trip.primary_currency,
    )

    rate_disclaimer = None
    unconverted_codes: set[str] = set()

    if convert_mode and categories:
        # All source currencies that appear anywhere on this trip:
        sources = {c for cat in categories for c in cat["totals_by_currency"]}
        rates = get_rates_for(
            "USD", sources | {show_as},
            db_session=db.session,
        )
        cross_rates = _cross_rates_via_usd(rates, target=show_as)
        for cat in categories:
            converted = convert_totals(
                cat["totals_by_currency"], show_as, cross_rates,
            )
            # Anything still keyed by a non-target code = missed rate:
            unconverted_codes.update(k for k in converted if k != show_as)
            cat["totals_by_currency"] = converted
            cat["primary_total"] = converted.get(show_as, 0.0)
        grand_primary = sum(cat["primary_total"] for cat in categories)
        for cat in categories:
            cat["share_fraction"] = (
                cat["primary_total"] / grand_primary if grand_primary > 0 else 0.0
            )
        if rates:
            rate_disclaimer = _format_rate_disclaimer(rates_date=date.today())

    grand_totals: dict = {}
    for cat in categories:
        for code, amount in cat["totals_by_currency"].items():
            grand_totals[code] = grand_totals.get(code, 0.0) + amount
    grand_total_label = format_money_totals(grand_totals, empty="No costs entered yet")
    total_uncosted = sum(cat["uncosted_count"] for cat in categories)

    return render_template(
        "trip_budget.html",
        trip=trip,
        user_role=user_role,
        categories=categories,
        grand_total_label=grand_total_label,
        total_bookings=len(bookings),
        total_uncosted=total_uncosted,
        show_as=show_as,
        convert_mode=convert_mode,
        supported_currencies=SUPPORTED_CURRENCIES,
        rate_disclaimer=rate_disclaimer,
        unconverted_codes=sorted(unconverted_codes),
    )
```

`_cross_rates_via_usd(rates_keyed_by_currency_per_usd, target)` is
a tiny helper in `app.py` (or `src/exchange_rates.py`) that
converts the USD-base rate dict into a source→target dict. Math:
`cross_rate(X→Y) = rate(USD→Y) / rate(USD→X)`. Returns `{}` if the
target rate is missing (which forces full pass-through).

### Route changes — `/settings`

```python
@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        units = (request.form.get("weather_units") or "").strip()
        home = (request.form.get("home_currency") or "").strip().upper()
        errors = {}
        if units not in ("metric", "imperial"):
            errors["weather_units"] = "Invalid units selection."
        if not is_valid_currency(home):
            errors["home_currency"] = "Pick a supported currency."
        if errors:
            for msg in errors.values():
                flash(msg, "danger")
            return render_template(
                "settings.html",
                supported_currencies=SUPPORTED_CURRENCIES,
            )
        current_user.weather_units = units
        current_user.home_currency = home
        db.session.commit()
        flash("Settings updated.", "info")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html",
        supported_currencies=SUPPORTED_CURRENCIES,
    )
```

`SUPPORTED_CURRENCIES` is imported from `src.currency`.

### Template changes

**`templates/settings.html`** — add a new fieldset for the home
currency below the existing temperature units fieldset:

```jinja
<fieldset class="mb-4">
  <legend class="h6 text-muted">Home currency</legend>
  <p class="small text-muted mb-2">
    Used as the default for budget conversions. You can switch
    targets per-page from the budget toggle.
  </p>
  <select name="home_currency" id="home_currency"
          class="form-select" style="max-width: 24rem;">
    {% for code, name in supported_currencies %}
      <option value="{{ code }}"
              {% if current_user.home_currency == code %}selected{% endif %}>
        {{ code }} — {{ name }}
      </option>
    {% endfor %}
  </select>
</fieldset>
```

**`templates/trip_budget.html`** — extend the hero card with the
toggle, the disclaimer line, and the unconverted-codes footnote:

```jinja
<div class="row align-items-center g-3">
  <div class="col-md-7">
    <div class="text-muted small">Estimated total</div>
    <div class="budget-hero-amount">{{ grand_total_label }}</div>
    {% if rate_disclaimer %}
      <div class="text-muted small mt-1">{{ rate_disclaimer }}</div>
    {% endif %}
    {% if unconverted_codes %}
      <div class="text-muted small">
        ({{ unconverted_codes | join(', ') }} not converted —
        rate unavailable)
      </div>
    {% endif %}
  </div>
  <div class="col-md-5">
    <form method="get" class="d-flex align-items-center gap-2 mb-2">
      <label for="show_as" class="small text-muted">Show in:</label>
      <select name="show_as" id="show_as"
              class="form-select form-select-sm"
              style="max-width: 12rem;"
              onchange="this.form.submit()">
        <option value="MIXED" {% if not convert_mode %}selected{% endif %}>
          Mixed (no conversion)
        </option>
        {% for code, name in supported_currencies %}
          <option value="{{ code }}"
                  {% if convert_mode and show_as == code %}selected{% endif %}>
            {{ code }}
          </option>
        {% endfor %}
      </select>
    </form>
    {# existing booking-count block stays #}
  </div>
</div>
```

The "Currencies aren't converted — totals are kept separate per
currency" note in the current hero is removed when `convert_mode`
is true and kept (slightly reworded — "Showing original
currencies") when the user picks "Mixed".

No new CSS needed — Bootstrap's `form-select-sm`, `text-muted
small`, and existing budget hero classes handle the layout.

## The page experience

### Budget page, conversion on (default)

```
Budget
═══════════════════════════════════════════

  Estimated total                  Show in: [USD ▼]
  $3,427.50
  ≈ rates as of 2026-06-09         8 bookings on this trip
    via exchangerate.host          2 without a cost set

  ✈️  Flights         3 bookings         $1,200.00
  ════════════════════════ 35%

  🏨  Hotels          2 bookings         $1,500.00
  ═══════════════════════════════ 44%

  🍴  Restaurants     2 bookings         $400.00
  ════════ 12%

  🚗  Car             1 booking          $327.50
  ══════ 9%
```

### Budget page, "Mixed (no conversion)" selected

Identical to today's behavior:

```
Budget
═══════════════════════════════════════════

  Estimated total                  Show in: [Mixed ▼]
  $1,200.00 + €600.00 + £150.00
  Showing original currencies      8 bookings on this trip
                                   2 without a cost set

  ✈️  Flights         3 bookings         $1,200.00
  🏨  Hotels          2 bookings         €600.00 + £150.00
  ...
```

The per-category bars hide for categories with mixed currencies
in this mode (same as today — `share_fraction` only meaningful
against `primary_currency`).

### Budget page, conversion on but one rate missing

```
  Estimated total                  Show in: [USD ▼]
  $3,427.50 + R$200.00
  ≈ rates as of 2026-06-09         8 bookings on this trip
    via exchangerate.host
  (BRL not converted — rate unavailable)
```

### Budget page, API down on this load

```
  Estimated total                  Show in: [USD ▼]
  $1,200.00 + €600.00
  Couldn't fetch rates — showing per-currency totals.
```

(The toggle still reads "USD" — the user's choice is honored, the
conversion just can't be applied this load. Reloading after the
API recovers does the right thing because the cache fills.)

### Settings page

```
Settings

Temperature units
  ◉ Celsius (°C)
  ◯ Fahrenheit (°F)

Home currency
  Used as the default for budget conversions. You can switch
  targets per-page from the budget toggle.
  [ USD — US Dollar              ▼ ]

[ Save ]
```

Saving updates both fields atomically. Flash: "Settings updated."

## Edge cases

| Case | Behavior |
|---|---|
| Trip has no bookings | `categories` is empty; the existing empty-state nudge renders; the toggle and disclaimer don't render (gated on `categories \| length > 0`). |
| All bookings are uncosted | `categories` populates but every `totals_by_currency` is empty; `convert_totals({}, ...)` returns `{}`; grand total shows the existing "No costs entered yet" empty string. |
| All bookings share one currency that equals the chosen target | `convert_totals({"USD": 1200}, "USD", {})` returns `{"USD": 1200}` — same-currency passes through with implicit rate 1.0. No API call needed (cache-first, but `get_rates_for` short-circuits when `targets` is `{base}` only). |
| `show_as` querystring is gibberish (`?show_as=XYZ`) | `XYZ` isn't in `SUPPORTED_CURRENCY_CODES`; route falls back to `home_currency`. No error page. |
| `show_as=MIXED` querystring | `convert_mode = False`; page renders today's behavior verbatim. |
| User has no `home_currency` yet (pre-B3 row, no default applied) | The column has `nullable=False, default='USD'`, and `_run_safe_alters` adds it with `DEFAULT 'USD'`, so existing rows pick up USD. New users get USD via the model default. |
| API returns a `success: false` body even with HTTP 200 | `fetch_latest_rates` checks the `success` field and returns `None` on failure. Logged as a warning. |
| API returns rates with codes we don't support | They're stored in cache anyway (forward-compat for adding currencies later) but ignored by `get_rates_for` because we only look up the codes we ask for. |
| API rate value is non-numeric / null | `fetch_latest_rates` filters those out before constructing the `RateBundle`. Logged. |
| `_cross_rates_via_usd` called when the target rate is missing | Returns `{}` — `convert_totals` then passes everything through unconverted. The disclaimer line says "Couldn't fetch rates." |
| User changes home_currency mid-session | Next page load picks up the new default. Any open budget page tab still shows the old value until reloaded — acceptable. |
| Concurrent fetches for the same `(USD, today)` key | Two requests racing: second one's insert fails on the unique index → catch and re-query. No user-visible difference. Same pattern as `WeatherCache`. |
| Cache row is stale (`fetched_at + 24h < utcnow`) | Treated as a miss. Re-fetch and upsert (delete-by-key + insert, or update-in-place). |
| One currency on the trip is a code that's not in `SUPPORTED_CURRENCIES` (manually inserted via DB) | `get_rates_for` returns no rate for it; `convert_totals` passes it through; template shows it in the unconverted footnote. Page doesn't crash. |
| Half-cent fractions after conversion | `convert_totals` returns a float; `format_money` rounds to 2 decimals (or 0 for JPY/KRW) on render. |
| Two trips with different `primary_currency` but same user | `home_currency` is global, so both trips' budgets convert to the same target. No conflict. |
| Settings POST with valid units but invalid home_currency | Both errors flash; neither field saves. Form re-renders with the user's typed values still in the inputs. |
| Bot / search-crawler hitting `/trips/<id>/budget?show_as=...` 500 times | Cache absorbs it — only one API call per day per base. Cheap. |
| Database migration — first deploy | `_run_safe_alters` adds `user.home_currency` with `DEFAULT 'USD'`. `db.create_all()` creates `exchange_rate_cache`. Existing trips and users inherit USD. |
| `exchange_rate_cache` missing on a deploy where `db.create_all()` hasn't run yet | `get_rates_for`'s DB query raises; we catch `OperationalError` (table missing) and treat it as "no cache, no rates available". Same defensive posture as B2's `timezonefinder` import-fails branch. |

## Testing

### Unit tests (new) — `tests/test_exchange_rates.py`

**`is_rate_fresh`** (~3):
- `fetched_at = now - 23h` → True.
- `fetched_at = now - 25h` → False.
- `fetched_at = now` → True.

**`cache_key_for`** (~2):
- Upper-cases base / target.
- Date passes through unchanged.

**`fetch_latest_rates`** (~4, with `requests.get` mocked):
- 200 + `success: true` → returns `RateBundle` with parsed rates.
- 200 + `success: false` → returns None, logs.
- 500 response → returns None, logs.
- Network error / timeout → returns None, logs.

**`get_rates_for`** (~5, with cache + API mocked):
- Cache miss → API call → cache write → returns expected dict.
- Cache hit (fresh) → no API call → returns cached dict.
- Stale rows → re-fetch and overwrite.
- API failure on cache miss → returns `{}`, no rows written.
- Target subset honored — only requested currencies in the result.

### Unit tests (new) — `tests/test_budget.py` (existing file extended)

**`convert_totals`** (~7):
- Empty totals → empty dict.
- All same-currency → pass through unchanged (implicit rate 1).
- Single foreign currency with rate present → converted to target.
- Multiple foreign currencies, all rates present → summed to one target entry.
- Missing rate for one currency → that currency passes through, others convert.
- Mixed target + sources — target stays as itself, sources fold in.
- Negative amounts handled — the helper doesn't special-case sign (refund-style entries).

### Unit tests (new) — `tests/test_app_helpers.py` (or wherever `_cross_rates_via_usd` lives)

**`_cross_rates_via_usd`** (~4):
- Target == base → returns same-rate identity (`{X: rate(USD→X)}`).
- Target missing from input → returns `{}`.
- Source missing → omitted from output (but a different source with a rate is included).
- Numeric precision sanity check (`1 / 1.10 ≈ 0.909`).

### Integration tests (extend) — `tests/test_routes.py`

- `test_settings_get_renders_home_currency_field` — body contains a `<select name="home_currency">` populated with the user's current code selected.
- `test_settings_post_saves_both_units_and_home_currency` — POST both fields → row updated, redirect, flash.
- `test_settings_post_rejects_invalid_home_currency` — POST `XYZ` → neither field saved, form re-renders, flash danger.
- `test_settings_post_rejects_invalid_units_even_when_currency_valid` — both errors flash, neither saves.
- `test_budget_default_show_as_uses_home_currency` — GET on a trip with mixed currencies, user `home_currency=USD` → body shows single converted total.
- `test_budget_show_as_mixed_disables_conversion` — `?show_as=MIXED` → body shows multi-currency total, no rate disclaimer.
- `test_budget_show_as_specific_currency_uses_it` — `?show_as=EUR` → body shows EUR total even if user's home is USD.
- `test_budget_invalid_show_as_falls_back_to_home` — `?show_as=ZZZ` → uses USD.
- `test_budget_unconverted_codes_listed_when_rate_missing` — mock `get_rates_for` to return rates for some but not all currencies → body shows the footnote naming the unconverted codes.
- `test_budget_api_down_falls_back_to_mixed_with_note` — mock `get_rates_for` to return `{}` → body still renders, multi-currency totals shown, "Couldn't fetch rates" line present.
- `test_budget_no_categories_skips_toggle` — trip with zero bookings → empty-state nudge renders, no toggle, no disclaimer.

Approximately 21 unit + 11 integration = **~32 new tests**. Suite
target: 603 → ~635.

### Manual smoke checklist

- Visit `/settings`; change home currency to EUR; save. Visit a
  trip's budget page → totals show in EUR with the disclaimer.
- Toggle "Show in:" to JPY → page reloads with JPY totals
  (rounded to whole yen, no decimals).
- Toggle "Show in:" to Mixed → page shows the multi-currency
  display with no disclaimer.
- Open DevTools, change URL to `?show_as=ZZZ` → page renders
  using the user's home currency (no error).
- Disconnect network, reload budget page → totals show in mixed
  currency with the "Couldn't fetch rates" note. No banner.
- Re-enable network, reload → totals show converted (cache hit if
  rates were already fetched today, fresh fetch otherwise).
- Visit a trip with bookings in a currency you've never used before
  (e.g. SEK) → it converts (rate available) or shows in the
  unconverted footnote (rate genuinely unavailable). No crash.
- Open the bookings list — booking rows still show original
  currencies. (Conversion is rollups only.)

## Dependencies

- B1's `/settings` page (route, template, navbar link) — extended,
  not replaced.
- B2's `_run_safe_alters` pattern — reused for the new column.
- `src/currency.py` — `SUPPORTED_CURRENCIES`, `is_valid_currency`,
  `format_money` are all reused unchanged.
- `src/budget.py` — `rollup_bookings_by_category` and
  `format_money_totals` are reused unchanged; `convert_totals` is
  the new pure helper added to the same module.
- `requests` library — already a dependency for geocoding and B1
  weather.
- No new Python packages.
- No new external service that needs a key — exchangerate.host is
  the same posture as Open-Meteo (B1) and `timezonefinder` (B2).

## Open questions resolved during brainstorm

| Question | Decision |
|---|---|
| Provider | exchangerate.host (free, no key) |
| Cache TTL | 24 hours |
| Cache key | `(base, target, date)` |
| Pivot currency | Always USD for the API fetch; cross-rates via USD |
| Home currency storage | `User.home_currency String(3)` default `'USD'` |
| Default page view | Convert to home_currency on load; toggle defaults to it |
| Toggle persistence | Querystring only; not saved |
| Conversion granularity | Per-category `totals_by_currency` collapsed to target |
| Per-category bars | Recomputed off converted totals |
| Missing rate behavior | Pass-through unconverted; named in a footnote |
| API failure | Silent fallback to mixed; small inline note |
| Booking rows | Unchanged — original currency stays |
| Settings UX | One combined form with both fields, one Save button |
| Rounding | Reuse `format_money` rules (2 decimals; 0 for JPY/KRW) |
| Disclaimer | "≈ rates as of YYYY-MM-DD via exchangerate.host" |

## Updating this document

Same convention as A1 / A2 / A3 / B1 / B2. Fix the spec inline and
commit `docs: clarify <section> in home-currency-budget spec` if
implementation reveals a design issue. The spec is the record of
"what we agreed to" — not a frozen artifact.
