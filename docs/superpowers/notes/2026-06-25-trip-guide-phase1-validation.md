# Phase 1 validation pass — trip-guide depth

**Date:** 2026-06-25
**Plan:** [docs/superpowers/plans/2026-06-23-trip-guide-depth.md](../plans/2026-06-23-trip-guide-depth.md)
**Method:** Regenerated an existing trip's guide end-to-end using the
new Phase 1 flow (archetype detection at Step 2.5, depth tier at 4.5,
narrator angle at 4.6, progressive disclosure / source disclosure /
wayfinding patterns in compose). Inspected the result in a browser.

## Overall

**In good shape.** The new editorial spine — archetype + depth tier +
narrator angle + the three progressive-disclosure modes + the sourcing
surfaces + the wayfinding scaffold — produced a guide that reads
distinctly more polished than the pre-Phase-1 output, without changing
the underlying section catalog. Sign-off granted to close Phase 1.

## Observations to feed Phase 2

### 1. Make hyperlinks a theme throughout

The "Sources & further reading" section at the foot lists titles,
authors, and annotations but the entries are not clickable. A reader
who wants to act on a recommendation has to retype the title into a
search box. Same gap shows up in the "Go deeper" 4-card rows.

Phase 2 should establish a hyperlink convention that runs across the
whole guide, not just the bibliography. Candidates worth thinking
through:

- **Bibliography entries** become anchor tags with a `rel="noopener"`
  link to a canonical landing page (publisher page, podcast feed,
  film page, Substack URL).
- **"Local voice" cards** link directly to the cited writer's current
  home (their Substack, IG, museum bio page).
- **Body-prose place names** — named restaurants, museums, sites —
  become clickable in `things_to_do`, `food`, and `day_by_day` site
  cards. Google Maps URLs are the obvious target.
- **Hotel and booking references** link to the booking's hotel record
  or to a Maps URL for the address.

This conflicts in spirit with the current Task 6 anti-pattern
("No URL citations in body prose — they go in the consolidated
'Sources & further reading' section only"). Phase 2 should revisit
that rule. The reasoning behind it (reading-rhythm preservation,
date-of-the-file resilience) is sound for citation links to long-form
sources — but it over-restricts practical links like Maps,
restaurant booking pages, museum opening-hours pages, which the
in-trip reader genuinely wants. Two-tier rule worth considering:
**citation links → bibliography only; practical links → fair game in
body prose, styled subtly**.

### 2. Add "walking distance from hotel" context

The day-by-day site cards and `things_to_do` entries are missing a
piece of context that mattered in the field: how far is this from
where I'm staying tonight? A `12 min walk · 0.9km from Hotel X`
chip on each entry would close that gap without forcing the reader
to flip to Maps.

The mechanics get interesting because trips can have multiple hotels
across multiple nights — so the chip should resolve to "from the
hotel you're sleeping in on this day," not "from the trip's first
hotel." For `things_to_do` (which isn't day-bound), the chip might
say "from your closest hotel" or break into per-hotel walking-time
groups when the trip is multi-city.

Phase 2 considerations:
- Where does the distance number come from? Pre-compute at compose
  time via a routing API (OSRM, Google Distance Matrix), or eyeball
  it from coordinates with a haversine + a "walking pace ÷ 5 km/h"
  multiplier and accept the imprecision?
- Visual treatment: small mono chip, paired with the existing
  travel-time pills documented in `day_by_day`. Same `<b>` accent on
  the duration so it grabs the eye.
- Privacy: hotel addresses are already in the guide. Distance chips
  don't leak anything new.

## Phase 2 seed

The two observations above should fold into the Phase 2 plan
(visual primitives toolkit). The hyperlink theme is more of an
editorial-spine refinement than a visual primitive, so it might
belong as a tail task at the end of Phase 2 or its own short
Phase 2.5 plan. The walking-distance chip is a clean new visual
primitive — fits the toolkit shape.

No regressions surfaced from Phase 1; the spine is solid. Both
observations are additive, not corrective.
