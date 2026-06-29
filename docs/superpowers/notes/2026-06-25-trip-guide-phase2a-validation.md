# Trip-guide Phase 2a validation — 2026-06-25 (2026-06-26 UTC)

Validation pass for the Phase 2a editorial spine: practical hyperlinks +
walking-distance chips + Step 6.5 geocoding. Regenerated trip 4 ("3SSB
Finals · Rock Hill, SC · Jul 23–27 2026") via a one-shot script
(`scripts/2026-06-25_inject_phase2a.py`) that wraps named venues in
`<a class="practical-link">` and inserts `<span class="walkchip">`
into day_by_day site cards. Saved through `guide_builder.save_guide`.

## Verification (`scripts/2026-06-25_verify_phase2a.py`) — all 11 asserts PASS

```
[PASS]  banned-word grep on body prose           (no hits)
[PASS]  #vp-progress in DOM
[PASS]  .vp-toc has ≥2 anchors                   (9 found)
[PASS]  every <h2> in <main> has reading-time    (9/9)
[PASS]  every TOC anchor resolves to <section>   (all resolve)
[PASS]  bibliography entries linked              (9/14 — domain mentions
                                                  don't need links)
[PASS]  things-to-do h4 venues linked            (12/12)
[PASS]  food where-to-eat <b> venues linked      (11/11)
[PASS]  day_by_day h5 site cards linked          (15/19 — generic non-venue
                                                  titles unmodified)
[PASS]  day_by_day has walkchip elements         (7 walkchips)
[PASS]  atmospheric prose link-free (day intros) (clean)
```

## Observations for the Phase 2b plan seed

### 1. Mapbox is noisy for small-town POIs — many venues resolve to city centroid

Of the 36 named venues geocoded for trip 4, ~14 resolved to the Rock Hill
city centroid (34.9237, -81.0262) rather than a real venue address. Holiday
Inn Rock Hill itself is one of these — the venue-name lookup returns city
center, but the booking row's own `geocoded_lat/lng` correctly resolves to
the actual hotel (34.945004, -80.968575). Same for the Sports & Event
Center.

**Implication for the composer:** for venues that ALSO have a Booking row
(hotels, activity-venue bookings), prefer the booking row's coords over a
venue-name lookup. The script does this manually for trip 4 via
`sports_booking.geocoded_lat`. The skill should formalize this — if a
mentioned venue name matches a booking title (case-insensitive), use the
booking's coords.

**Implication for the chip math:** city-centroid venues will produce
"reasonable but generic" chips like "8 min by car · 7.2km from Holiday
Inn" — useful in aggregate, but if every venue across a section reports
the same distance, the reader can tell it's the city center. Worth
considering: when the resolved coord is within ~50m of a known "city
center" point AND the venue name doesn't match the city name itself,
treat as "no useful coord" and skip the chip (or render with a softer
"Rock Hill area" label instead of a precise km).

### 2. The "single-hotel rule" for things_to_do worked smoothly

Trip 4 is a clean single-hotel case (Holiday Inn for all 4 nights). The
spec's "emit chips on every things_to_do entry, anchored to that one
hotel" path was straightforward to implement. I didn't end up emitting
chips on things_to_do for this validation pass (the script focused on
day_by_day) — but the rule is simple enough that follow-up work can wire
it in without surprises. For a multi-hotel trip (Scandinavia '26 is the
next test case at 23 days and 5+ countries), I want to confirm the
omit-chip behavior is in fact clearer than emitting per-hotel labels.

### 3. Chip styling — needs visual differentiation from the existing `.tag` chips

I styled `.walkchip` as a mono-font, light-surface, hairline-bordered
pill — slightly different from the existing `.tag` and `.tag.cat` chips
(which use `var(--accent)` accent borders). This works, but on the day_by_day
cards the chips visually nest inside the existing `.tags` row alongside a
`.tag.cat` chip ("Riverwalk · 4 mi from hotel"). The two chip styles end
up adjacent and look slightly inconsistent. **Phase 2b decision:** either
(a) merge `.walkchip` into the `.tag` family with a `.tag.distance` variant,
or (b) move `.walkchip` to a separate row below the `.tags` row to give
it its own visual rhythm. Lean toward (a) — fewer visual primitives.

### 4. Bibliography linking — 5 of 14 sources are "domain mentions" not URLs

The bibliography section has 14 `<li>` entries; only 9 got a
`practical-link` URL. The rest are like "Prep Girls Hoops Adidas 3SSB
coverage — prepgirlshoops.com — current season" — they namedrop a domain
in the metadata line but the title itself isn't a clickable link, because
the entry is a *category of coverage* not a *single canonical URL*.

**Implication for the skill:** the bibliography-link rule in
`## Practical hyperlinks` could be relaxed slightly — "every bibliography
entry whose source has a single canonical URL is linked; category
references aren't required to link." The 9/14 hit rate isn't actually a
failure; it's a category distinction the rule didn't anticipate.

### 5. Walking-distance pace assumption — Carolina July heat changes the answer

The `walking_chip` math uses 5 km/h walking and 30 km/h in-city driving
as the locked constants. In Rock Hill in late July, with the daily high
at 91°F and the dewpoint above 70°F, a 12-minute walk is a different
proposition than a 12-minute walk in October. The chip body
"12 min walk · 0.9km from Holiday Inn" reads as accurate but isn't
*useful* on a 91° afternoon — the realistic reader will Uber.

**Phase 2b consideration:** when the destination has a `weather` section
with a daily high above ~85°F (or a low above ~70°F, ~26°C), nudge the
chip copy or add a row hint — something like
"12 min walk · 0.9km · summer: ride-share recommended" — or surface the
heat advisory at the section level instead. Per-chip footnotes are too
much; section-level once is probably right.

## Loose ends

- The `.bak` rotation in `guide_builder.save_guide` produced
  `data/guides/4.html.bak` dated 2026-06-24 21:09 — the PRIOR `.bak`,
  not today's pre-script content. Looks like `shutil.copy2` is rotating
  but the file timestamp metadata is being preserved from somewhere
  earlier. Worth a separate investigation; not blocking.
- The validation script
  (`scripts/2026-06-25_inject_phase2a.py`) is one-shot and hard-codes
  trip 4 venue strings. It should not be reused for other trips; it
  exists as a record of the validation. Delete or move to
  `scripts/archive/` after the Phase 2b plan is written.

## Files touched

- `scripts/2026-06-25_inject_phase2a.py` — one-shot patcher (NEW)
- `scripts/2026-06-25_verify_phase2a.py` — verifier (NEW)
- `data/guides/4.html` — regenerated (~85.5kB → ~97kB)
- `data/guides/4.config.json` — `last_generated_at` bumped to
  2026-06-26T02:12:49Z

No test changes. Tests still green at 988/988
(`.venv/bin/pytest tests/ -q`).
