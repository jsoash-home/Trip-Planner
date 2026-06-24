# Trip Guide Depth Enhancements — Multi-Phase Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise the depth bar of the `trip-guide` skill so a generated
guide reads like a souvenir-grade publication — with serious history
and nature depth — without bloating short trips. Resolved by two
orthogonal levers (a 4-tier depth setting + an archetype classifier),
a documented visual vocabulary, and a progressive-disclosure structure
that lets a skim reader and an obsessive reader share the same file.

**Architecture:** Three rewrites, not one. Phase 1 codifies the
editorial spine in `SKILL.md` (depth tiers, archetype matrix, voice
rules, progressive-disclosure CSS, ERA_COLORS palette, sourcing
pattern, wayfinding JS) and adds three fields to `GuideConfig`.
Phase 2 builds a Python helper toolkit for the inline-SVG visual
primitives (so the composer passes data, not raw SVG). Phase 3 adds
the in-trip companion surfaces and the structural deep-dives
(habitat-first field guide, histpins, character vignettes, SOS
panel). Each phase is its own plan file written after the prior one
ships, per `~/.claude/CLAUDE.md` plan-splitting standard.

**Research backing:** 10-agent research workflow run 2026-06-23,
synthesised into 10 top recommendations + history/nature deep dives.
The full synthesis lives in the chat transcript that produced this
plan. The decisions below are the load-bearing ones; everything else
falls out of them.

---

## The two levers (decision summary)

The user asked whether a 1–10 depth dial replaces archetype detection.
Answer: they're orthogonal and both ship.

### Lever 1 — Depth tier (4 named levels)

Replaces a 1–10 dial because the model cannot consistently calibrate
10 distinct levels — 4 and 6 would look identical. Each tier has
documented word-count floors and a fixed module checklist, so output
is predictable and debuggable.

| Tier | Word target | Sections | Visual primitives | Voice density |
|---|---|---|---|---|
| **Light** | ~3,000 | 4–5 | None beyond hero | Prose only, 1 sensory opener per section |
| **Standard** | ~8,000 | 6–8 | Hero route SVG, 4-stat weather grid, phenology strip (if nature) | ≥1 named particular per paragraph |
| **Deep** | ~15,000 | 7–8 + bonus | Full Visual Primitives toolkit, era palette, sidenotes ≥3/major subsection | ≥1 callout per ~600 words, dig-deepers on demand |
| **Souvenir-grade** | ~25,000 | All 8 + bonus + `quick_reference` + `life_list` | All of Deep + annotated bibliography + 4-card go-deeper rows + character vignettes | ≥3 vignettes in history, dual-narrator history where contested |

A **per-section override** lets the user say "Deep overall, Souvenir-grade
on history" without dragging everything else up. Stored as
`cfg.depth_tier` (default) + optional `cfg.section_depth_overrides`
dict.

### Lever 2 — Archetype (which sections matter)

Detected from the trip's destinations, bookings, and itinerary keywords.
Drives which optional modules fire. Stored as `cfg.archetype`.

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

Multi-archetype trips (Rome + Tuscany hiking) blend two: primary
archetype owns the depth-tier word floors, secondary archetype
contributes its modules at half weight.

### How they interact

```
final_guide = compose(
    sections = ARCHETYPE_TO_SECTIONS[archetype],
    depth_per_section = depth_tier_floor_for(tier),
    modules = ARCHETYPE_TO_MODULES[archetype],
    overrides = section_depth_overrides,
)
```

---

## Multi-phase roadmap

Three phases, run as separate sessions across separate days. Each
ships independently and produces a usable guide before the next starts.

### Phase 1 — Editorial spine (this plan, ~6 sessions)

Tightens `SKILL.md` with the rules, taxonomies, CSS, and JS that
make depth possible *without writing any visual-primitive Python
yet*. Adds three fields to `GuideConfig`. After this phase: a
generated guide will read more like a magazine and less like a
filled-in template, but won't yet have swimlane timelines or
phenology strips — those land in Phase 2.

### Phase 2 — Visual primitives toolkit (separate plan, ~5 sessions)

Builds Python helpers in `src/guide_builder.py` (or a new
`src/guide_visuals.py`) that emit inline SVG from structured data:
`silhouette_svg`, `phenology_strip`, `geology_section_svg`,
`swimlane_timeline`, `climate_strip`, `size_comparison_panel`,
`stratigraphic_stack`, `era_chip`. Plus a reusable `<defs>` icon
library (IUCN status, endemic-to, period glyphs). The skill stops
hand-writing SVG and starts passing data dicts.

### Phase 3 — In-trip companion + structural deep-dives (separate plan, ~6 sessions)

Habitat-first field guide rewrite, character vignettes, sidenote
system, histpin field on day cards, `quick_reference` 9th section
+ fixed-bottom SOS overlay, day-of auto-scroll, place-card tap
actions (tel: / geo: / copy-address), narrator-angle persona injection.
This phase doubles the in-trip usefulness of every guide.

**Why this order:** Phase 1 unlocks the depth dial and writing rules
that every later module assumes. Phase 2 turns the visual constraint
("inline SVG only") into a vocabulary. Phase 3 is the structural
work that the first two phases make cheap.

---

## Cross-cutting decisions to lock now

These are the choices that cascade through every phase. Recording
them here so future-me doesn't relitigate them.

### Banned-word list (greppable at verify time)

Add to `SKILL.md` editorial voice section. Composer must strip any
of these from prose:

```
vibrant, bustling, hidden gem, must-see, rich heritage, melting pot,
charming, picturesque, unspoilt, off-the-beaten-path, dates back to,
centuries of, has long been, something for everyone, a feast for the
senses, gem of a, jewel of, crown jewel, postcard-perfect, fairytale,
storied, world-class, breathtaking
```

Phase 1 documents the list. Phase 1 verification step adds a
greppable post-compose check that fails the build if any appear in
body prose (allowed inside quoted material).

### Named-particulars rule

Every paragraph in `history`, `field_guide`, `food`, `things_to_do`,
and `day_by_day` intros must contain at least one proper noun —
named street, person, date, dish, species, building. No more
"a great cafe" — name Café Tortoni.

### Narrator angle (new Step 4.5 in the skill flow)

After section picking, before composition:

> "Who is this guide written for?
> 1. First-timer with a history obsession
> 2. Returning after 10+ years, wants what's new
> 3. Family with kids 5–12
> 4. Active outdoors / "out before sunrise" type
> 5. Food-first traveler
> 6. Cultural completionist
> 7. Honeymoon / slow-travel
> 8. Custom (free text)"

Stored as `cfg.narrator_angle`. Surfaced in the hero as a one-line
italic dek under the trip title. Influences voice across all sections.

### ERA_COLORS per destination (not global)

Each guide researches its own period palette at compose time. A
Rome guide gets Republican / Imperial / Late Antique / Medieval /
Renaissance / Baroque. An Iceland guide gets Settlement / Commonwealth
/ Norwegian / Danish / Republic. Declared as CSS variables once at
the top of the file; used by era boxes, date chips, layer chips,
histpins, and the swimlane timeline (Phase 2).

### Sourcing surfaces (three places, no inline citations in prose)

1. **`<details>` "A note on sources" block** right after the title —
   3–5 plain-language sentences naming the kinds of sources used
   and the destination's evidence-quality issues.
2. **Per-section closing 4-card row** — BOOK / PODCAST / FILM /
   LOCAL VOICE-TO-FOLLOW, each with a one-line annotation.
3. **Consolidated "Sources & further reading" section** at the foot —
   grouped by topic, 3–5 annotated entries each.

---

## File map (all phases)

**Created in Phase 1:**
- `docs/superpowers/plans/2026-06-23-trip-guide-depth.md` (this file)
- *(no Python or template files created in Phase 1 — `SKILL.md` is the work)*

**Modified in Phase 1:**
- `.claude/skills/trip-guide/SKILL.md` — every change in Phase 1 lands here
- `src/guide_builder.py` — adds three fields to `GuideConfig` dataclass + JSON serialization
- `tests/test_guide_builder.py` — round-trip + default tests for the new fields

**Created in Phase 2 (preview, not in scope here):**
- `src/guide_visuals.py` — SVG helpers (~400 lines)
- `tests/test_guide_visuals.py` — output-shape tests per helper

**Created in Phase 3 (preview, not in scope here):**
- *(SKILL.md additions only; possibly new `src/guide_research.py` for the sourcing helpers)*

**Untouched across all phases:** Flask routes, models, all other
`src/*` modules, all other templates, all other tests. The skill
and its config sidecar are the entire surface.

---

## Background reading

Before starting Phase 1:

- `.claude/skills/trip-guide/SKILL.md` — the current skill, especially
  steps 4–7 of the 10-step flow, and the section content model.
- `src/guide_builder.py` — the `GuideConfig` dataclass and
  `load_or_init_config` / `save_config` flow.
- `tests/test_guide_builder.py` — pattern for testing the config sidecar.
- `~/.claude/CLAUDE.md` § "Plan writing standards" — the 1000-line /
  17-task caps and what belongs vs doesn't belong in a plan.
- `CLAUDE.md` § "Trip guide" — the project-level context on this skill.

---

## Phase 1 — Editorial spine

**End state:** A regenerated guide reads with editorial voice, has a
period palette that cross-references between sections, uses
progressive disclosure (lede / `.deep`) with a Skim / Curious / Deep
toggle, names its sources without inline clutter, and has a
wayfinding spine (sticky TOC, scroll-spy, progress bar, reading-time
chips). Visual primitives (swimlanes, cross-sections, phenology
strips) are NOT yet in scope — those are Phase 2.

Each task in this phase ends with a commit, per the project's
TDD-with-commit-per-task discipline.

---

### Task 1 — Extend `GuideConfig` with depth, archetype, narrator angle

**Files:**
- Modify: `src/guide_builder.py` — `GuideConfig` dataclass
- Modify: `tests/test_guide_builder.py`

**Public surface change.** Three new fields on `GuideConfig`:

```python
@dataclass
class GuideConfig:
    # ...existing fields...
    depth_tier: Optional[str] = None           # "light" | "standard" | "deep" | "souvenir_grade"
    section_depth_overrides: dict = field(default_factory=dict)  # {section_key: tier}
    archetype: Optional[str] = None            # "history_stacked" | "wildlife" | "geology" | "cuisine_led" | "pilgrimage" | "expedition" | "architecture_modern" | "mixed_leisure"
    narrator_angle: Optional[str] = None       # free-form short string (max ~80 chars)
```

All four fields are nullable to preserve backwards compat with
existing sidecar JSON files. `load_or_init_config` reads missing
fields as `None` / `{}` and `save_config` only emits non-default
values to keep the JSON tidy.

**Test list (names only, no bodies — write them in `tests/test_guide_builder.py`):**
- `test_guide_config_defaults_new_fields_to_none`
- `test_guide_config_roundtrip_with_depth_tier`
- `test_guide_config_roundtrip_with_section_overrides`
- `test_guide_config_roundtrip_with_archetype`
- `test_guide_config_roundtrip_with_narrator_angle`
- `test_guide_config_back_compat_missing_fields_load_as_none` — write a sidecar JSON missing all four fields, assert load returns defaults
- `test_guide_config_invalid_depth_tier_rejected_or_normalized` — pick one behaviour and commit to it

**Verify:** `pytest tests/test_guide_builder.py -q` passes; full
suite (`pytest tests/ -q`) still passes.

**Commit:** `feat(guide_builder): add depth_tier, archetype, narrator_angle to GuideConfig`

---

### Task 2 — `SKILL.md`: Document the depth-tier system

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Depth tiers — the 1-knob calibration"** inserted between "Quality bar — read the benchmarks first" and "The 10-step flow".

**What goes in:**
- The 4-tier table (Light / Standard / Deep / Souvenir-grade) from
  this plan's "The two levers" section, reproduced verbatim.
- Explicit per-section word floors at each tier:

  | Section | Light | Standard | Deep | Souvenir |
  |---|---|---|---|---|
  | `history` | 300 | 800 | 1,500 | 3,000 |
  | `field_guide` (per entry) | 40 | 80 | 150 | 250 |
  | `day_by_day` (per day intro) | 60 | 150 | 300 | 500 |
  | `food` (each "things to try" entry) | 25 | 60 | 120 | 200 |
  | `fun_facts` | 200 | 400 | 700 | 1,200 |
  | *(others scale by same multipliers)* | | | | |

- **Per-section override** semantics: a sidecar config can carry
  `{ "history": "souvenir_grade" }` to lift one section above the
  trip's default tier. Document the merge rule (override wins;
  fallback to `depth_tier`; ultimate fallback to "standard").
- New step in the 10-step flow: insert **Step 4.5 "Pick depth tier"**
  between section picking (Step 4) and palette proposal (Step 5).
  Wording: "Light / Standard / Deep / Souvenir-grade — which?"
  + a one-line description of each + the per-section override prompt.
- Update the existing Step 3 (detect prior run) — when offering
  "Regenerate with same sections", also reuse the saved depth_tier
  and overrides.

**Anti-pattern to document:** Do NOT auto-pick depth from trip
length. A 14-day Greek-islands lounge can be Light; a 3-night Rome
trip can be Souvenir-grade. The user picks; the skill never
infers.

**Verify:** `SKILL.md` reads cleanly top-to-bottom; the per-section
floor table renders in Markdown preview.

**Commit:** `docs(trip-guide): document depth tier system + per-section overrides`

---

### Task 3 — `SKILL.md`: Document archetype detection

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Archetype detection"**
inserted as the new **Step 0** of the 10-step flow (renames the
existing "Resolve the trip" to Step 1's first sub-bullet, or
simply prepend Step 0 — pick one and commit).

Actually — prepend as **Step 1.5** between trip resolution and data
loading, so trip lookup happens first and the skill can use the
trip's destinations/bookings as classification signals.

**What goes in:**
- The 8-archetype table from "Lever 2" above, reproduced verbatim.
- A classification rubric: a 12-question yes/no checklist the skill
  walks before proposing an archetype, e.g.
  - "Does the destination have ≥3 named historical periods with
    visible material remains?"
  - "Is the primary motivation a specific ecosystem or wildlife
    encounter?"
  - "Are there bookings or itinerary items for guided naturalist
    activities, dives, or safari drives?"
  - "Is the destination known for endemism or unique geology?"
  - *(8 more — pick the strongest signals per archetype)*
- A worked example: "Iceland in August, 7 days, 1 hotel in Reykjavík
  + a campervan booking + an itinerary mentioning Þingvellir →
  primary `geology`, secondary `mixed_leisure`."
- **Confirmation step:** the skill proposes its archetype out loud
  ("This reads as a `geology` trip with `mixed_leisure` blended in
  — agree?") and waits for user acceptance or correction. Save to
  `cfg.archetype` immediately.
- **Module matrix:** for each archetype, the default-fire optional
  modules at each depth tier:

  ```
  history_stacked × Deep    → era_palette, swimlane_timeline (Phase 2), histpins, vignettes ×3, etymology cards, sidenotes ≥3/section
  wildlife × Deep           → habitat_chapters, layered_species_cards, phenology_strip (Phase 2), endemism_callouts
  geology × Deep            → stratigraphic_stack (Phase 2), cross_sections (Phase 2), deep_time_timeline
  (etc.)
  ```

- **Multi-archetype rule:** primary archetype's modules fire at
  full weight; secondary at half (e.g. 1 vignette instead of 3).

**Anti-pattern to document:** Do NOT silently change archetype on
regenerate. If the user re-picks sections, ask whether to re-classify
or keep the prior archetype.

**Verify:** Read top-to-bottom; the matrix renders.

**Commit:** `docs(trip-guide): document archetype detection + module matrix`

---

### Task 4 — `SKILL.md`: Editorial voice rules + narrator angle step

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Editorial voice — the writing rules"** between the new archetype/depth sections and the existing "10-step flow". Plus a new **Step 4.5 "Narrator angle"** in the flow.

**What goes in the voice section:**

1. **Banned phrases** — the full list from "Cross-cutting decisions"
   above, with a one-line rationale per cluster.
2. **Named-particulars density floor** — every atmospheric paragraph
   must carry ≥1 proper noun. Codify which sections count as
   "atmospheric" (history, field_guide entries, day intros, food,
   things_to_do) vs "practical" (before_you_go, weather stats,
   fun_facts → tips column).
3. **History claim triad** — date + named person/building +
   present-day consequence required for every history paragraph.
4. **Sensory opener rule** — each section's first paragraph opens
   on a sensory note (smell, sound, light, texture), named and
   specific.
5. **Register split** — document two CSS classes the composer
   applies at the section level:
   - `.section--practical` — sans-serif, ~52ch line length, bullets
     allowed, terse.
   - `.section--atmospheric` — serif body, ~62ch, scene-led, no
     bullets.

   Provide the exact CSS verbatim (this is hard-to-recover and
   easy to drift):

   ```css
   .section--practical { font-family: var(--font-sans); max-width: 52ch; }
   .section--practical p { margin: 0.6em 0; }
   .section--practical ul { padding-left: 1.2em; }
   .section--atmospheric { font-family: var(--font-serif); max-width: 62ch; }
   .section--atmospheric p { margin: 1em 0; text-indent: 0; }
   .section--atmospheric p + p { text-indent: 1.5em; }
   ```

   The text-indent on `p + p` mimics print typesetting and is the
   single highest-signal "this looks edited" move.

**What goes in Step 4.5:**

- The narrator-angle picker (8 options + custom free-text) from
  the cross-cutting decisions section.
- Persistence: save to `cfg.narrator_angle` immediately via
  `save_config`.
- Surface in hero: one-line italic dek under the trip title.
  Example: *"For the returning visitor — what's changed since 2015."*
- Influence on prose: document that the angle is woven into every
  section's opening, not stated outright everywhere. The reader
  feels the lens; they don't read the label.

**Verification addition:** Update Step 10 (Frontend verification)
to add a greppable post-compose check: any banned word found in
body text (outside quoted strings) fails verification. Pseudocode
in `SKILL.md`:

```python
BANNED = ["vibrant", "bustling", ...]  # full list
body_text = strip_html_tags(html)
hits = [w for w in BANNED if re.search(rf"\b{w}\b", body_text, re.I)]
if hits:
    raise VerifyFail(f"banned phrases in body: {hits}")
```

**Anti-pattern to document:** Banned-word check operates on prose
ONLY, not on quoted material. A history vignette can quote a
period author saying "the bustling port" — that's a citation, not
the guide's voice.

**Verify:** Re-read both new blocks top-to-bottom.

**Commit:** `docs(trip-guide): editorial voice rules + narrator angle step`

---

### Task 5 — `SKILL.md`: Progressive disclosure + ERA_COLORS + Skim/Curious/Deep toggle

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Progressive disclosure architecture"** between "Editorial voice" and the 10-step flow.

**This task carries verbatim CSS and JS** because that's the
hard-to-recover detail. Per `~/.claude/CLAUDE.md`, code in plans is
for design decisions that are hard to recover mid-flow — these are
the canonical examples.

#### 5a. Lede / `.deep` two-track pattern

Document the rule: every dense subsection opens with a **bold
standalone lede** (2–3 sentences that are the complete short answer)
followed by `.deep` prose styled softer + slightly smaller +
slightly muted.

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

`--ink-soft` is a new palette variable: typically the body ink
mixed 12% toward the page bg. Document in the palette section
that every palette must declare both `--ink` and `--ink-soft`.

#### 5b. Skim / Curious / Deep toggle

A 3-position toggle in the sticky nav. Sets `data-mode` on
`<body>`; CSS hides `.deep`, `.dig-deeper`, `.sidenote-content`,
`.endnotes` in Skim mode and shows everything in Deep mode.
`localStorage["vp.guide.mode"]` persists choice. `@media print`
forces Deep regardless.

Document the verbatim HTML pattern:

```html
<div class="mode-toggle" role="radiogroup" aria-label="Reading depth">
  <button data-mode="skim" aria-pressed="false">Skim</button>
  <button data-mode="curious" aria-pressed="true">Curious</button>
  <button data-mode="deep" aria-pressed="false">Deep</button>
</div>
```

CSS verbatim:

```css
body[data-mode="skim"] .deep,
body[data-mode="skim"] .dig-deeper,
body[data-mode="skim"] .sidenote-content,
body[data-mode="skim"] .endnotes { display: none; }

body[data-mode="curious"] .dig-deeper,
body[data-mode="curious"] .sidenote-content { display: none; }

@media print {
  .deep, .dig-deeper, .sidenote-content, .endnotes { display: block !important; }
  .mode-toggle { display: none; }
}
```

JS verbatim (~30 lines):

```js
(function(){
  var KEY = "vp.guide.mode";
  var saved;
  try { saved = localStorage.getItem(KEY); } catch(e) { saved = null; }
  var mode = saved || "curious";
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

#### 5c. ERA_COLORS palette pattern

Document that history-stacked archetypes (and any archetype with
non-trivial history) declare a per-destination period palette at
the top of the file alongside the regular palette. Pattern:

```css
:root {
  /* trip palette */
  --bg: ...; --ink: ...; --accent: ...;
  /* era palette — researched per destination */
  --era-prehistoric: #6b7280;
  --era-roman:       #b45309;
  --era-medieval:    #4a6741;
  --era-renaissance: #8e3a59;
  --era-modern:      #4769a8;
}
.era-card { border-left: 4px solid var(--era); padding-left: 12px; }
.era-card.era-roman { --era: var(--era-roman); }
.era-card.era-medieval { --era: var(--era-medieval); }
/* etc. */

.date-chip { background: var(--era); color: white; padding: 1px 6px; font-family: var(--font-mono); }
```

Document the rule: era names are researched per destination
(Rome ≠ Kyoto ≠ Iceland). Stored as `cfg.era_palette = {name, eras: [{slug, label, hex, year_range}]}`.

The era palette is REUSED across sections — every date chip in
the body, every era box, every layer chip on a site card, every
histpin (Phase 3), every swimlane band (Phase 2) uses the same
five colours. That repetition is what teaches the reader the period
system without a memorization quiz.

**Verify:** Lint-pass through `SKILL.md`; make sure the CSS/JS
blocks fence cleanly and don't break the markdown.

**Commit:** `docs(trip-guide): progressive disclosure + ERA_COLORS palette`

---

### Task 6 — `SKILL.md`: Source disclosure pattern

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Source disclosure"**
between "Progressive disclosure architecture" and "10-step flow".
Plus modify the 10-step flow's Step 7 (Compose) to require the
three sourcing surfaces.

**What goes in:**

1. **"A note on sources" `<details>` block** required right after the
   hero. 3–5 plain-language sentences. Template:

   > Sources for this guide. The history draws on
   > [academic source class], the wildlife sections on [field
   > resource], the food on [local press / cookbook authors]. Live
   > data (weather, opening hours) was current as of {generation_date}
   > — verify before booking. Opinion is marked in the prose; sources
   > for individual claims are linked in the "Further reading"
   > section at the foot.

2. **Per-section "Go deeper" 4-card row** at the close of every
   section the depth tier marks as deep. Pattern:

   ```html
   <aside class="go-deeper">
     <h4>Go deeper on this</h4>
     <div class="gd-grid">
       <article class="gd-card"><span class="gd-kind">Book</span><h5>Title</h5><p>One-line annotation.</p></article>
       <article class="gd-card"><span class="gd-kind">Podcast</span>...</article>
       <article class="gd-card"><span class="gd-kind">Film</span>...</article>
       <article class="gd-card"><span class="gd-kind">Local voice</span>...</article>
     </div>
   </aside>
   ```

3. **Consolidated "Sources & further reading"** as the last content
   section before the footer. Grouped by topic (`On the history`,
   `On the wildlife`, `On the food`); 3–5 annotated entries each.
   Each entry: `Title — Author (Year). One-line opinionated annotation.`

4. **Live data callouts** — for any section pulling current data,
   a small mono attribution line at the section foot:
   `Weather data: NOAA, fetched 2026-06-23. Wildlife sightings: eBird hotspot data, last 30 days.`

5. **`.opinion` typographic container** for explicitly marked
   editorial judgment:

   ```html
   <p class="opinion">If you only do one thing in Rome: skip the Trevi Fountain queue and walk to the Palazzo Doria Pamphilj. The crowd never finds it.</p>
   ```

   ```css
   .opinion {
     border-left: 3px solid var(--accent);
     padding-left: 12px;
     font-style: italic;
     color: var(--ink-soft);
   }
   ```

   Required ≥1 per `things_to_do` and per `food` at Deep tier.

**Anti-patterns:**
- No fabricated sources. If the skill can't name a real book, the
  card is omitted, not faked.
- No URL citations in body prose — they go in the consolidated
  sources section only.
- "Local voice to follow" cards must name a real person, museum,
  or institution that has a current public presence (Substack, IG,
  podcast). If none can be confirmed via WebSearch, omit the card.

**Verify:** Read through.

**Commit:** `docs(trip-guide): source disclosure pattern (note + go-deeper + bibliography)`

---

### Task 7 — `SKILL.md`: Wayfinding scaffold

**Files:**
- Modify: `.claude/skills/trip-guide/SKILL.md`

**Where it lands:** New top-level section **"Wayfinding scaffold (required)"** between "Hero details" and "Accessibility patterns".

**Required on every guide regardless of depth tier:**

1. **Sticky side TOC** keyed to `<h2>`s with IntersectionObserver
   scroll-spy. Collapses to a top-bar dropdown under 760px.
2. **3px top-edge progress bar** that fills as the document scrolls.
3. **Per-section reading-time chip** computed at compose time —
   small mono "7 min · history" stuck to each section header.
4. **Permalink anchors** with hover-reveal `¶` glyph,
   `scroll-behavior: smooth`, and `scroll-margin-top` so the
   sticky bar doesn't cover headings when jumping in.

**JS verbatim** (~50 lines, namespace under `window.VPGuide`):

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

CSS verbatim:

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

**Reading-time computation** documented in `SKILL.md`: at compose
time, count words per section, divide by 220 (avg adult reading
pace), round up, emit `<span class="reading-time">N min · {label}</span>`
inside each section's `<h2>`.

**Namespace discipline note** — call out the const-collision
incident from `~/.claude/CLAUDE.md`. Every behaviour must be an
IIFE that try/catches its own setup. A broken scroll-spy must not
break the depth toggle.

**Update Step 10 verification:** add explicit asserts —
- progress bar element exists
- TOC has ≥2 links and at least one has `.active` after scroll
- every `<h2>` has a `.reading-time` chip
- every section has an `id` matching a TOC anchor

**Verify:** Read top-to-bottom; CSS/JS fence cleanly.

**Commit:** `docs(trip-guide): wayfinding scaffold (TOC, scroll-spy, progress, reading-time)`

---

### Task 8 — Validation pass: regenerate a guide

**Files:** No file edits expected — this is a smoke test of the
Phase 1 spec.

**Process:**
1. Pick an existing trip from `vacation.db` that already has a guide.
2. Invoke `/trip-guide`. Walk the new flow:
   - Step 1: resolve trip.
   - Step 1.5: archetype proposal + confirmation (NEW).
   - Step 2: load data.
   - Step 3: prior-run detection.
   - Step 4: section picker.
   - Step 4.5: depth tier + narrator angle pickers (NEW).
   - Step 5: palette + era palette proposal.
   - Steps 6–10: research, compose, save, share, verify.
3. Inspect the generated guide in the browser:
   - Depth toggle works; persists across reload.
   - TOC scroll-spy works.
   - Progress bar fills.
   - Reading-time chips render on every section.
   - Era-colour date chips appear in history body prose.
   - No banned words in body prose.
   - Sources surfaces appear (note + go-deeper + bibliography).
4. Capture 3–5 observations: what feels right, what's awkward,
   what to polish before Phase 2.

**Output:** A short markdown note `docs/superpowers/notes/2026-XX-XX-trip-guide-phase1-validation.md` capturing observations. This note seeds the Phase 2 plan.

**Verify:** The user manually reviews the guide and signs off
before closing the session.

**Commit:** `docs(trip-guide): phase-1 validation notes`

---

## Phase 2 stub — Visual primitives toolkit

*To be written after Phase 1 ships.* Estimated 5 sessions, ~10 tasks.

**End state:** `src/guide_visuals.py` exports typed Python helpers
that emit inline SVG strings from data dicts. The skill stops
hand-writing SVG and starts calling `swimlane_timeline(events=...)`,
`phenology_strip(months=..., highlight_range=...)`,
`geology_section_svg(layers=...)`, `silhouette_svg(slug, callouts)`,
`climate_strip(daily_highs=...)`, `size_comparison_panel(items=...)`,
`stratigraphic_stack(periods=...)`, `era_chip(era_slug, label)`.
Plus a reusable `<defs>` icon library declared once at the top
of every guide: IUCN status pills, endemic globe, period glyphs.

**Why this phase needs its own plan:** each helper is its own
public-surface decision (what shape does the data take? what's
the viewBox convention? how does it handle missing data?). Plus
tests per helper. That's 8–10 tasks just for the helpers.

**Hardest design choices to lock during Phase 2 planning:**
- viewBox sizing convention (cap at 800 wide, or per-helper?)
- Colour-variable substitution: helpers take `palette_var: str` and
  emit `fill="var(--era-roman)"` rather than literal hexes? Yes,
  to keep the era palette as the single source of truth.
- Where the silhouette path data lives (a separate JSON-ish module
  vs. hard-coded per call). Probably a `data/silhouettes.json`-style
  registry.
- How missing data degrades — empty status field, no IUCN pill.
- A11y: every primitive carries an `aria-label` prose summary; data
  also rendered as a `<table class="sr-only">` for screen readers.

**Phase 1 dependency:** The ERA_COLORS palette pattern (Task 5)
defines the CSS variable scheme that swimlanes and date chips
consume.

---

## Phase 3 stub — In-trip companion + structural depth

*To be written after Phase 2 ships.* Estimated 6 sessions, ~12 tasks.

**End state:** Guides become useful DURING the trip, not just before.
Plus the structural deep-dives (habitat-first field guide,
character vignettes, sidenote system, histpin field on day cards).

**Tasks in scope (rough list — to be sharpened in the Phase 3 plan):**
- Habitat-first field guide rewrite — replace flat species grid
  with 2–5 habitat chapters per guide, each with cross-section
  SVG + species grid + phenology strip.
- Sidenote system — Tufte-style CSS-only (checkbox-hack),
  float-right on desktop, expand-on-tap on mobile.
- Character vignette card pattern — 100–150 word stories anchored
  on a single named person, in `history` and `food`.
- Histpin field on every day-by-day site card — one dated
  this-spot sentence per card where applicable.
- `quick_reference` 9th always-included section — emergency
  numbers as `tel:` links, phrases, transit cheat sheet, tipping.
- Fixed-bottom SOS overlay — opens the quick_reference content
  fullscreen on tap.
- Day-of auto-scroll — on page load, compute today's relative
  position in the trip and scroll to that day section if mid-trip.
- Place-card tap-action row — every named venue gets `tel:`,
  `geo:`/maps URL, copy-address actions at ≥44×44px.
- `twovoices` module for contested-history destinations (opt-in
  during composition).
- Annotated further-reading shelf grouped by purpose for the
  history section.
- Etymology micro-cards sprinkled across history, day intros,
  field guide.
- "Then & Now" and "Local Custom" callout vocabulary with
  one-per-600-words density rule.

**Phase 1 + 2 dependencies:**
- Editorial voice rules (Phase 1 Task 4) and depth tiers (Phase 1
  Task 2) decide which of these fire at which tier.
- Visual primitives (Phase 2) supply the silhouettes, cross-sections,
  swimlanes, and phenology strips that the habitat-first field
  guide assumes.

---

## Open questions to answer before Phase 1

These are real ambiguities. Pick one position each before opening
the Phase 1 session.

- [ ] **Depth-tier slug convention.** `souvenir_grade` (snake) vs.
      `souvenir-grade` (kebab). Pick one; stick to it across config,
      CSS classes, and prose.
- [ ] **Banned-word check failure mode.** Hard fail (verification
      blocks save) vs. soft warn (logs hits, lets user decide).
      Recommend hard fail — soft warn means the rule erodes.
- [ ] **Per-section override JSON shape.** Flat `{ "history": "deep" }`
      vs. nested `{ "history": { "tier": "deep", "modules": ["swimlane"] } }`.
      Recommend flat for Phase 1; nested when modules are real (Phase 2).
- [ ] **Where the era palette is researched.** During Step 5 alongside
      the trip palette, or its own Step 5.5? Recommend during Step 5
      so the user sees both palette systems at once.
- [ ] **Architecture handling — `architecture_modern` is the only
      archetype with no current depth modules.** Add building cards
      with architect + year as the placeholder, or defer to Phase 3?
      Recommend defer; ship `mixed_leisure` defaults for it in
      Phase 1.

---

## Phase 1 entry checklist

- [ ] Read this file end-to-end.
- [ ] Read `.claude/skills/trip-guide/SKILL.md` (current version) end-to-end.
- [ ] Read `~/.claude/CLAUDE.md` § "Plan writing standards" and § "Frontend verification".
- [ ] Answer the five open questions above.
- [ ] Pick a sample trip ID from `vacation.db` for Task 8 validation.
- [ ] Confirm `pytest tests/ -q` is green before starting Task 1.
