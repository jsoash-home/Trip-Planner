# Vacation Planner UI Redesign — Multi-Session Implementation Plan

This plan breaks the 19 selected recommendations into 20 bite-size sessions
designed to fit within a single focused work session. Each session is
self-contained, ends with tests passing and one commit, and can be tackled
in order or picked à la carte within a phase.

---

## Session sizing guide
- **S (small):** ~1–2h, single focused change, 15–25 tool calls.
- **M (medium):** ~2–3h, 25–40 tool calls.
- **L (large):** split here — listed as a/b pair.

Start fresh context per session (don't resume a compacted conversation).

---

## Phase 1 — Foundation (CSS & shell)

These come first because dark mode (Session 17) and several other items
depend on the token system being clean and the shell being lean.

### Session 1 — Heal the token leak (M)
**Goal:** Replace every `var(--bs-*)` in `static/css/app.css` (lines ~1003–1187)
with `--vp-*` equivalents, and introduce new tokens where the late additions
invented their own colors.
**Files:** `static/css/app.css`
**Deliverable:** Countdown hero is coral/sand, not Bootstrap blue/purple. Ring
+ unit-toggle + milestone overlay all reference `--vp-*` tokens. New tokens
added: `--vp-hero-gradient-start/end`, `--vp-ring-bg`, `--vp-ring-fg`,
`--vp-toggle-bg`.
**Risk:** Low — pure CSS, no JS or template churn. Visual review needed on
the trip overview + dashboard.

### Session 2 — Self-host Inter (or drop it) + inline critical CSS (M)
**Goal:** Eliminate the Google Fonts roundtrip; move the `:root` token block
into a `<style>` block in `<head>` so first paint isn't waiting on `app.css`.
**Files:** `templates/base.html`, `static/css/app.css`, possibly add
`static/fonts/`
**Deliverable:** Two CDN roundtrips removed from `<head>`. App still renders
with Inter (self-hosted, woff2, weights 400/600/700 only) or system stack.
**Risk:** Low — verify font fallback chain renders cleanly if you choose
the system-stack path.

### Session 3 — Lazy-load canvas-confetti (S)
**Goal:** Stop shipping ~10KB of confetti to every page. Move the `<script>`
out of `templates/base.html` and `import()` it from
`static/js/countdown.js` only when a milestone is about to fire.
**Files:** `templates/base.html`, `static/js/countdown.js`
**Deliverable:** Network tab shows confetti only loading when a milestone
fires. Existing milestone test still passes (visual check).
**Risk:** Low.

### Session 4a — Build SVG icon macro + first sweep (M)
**Goal:** Create a `templates/_icon.html` macro that emits inline SVGs for
the ~15 Bootstrap Icons in use. Sweep half the templates (`base`,
`trips_list`, `trip_overview`, `trip_card`, `bookings_list`, `booking_form`).
**Files:** new `templates/_icon.html`, 6 swept templates
**Deliverable:** All `<i class="bi bi-*">` in swept files replaced with
`{{ icon('name') }}`. Bootstrap Icons font still loaded — old icons
unaffected.
**Risk:** Low — additive; old `<i class="bi">` still works until 4b.

### Session 4b — Finish icon sweep + remove Bootstrap Icons font (M)
**Goal:** Sweep the remaining templates (`trip_itinerary`, `trip_packing`,
`trip_budget`, `trip_share`, `trip_form`, `login`, `drift_*`). Remove the
Bootstrap Icons CDN `<link>` from base.html.
**Files:** ~8 templates, `templates/base.html`
**Deliverable:** Zero `<i class="bi">` references remain (grep proves it).
Page weight drops by ~80KB.
**Risk:** Medium — missing one icon leaves a blank. Grep before removing
the font link.

### Session 5 — Tighten heading semantics (S)
**Goal:** Promote section "headings" that are currently styled spans
(`.today-section-day`, `.vp-section-title` on dashboard groups) to real
`<h2>`/`<h3>` elements.
**Files:** `templates/trip_overview.html`, `templates/trips_list.html`,
`static/css/app.css`
**Deliverable:** Heading outline is clean on every page (verify with browser
a11y inspector). Visual appearance unchanged.
**Risk:** Low.

---

## Phase 2 — Forms & flows

### Session 6 — Inline form validation (M)
**Goal:** Surface per-field errors with `is-invalid` + `.invalid-feedback`
+ `aria-invalid`, in addition to the existing top-of-form summary.
**Files:** `app.py` (route handlers for `trip_new/edit`, `booking_new/edit`,
`share_add`), `templates/trip_form.html`, `templates/booking_form.html`,
`templates/trip_share.html`, `templates/itinerary_form.html`,
`templates/packing_form.html`
**Deliverable:** Routes pass `field_errors: dict[str, str]` to templates.
Templates render per-field feedback. Server validation tests still pass.
**Risk:** Medium — touches every form route. Consider extracting a tiny
`{% macro field_error(name) %}` helper.

### Session 7 — Primary action on the right (S)
**Goal:** Reorder form footers to put the primary button on the right
(platform convention).
**Files:** 5 form templates (trip, booking, itinerary, packing, share)
**Deliverable:** "Cancel ··· Save" on every form. CSS already supports it
(`d-flex gap-2`); just reorder the markup.
**Risk:** Low.

### Session 8 — Branded confirm dialog (M)
**Goal:** Replace every `onsubmit="return confirm(...)"` with a reusable
`<dialog>`-based confirm. Native, no library.
**Files:** new `templates/_confirm_dialog.html`, new
`static/js/confirm.js`, sweep all templates with `onsubmit="return confirm"`
(trip_overview, bookings_list, trip_itinerary, trip_packing, trip_share)
**Deliverable:** Grep for `window.confirm` and `onsubmit="return confirm`
returns zero results. Destructive actions open a branded dialog. Escape
closes it. Focus returns to the trigger.
**Risk:** Medium — focus management and keyboard handling need care; verify
with keyboard only.

---

## Phase 3 — Scannability

These are all small and independent — pick any order.

### Session 9 — Day-N-of-M on active-trip cards (S)
**Goal:** Replace the generic "Active" pill on in-progress trip cards with
"Day 3 of 7".
**Files:** `templates/_trip_card.html`, possibly a new helper in
`src/trip_helpers.py` + test in `tests/test_trip_helpers.py`
**Deliverable:** Active trips show day progress; tests cover the helper.
**Risk:** Low.

### Session 10 — Budget per-category bars (S)
**Goal:** Add a thin (4px) horizontal bar under each category in
`trip_budget` showing its share of the trip's primary-currency total.
**Files:** `templates/trip_budget.html`, `static/css/app.css`, helper
update in `src/budget.py` + test
**Deliverable:** Visible at-a-glance share per category. Multi-currency
rows degrade gracefully (no bar if no primary-currency total).
**Risk:** Low.

### Session 11 — Per-category packing progress (S)
**Goal:** Add "3/7 packed" subhead to each category group on the packing
page.
**Files:** `templates/trip_packing.html`, helper update in `src/packing.py`
+ test
**Deliverable:** Each `.packing-group-title` shows category-level progress
alongside the count.
**Risk:** Low.

### Session 12 — Per-day itinerary counts (S)
**Goal:** Add "5 items · 4h scheduled" subhead to each day-column header
in the itinerary.
**Files:** `templates/trip_itinerary.html`, helper in `src/itinerary.py`
(sum durations) + test
**Deliverable:** Each `.day-column-header` shows count + total duration.
Items without times don't contribute hours.
**Risk:** Low.

---

## Phase 4 — Navigation & mobile

### Session 13 — Bookings filter chips (S)
**Goal:** Above the grouped bookings list, render toggleable chips (All /
✈ Flights / 🏨 Hotels / 🚗 Cars / 🍽 Dining / 🎟 Activities). Use a
`?type=flight` URL param so the view is shareable.
**Files:** `templates/bookings_list.html`, `app.py` `bookings_list` route,
`static/css/app.css`
**Deliverable:** Clicking a chip filters the list and updates the URL.
**Risk:** Low.

### Session 14 — Trip switcher in nav (M)
**Goal:** When on a trip page, expose a "Trips ▾" dropdown in the navbar
listing the user's other trips (recent 5 + "All trips" link). Pure CSS
dropdown (no Bootstrap JS).
**Files:** `templates/base.html`, `app.py` (context processor for nav
trips), `static/css/app.css`
**Deliverable:** Dropdown opens on click, closes on outside-click and
Escape, keyboard accessible.
**Risk:** Medium — keyboard nav and focus trapping in a dropdown have edge
cases.

### Session 15 — Mobile day-picker for itinerary (M)
**Goal:** On viewports below ~768px, replace the day-column grid with a
horizontally-scrollable day chip bar (1, 2, 3 … N) above a single-column
view of the selected day.
**Files:** `templates/trip_itinerary.html`, `static/css/app.css`, new tiny
script in `static/js/itinerary.js`
**Deliverable:** A 14-day trip is browsable on iPhone without an infinite
vertical scroll. Desktop unchanged.
**Risk:** Medium — responsive testing needed; consider keyboard left/right
arrow support.

---

## Phase 5 — Delight

### Session 16 — Active-trip ribbon (S)
**Goal:** When the user has any trip with status `in_progress`, render a
thin coral bar above the navbar on every page: "🏝️ Italy Honeymoon — Day
3 — Open today's plan →"
**Files:** `templates/base.html`, `app.py` (context processor returning
the active trip, if any), `static/css/app.css`
**Deliverable:** Ribbon appears only when relevant. Dismissible per-session
via localStorage (optional).
**Risk:** Low.

### Session 17 — Dark mode (M)
**Goal:** Add a `data-theme="dark"` block in `:root[data-theme=dark]`
defining dark-palette values for every `--vp-*` token. Add a theme toggle
(☀/🌙) in the navbar; persist in localStorage; respect
`prefers-color-scheme` on first load.
**Files:** `static/css/app.css`, `templates/base.html`, new
`static/js/theme.js`
**Deliverable:** App is fully usable in dark mode. No element renders
against an unintended background (Session 1 prerequisite is exactly why
this is possible).
**Risk:** Medium — every color decision in Session 1 will be revisited;
expect to discover tokens you missed.

### Session 18 — "What changed since last visit" banner (M)
**Goal:** On the trip overview, when there are new bookings or itinerary
items since the user last viewed this trip, render a banner: "Sarah added
2 bookings and 1 itinerary item since your last visit".
**Files:** `models.py` (add `last_seen_at` column to either
`TripCollaborator` or a new `TripView` table), `app.py` (`trip_overview`
route updates `last_seen_at` after rendering; query for newer rows),
`templates/trip_overview.html`
**Deliverable:** Owner and collaborators see what's new on return. Initial
visit shows nothing.
**Risk:** Medium-High — schema change. Project uses `create_all` on
bootstrap (no Alembic per CLAUDE.md). Plan to back up `vacation.db` before
running.

### Session 19 — Trip cover photo (M)
**Goal:** Add `cover_image_url` column to `Trip`. Render it as a soft
backdrop on the dashboard trip card and behind the trip overview header.
**Files:** `models.py`, `app.py` (trip form parse), `src/trip_helpers.py`
(`parse_trip_form` validation — URL only, no upload),
`templates/trip_form.html`, `templates/_trip_card.html`,
`templates/trip_overview.html`, `static/css/app.css`
**Deliverable:** Optional image URL field on the trip form. Cards and
overview render the photo dimmed behind the emoji/text with a CSS gradient
overlay for legibility.
**Risk:** Medium-High — schema change again. Decide validation rules
(allowed domains? max length? lazy-loading attribute on `<img>`).

---

## Rough total
**19 sessions** across 5 phases — mostly S/M, no true L. Estimate **6–10
working windows** depending on how you batch the small sessions. Budget
padding for: dark-mode token discovery (Session 17), schema migrations
(Sessions 18 & 19), and responsive testing (Session 15).

## Suggested sequencing
- **Week 1:** Phase 1 (Sessions 1–5) — the foundation everything else
  builds on. Do these in order.
- **Week 2:** Phase 2 (Sessions 6–8) — forms feel measurably better
  immediately.
- **Week 3:** Phase 3 (Sessions 9–12) — pick any order, batch 2 small ones
  per sitting.
- **Week 4:** Phase 4 (Sessions 13–15) — navigation polish.
- **Week 5:** Phase 5 (Sessions 16–19) — save the big-personality items
  for last when the foundation is solid. **Do Session 17 only after
  Session 1.**

## How to run each session

Each session is its own fresh Claude Code window. The workflow:

1. **Start** the session with the prompt provided at the bottom of the
   previous session's wrap-up (or, for Session 1, the prompt in
   `docs/ui_redesign_session1_prompt.md`).
2. **Work** the session: read the relevant files, propose a concrete plan,
   wait for approval, implement, test.
3. **Test thoroughly** before claiming done: `pytest tests/` for the unit
   tests, and a manual browser pass on the affected pages.
4. **Commit** with a single focused commit message.
5. **End** the session by producing two things in chat:
   - **a) Completion summary** — 2–4 sentences in plain English: what
     changed, what was tested, anything to watch.
   - **b) Next-session prompt** — a self-contained block I can paste into
     a fresh Claude Code window to start the next session. Include: the
     plan file path, the session number + name, the goal, the files,
     the deliverable, the testing bar, and the end-of-session protocol
     (this list).
6. **Check off** the box below.
7. **Close** the window and open a fresh one for the next session.

## Progress tracking

- [x] 1. Heal the token leak
- [x] 2. Self-host Inter + inline critical CSS
- [x] 3. Lazy-load canvas-confetti
- [x] 4a. Build SVG icon macro + first sweep
- [x] 4b. Finish icon sweep + remove Bootstrap Icons font
- [x] 5. Tighten heading semantics
- [ ] 6. Inline form validation
- [ ] 7. Primary action on the right
- [ ] 8. Branded confirm dialog
- [ ] 9. Day-N-of-M on active-trip cards
- [ ] 10. Budget per-category bars
- [ ] 11. Per-category packing progress
- [ ] 12. Per-day itinerary counts
- [ ] 13. Bookings filter chips
- [ ] 14. Trip switcher in nav
- [ ] 15. Mobile day-picker for itinerary
- [ ] 16. Active-trip ribbon
- [ ] 17. Dark mode
- [ ] 18. What changed since last visit
- [ ] 19. Trip cover photo
