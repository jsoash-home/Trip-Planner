---
name: trip-guide
description: Use when the user asks to build, generate, regenerate, or share a trip guide for a Vacation Planner trip.
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

### ERA_COLORS palette pattern

`history_stacked` archetypes (and any other archetype with non-trivial
history — e.g. `architecture_modern`) declare a **per-destination
period palette** at the top of the file, alongside the regular trip
palette. The same five-or-so colours are reused across every history
surface: date chips in body prose, era boxes, layer chips on site
cards, histpins (Phase 3), swimlane bands (Phase 2). That repetition
is what teaches the reader the period system without a memorization
quiz.

CSS pattern:

```css
:root {
  /* trip palette */
  --bg: #1a1a1e; --ink: #e8e6e1; --ink-soft: #b5b1a8; --accent: #c97f3a;

  /* era palette — researched per destination */
  --era-prehistoric: #6b7280;
  --era-roman:       #b45309;
  --era-medieval:    #4a6741;
  --era-renaissance: #8e3a59;
  --era-modern:      #4769a8;
}

.era-card { border-left: 4px solid var(--era); padding-left: 12px; }
.era-card.era-roman       { --era: var(--era-roman); }
.era-card.era-medieval    { --era: var(--era-medieval); }
.era-card.era-renaissance { --era: var(--era-renaissance); }
/* etc. */

.date-chip {
  background: var(--era);
  color: white;
  padding: 1px 6px;
  font-family: var(--font-mono);
}
```

The `--era` indirection on `.era-card` lets one rule (`border-left:
4px solid var(--era)`) drive every variant — the variant class just
swaps which palette colour `--era` resolves to. Same trick for
`.date-chip` once it's wrapped in an era-tagged ancestor.

**Era names are researched per destination.** Rome's eras are not
Kyoto's are not Iceland's. Don't ship the example slugs above as
defaults — they're illustrative. The skill researches each
destination's actual historical periodization at compose time and
emits slugs that match (Rome: `republican` / `imperial` / `medieval`
/ `renaissance` / `baroque` / `modern`; Kyoto: `heian` / `kamakura`
/ `muromachi` / `edo` / `meiji` / `modern`; Iceland: `settlement` /
`commonwealth` / `norwegian-rule` / `danish-rule` / `republic`).

**Storage shape.** Persist the era palette on `GuideConfig.era_palette`:

```json
{
  "name": "Rome periodization",
  "eras": [
    {"slug": "republican",  "label": "Republican",  "hex": "#8b6f47", "year_range": "509–27 BCE"},
    {"slug": "imperial",    "label": "Imperial",    "hex": "#b45309", "year_range": "27 BCE–476 CE"},
    {"slug": "medieval",    "label": "Medieval",    "hex": "#4a6741", "year_range": "476–1417"},
    {"slug": "renaissance", "label": "Renaissance", "hex": "#8e3a59", "year_range": "1417–1600"},
    {"slug": "baroque",     "label": "Baroque",     "hex": "#c97f3a", "year_range": "1600–1800"},
    {"slug": "modern",      "label": "Modern",      "hex": "#4769a8", "year_range": "1800–today"}
  ]
}
```

Five to seven eras. Fewer and the palette doesn't carry enough signal;
more and the reader can't hold them in working memory across the
guide.

**Cross-section reuse is the point.** Every surface in the guide that
references a period uses the era palette. A 1417 date in body prose
becomes `<span class="date-chip era-renaissance">1417</span>`. A
"Layers" row on a site card lists chips coloured by era. The swimlane
band (Phase 2) for the same range is the same colour. After two or
three encounters the reader internalises the period → colour mapping
and can scan visual rhythm at speed.

**When to skip.** `mixed_leisure`, `wildlife`, `geology`,
`cuisine_led`, `pilgrimage`, and `expedition` archetypes typically
don't need an era palette — their history surfaces are too thin to
amortise the visual machinery. Add one only if the trip has both a
`history` section at Deep or Souvenir-grade tier AND ≥3 clearly named
periods in the prose. Otherwise the era palette is overhead with no
payoff.

---

## Source disclosure

A souvenir-grade guide is opinionated. That's the point. But
opinion without disclosure reads as bluster, and unsourced facts
read as hallucinations. Every guide carries three sourcing surfaces
plus two prose conventions that let the reader see where the
authority comes from — and where it doesn't.

The three required surfaces:

1. A **"note on sources"** `<details>` block right after the hero
2. A per-section **"Go deeper" 4-card row** at the close of every
   section that ships at Deep tier or above
3. A consolidated **"Sources & further reading"** section as the
   last content section before the footer

Plus two prose conventions:

4. **Live-data callouts** — mono attribution lines at the foot of any
   section pulling current data
5. **`.opinion` typographic container** for explicitly marked
   editorial judgment

### 1. "A note on sources" block

A `<details>` element right after the hero, opening with a single
summary line. 3–5 plain-language sentences inside. Template:

```html
<details class="sources-note">
  <summary>A note on sources</summary>
  <p>Sources for this guide. The history draws on
  [academic source class], the wildlife sections on [field
  resource], the food on [local press / cookbook authors]. Live
  data (weather, opening hours) was current as of
  {generation_date} — verify before booking. Opinion is marked in
  the prose; sources for individual claims are linked in the
  "Sources &amp; further reading" section at the foot.</p>
</details>
```

The block is collapsed by default — readers who care expand it;
readers who don't get a clean hero-to-content flow. Required on
every guide regardless of depth tier; the Light tier still benefits
from the honesty.

### 2. Per-section "Go deeper" 4-card row

At the close of every section that lands at Deep tier or above
(check the merged tier per section, not the trip-wide default),
ship a 4-card aside with one card per medium: a book, a podcast,
a film, and a "local voice to follow" (a real working
journalist, museum, Substack writer, or institution with a
current public presence).

```html
<aside class="go-deeper">
  <h4>Go deeper on this</h4>
  <div class="gd-grid">
    <article class="gd-card">
      <span class="gd-kind">Book</span>
      <h5>Title</h5>
      <p>One-line opinionated annotation.</p>
    </article>
    <article class="gd-card">
      <span class="gd-kind">Podcast</span>
      <h5>Title</h5>
      <p>One-line opinionated annotation.</p>
    </article>
    <article class="gd-card">
      <span class="gd-kind">Film</span>
      <h5>Title</h5>
      <p>One-line opinionated annotation.</p>
    </article>
    <article class="gd-card">
      <span class="gd-kind">Local voice</span>
      <h5>Name or handle</h5>
      <p>One-line opinionated annotation.</p>
    </article>
  </div>
</aside>
```

The "Local voice" card is the highest-signal one. It says: someone
with a current relationship to this place writes about it, and here's
where to find them. If WebSearch can't confirm a real current
presence, **omit the card entirely** — better three cards than four
with a fabricated fourth.

The annotation is opinionated, not summary. "The standard one-volume
history; dense but readable" beats "A history of Rome from
foundation to fall."

### 3. Consolidated "Sources & further reading"

The last content section before the footer. Grouped by topic with
small headings:

- `On the history`
- `On the wildlife` (or `On the geology`, `On the architecture`,
  etc. — match what the guide covers)
- `On the food`
- `On the practical stuff` (transit, money, etiquette — optional)

3–5 annotated entries per group. Each entry uses this exact format:

```
Title — Author (Year). One-line opinionated annotation.
```

Render as a `<ul>` with one `<li>` per entry. The title is bold; the
author/year is mono; the annotation is body-weight prose. Example:

> **The Romans: From Village to Empire** — Mary Beard, John North
> & Sarah Price *(2014)*. The teaching standard; written by three
> classicists who disagree productively. Read alongside SPQR.

### 4. Live-data callouts

For any section that pulled current data at compose time — weather,
festival dates, opening hours, eBird sightings, currency rates — add
a small mono attribution line at the section foot:

```html
<p class="live-data">
  Weather data: NOAA, fetched 2026-06-23.
  Wildlife sightings: eBird hotspot data, last 30 days.
</p>
```

```css
.live-data {
  font-family: var(--font-mono);
  font-size: 0.82em;
  color: var(--ink-soft);
  margin-top: 1.5em;
  padding-top: 0.6em;
  border-top: 1px dashed var(--hairline);
}
```

The point isn't legal CYA — it's letting the reader judge staleness.
A weather call fetched 6 months ago is information; the reader can
decide whether to re-check.

### 5. `.opinion` typographic container

Explicitly marked editorial judgment gets the `.opinion` class. This
is the one place in the guide where the author's voice is named as
opinion rather than reported.

```html
<p class="opinion">If you only do one thing in Rome: skip the
Trevi Fountain queue and walk to the Palazzo Doria Pamphilj. The
crowd never finds it.</p>
```

```css
.opinion {
  border-left: 3px solid var(--accent);
  padding-left: 12px;
  font-style: italic;
  color: var(--ink-soft);
}
```

**Required minimum:** ≥1 `.opinion` block per `things_to_do` section
and per `food` section, at Deep tier or above. These are the
sections where opinion is the whole point; an unopinionated
`things_to_do` is a worse guide than no `things_to_do` at all.

Use sparingly elsewhere. Three `.opinion` blocks per section is
plenty; ten is performative.

### Anti-patterns

- **No fabricated sources.** If the skill cannot name a real book,
  podcast, film, or local voice for a "Go deeper" card, the card is
  **omitted**, not invented. A 3-card row is fine; a 4-card row with
  a faked entry is not. Same rule for the consolidated bibliography:
  every entry must be a real, findable work.
- **No _citation_ URLs in body prose.** Book / podcast / film /
  Substack links go in the consolidated "Sources & further reading"
  section and "Go deeper" cards only — never sprinkled inline through
  history paragraphs or day intros (they break reading rhythm and
  date the file the fastest). **Practical** URLs — Google Maps for
  venues, ticketing pages, official sites — ARE fair game in the
  card grids and tables listed in `## Practical hyperlinks` below.
  The two-tier split is documented there.
- **"Local voice" cards must clear a real-presence bar.** A real
  person, museum, podcast, or Substack writer with a current public
  presence (last post within ~12 months, named institution still
  operating). Cards that can't be confirmed via WebSearch at compose
  time are omitted, not invented.
- **Don't let `.opinion` become a typographic crutch.** Italic
  border-left is striking; the temptation is to wrap every spicy
  sentence in it. The class is for *explicitly named editorial
  judgment* — "skip X, do Y" — not for every assertion the author
  feels strongly about. Most opinion lives in unmarked prose; the
  `.opinion` block is the rare moment of stepping out from behind the
  reportorial voice.

---

## Practical hyperlinks

A trip guide that lists named venues, restaurants, museums, and
hotels but doesn't link any of them out is asking the reader to
retype every name into Google Maps. The convention below treats
practical links as a first-class part of the guide while keeping
atmospheric body prose link-free.

### The two-tier rule

| Tier | What | Where it appears |
|---|---|---|
| **Citation** | Books, podcasts, films, Substacks of named authors, academic sources | ONLY in the consolidated "Sources & further reading" section and the per-section "Go deeper" 4-card rows |
| **Practical** | Google Maps URLs for named venues, ticketing pages, official-site URLs | In the card grids and tables listed below — NOT in atmospheric body prose |

**Practical surfaces** (links allowed and expected):

- Every named venue in `things_to_do`.
- Every named restaurant in `food` (where to eat).
- Every named site card in `day_by_day`.
- Every named landmark / museum entry in `field_guide` (wildlife
  entries have no Maps target — skip).
- Every hotel row in the "Hotels at a glance" table.

**Atmospheric prose stays link-free.** `history` paragraphs,
`day_by_day` day-intro sentences, `food` culture intros, and any
other prose covered by the named-particulars density floor are
unlinked. The reading-rhythm preservation goal from the editorial
voice rules is unchanged.

### Helper invocation

The composer imports two pure helpers from `src/place_links.py`:

```python
from src.place_links import maps_url, practical_link

# Google Maps search URL — used when you want just the URL string.
url = maps_url("Vasa Museum", "Stockholm")
# → "https://www.google.com/maps/search/?api=1&query=Vasa%20Museum%2C%20Stockholm"

# Full <a> tag with rel="noopener" + target="_blank" + html-escaped name.
html = practical_link("Vasa Museum", "Stockholm")
# → '<a class="practical-link" href="..." rel="noopener" target="_blank">Vasa Museum</a>'
```

`rel="noopener"` is a security convention — the new tab can't
`window.opener.location = ...` back at the guide. `target="_blank"`
opens the link in a new tab so the reader doesn't lose their place
in the guide.

### CSS verbatim

```css
a.practical-link {
  color: var(--ink);
  text-decoration-color: var(--ink-soft);
  text-decoration-thickness: 1px;
  text-underline-offset: 2px;
  transition: color 120ms, text-decoration-color 120ms,
              text-decoration-thickness 120ms;
}
a.practical-link:hover,
a.practical-link:focus-visible {
  color: var(--accent);
  text-decoration-color: var(--accent);
  text-decoration-thickness: 2px;
}
```

The same class powers bibliography entries and Go-deeper card
titles too. Citation and practical links style identically — they
never share a paragraph, so a per-tier variant would be ceremony
with no payoff.

### Bibliography + Go-deeper cards

Every entry in the consolidated "Sources & further reading"
section is an `<a class="practical-link">` tag. Every "Go deeper"
card title is an `<a class="practical-link">` tag wrapping the
title text (the card's icon, kind label, and annotation stay
plain text). When `WebSearch` cannot confirm a real landing page
for a source, **omit the card entirely** per the Source disclosure
anti-pattern — better three cards than four with a faked fourth.

### Anti-patterns

- **No inline citation markers** (`[1]`, `[2]`, footnote-style
  superscripts) in body prose. The bibliography is the single
  citation surface; ducking out to it mid-paragraph breaks reading
  rhythm.
- **No external-link glyphs** (`↗`, `🔗`) appended to practical
  links. Subtle underline + accent on hover already says "link";
  the glyph adds visual noise without information.
- **No user-agent-aware Maps rewriting** (Apple Maps on iOS,
  Google Maps elsewhere). Google Maps deep-links into the
  appropriate native app on both iOS and Android — the rewrite is
  unnecessary work for zero user benefit.
- **No links in atmospheric prose.** If you find yourself wanting
  to link a name in a `history` paragraph or a day intro, that's a
  signal to move the recommendation into a `things_to_do` entry
  where the link belongs.

---

## Walking-distance chips

Day-of trip readers want to know, for every named site card or
recommendation, **how far is it from where I'm sleeping tonight?**
The walking-distance chip lives in the `.tags` row of every
`day_by_day` site card (and on `things_to_do` entries when the trip
is single-hotel) with that one piece of information made literal:
"12 min walk · 0.9km from Hotel Skansen."

### The math

```
km_straight  = haversine(venue_coords, hotel_coords)
km_routed    = km_straight * 1.3           # street multiplier
walk_min     = ceil(km_routed / 5.0 * 60)  # 5 km/h walking pace
drive_min    = ceil(km_routed / 30.0 * 60) # 30 km/h in-city driving
```

The 1.3 multiplier approximates the typical detour between
straight-line and routed walking on a city street grid. It's
deliberately rough — the chip's job is "is this close-ish?" not
"exactly how many seconds."

### Three adaptive format bands

| Routed km | Chip body |
|---|---|
| ≤ 2 km | `12 min walk · 0.9km from {hotel}` |
| 2 – 5 km | `40 min walk · 3.2km · or 10 min by car from {hotel}` |
| > 5 km | `15 min by car · 5.8km from {hotel}` |

The middle band's "or N min by car" alternate gives the reader the
"do I walk or grab a taxi?" decision in one glance. The >5 km band
drops the walk number — at that distance, walking isn't the
default, and showing "65 min walk" makes the chip noisier than
useful.

### Helper invocation

```python
from src.walking_distance import walking_chip

chip_html = walking_chip(
    venue_coords=(59.3293, 18.0686),
    hotel_coords=(59.3275, 18.0712),
    hotel_name="Hotel Skansen",
)
# → '<span class="walkchip">5 min walk · 0.4km from Hotel Skansen</span>'
```

Either coord can be `None`; in that case `walking_chip` returns the
empty string and the composer omits the chip entirely. This is the
graceful path when geocoding hasn't run yet or returned no result.

### Hotel resolution per day

The hotel that the chip resolves to depends on which day the site
card belongs to. Use `hotel_for_night(bookings, target_date)` from
`src/trip_helpers.py`:

```python
from src.trip_helpers import hotel_for_night

hotel = hotel_for_night(trip.bookings, day_date)
if hotel is None:
    # Transit day, no hotel covers tonight — omit the chip on this day.
    pass
else:
    hotel_coords = (hotel.geocoded_lat, hotel.geocoded_lng)
    # ...
```

**Hotel-night semantics.** A hotel booking with check-in
`start_datetime` and check-out `end_datetime` covers nights where
`start_datetime.date() <= target_date < end_datetime.date()`. The
night of the check-out date is NOT a hotel night at that booking —
the reader is somewhere else by then.

### Single-vs-multi-hotel rule for `things_to_do`

`day_by_day` site cards have a clear "tonight's hotel" anchor.
`things_to_do` entries don't — they're generic picks not bound to a
day. The rule:

- **Single-hotel trip** (one hotel covers every night of the trip):
  emit the chip on every `things_to_do` entry, anchored to that one
  hotel.
- **Multi-hotel trip** (two or more hotels across the trip's
  nights): **omit the chip entirely** on `things_to_do`. Labelling
  "which hotel?" is more noise than signal — readers can read the
  neighborhood and judge for themselves.

### Geocoding reuses existing infrastructure

The composer does NOT introduce new geocoding code. Coordinates
come from the project's existing Mapbox geocoder:

- **Hotels:** `Booking.geocoded_lat` and `.geocoded_lng` columns,
  auto-populated by `ensure_geocoded(rows, db_session, token)` from
  `src/geocoding.py`. Step 6.5 below calls this on the trip's
  bookings once before composition starts.
- **Venues mentioned in body prose:** call
  `geocode_with_cache(text=f"{name}, {city}", db_session=db.session,
  token=MAPBOX_TOKEN)` and read `.lat` and `.lng` off the returned
  `GeocodeResult`. Results are cached in the `GeocodeCache` DB
  table, so regeneration is free.

If `MAPBOX_TOKEN` is empty in the environment, log a warning and
skip Step 6.5 entirely — chips just won't render. The guide still
composes; links still work.

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

**Re-ask themed-bonus when the saved sections pre-date the rule.** When
`cfg.last_generated_at` is older than 2026-06-25 (when the themed-bonus
REQUIRED prompt landed in this skill), the saved section list was chosen
without ever being asked about themed bonuses. **Treat option 1
("regenerate with same sections") as still requiring the themed-bonus
offer** — silently reusing the old list will repeat the original omission.
A one-line confirmation works: *"Sections look good. Quick check before I
start: want a themed bonus section? Common ones: beer / coffee /
photography / books / running / birding. Skip if none fit."* Apply the
same rule when the user picks option 1 on any trip whose saved list
omits a section the destination obviously calls for (e.g. a Scandinavia
trip with no `beer` section, given the craft-beer scene across Oslo,
Bergen, Helsinki, Tallinn, Stockholm, Copenhagen).

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

**Themed bonus sections — REQUIRED prompt.** After proposing the base section
list, the skill MUST ask the user — in one explicit line, not as a passive
"let me know if you want anything else" — whether to add a themed bonus
section. The skill does not get to decide this by listening alone; absence of
volunteered interest is NOT permission to skip the offer.

Use this prompt verbatim or near-verbatim at section-picker time:

> Want a themed bonus section? Common ones: beer / breweries, coffee, photography
> spots, bookstores, running routes, birding, live music. Skip if none fit.

Only treat silence as "no" if the user has affirmatively said the base list is
enough — never as the default. On any trip where the destination has a
plausible scene for one of the example interests (e.g. a US city has a
brewery scene; a Pacific Northwest city has a coffee scene; almost anywhere
has photography spots), the offer is non-negotiable.

When the user says yes, the bonus section is built with the same visual
language as the rest of the guide — card grid, mono labels, area/city group
headers — and sits between `food` and `fun_facts` in the nav order
(adjacent to `food` so it reads as related material). Examples: a `beer`
section with area-grouped breweries + a "where to drink" list per area, a
`coffee` section with notable roasters, a `photography` section with
locations and golden-hour timing. Themed sections are additive, not
replacements.

**Anti-pattern: don't skip the offer because you can already see relevant
items in the base sections.** A `food` section that mentions two breweries
in passing is NOT a substitute for a dedicated `beer` section — the dedicated
section can group by area, add style tags, and recommend where to drink with
opinionated context that won't fit in a "where to eat" tier. If the base
sections surface ≥2 items in a category (≥2 breweries, ≥2 coffee shops, ≥2
record stores), that's a signal to escalate the themed-bonus offer to a
specific recommendation: *"Rock Hill + Charlotte have a deep brewery scene
— want a `beer` section?"* — not a generic list of options.

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

### 6.5. Ensure coordinates

Before composing the HTML, fill in the coordinates needed for the
walking-distance chips and (later) the practical-link Maps URLs.
The composer reuses the project's existing Mapbox geocoder — no new
cache, no new env var.

```python
import os
from app import db
from src.geocoding import ensure_geocoded, geocode_with_cache

MAPBOX_TOKEN = os.environ.get("MAPBOX_TOKEN", "").strip()

with app.app_context():
    if not MAPBOX_TOKEN:
        logger.warning("MAPBOX_TOKEN not configured — chips will be skipped")
    else:
        # 1. Fill in hotel coords on Booking rows (uses GeocodeCache table).
        ensure_geocoded(trip.bookings, db_session=db.session, token=MAPBOX_TOKEN)

        # 2. For each named venue you're about to render in a practical surface,
        # cache its coords too. Keep the GeocodeResult alongside the venue data
        # so Step 7 can read .lat / .lng off it.
        venue_coords = {}
        for venue in named_venues_in_things_to_do + day_by_day_named_sites + ...:
            result = geocode_with_cache(
                text=f"{venue.name}, {venue.city}",
                db_session=db.session,
                token=MAPBOX_TOKEN,
            )
            if result is not None:
                venue_coords[venue.id] = (result.lat, result.lng)
```

Coordinates for hotels live on `Booking.geocoded_lat / geocoded_lng`
after `ensure_geocoded` runs. Coordinates for venues live in the
`venue_coords` dict the composer just built. Both feed Step 7.

If `MAPBOX_TOKEN` is missing, skip both calls and let the chip
helpers return empty strings on `None` coords — the composer
continues; the guide still ships; the chips just don't render.

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

**Sourcing surfaces (required on every guide).** See the "Source disclosure"
section above for the full pattern. At compose time, emit all three:

1. The `<details class="sources-note">` "A note on sources" block immediately
   after the hero.
2. A `<aside class="go-deeper">` 4-card row at the close of every section
   merged to Deep tier or above.
3. A consolidated `Sources & further reading` section as the last content
   section before the footer.

Plus the prose conventions: `.live-data` mono attribution lines on any
section pulling current data, and ≥1 `.opinion` block per `things_to_do`
and per `food` section at Deep tier or above.

**Practical hyperlinks (required on every guide).** See the
`## Practical hyperlinks` section above. At compose time:

- Wrap every named venue title in `things_to_do`, `food` (where to
  eat), `day_by_day` site cards, and `field_guide` landmark / museum
  entries with `practical_link(name, city)`.
- Wrap every bibliography entry's title and every "Go deeper" card
  title with `<a class="practical-link" href="...">`. Use the
  source's canonical landing URL (publisher page, podcast feed, film
  page, Substack URL) when known. If `WebSearch` cannot confirm a
  real URL, omit the card per the Source disclosure anti-pattern.
- Leave atmospheric body prose (history paragraphs, day intros, food
  culture intros) unlinked — the named-particulars density floor
  carries the same names, but in prose, not as anchors.

**Walking-distance chips (required where coords resolve).** See
the `## Walking-distance chips` section above. At compose time:

- For each `day_by_day` site card on day `d`:
  ```python
  hotel = hotel_for_night(trip.bookings, d.date)
  hotel_coords = (hotel.geocoded_lat, hotel.geocoded_lng) if hotel and hotel.geocoded_lat else None
  chip_html = walking_chip(venue_coords.get(site.id), hotel_coords, hotel.title if hotel else "")
  # Emit chip_html in the .tags row alongside .travelpill / category tag.
  ```
  If `chip_html` is the empty string (any None coord, or no hotel
  covers tonight), no chip renders — graceful skip.
- For each `things_to_do` entry on a **single-hotel** trip: same
  pattern, with the single hotel as the anchor. On a **multi-hotel**
  trip, skip the chip entirely.

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

5. **Wayfinding scaffold asserts.** Required on every guide per the
   Wayfinding scaffold section. Any miss fails verification:
   - `#vp-progress` element exists in the DOM.
   - `.vp-toc` exists with ≥2 `<a>` links, and after a scroll-to-bottom
     action at least one link has the `.active` class
     (proves scroll-spy is wired).
   - Every `<h2>` inside `<main>` contains a `<span class="reading-time">`
     chip (proves compose-time reading-time computation ran).
   - Every TOC `<a href="#…">` target resolves to a `<section id="…">`
     element. Orphan TOC links (anchor with no matching section) fail.

6. **Practical hyperlinks asserts.** Required on every guide per
   the Practical hyperlinks section. Any miss fails verification:
   - Every bibliography `<li>` contains an `<a class="practical-link">`
     wrapping its title.
   - Every `.go-deeper` card title is an `<a class="practical-link">`
     (or the card is omitted per Source disclosure's no-fabricated-
     sources rule — a 3-card row is fine).
   - Every named venue in `things_to_do`, `food` (where to eat),
     `day_by_day` site cards, and `field_guide` landmark/museum
     entries has an `<a class="practical-link" href="...google.com/maps...">`.
   - Atmospheric body prose (under `.section--atmospheric > p` and
     under day-intro paragraphs) contains zero `<a>` tags — the
     verifier grep should find none.

7. **Walking-distance chip asserts.** Required where coords resolved.
   Skipped guides (multi-hotel `things_to_do`, transit days,
   `MAPBOX_TOKEN` unset, geocode-miss venues) do NOT fail verification:
   - On any `day_by_day` site card where `hotel_for_night` resolved
     AND `venue_coords.get(site.id)` is not None, a
     `<span class="walkchip">` element renders inside the `.tags` row.
   - On single-hotel trips, every `things_to_do` entry where venue
     coords resolved has a `<span class="walkchip">`.
   - The "Hotels at a glance" addresses are clickable (each address
     cell wraps in `<a class="practical-link">` linking to the
     hotel's Google Maps URL).

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

**Per-stop wildlife minimum (REQUIRED at Deep+, recommended at Standard).**
Every named stop with enough distance or biogeographic distinctiveness gets
**at least a minimum birds + wildlife rundown** — 3–5 entries per stop
answering "what local fauna defines this place that the reader has a
realistic shot at noticing?" Stops where nature is the headline (Arctic
archipelago, rainforest, safari country, pelagic islands) get the **deep
dive** — habitat-first organisation, ~150 words per entry, likelihood
badges, endemism callouts, phenology strips where seasonally relevant.

"Enough distance or distinctiveness" means: the stop is ≥4 hours' transit
from the previous stop OR is a named ecoregion (Svalbard, Lofoten, Galápagos,
Yellowstone) OR has a non-urban primary draw. City stops separated only by
short flights or trains within the same biogeographic region (Stockholm +
Copenhagen) can share one entry; Lofoten and Bergen (300 km apart, different
fauna) cannot.

**Anti-pattern to avoid.** Deep-diving one stop's wildlife (Svalbard polar
bears, beluga, walrus) and skipping every other stop's fauna entirely
because they're "not the headline." A reader walking the Bergen harbour
benefits from knowing they're likely to see eider, common gull, and the
occasional harbour porpoise — the entry doesn't need to be as long as the
Svalbard ones, but skipping it tells the reader the section isn't for
them at this stop.

At Light tier only the marquee stop gets entries; the others get a
one-line mention in the day-by-day intro instead. At Standard tier emit
3–5 entries per stop for the top three stops. At Deep+ emit them for
every qualifying stop.

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

## Wayfinding scaffold (required)

Long guides earn the reader's time only if the reader can tell where
they are, how far they've gone, and how far is left. The scaffold
below is required on every guide regardless of depth tier — even a
Light-tier 3,000-word guide gets the TOC, progress bar, reading-time
chips, and permalink anchors. The wayfinding apparatus costs almost
nothing and rewards every reader.

Four pieces, all sharing one initialiser:

1. **Sticky side TOC** keyed to `<h2>`s with IntersectionObserver
   scroll-spy that highlights the section currently in view.
   Collapses to a top-bar dropdown under 760px.
2. **3px top-edge progress bar** that fills as the document scrolls.
   The dumbest possible "you're 60% of the way through this" cue.
3. **Per-section reading-time chip** computed at compose time —
   small mono "7 min · history" badge stuck inside each section's
   `<h2>`.
4. **Permalink anchors** with hover-reveal `¶` glyph,
   `scroll-behavior: smooth` on `<html>`, and `scroll-margin-top` on
   `<section>` so the sticky bar doesn't cover headings when jumping
   in from a link.

### JS verbatim

Namespaced under `window.VPGuide` so each behaviour is independently
addressable, wrapped in an IIFE so its closure scope stays out of the
global namespace, and every init function `try/catch`es its own
setup. The const-collision incident in `~/.claude/CLAUDE.md` — two
script blocks declaring the same `const` name silently killed a
whole page — is the cautionary tale here. **A broken scroll-spy
must not break the depth toggle.** Same discipline applies to every
future module added to a guide.

```js
window.VPGuide = window.VPGuide || {};

(function(VPGuide){
  // Top progress bar
  function initProgressBar(){
    try {
      var bar = document.getElementById("vp-progress");
      if (!bar) return;
      window.addEventListener("scroll", function(){
        var h = document.documentElement;
        var pct = (h.scrollTop / (h.scrollHeight - h.clientHeight)) * 100;
        bar.style.width = pct + "%";
      }, { passive: true });
    } catch(e){ console.warn("progress bar init failed", e); }
  }

  // Scroll-spy TOC
  function initScrollSpy(){
    try {
      var links = document.querySelectorAll(".vp-toc a[href^='#']");
      if (!links.length || !("IntersectionObserver" in window)) return;
      var byId = {};
      links.forEach(function(a){ byId[a.getAttribute("href").slice(1)] = a; });

      var obs = new IntersectionObserver(function(entries){
        entries.forEach(function(e){
          var a = byId[e.target.id];
          if (!a) return;
          if (e.isIntersecting) {
            links.forEach(function(l){ l.classList.remove("active"); });
            a.classList.add("active");
          }
        });
      }, { rootMargin: "-40% 0px -55% 0px" });

      document.querySelectorAll("main section[id]").forEach(function(s){ obs.observe(s); });
    } catch(e){ console.warn("scroll-spy init failed", e); }
  }

  VPGuide.initWayfinding = function(){
    initProgressBar();
    initScrollSpy();
  };
  document.addEventListener("DOMContentLoaded", VPGuide.initWayfinding);
})(window.VPGuide);
```

The IntersectionObserver `rootMargin: "-40% 0px -55% 0px"` shrinks
the viewport to a narrow band in the upper-middle; a section is
"active" only when its top edge crosses that band. Adjust the
percentages to taste, but the principle — a band, not a line — is
what stops the active chip from flickering between two sections
during scroll.

### CSS verbatim

```css
#vp-progress {
  position: fixed; top: 0; left: 0; height: 3px; width: 0%;
  background: var(--accent); z-index: 100; transition: width 80ms linear;
}
.vp-toc { position: sticky; top: 80px; }
.vp-toc a { color: var(--ink-soft); text-decoration: none; }
.vp-toc a.active { color: var(--accent); font-weight: 600; }
.vp-toc a.active::before { content: "▸ "; }
main section[id] { scroll-margin-top: 90px; }
.permalink {
  opacity: 0; margin-left: 0.3em; color: var(--ink-soft);
  text-decoration: none; transition: opacity 120ms;
}
h2:hover .permalink, h3:hover .permalink { opacity: 0.6; }
.permalink:hover { opacity: 1 !important; color: var(--accent); }
.reading-time {
  display: inline-block; font-family: var(--font-mono);
  font-size: 0.75em; color: var(--ink-soft);
  margin-left: 0.8em; padding: 1px 6px;
  border: 1px solid var(--hairline); border-radius: 3px;
}
@media (max-width: 760px) {
  .vp-toc { position: static; }
}
@media print {
  #vp-progress, .vp-toc, .mode-toggle, .reading-time, .permalink { display: none !important; }
}
```

`html { scroll-behavior: smooth; }` belongs in the base styles so
permalink clicks animate. `prefers-reduced-motion: reduce` should
flip it back to `auto` per the existing accessibility convention.

### Reading-time computation

At compose time, count words in each section's body (stripped of
HTML tags), divide by **220** (average adult reading pace, words per
minute), `math.ceil` to the nearest minute, and emit the chip inside
the `<h2>`:

```html
<h2 id="history">
  History
  <span class="reading-time">7 min · history</span>
  <a class="permalink" href="#history" aria-label="Permalink to History">¶</a>
</h2>
```

The label after the dot — "history", "field guide", "food" —
echoes the section slug. A reader skimming the TOC can read "7 min ·
history" and decide whether to dive in now or skim it.

### Section IDs and permalink anchors

Every `<section>` gets an `id` matching the slug used in the TOC
anchor (`<a href="#history">`). Every `<h2>` and `<h3>` ships with a
`<a class="permalink" href="#…">¶</a>` immediately after its text.
The `¶` glyph (`&para;`) appears only on hover thanks to the CSS
`opacity: 0` → `opacity: 0.6` transition; click copies the URL with
fragment to the address bar via the browser's default anchor
behaviour.

### Sticky-nav offset rule

The 80px / 90px figures in the CSS assume the sticky top bar
(housing the mode toggle and the mobile TOC dropdown) is ~70px
tall. If the top bar grows, bump both numbers in lockstep:
`.vp-toc { top: <bar-height + 10>px }` and
`main section[id] { scroll-margin-top: <bar-height + 20>px }`.
The extra 10–20px is breathing room above the heading so it doesn't
sit pinned to the bar after a fragment jump.

### Anti-pattern: don't ship a TOC without `id`s

A `.vp-toc` with `href="#section"` links that point at non-existent
section IDs is a silent failure — clicking does nothing, scroll-spy
never fires, and nothing on screen tells the reader why. The Step 10
verification grep below catches this case. Keep the rendered TOC
and the section ID set in lockstep.

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
