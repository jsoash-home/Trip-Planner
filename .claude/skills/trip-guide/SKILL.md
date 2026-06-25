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

## Depth tiers — the 1-knob calibration

The user picks ONE depth tier per trip, plus optional per-section overrides.
The tier sets word floors, section counts, visual-primitive use, and voice
density. Depth is orthogonal to archetype — a `wildlife` trip can ship at
Light or Souvenir-grade; same for `history_stacked`.

| Tier | Word target | Sections | Visual primitives | Voice density |
|---|---|---|---|---|
| **Light** | ~3,000 | 4–5 | None beyond hero | Prose only, 1 sensory opener per section |
| **Standard** | ~8,000 | 6–8 | Hero route SVG, 4-stat weather grid, phenology strip (if nature) | ≥1 named particular per paragraph |
| **Deep** | ~15,000 | 7–8 + bonus | Full Visual Primitives toolkit, era palette, sidenotes ≥3/major subsection | ≥1 callout per ~600 words, dig-deepers on demand |
| **Souvenir-grade** | ~25,000 | All 8 + bonus + `quick_reference` + `life_list` | All of Deep + annotated bibliography + 4-card go-deeper rows + character vignettes | ≥3 vignettes in history, dual-narrator history where contested |

Stored on `GuideConfig.depth_tier` as one of `"light"`, `"standard"`, `"deep"`,
`"souvenir_grade"` (snake-case, lowercase). Invalid values normalize to
`None`; the skill prompts at Step 4.5 when unset.

### Per-section word floors

The trip's `depth_tier` sets the default; per-section overrides lift one
section higher (or drop one lower) without dragging the rest.

| Section | Light | Standard | Deep | Souvenir |
|---|---|---|---|---|
| `history` | 300 | 800 | 1,500 | 3,000 |
| `field_guide` (per entry) | 40 | 80 | 150 | 250 |
| `day_by_day` (per day intro) | 60 | 150 | 300 | 500 |
| `food` (each "things to try" entry) | 25 | 60 | 120 | 200 |
| `fun_facts` | 200 | 400 | 700 | 1,200 |

*(other sections scale by the same multipliers)*

### Per-section overrides

`GuideConfig.section_depth_overrides` is a flat dict keyed by section key:

```json
{
  "history": "souvenir_grade",
  "food": "deep"
}
```

**Merge rule, applied per section at compose time:**

1. If the section has an entry in `section_depth_overrides` → use it.
2. Else if `cfg.depth_tier` is set → use it.
3. Else fall back to `"standard"`.

### Anti-pattern: do NOT auto-pick depth from trip length

A 14-day Greek-islands lounge can be Light; a 3-night Rome trip can be
Souvenir-grade. The user picks at Step 4.5; the skill never infers depth
from duration, destination count, or itinerary density.

---

## Editorial voice — the writing rules

These rules apply to body prose in every section. The composer enforces
them at write time; Step 10 verification greps for violations.

### Banned phrases

Strip any of these from prose. Quoted material (a period author, a local
quoted by name) is exempt — see the anti-pattern at the end of this
section.

```
vibrant, bustling, hidden gem, must-see, rich heritage, melting pot,
charming, picturesque, unspoilt, off-the-beaten-path, dates back to,
centuries of, has long been, something for everyone, a feast for the
senses, gem of a, jewel of, crown jewel, postcard-perfect, fairytale,
storied, world-class, breathtaking
```

Clustered, with the reason each fails:

- **Brochure adjectives** (`vibrant`, `bustling`, `charming`, `picturesque`, `postcard-perfect`, `fairytale`) — evoke nothing specific. Replace with a named sound, a named smell, or a named scene.
- **Discovery framing** (`hidden gem`, `off-the-beaten-path`, `must-see`, `gem of a`, `jewel of`, `crown jewel`) — implies the reader is rare and special; meaningless and slightly insulting. Replace with the specific recommendation plus the constraint that makes it specific (when to go, who runs it, what you'll see).
- **Vague-history filler** (`rich heritage`, `melting pot`, `dates back to`, `centuries of`, `has long been`, `storied`) — claim without dates or names. Replace with a date, a named figure, and a present-day consequence (see the History claim triad below).
- **Ungraded superlatives** (`unspoilt`, `world-class`, `breathtaking`) — grading without specifics. The reader can't picture it. Replace with the comparison that grounds the grade — compared to what, on what axis.
- **Anti-content** (`something for everyone`, `a feast for the senses`) — says nothing. Delete.

### Named-particulars density floor

Every paragraph in an **atmospheric** section must carry ≥1 proper noun —
named street, named person, named date, named dish, named species, named
building. "A great cafe" → "Café Tortoni"; "an old church" → "Hagia
Sophia, completed 537."

**Atmospheric sections** (rule applies):

- `history` (every paragraph)
- `field_guide` (every entry's flavor text)
- `day_by_day` (each day's intro paragraph)
- `food` ("things to try" entries)
- `things_to_do` (every recommendation)

**Practical sections** (rule does not apply — these are terse and
factual):

- `before_you_go`
- `weather` (stats + packing list)
- `fun_facts` (the tips column)

### History claim triad

Every history paragraph must carry all three:

1. **Date** — a specific year or named period (`Augustan`, `Trecento`), not "centuries ago".
2. **Named person or building** — Bramante, Sant'Andrea della Valle, not "a Renaissance architect".
3. **Present-day consequence** — what the reader sees today because of this fact.

A paragraph missing any of the three reads as filler. Strip it or
rewrite.

### Sensory opener rule

The first paragraph of every section opens on a sensory note — smell,
sound, light, texture — and the sense is named and specific.

> "Roma Termini smells of coffee burnt the way station bars burn it:
> too hot, too fast, the espresso pulled before the puck is wet through."

Not:

> "Rome welcomes you with energy and warmth."

The first form names a place (Roma Termini), a sensation (burnt coffee),
and a mechanism (puck pulled too fast). The second names none of these —
it could be any city.

### Register split — section-level CSS classes

Atmospheric and practical sections render with different typography to
signal the shift to the reader. The composer applies one class per
section's wrapping element. CSS verbatim:

```css
.section--practical { font-family: var(--font-sans); max-width: 52ch; }
.section--practical p { margin: 0.6em 0; }
.section--practical ul { padding-left: 1.2em; }
.section--atmospheric { font-family: var(--font-serif); max-width: 62ch; }
.section--atmospheric p { margin: 1em 0; text-indent: 0; }
.section--atmospheric p + p { text-indent: 1.5em; }
```

The `text-indent: 1.5em` on `p + p` mimics print typesetting and is the
single highest-signal "this looks edited" move. Do not skip it.

### Anti-pattern: banned-word check on quoted material

The Step 10 verification grep operates on prose only, not on quoted
material. A history vignette can quote a period author saying "the
bustling port" — that's a citation, not the guide's voice. The composer
wraps quoted material in `<blockquote>`, `<q>`, or `<cite>` tags; the
verifier strips these tags' text content before scanning the body.

---

## Progressive disclosure architecture

Souvenir-grade guides carry a lot of prose. The reader who's about to
board a plane needs the short answer; the reader on the couch the night
before wants the long one. These three patterns let one HTML file serve
both without splitting into two guides.

### Lede / `.deep` two-track pattern

Every dense subsection opens with a **bold standalone lede** — 2–3
sentences that are the complete short answer. The lede is followed by
`.deep` prose: styled softer, slightly smaller, slightly muted. A reader
who only reads ledes still gets a usable guide; a reader who wants the
full essay reads on into `.deep`.

The lede is not a "TL;DR" label. It is the same content, compressed.
Write it last, after the deep version exists, so the lede reflects what
the section actually says.

CSS verbatim:

```css
.lede {
  font-weight: 600;
  font-size: 1.05em;
  line-height: 1.5;
  margin: 0 0 1em 0;
  color: var(--ink);
}
.deep {
  font-size: 0.96em;
  line-height: 1.65;
  color: var(--ink-soft);
}
.deep p:first-child { margin-top: 0; }
```

**Palette rule.** Every guide's palette MUST declare both `--ink` (body
ink at full strength) and `--ink-soft` (body ink mixed ~12% toward the
page background). The Palette proposal step (Step 5) selects both. The
soft variant powers `.deep` prose, the `.opinion` container, the
sidenote text, and any other "secondary register" surface. Without
`--ink-soft`, `.deep` falls back to inheriting `--ink` and the
contrast collapse disappears.

HTML pattern:

```html
<section class="section--atmospheric">
  <h2>The Republic, in plain sight</h2>
  <p class="lede">Rome's first Republic walls still mark out the
  Aventine district. Walk the perimeter on a Sunday morning and you can
  read the city's earliest political geography in the street grid.</p>
  <div class="deep">
    <p>Servius's wall went up in the 4th century BC after the Gallic
    sack, built from tufa quarried at Grotta Oscura...</p>
    <p>Three of the original gates survive in named form...</p>
  </div>
</section>
```

The `.deep` div is the unit Skim mode hides (see below). Wrap every
non-lede paragraph in it, not just the long ones — partial hiding looks
broken.

### Skim / Standard / Deep toggle

A 3-position toggle sits in the sticky nav. It sets `data-mode` on
`<body>`; CSS keys off that attribute to show or hide whole layers of
content. The user's choice persists in `localStorage["vp.guide.mode"]`,
so reopening the guide remembers the mode. `@media print` forces every
layer visible regardless of mode.

The three modes:

- **Skim** — ledes only. `.deep`, `.dig-deeper`, `.sidenote-content`,
  and `.endnotes` are hidden. Best for the day-of-trip read.
- **Standard** — ledes + `.deep`. `.dig-deeper` and `.sidenote-content`
  stay hidden; `.endnotes` shows. The default mode on first load.
- **Deep** — everything visible. Sidenote bodies, dig-deeper insets,
  endnotes, full apparatus. Best for the pre-trip read.

**Naming note.** The toggle's "Standard" label is intentionally aligned
with the depth-tier `"standard"` slug — both signal "the middle
amount." The toggle is a *reader-side* control over what's revealed; the
depth tier is an *author-side* control over how much was written. A
Deep-tier guide in Skim mode still only shows the ledes; a Light-tier
guide in Deep mode just doesn't have much extra to reveal.

HTML pattern:

```html
<div class="mode-toggle" role="radiogroup" aria-label="Reading depth">
  <button data-mode="skim" aria-pressed="false">Skim</button>
  <button data-mode="standard" aria-pressed="true">Standard</button>
  <button data-mode="deep" aria-pressed="false">Deep</button>
</div>
```

CSS verbatim:

```css
body[data-mode="skim"] .deep,
body[data-mode="skim"] .dig-deeper,
body[data-mode="skim"] .sidenote-content,
body[data-mode="skim"] .endnotes { display: none; }

body[data-mode="standard"] .dig-deeper,
body[data-mode="standard"] .sidenote-content { display: none; }

@media print {
  .deep, .dig-deeper, .sidenote-content, .endnotes { display: block !important; }
  .mode-toggle { display: none; }
}
```

JS verbatim (~30 lines, wrap in an IIFE so the closure stays out of
window globals):

```js
(function(){
  var KEY = "vp.guide.mode";
  var saved;
  try { saved = localStorage.getItem(KEY); } catch(e) { saved = null; }
  var mode = saved || "standard";
  document.body.setAttribute("data-mode", mode);

  var buttons = document.querySelectorAll(".mode-toggle [data-mode]");
  buttons.forEach(function(btn){
    btn.setAttribute("aria-pressed", btn.dataset.mode === mode ? "true" : "false");
    btn.addEventListener("click", function(){
      var next = btn.dataset.mode;
      document.body.setAttribute("data-mode", next);
      buttons.forEach(function(b){
        b.setAttribute("aria-pressed", b.dataset.mode === next ? "true" : "false");
      });
      try { localStorage.setItem(KEY, next); } catch(e){}
    });
  });
})();
```

**Why `try/catch` around localStorage.** Private-browsing windows
(Safari, mobile Firefox) throw on `localStorage.setItem`. The catch
keeps the toggle working for the session even when persistence fails —
same pattern the dashboard countdown uses.

**Accessibility.** The toggle is `role="radiogroup"`; each button is a
radio. `aria-pressed` reflects the current mode. Keyboard focus styles
inherit the global `*:focus-visible` rule from the Accessibility
patterns section.

**Default on first load.** Standard, not Skim. A new reader landing on
a guide should see the lede AND the deep prose by default — Skim is the
mode you opt into on the plane, not the impression we want the guide to
make first.

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
os.environ.pop("DATABASE_URL", None)  # let app.py resolve to absolute project-root vacation.db
from app import app
from src import guide_builder
with app.app_context():
    data = guide_builder.load_trip_data(trip_id)
    # data = {"trip": {...}, "bookings": [...], "itinerary": [...], "collaborators": [...]}
```

**Why `pop`, not `setdefault`.** Passing `DATABASE_URL=sqlite:///vacation.db` makes
Flask-SQLAlchemy resolve the relative path to `instance/vacation.db` — an empty
file the real app doesn't use. `Trip.query.get(...)` then returns `None` and you
hit `TripNotFound` even though the trip exists. Popping the env var lets `app.py`'s
own default kick in, which is the absolute path to project-root `vacation.db`
(the file the running web app reads).

Itinerary is pre-grouped by `day_date` and sorted via `sort_within_day`.
Bookings include their `linked_booking_id` itinerary children.

### 2.5. Archetype detection

Trip data is loaded — now classify the trip's editorial lens. Archetype
drives which optional Deep-tier modules fire later; it's orthogonal to
`depth_tier` (a `wildlife` trip can ship at Light or Souvenir-grade).

#### The 8 archetypes

| Archetype | Signal | Default Deep modules |
|---|---|---|
| `history_stacked` | Old-world capitals (Rome, Istanbul, Kyoto, Jerusalem) | Swimlane timeline, ERA palette, character vignettes, etymology cards, `twovoices` opt-in |
| `wildlife` | Safari, Galápagos, Costa Rica, Madagascar | Habitat-first field guide, layered species cards, phenology strips, endemism callouts |
| `geology` | Iceland, Patagonia, Yellowstone, Atacama | Stratigraphic stack, cross-sections, deep-time timeline |
| `cuisine_led` | Tokyo, Lyon, Oaxaca, San Sebastián | Expanded food atlas, dish etymology cards, market guide |
| `pilgrimage` | Camino, Varanasi, Mt Athos, Shikoku | Stage strip, ritual clock, etiquette callouts |
| `expedition` | Antarctica, Svalbard, Greenland | Logistics-first, gear sidebars, SOS panel mandatory |
| `architecture_modern` | Berlin, Bilbao, Marfa, Rotterdam | Building cards with architect + year, walking-line maps |
| `mixed_leisure` | Beach + city blends without one dominant lens | Standard sections, no exotic modules — the safe default |

Stored on `GuideConfig.archetype` as the snake-case string from the
"Archetype" column.

#### Classification rubric — 12 yes/no questions

Walk the rubric in order. Record signal hits; the highest-scoring archetype
becomes primary, with a runner-up promoted to "secondary" if it scored ≥3.

1. **History layers.** Does the destination have ≥3 named historical periods with visible material remains (Republican / Imperial / Medieval / Renaissance / Baroque, etc.)? → `history_stacked`
2. **Ecosystem lens.** Is the primary motivation a specific ecosystem, biome, or wildlife encounter? → `wildlife`
3. **Naturalist bookings.** Are there bookings or itinerary items for guided naturalist activities, dives, hides, or safari drives? → `wildlife`
4. **Endemism / unique geology.** Is the destination known for endemic species or geologically unique landforms? → `wildlife` or `geology`
5. **Tectonic / volcanic / glacial.** Are there visible tectonic, volcanic, or glacial features the trip is built around (named volcanoes, glaciers, fault lines, hot springs as primary draws)? → `geology`
6. **Chef / dish / market named.** Did the user mention a chef, named dish, market, or food-specific reason for picking the destination? → `cuisine_led`
7. **Food-concentrated bookings.** Are bookings concentrated around restaurants, food tours, cooking classes, or markets (~≥40% of bookings)? → `cuisine_led`
8. **Religious / spiritual route.** Is there a religious site, pilgrimage route, or spiritual practice central to the itinerary (Camino, Shikoku 88, Hajj, Char Dham)? → `pilgrimage`
9. **Polar / expedition vessel.** Does the trip involve polar regions, ice, or expedition vessels with named departure ports? → `expedition`
10. **Named architects / buildings.** Did the user mention named architects (Gehry, Niemeyer, Aalto), specific modern buildings, or design pilgrimage as a draw? → `architecture_modern`
11. **No dominant lens.** Are there ≥2 distinct categories of activity (beach + museum + hike) without one dominating? → `mixed_leisure`
12. **Soft leisure framing.** Did the user describe the trip as primarily relaxation, honeymoon, or "off" time? → `mixed_leisure`

#### Worked example: Iceland, August, 7 days

- 1 hotel booking in Reykjavík
- 1 campervan booking (Reykjavík → Reykjavík)
- Itinerary mentions Þingvellir, Geysir, Gullfoss, Vatnajökull, Reynisfjara

**Rubric hits:** Q5 (volcanic + glacial — strong), Q4 (high geological uniqueness), Q2 (Vatnajökull suggests landscape lens), Q11 (campervan + several types of stop without one dominating).

**Verdict:** primary `geology`, secondary `mixed_leisure`.

#### Confirmation step

Propose the verdict out loud and wait for the user:

> "This reads as a `geology` trip with `mixed_leisure` blended in — agree?"

On acceptance, save immediately:

```python
cfg.archetype = "geology"
guide_builder.save_config(trip_id, cfg)
```

On correction, accept the user's choice without relitigating.

#### Module matrix at Deep tier

Modules each archetype fires by default at `depth_tier="deep"`. Phase 1
ships the editorial spine; visual primitives marked `(Phase 2)` arrive in
the next plan and the corresponding row entries will be skipped until then.

```
history_stacked × Deep    → ERA palette, swimlane timeline (Phase 2), histpins (Phase 2),
                            character vignettes ×3, etymology cards, sidenotes ≥3/section
wildlife × Deep           → habitat-first field guide, layered species cards,
                            phenology strips (Phase 2), endemism callouts
geology × Deep            → stratigraphic stack (Phase 2), cross-sections (Phase 2),
                            deep-time timeline
cuisine_led × Deep        → expanded food atlas, dish etymology cards, market guide
pilgrimage × Deep         → stage strip, ritual clock, etiquette callouts
expedition × Deep         → logistics-first sections, gear sidebars,
                            SOS panel (mandatory at Deep)
architecture_modern × Deep → building cards (architect + year),
                            walking-line maps (Phase 2)
mixed_leisure × Deep      → standard sections, no exotic modules (the safe default)
```

**Tier scaling.** Lower tiers drop modules from the bottom of each row;
`Souvenir-grade` adds annotated bibliography + 4-card go-deeper rows on
top of the Deep matrix for every archetype.

#### Multi-archetype rule

A trip with both a strong primary and a runner-up secondary (Rome history +
Tuscany hiking, say) blends both:

- **Primary archetype** modules fire at full weight (e.g. 3 vignettes).
- **Secondary archetype** modules fire at half weight (e.g. 1 vignette).

The depth-tier word floors are owned by the primary; the secondary
contributes modules, not word budget.

#### Anti-pattern: don't silently change archetype on regenerate

When the user re-runs the skill on an existing trip with a different
section pick, do NOT silently re-classify. Ask:

> "Sections changed. Re-classify archetype (currently `geology`), or keep it?"

A silent re-classification can flip a Souvenir-grade Rome guide from
`history_stacked` to `mixed_leisure` and gut the modules. Always confirm.

### 3. Detect prior run

```python
with app.app_context():
    cfg = guide_builder.load_or_init_config(trip_id)
```

If `cfg.last_generated_at` is set, present three options and wait for user choice:

1. Regenerate with same sections + depth (reuse saved sections, palette, `depth_tier`, and `section_depth_overrides`; re-research; overwrite)
2. Change sections (re-run the picker; optionally re-pick palette)
3. Cancel

Never auto-regenerate without asking.

### 4. Section picker

Present a multi-select from the 8-section catalog. The user picks a subset.
Save their choice immediately via `guide_builder.save_config(trip_id, cfg)`.

| Key | Section |
|---|---|
| `before_you_go` | Pre-trip prep card grid + hotel-address quick-copy table |
| `day_by_day` | Editorial timeline from itinerary + bookings |
| `field_guide` | Filterable encyclopedia (wildlife / museums / landmarks) |
| `things_to_do` | Curated picks, distinct from field guide |
| `weather` | 4-stat grid + season notes + packing implications |
| `history` | Prose + phrase table |
| `fun_facts` | 2-col trivia + practical tips |
| `food` | "Things to try" cards + "where to eat" by price tier |

All 8 can be included. Any subset is valid. The picker is the source of truth —
the skill does NOT auto-detect "nature trip" and skip sections.

**Themed bonus sections.** Listen for user interests volunteered during the
picker conversation ("I'm a coffee nerd", "we love craft beer", "I bird"). Offer
to add a themed section tailored to that interest — e.g. a `beer` section with
country-grouped breweries + bar lists, a `coffee` section with notable roasters,
a `photography` section with locations and timing. Themed sections sit alongside
the 8 base sections; they're additive, not replacements. Use the same visual
language (card grid, mono labels, group headers).

**Optional closing section.** Consider a `life_list` footer for nature- or
encounter-heavy trips: a checklist grid of "things to keep an eye out for" —
wildlife, views, foods, small moments — synthesised from the trip's other
sections. Mirrors the Galapagos Field Log benchmark.

### 4.5. Pick depth tier

Before proposing a palette, lock the depth. Ask:

> "Light / Standard / Deep / Souvenir-grade — which?
>
> - **Light** (~3,000 words): prose-only, 4–5 sections. Day-of read on the plane.
> - **Standard** (~8,000 words): 6–8 sections, route SVG + weather grid.
> - **Deep** (~15,000 words): full visual toolkit, era palette, sidenotes throughout.
> - **Souvenir-grade** (~25,000 words): everything + vignettes + annotated bibliography. A keepsake.
>
> Any sections you want lifted above (or dropped below) that default? (e.g. *"Deep overall, Souvenir-grade on history"*)"

Save the agreed tier and overrides immediately:

```python
cfg.depth_tier = "deep"  # or whatever the user picked, snake-case
cfg.section_depth_overrides = {"history": "souvenir_grade"}  # optional
guide_builder.save_config(trip_id, cfg)
```

See the "Depth tiers" section above for the per-section word floors that
the chosen tier enforces, and the override merge rule. Reminder: never
auto-pick depth from trip length.

### 4.6. Narrator angle

After depth, before palette: pick the lens that shapes voice across every
section. Ask:

> "Who is this guide written for?
>
> 1. First-timer with a history obsession
> 2. Returning after 10+ years, wants what's new
> 3. Family with kids 5–12
> 4. Active outdoors / "out before sunrise" type
> 5. Food-first traveler
> 6. Cultural completionist
> 7. Honeymoon / slow-travel
> 8. Custom (free text, ≤80 chars)"

Save the chosen angle immediately:

```python
cfg.narrator_angle = "First-timer with a history obsession"
guide_builder.save_config(trip_id, cfg)
```

**How it surfaces in the guide.** A one-line italic dek under the trip
title in the hero. Example:

> *"For the returning visitor — what's changed since 2015."*

**How it influences prose.** The angle is woven into every section's
opening, not stated outright everywhere. The reader feels the lens; they
do not read the label. A "Family with kids 5–12" narrator angle changes
which restaurants get recommended, how walking distances are described,
and which museums get covered — without the guide ever announcing "this
is for families."

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

4. **Banned-word grep on body prose.** Strip HTML tags and the text content
   of any `<blockquote>`, `<q>`, and `<cite>` tags (quoted material is
   exempt — see the "Editorial voice" anti-pattern), then case-insensitively
   word-boundary-search for any banned phrase. Any hit fails verification:

   ```python
   import re
   BANNED = [
       "vibrant", "bustling", "hidden gem", "must-see", "rich heritage",
       "melting pot", "charming", "picturesque", "unspoilt",
       "off-the-beaten-path", "dates back to", "centuries of",
       "has long been", "something for everyone", "a feast for the senses",
       "gem of a", "jewel of", "crown jewel", "postcard-perfect",
       "fairytale", "storied", "world-class", "breathtaking",
   ]
   body_text = strip_html_and_quoted(html)  # see "Editorial voice"
   hits = [w for w in BANNED if re.search(rf"\b{re.escape(w)}\b", body_text, re.I)]
   if hits:
       raise VerifyFail(f"banned phrases in body: {hits}")
   ```

If any check fails, surface the offending phrase, console error, or
missing element and stop. Do not smooth over failures with "probably fine."

---

## Section content model

### before_you_go

A 4-card grid of pre-trip prep, sitting between the hero and `day_by_day`.
Each card has a mono uppercase heading and a tight bulleted list. Suggested cards:

1. **Download before takeoff** — eSIM provider, per-city transit apps, offline
   maps, offline Translate, weather app
2. **Documents & entry** — passport validity, Schengen/visa rules, PDF backups,
   insurance (especially adventure-activity coverage)
3. **One adapter, one card** — plug type, voltage, currency by country, contactless
   norm, ATM advice
4. **Things easy to forget** — destination-specific small items: sleep mask
   (Arctic perpetual light), closed-toe shoes (zipline), hat + gloves (cold sea
   wind), reusable water bottle

Follow with a "Hotels at a glance" table: each row has city + dates, hotel name +
address, copy button. The address strings get a `.copy-btn[data-copy="..."]` that
fires the shared clipboard JS (with `execCommand` fallback for restricted
contexts — see HTML pitfalls).

### day_by_day

Editorial timeline. Per-day section: large day number + date, 1–2 sentence intro,
site cards in time order. Each card: mono time badge, name, 2–3 sentences of context,
optional history / fun-fact tags. Inputs: itinerary items grouped by `day_date`
via existing `src/itinerary.py:group_items_by_day`, plus bookings overlapping each
day. ~150–300 words per day. Layout mirrors `Galapagos_Field_Log_Mar27-Apr3_2027.html`.

**Day-meta badge.** Each `.daymark` block gets a small mono badge below the
place name with the day's weather + light context: e.g.
`<div class="daymeta"><b>5° / 1°C</b> · ~20h light</div>` or
`<b>17° → 5°C</b> · midnight sun final week`. Ties the weather section into the
timeline and surfaces day-by-day climate transitions without forcing the reader
to flip sections. Wrap critical figures (temps, light hours, transition arrows)
in `<b>` so they get the accent colour.

**Surface booking notes.** Operational notes in `booking.notes` ("Email host
arrival time", "Early check-in approved at 13:00", "Bring closed-toe shoes",
"Ferry serves dinner buffet 18:30–20:00") are gold for the in-trip reader. Lift
them into the matching site card as a `.opnote` div — accent-coloured italic
text with a left border. Filter aggressively: skip notes that are pure pricing
math ("$X × Y nights = $Z") or speculative TODOs.

**Travel-time pills.** Long transits (any drive over 3h, ferries over 4h, train
journeys over 4h, multi-leg flights) get a `.travelpill` badge in the `.tags`
row: `Drive · ~7h · 580km · 1 ferry` or `Ferry · 16h30 · overnight`. Short
transits don't need it — the time stamp already communicates duration.

**Free-day enrichment.** When a day has no bookings (or only check-in/check-out),
don't fall back to a single generic "Suggested arc" card. Plan 4–6 specific
site cards with morning/midday/afternoon/evening/late time stamps and concrete
names. These are the days a reader most needs pre-research.

### field_guide

Filterable encyclopedia — the **encyclopedic** half of the discovery pair. Sticky
search bar + filter chips, card grid. Each card: name, optional latin /
local-language name, likelihood or quality badge, 1–2 line description, "best
day to encounter" tags. Vanilla JS for search + chip toggles. Adapts by
destination: nature trip → species; city → museums + landmarks. Layout mirrors
`galapagos-wildlife-guide.html`.

Voice: factual and reference-grade. Each card answers "what is it and when do I
have a shot at seeing it?" Think field guide / Wikipedia, not travel-blog.

**Day-range chip labels.** For multi-region trips, name the geography chips
with their day range too — e.g. "Arctic · Days 4–7", "Lofoten + Fjords · Days
8–15", "Baltic + Cities · Days 16–23". Doubles as a trip-day filter without
adding new JS.

### things_to_do

Curated picks — the **editorial** half of the discovery pair. Distinct from
field guide. No search, no chips. Grouped: morning ideas, evening ideas,
half-day excursions, rainy-day fallbacks. Each entry: name, neighborhood, why
it's worth it, what to pair with it, optional cost / time-needed note. ~12–25
picks. Exclude items the user has already booked — no redundant suggestions.

Voice: opinionated and recommendatory. Each entry answers "should I spend a
half-day on this, and why?" Think tipped friend who lives there, not encyclopedia.

**Test for the distinction:** if you'd write the same entry for both sections,
one of them is wrong. Field guide entries describe a thing's identity; things-to-do
entries describe an action and its tradeoff. The Vasa ship is a `field_guide`
entry ("1628 warship, 98% original wood, raised 1961"). The Vasa Museum visit
is a `things_to_do` entry ("Don't skip — even non-museum-people love this one;
budget 90 min").

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

**Group multi-location content by location.** If the trip spans multiple places
and the trivia naturally tags by country / city / region (e.g. one Sweden fact,
two Estonia facts, three Norway facts), wrap each location's items in a
`<div class="fact-group">` with an `<h4 class="fg-loc">Location</h4>` header
above its `<ul>`. A flat list with per-item country labels reads as jumbled even
when the labels are styled; explicit group headers + a divider rule between
groups let the eye scan one location at a time.

The same grouping principle applies in `things_to_do` and `food` (where it's
already per-city). Apply it anywhere the items have a natural location boundary
and the user would benefit from scanning one location at a time.

### food

Short prose intro on the food culture, then two subsections:

- **Things to try** — card grid, 8–15 entries. Each: dish or drink name, optional
  local-language name in mono, 1–2 line description, optional "best eaten" hint,
  small tag (dish / drink / street snack / breakfast / dessert).

- **Where to eat** — grouped by four price tiers: Splurge, Sit-down, Casual,
  Street + markets. 3–5 entries per tier. Each: name, neighborhood, signature dish,
  why, optional logistics tag. **Booked restaurants from the user's trip appear in
  their correct price tier with a "✓ you've booked" tag** — do not filter them out.

### Themed bonus sections (e.g. beer, coffee, photography, books)

If the user volunteered an interest at section-picking time, add a bespoke
section tailored to it. Use country / city grouping with the same visual
language as `food`: each location gets a card grid of the things to try +
a "where to drink/find/visit" list. Example: a `beer` section for a beer-lover's
trip lists 4–6 breweries per country (with a small style tag like
"craft" / "pilsner" / "brewpub" / "historic") and a 4–5 entry bar list under a
mono "Where to drink (Country)" heading.

Themed sections sit between `fun_facts` and `food` in the nav order — close
enough to `food` that they read as adjacent material but distinct enough to
stand alone. The user can always opt out at section-pick time; never assume.

### life_list

Optional closing section, best for nature- or encounter-heavy trips. A grid of
~15–25 short "things to keep an eye out for" — wildlife you might spot, views
worth the detour, foods to try, small moments. Each entry is one sentence,
prefixed with a checkmark via `::before`. Synthesised from the trip's other
sections (especially `field_guide`, `food`, key day intros) — readers use it as
a pre-trip mental priming list and a during-trip checklist.

Layout mirrors the Galapagos Field Log's life-list footer. Sits between the
last content section and the page footer.

---

## Hero details

The hero is the first thing the reader sees — earn its weight.

**Required:** mono eyebrow ("Trip guide · {Palette name}"), display title in
serif, 1–2 sentence subtitle that names the arc of the trip (not the destination
in isolation), mono meta row with When / Length / Countries / Bookings count.

**Recommended polish:**

- **Radial accent gradient** in the upper-left corner using the palette's
  primary accent at 8–12% opacity. Subtle; you should barely notice it but it
  warms the dark background.
- **Accent bottom border** in the primary accent, 2px solid, plus a secondary
  accent fade-out line via `::after` for a two-tone separation from the nav.
- **Inline route SVG** for multi-stop trips. Don't use real geography — use an
  abstract dot-and-arc visualization keyed to trip rhythm. Use vertical
  position to suggest latitude (north = up); use a marked stop (`stop-dot.major`)
  for the trip's furthest extreme. Add an `aria-label` describing the route in
  prose. The SVG should be `viewBox` based with no fixed dimensions, so it
  scales cleanly on mobile.

The route arc is a single biggest single-piece-of-polish for multi-destination
trips. Skip it for single-city trips where it would feel inflated.

---

## Accessibility patterns

These are not optional. A souvenir-grade guide is also a keyboard- and
screen-reader-friendly guide.

- **Skip link** as the first body element: `<a class="skip-link" href="#main">
  Skip to content</a>`. Hidden off-screen by default (`left:-9999px`); becomes
  visible on `:focus` (`left:0`). The `<main>` element must have `id="main"`.
- **Visible focus styles** for keyboard navigation:
  `*:focus-visible{outline:2.5px solid var(--accent);outline-offset:3px}`.
  Don't use just hover styles — keyboard users see no hover state.
- **Aria-labels on interactive SVG.** The route arc should describe its route
  in `aria-label` prose so screen readers can read it. Decorative SVGs (palette
  swatches in the footer) use `aria-hidden="true"`.
- **Semantic landmarks.** Nav is `<nav>`, main content is `<main id="main">`,
  the footer is `<footer>`. Section headings step down properly (h1 → h2 → h3 → h4).

---

## Helper invocation pattern

Always push a Flask app context before any helper call. Template:

```python
import os
os.environ.pop("DATABASE_URL", None)  # see step 2 — relative sqlite path resolves to instance/, not project root
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

## HTML / CSS pitfalls

Real bugs hit during prior generations. Avoid in future composition.

### Don't put `display:grid` on a `<li>` that has trailing text after a child

If a bullet item looks like `<li><b>Label</b>Body text after the bold.</li>` and
its CSS sets `display:grid; grid-template-columns: <narrow> 1fr` on the `<li>`
(intending the narrow column for a `::before` bullet), the trailing anonymous
text node falls onto a second row in the narrow column and wraps one character
per line. Use the position/pseudo pattern instead:

```css
.facts-grid li{position:relative;padding:12px 0 12px 22px;border-bottom:1px solid var(--hairline)}
.facts-grid li::before{content:"\002022";color:var(--accent);position:absolute;left:0;top:10px}
```

This keeps the `<li>` as a normal block, lets prose flow naturally, and floats
the bullet in the left gutter. The original buggy form rendered as a vertical
column of single characters in the fun_facts section before being caught at
verification.

### Clipboard copy: always include a `document.execCommand` fallback

`navigator.clipboard.writeText` requires a secure context AND a focused page,
and headless Chromium on `file://` URLs often denies it silently. If the copy
button JS early-returns when `navigator.clipboard` is missing, the buttons do
nothing and verification fails.

Pattern: try `navigator.clipboard` first, catch any rejection, fall back to the
legacy textarea + `document.execCommand('copy')` path. This makes copy buttons
work in restricted browser contexts AND lets verification scripts assert the
copied-state class applies on click.

```js
function legacyCopy(text){
  try{
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    var ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch(e){ return false; }
}
btn.addEventListener('click', function(){
  var text = btn.getAttribute('data-copy') || '';
  if(navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(flash).catch(function(){
      if(legacyCopy(text)) flash();
    });
  } else if(legacyCopy(text)){ flash(); }
});
```

Same principle applies anywhere you'd reach for a modern web API that may not
be available in every context. Always offer a graceful path.

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
