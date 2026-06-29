# Trip-guide Phase 2a validation — 2026-06-27

End-to-end validation of the Phase 2a editorial spine (practical hyperlinks +
walking-distance chips + multi-hotel skip + transit-day skip) by composing a
**Deep-tier** guide for Trip 2 (Scandinavia '26, 23 days, 5 countries, 11
hotels) and verifying the rendered output in the browser.

This run extends the 2026-06-25 script-injected validation on Trip 4 to a
genuine end-to-end skill run on the heaviest trip in the user's database.

## Compose pipeline

Wrote `scripts/2026-06-27_compose_trip2.py` (~2300 lines) — a one-shot compose
script that follows the `/trip-guide` SKILL.md 10-step flow:

- Step 2.5 archetype: `wildlife` primary + `mixed_leisure` secondary + history
  layered in (user explicitly added history — full ERA palette for the 5
  country vignettes)
- Step 4.5 depth: `deep`
- Step 4.6 narrator angle: "Returning traveler, wants what's distinctive
  about Scandinavia + Arctic"
- Step 5 palette: kept existing `nordlys`
- Step 6.5 geocoding: filled coords for 2 missing hotels (Radisson Blu Plaza
  Oslo, Tallinn City Apartments) + cached coords for 72 named venues
- Step 7 compose: 175,515 chars of HTML emitting all spec markers
- Step 8 save: via `guide_builder.save_guide` (atomic + .bak rotation)
- Step 9 share token: minted `fd581f88-440b-47cf-9680-ba08791c2e63`
- Step 10 verification: passed all asserts after one banned-word fix

## Verification (all asserts PASS)

```
[PASS]  banned-word grep on body prose          (0 hits after 1 fix)
[PASS]  #vp-progress in DOM
[PASS]  .vp-toc has ≥2 anchors                  (8 found)
[PASS]  every <h2> in <main> has reading-time   (8/8)
[PASS]  every TOC anchor resolves to <section>  (0 orphans)
[PASS]  bibliography entries linked             (all)
[PASS]  things-to-do venue h5 wrapped           (all named venues)
[PASS]  food where-to-eat <h5> wrapped          (all named venues)
[PASS]  day_by_day h5 site cards wrapped        (all venue_key cards)
[PASS]  day_by_day walkchips render             (53 chips across 23 days)
[PASS]  things_to_do walkchip SKIP              (0 chips — multi-hotel rule)
[PASS]  transit-day walkchip SKIP               (Days 01/15/23 have 0 chips)
[PASS]  atmospheric prose link-free             (0 prose anchor leaks)
[PASS]  ERA-chip per history vignette           (5 vignettes, 5 chips)
[PASS]  go-deeper card row per Deep section     (4 sections, 4 rows)
```

Body word count: **12,490 words** (Deep tier target ~15k, comfortably in
range). Generated HTML: **175 KB**.

## Observations for the Phase 2b plan seed

### 1. Multi-hotel things_to_do skip is the right call — but the section needs an explanatory line

The spec's multi-hotel rule (skip the chip entirely on `things_to_do` for
multi-hotel trips) is correct: the section reads cleanly without orphaned "0
km from <some hotel>" chips that would have varied wildly by which city the
entry refers to. But a reader who has just come from a chip-heavy
`day_by_day` section will notice the chips are gone and wonder why.

The compose script added a single-line italic explanation at the top of the
section: *"Walking-distance chips are omitted in this section — this is a
multi-hotel trip and the right anchor varies by which city you're in. Read
the neighborhood and judge for yourself."* Worth folding into SKILL.md as
required text on multi-hotel composes.

**Phase 2b decision:** add a "When chips are skipped, say why" rule alongside
the multi-hotel skip rule, with a small `.skip-note` CSS class for the
explanatory line.

### 2. Transit-day skip works cleanly — but conflates two cases

`hotel_for_night(bookings, target_date)` returns `None` in two distinct
situations:

1. **True transit day** — flight or ferry day with no overnight (Day 01
   MSP→Oslo overnight flight; Day 15 Bergen→Helsinki gap where the user
   slept somewhere but the booking ended at the check-out date; Day 23
   Copenhagen→MSP).
2. **Day with no venue_key cards** — Day 06 (full-day fishing tour),
   Day 11 (cabin kayak / Bunes Beach hike with no named-venue entries).

The compose script's day-by-day showed 5 days with zero walkchips. From the
markup alone you cannot tell which were transit-day-skips versus
no-venue-coord-skips. Both produce the same output. The user reading the
guide doesn't care, but for debugging it's two different code paths
collapsed.

**Phase 2b consideration:** if we ever want to surface a `.transit-pill`
("travel day — no hotel tonight") for true transit days, the `hotel_for_night`
return value alone isn't enough — we'd need to distinguish "this day has no
hotel covering" from "this day has no nameable venue to chip." Probably not
worth a separate primitive.

### 3. Hotel-night semantics caught a real data-quality issue

The user's Bergen booking (Radisson Blu Bergen) has check-out 2026-08-28
morning. Per the spec, night-of-2026-08-28 is NOT covered by that booking.
But the user clearly stayed in Bergen Aug 28 (the day-by-day has a full
Bergen city day). The next hotel (Helsinki) starts Aug 29.

So Aug 28 night is a real data hole — either the Bergen booking should extend
through 08-29, or there's an unbooked Bergen night. The chip-skip behavior is
correct per the data; the data is what's off. Worth surfacing in a Phase 2b
"data check" callout — the same pattern as Trip 4's "Data check" Delta CLT
return-flight warning. The trip guide can spot bookings-data inconsistencies
the user might not see.

**Phase 2b plan seed:** lift the "Data check" callout from Phase 1 into a
reusable pattern; emit it automatically when `hotel_for_night` returns None
for a day that has bookings or itinerary items (suggesting the user stayed
SOMEWHERE that the bookings table doesn't capture).

### 4. Mapbox geocoder quality varies sharply by destination — and the venue lookup is the long pole

72 named venues for a 5-country guide. Mapbox geocoded all 72 to *something*,
but quality varied:

- **Excellent (named landmarks):** Vasa Museum, Tivoli Gardens, Reinebringen,
  Helsinki Cathedral — all snapped to the actual venue centroid.
- **Mediocre (small businesses):** "Fruene Coffee" → Longyearbyen post office
  area; "Tim Wendelboe" → Grünerløkka general area (close-ish but not the shop
  doorstep).
- **Generic (city-name-only):** A few entries snapped to the city centroid
  when Mapbox didn't know the venue — chip math still works but the distance
  is the distance-from-city-center, which can be wildly off.

For the validation chip "24 min walk · 2.0km from Wright Apartments -
Sørenga" on the Viking Ship Museum, the math is correct but the venue
coord may be a Bygdøy-area centroid rather than the actual museum address
(the museum is closed for renovation, which may have de-prioritized its
Mapbox listing). This is the same observation as the 2026-06-25 Trip 4
note (Holiday Inn Rock Hill → city centroid issue).

**Phase 2b decision:** add a confidence score to `geocode_with_cache`
results — Mapbox returns a `relevance` field 0.0–1.0; below ~0.7 the result
is likely city-centroid. The composer could then skip walkchips on
low-confidence venues OR render a softer label ("~2 km from Wright
Apartments" without the precision implied by "24 min walk").

### 5. The compose-script-as-skill-runner pattern is excellent for validation

The script approach (Python data structures for prose + emit functions for
HTML + `save_guide` call) is significantly better for validation than
in-conversation HTML authoring. Advantages:

- **Reproducible:** re-run the script after spec changes, get the same
  output structure with the new markers wired in.
- **Greppable source:** the prose lives in editable Python strings (no `<p>`
  tags between every sentence), the markup logic lives in centralized emit
  functions.
- **Cheap iteration:** the banned-word fix today was a one-line Edit + re-run,
  not a full re-compose.
- **Audit-friendly:** the script can print markup audit counts at the end
  ("128 practical-link, 53 walkchips, 6 era-chips") for fast verification
  without opening the browser.

The 2026-06-25 inject script proved this pattern on a smaller scale; today's
2026-06-27 script proved it scales to a Deep-tier 23-day multi-country guide
without losing legibility. **Plan seed:** the skill's `compose()` function
itself should adopt this two-track pattern (Python data + emit) rather than
trying to author HTML inline — it's faster to write, easier to test, and the
markup rules are easier to enforce centrally.

## Composition stats

```
HTML size:        175,515 bytes (~175 KB)
Body word count:  12,490 (Deep tier ~15k target)
Sections:         9 (hero + 8 content)
Day-by-day cards: 110 site cards across 23 days
Hotels:           11 (all geocoded after Step 6.5)
Named venues:     72 (all geocoded)
practical-link:   128 instances
walkchip:         53 instances (all in #days)
date-chip:        1 (era system on the history vignettes)
era-chip:         5 (one per history vignette)
go-deeper rows:   4 (day_by_day, field_guide, history, food)
Bibliography:     11 entries across 4 groups
```

## Files touched

- `scripts/2026-06-27_compose_trip2.py` — full compose script (NEW)
- `data/guides/2.html` — regenerated end-to-end (97KB → 175KB)
- `data/guides/2.config.json` — `depth_tier=deep`, `archetype=wildlife`,
  `narrator_angle` populated, `section_depth_overrides={"history":"deep"}`,
  `last_generated_at=2026-06-27T...`
- `vacation.db` — Booking [27] + [29] geocoded coords filled; Trip 2 share
  token minted

No test changes; tests still green at 988/988 (`.venv/bin/pytest tests/ -q`).

## Loose ends → Phase 2b plan inputs

1. **Skip-note for multi-hotel things_to_do** (Obs 1) — formalize the
   explanatory line into SKILL.md as required.
2. **Data-check callout for hotel-night gaps** (Obs 3) — lift from Phase 1
   into a reusable pattern; auto-emit when `hotel_for_night` returns None on
   a day with bookings/itinerary.
3. **Geocoder confidence threshold** (Obs 4) — use Mapbox's relevance field
   to skip or soften chips on low-confidence venues.
4. **Two-track compose pattern** (Obs 5) — refactor the skill itself to
   emit HTML via central helpers rather than authoring inline.

The script (`scripts/2026-06-27_compose_trip2.py`) is one-shot for Trip 2
but the emit-helper architecture inside it is the template for the
Phase 2b skill refactor.

## Follow-up additions (same session, after user feedback)

User reviewed the first compose and flagged two omissions that became
SKILL.md updates and a second compose pass:

### Addition A — Beer section (themed bonus, REQUIRED offer)

**Failure caught:** I batched the section/depth/narrator questions and
never asked the themed-bonus question. The Trip 2 saved sections list
(from June 2026, pre-rule) didn't include `beer`, and I silently reused
it. **Failure mode codified:** when `cfg.last_generated_at` pre-dates
2026-06-25 (when themed-bonus REQUIRED prompt landed), the offer is
STILL required on regenerate — saved-sections silence ≠ user said no.
Added to SKILL.md Step 3.

**Beer section now ships:** 17 venues across 7 cities (Oslo → Tromsø →
Bergen → Helsinki → Tallinn → Stockholm → Copenhagen). Each venue
wrapped in `practical-link` with style tag (saison / IPA / sour /
imperial stout / etc.). Opinion block recommending Põhjala Tap Room as
the must-stop. Sits between `food` and `fun_facts` per spec.

### Addition B — Per-stop wildlife in field_guide

**Failure caught:** I deep-dived Svalbard's 6 wildlife entries but left
Lofoten, Bergen, Helsinki, Tallinn, Stockholm, and Copenhagen with zero
fauna entries. The user pointed out Lofoten has white-tailed sea eagles
+ puffins; Stockholm archipelago has eider + arctic tern; Copenhagen
harbour has porpoises. **Rule codified in SKILL.md:** every stop with
≥4 hours' transit from the previous OR a named ecoregion OR non-urban
primary draw gets at minimum 3–5 fauna entries at Deep+. The marquee
stop (Svalbard here) keeps the deep dive.

**Field guide now ships:** 19 wildlife entries (was 6) across 4 regions:
Svalbard (6 deep-dive — unchanged), Norway mainland (5 new — sea eagle,
puffin, orca, eider, porpoise), Baltic cities (4 new — hooded crow,
barnacle goose, sea eagle, ringed plover), Stockholm+Copenhagen (4 new
— mute swan, goldeneye, porpoise, black-back gull). Tighter
(60–80 word) cards on the per-stop entries; the Svalbard cards stay
~120 words.

### Second-pass stats (after both additions)

```
HTML size:        195,137 bytes (~195 KB, up from 175)
Body word count:  13,977 (up from 12,490)
Sections:         10 (added Beer & breweries)
practical-link:   145 (up from 128 — +17 for beer venues)
walkchip:         53 (unchanged — beer doesn't get chips since
                       multi-hotel skip rule applies there too)
field_guide:      30 cards total (19 wildlife + 11 landmark, was
                       6 + 14)
era-chip:         5
go-deeper:        4
banned-word hits: 0 (after one fix: "world-class" → "1000-bottle"
                       in first pass; second fix on Cervisiam
                       beer entry)
```

### SKILL.md updates committed

1. **Step 3 "Detect prior run"** — added "Re-ask themed-bonus when the
   saved sections pre-date the rule" subsection. Trips with
   `last_generated_at < 2026-06-25` get the themed-bonus offer even on
   option-1 (regenerate with same sections).
2. **`field_guide` content model** — added "Per-stop wildlife minimum
   (REQUIRED at Deep+, recommended at Standard)" subsection with the
   ≥4h-transit / named-ecoregion / non-urban-draw qualification rule.

### Memory updates committed

- `feedback_themed_bonus_sections.md` — added 2026-06-27 second-strike
  audit trail with the saved-sections-pre-date-rule failure mode.
- `feedback_field_guide_per_stop_wildlife.md` (NEW) — captures the
  per-stop wildlife minimum rule for future runs.
- `MEMORY.md` index updated with the new memory pointer.
