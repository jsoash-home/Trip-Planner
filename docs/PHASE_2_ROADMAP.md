# Vacation Planner — Phase 2 Roadmap

> **Status:** Vision document. Captures the six phase-2 features in depth so
> nothing about the plan can be lost. Detailed TDD implementation plans live
> in `docs/superpowers/plans/` and are written one at a time, just before
> each feature is built.

## How to use this document

- This roadmap is **the source of truth for what phase 2 means**.
- Each feature has a short executable plan written when you're ready to
  build it. See the table below for the current status.
- Pick the next feature from the ordering section, then ask Claude (or
  yourself) to "write the plan for trip duplication" / "write the plan
  for pre-trip checklist" / etc.
- When a feature ships, mark it ✓ in the status column and link the
  plan that built it.

## Status table

| # | Feature                               | Effort         | Status      | Plan |
|---|---------------------------------------|----------------|-------------|------|
| 6 | Trip duplication                      | small          | not started | [2026-05-22-trip-duplication.md](superpowers/plans/2026-05-22-trip-duplication.md) |
| 1 | Pre-trip checklist                    | medium         | not started | _to be written_ |
| 4 | Public read-only share links          | small-medium   | not started | _to be written_ |
| 3 | Email notifications                   | medium         | not started | _to be written_ |
| 2 | Document storage with file upload     | large          | not started | _to be written_ |
| 5 | Map view of pinned locations          | large          | not started | _to be written_ |

The numbering follows the README; the row order is the **recommended build
order** (see "Ordering rationale" below).

---

## The six features, in depth

### #6 — Trip duplication

**What it is.** A "Duplicate" button on the trip overview page. Click it,
pick a new start date (and optionally a new name), and you get a brand-new
trip owned by you with every booking, itinerary item, and packing item
copied across — with all the dates shifted by the offset between the old
and new start date. Collaborators are not copied. The new trip's status
resets to "planning".

**Why it's first.** It's the smallest of the six. It touches code you
already understand (Trip / Booking / ItineraryItem / PackingItem). It does
not introduce a new model, a new external service, or a new UI pattern.
The whole feature can be expressed as one route + a handful of pure
"clone these fields with dates shifted" helpers + a tiny form. It's a
high-confidence first build to warm up the phase-2 branch.

**What code to mirror.** The route shape is just like `trip_new()` at
[app.py:488](../app.py) — parse a form, build a Trip row, flush, populate
child rows, commit, redirect. Access control uses the same
`_trip_with_access_or_404` helper every other trip route uses.

**Key design decisions.**
- **Who can duplicate?** Any role with read access (owner / editor / viewer).
  Duplicating gives you your *own* copy — it's effectively "fork as a
  template," which is useful even for someone who only has view access to
  the source trip.
- **Auto-itinerary on copied bookings?** No. We copy itinerary items
  directly; we do NOT re-trigger `auto_itinerary_items_for_booking()` on
  the new bookings. Otherwise we'd end up with duplicate Depart/Arrive
  chips on top of the user's existing items. The `linked_booking_id` on
  copied itinerary items is remapped to point at the corresponding new
  booking via a dict.
- **What gets reset on the copy?** `packed=False` on every packing item;
  `status="planning"` on the trip; collaborators dropped; `confirmation_number`
  on bookings cleared (those are specific to the original reservation).
- **What does not get reset?** Notes, locations, vendors, titles, costs,
  itinerary categories — all assumed reusable as a template.

**Dependencies.** None. Can be built today against the v1 codebase.

**See:** [superpowers/plans/2026-05-22-trip-duplication.md](superpowers/plans/2026-05-22-trip-duplication.md)
for the executable TDD plan.

---

### #1 — Pre-trip checklist (visa / vaccines / currency)

**What it is.** A new section on each trip for "things to handle before
you leave." Items like "Apply for Schengen visa," "Get yellow fever shot,"
"Order €500 in euros." Each item has a title, a done-checkbox, optional
notes, and an optional due date so the dashboard can surface "due soon"
items.

**Why second.** It mirrors the packing list almost exactly — a new model
with a `trip_id` foreign key, a small pure helpers module, a form, a
template, a section tile on the overview. The packing list (see
[src/packing.py](../src/packing.py)) is the template; this feature is
mostly a careful copy-and-rename. It's the highest payoff-per-effort
feature in phase 2, and it gives you a second model class to practice
the pattern on before you take on anything genuinely new.

**What code to mirror.**
- Model: copy the shape of `PackingItem` in [models.py:172](../models.py)
  — add `due_date` (nullable Date) and rename `packed → done`.
- Pure helpers: copy [src/packing.py](../src/packing.py) wholesale to
  `src/checklist.py`. Replace `PACKING_CATEGORIES` with checklist categories
  (e.g. `documents`, `health`, `money`, `bookings`, `other`).
- Default items: a `DEFAULT_CHECKLIST_ITEMS` tuple analogous to
  `DEFAULT_PACKING_ITEMS`. Seed on trip creation in `_seed_default_packing`'s
  sibling.
- Routes: copy the packing routes — `checklist_list`, `checklist_new`,
  `checklist_edit`, `checklist_delete`, `checklist_toggle`.
- Templates: copy `packing_form.html` → `checklist_form.html`,
  `trip_packing.html` → `trip_checklist.html`. Update the section-tile
  builder in [app.py](../app.py) to add a checklist tile.

**Key design decisions.**
- **Categories.** Suggested: `documents` (visa, ESTA, ID), `health`
  (vaccines, prescriptions), `money` (currency, cards, travel insurance),
  `bookings` (confirm flight check-in, reconfirm hotel), `other`. Confirm
  with the user before building.
- **Due dates.** Optional. When present, the checklist section sorts
  overdue items first, then by due date ascending, then by category.
  When absent, the item goes at the bottom of its category.
- **Default seed.** Universal items every traveler needs: "Passport valid 6+
  months past trip end," "Check visa requirements for destination," "Notify
  bank of travel dates," "Photocopy passport." Probably 6–10 items.
- **Does trip duplication carry checklist items?** Yes, and reset `done=False`
  on each — same pattern as packing. This is one reason trip duplication
  is being built first: the duplication code needs to be updated whenever
  a new trip-child model appears, so getting the duplication pattern
  cemented before more child models exist keeps each addition small.

**Dependencies.** None on phase-2 work. Builds on v1 patterns.

---

### #4 — Public read-only share links

**What it is.** A trip owner can generate a magic URL like
`/share/<token>` that anyone can open without logging in to view the trip
read-only. Bookings, itinerary, packing list, budget — all visible; no
edit, delete, add, or share controls rendered. Owner can revoke the link
(rotates the token, old link 404s).

**Why third.** It's small in code volume but the *security* matters. It's
the first feature in this project where the access guard isn't just
"is this user a collaborator." Building it third means the access pattern
is in place before email notifications need a "view link" to include.

**What code to mirror.** The access guard is the centerpiece. Look at
`_trip_with_access_or_404` in [app.py](../app.py) — the new public route
needs an analogous but *much* tighter helper: `_trip_by_token_or_404` that
loads a trip by token, asserts `share_enabled=True`, and returns it
without any role concept. Then every read-only template needs to know
"are we in public mode" so we don't render edit chrome.

**Key design decisions.**
- **Model change.** Add to `Trip`: `share_token` (String, unique, nullable,
  indexed) and `share_enabled` (Boolean, default False). Token is generated
  with `secrets.token_urlsafe(24)` — long enough to be unguessable.
- **Toggle UI.** On the existing `trip_share.html` page, add a section
  above the collaborators list: "Public link," with a toggle, the current
  link (copyable), and a "Rotate link" button that generates a new token
  (invalidating the old).
- **The public route.** `GET /share/<token>` — no `@login_required`. Loads
  the trip, sets `public_view=True` in the template context, renders
  `trip_overview.html` with a banner ("You're viewing a shared trip — read
  only"). The template needs to suppress every edit/delete/add link when
  `public_view` is truthy.
- **Public sub-pages.** Each subsection (bookings, itinerary, packing,
  budget) needs an equivalent public route — `/share/<token>/bookings`,
  etc. — that loads the trip by token and renders the same template with
  `public_view=True`. Or, simpler: just do the overview public for v1 and
  add subsections in a follow-up. Decide during planning.
- **What's NOT shown in public mode.** Collaborator emails (privacy),
  booking URLs (might contain auth tokens), and the "Share" button itself.
- **Token rotation.** When the owner clicks "Rotate," generate a fresh
  token. Log the rotation so we can debug "I shared a link and now it
  doesn't work" (yes, because you rotated it).

**Dependencies.** None hard. Email notifications (#3) will want to include
a public link in the email body, so doing this before #3 is convenient.

---

### #3 — Email notifications when collaborators add things

**What it is.** When a collaborator on a trip adds a booking, an itinerary
item, or a packing item, email the *other* collaborators and the owner so
they know something changed. The email links back to the trip (and to the
public share link if enabled, so non-logged-in family members can preview
the change).

**Why fourth.** Medium effort but adds the first external service to the
project, which means new failure modes (API down, rate limits, deliverability)
and the first piece of code that runs *outside the request/response cycle*
(unless we send synchronously). Doing it after share links means we have
something useful to put in the email.

**What code to mirror.** Nothing in v1 sends email. This is genuinely new.
The closest analogue is the `auto_itinerary_items_for_booking` hook in
[app.py:668](../app.py) — that's the pattern for "when a thing is created,
fire off a side effect." Email notifications follow the same shape: at the
end of the create handler, after commit, call a `notify_collaborators(...)`
function.

**Key design decisions.**
- **Email service.** Three reasonable choices:
  - **Resend** — small, developer-friendly, generous free tier. Recommended
    for v1.
  - **Postmark** — best deliverability, costs money sooner.
  - **SendGrid** — most "enterprise," more complex API, free tier exists
    but has a lower sending limit.
  Pick during planning. Add `RESEND_API_KEY` to `.env.example` and document.
- **Synchronous or async?** v1: synchronous. Each create handler sends the
  email inline after commit. This means a slow email API blocks the user's
  POST. Acceptable trade-off for a beginner project (no Celery / no Redis
  / no worker process) but document it as a known limit. Async with a job
  queue is a future improvement.
- **What events trigger an email?**
  - Booking created (not edited — too noisy)
  - Itinerary item created (not edited)
  - Packing item created? Probably not — too noisy.
  - Collaborator added (sent only to the new collaborator: "Jeff added you
    to 'Scandinavia 26'")
- **Who receives it?** Everyone on the trip *except the person who made
  the change*. So a trip with owner + 2 editors: editor A adds a booking,
  the owner and editor B both get an email; editor A does not.
- **Opt-out.** Add a `email_notifications` boolean on `User` (default
  True) so individuals can mute. v1: a single global toggle per user, not
  per-trip preferences.
- **Rate limiting / batching.** Out of scope for v1. If a user adds 30
  bookings in 5 minutes they will trigger 30 emails per other-collaborator.
  Document it and consider digest mode as a future enhancement.
- **Email rendering.** Plain text v1. Subject: "Jeff added a booking to
  Scandinavia 26"; body: a few lines + a link to the trip + a link to the
  public share view if `share_enabled`.

**Dependencies.** Soft dep on #4 — the email is much better if it can
include a public link for recipients who haven't signed in.

---

### #2 — Document storage with file upload

**What it is.** Attach files to a trip: passport PDFs, hotel confirmation
emails saved as PDF, ticket screenshots, insurance docs. List them per
trip with download links. Delete supported.

**Why fifth.** It's the first feature whose complexity isn't "more rows
in a table." It introduces real binary storage, MIME validation, size
limits, and a forked storage strategy (local disk in dev, object storage
in prod). The risk is real — an upload feature done badly is an attack
surface. Worth doing after the lighter features are out of the way so
this can get the careful attention it needs.

**What code to mirror.** No existing analogue. This is the biggest
"new pattern" feature in phase 2.

**Key design decisions.**
- **Model.** `Document` table with: id, trip_id FK, original_filename
  (display only), stored_filename (UUID-prefixed, on-disk name),
  content_type (MIME), size_bytes, uploaded_by_user_id, created_at, notes.
- **Storage.** Two backends, picked by env var:
  - Local: `DATA_DIR/uploads/<trip_id>/<stored_filename>`. Gitignored.
  - Cloud: S3 (or compatible — Backblaze B2, R2). New env vars:
    `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`.
  An abstraction layer (`src/storage.py`) hides which backend is in use.
- **Upload constraints.**
  - Max size: 10 MB per file (configurable via `MAX_UPLOAD_MB`).
  - MIME allowlist: PDF, JPEG, PNG, HEIC, plain text. Reject everything
    else.
  - Filename sanitization: strip path separators; preserve extension; the
    stored filename is `<uuid4>.<ext>` so two users can both upload
    `passport.pdf` without colliding.
- **Download.** A route `/trips/<id>/documents/<doc_id>/download` that
  checks trip access, looks up the document, streams the file with
  `Content-Disposition: attachment`. Public share mode: documents are
  NOT exposed (we don't want a leaked share link to expose passport
  scans).
- **Delete.** Editor+ can delete. Removes the row and the underlying file
  (both backends).
- **Storage limits per trip / user.** v1: none. Document it.
- **Trip duplication.** Documents are NOT copied — they're tied to a
  specific instance of the trip, not the template (you don't want your
  2024 boarding pass on your 2026 trip).
- **Audit trail.** `uploaded_by_user_id` lets the trip view show "Jeff
  uploaded passport.pdf on 2026-05-01."

**Dependencies.** Trip duplication code must be aware that documents
don't get copied (one extra line; just a "skip documents" comment in the
duplication loop).

---

### #5 — Map view of pinned locations

**What it is.** A map embedded on the trip overview showing pins for
every booking and itinerary item that has a location. Click a pin to see
the booking / item title and time. Possibly an "itinerary day" filter to
show only one day's pins at a time.

**Why last.** Large effort. New external service (Mapbox or Google Maps).
Geocoding free-text location strings ("Eiffel Tower, Paris" → lat/lng) is
imprecise — a percentage of locations will geocode wrong and the user has
to be able to correct them. New caching concerns (geocoding API calls
cost money and we don't want to re-geocode "Paris" 50 times). New
frontend complexity (a third-party JS map widget on a Bootstrap page).
Doing it last means the rest of phase 2 isn't blocked on this getting
right.

**What code to mirror.** Nothing local. The booking and itinerary models
already have a `location` (String) field — that's the input to geocoding.

**Key design decisions.**
- **Provider.** Mapbox: better free tier (50k loads/month) and a clean
  static-image API for thumbnails. Google Maps is more familiar to users
  but the billing model is harsher and requires a card on file from day
  one. Recommend Mapbox for v1.
- **Geocoding.** Two columns on `Booking` and `ItineraryItem`:
  `geocoded_lat` (Float, nullable), `geocoded_lng` (Float, nullable),
  `geocoded_at` (DateTime, nullable). When a location string changes, the
  geocode is invalidated (set all three to NULL) and re-geocoded on next
  page render (or via a "Refresh map" button — don't geocode on every
  request).
- **Cache.** Geocoded lat/lng is stored on the row, so it's already
  cached. Add a separate `GeocodeCache` table keyed by the *normalized
  location string* (lowercased, stripped) so two bookings to "Eiffel
  Tower" share one geocode lookup. Especially useful for restaurants on
  the same street.
- **Map widget.** Mapbox GL JS. Render a small map on the trip overview
  and a bigger one on a new `/trips/<id>/map` page. Pins color-coded by
  type (booking type or itinerary category — pick one).
- **Manual override.** Geocoding will get some locations wrong. Add a
  "Pin location manually" interaction: user drags the pin to the right
  spot, lat/lng saved to the row, `geocoded_at` set to NULL to mark it as
  "human-pinned, do not re-geocode."
- **Privacy in public share mode.** Map shown, locations not redacted
  (locations are inherently in the booking title for restaurants/hotels
  anyway).

**Dependencies.** Soft: document upload (#2) might want to attach
location to photos for "where was this taken" — but that's a v3 thing,
not a blocker.

---

## Ordering rationale

The recommended order, top to bottom: **6, 1, 4, 3, 2, 5.**

The principles in priority order:

1. **Confidence first, novelty later.** Build features that reuse
   existing patterns before features that introduce new patterns. New
   patterns = new failure modes. Get the v1 muscle warmed up before
   asking it to do new things.
2. **Cement the trip-duplication pattern before adding new child
   models.** Every new trip-child model (checklist items, documents) is
   a thing trip duplication must know how to copy. The duplication code
   is simpler when there are fewer models to copy. Build it once with the
   v1 child models, then update it (1 line per new model) as features
   land.
3. **Build dependencies before dependents.** Public share links (#4) is
   a soft dependency of email notifications (#3) — the email is more
   useful with a public link to include. Document storage (#2) is a
   soft dependency of trip duplication's "what not to copy" rules
   (already accounted for).
4. **Save the largest-risk features for last.** Map view and document
   upload both touch external services with cost / security implications.
   Doing them after the lighter wins means they get attention they
   deserve.

If you want to deviate, the safe deviations are:

- **Swap #4 and #3.** Building email first is fine; the link in the email
  just temporarily can't include a public preview. Add it after #4 lands.
- **Pull #5 (map) earlier.** Risky — the geocoding accuracy work will eat
  time. But if the map is the feature you actually *want*, do it
  earlier — phase 2 is a hobby project, not a release plan.

Avoid these deviations:

- **#2 (document upload) before #6 (duplication).** You'd build the
  duplication code with documents-as-a-child-model in mind, but
  duplication's contract on documents ("don't copy them") is the
  simplest possible. No real win, and you've taken on the largest
  feature first.

---

## Updating this document

This roadmap is checked into the repo. When you finish a feature:

1. Mark its row in the status table as ✓ and link the plan that built it.
2. If your understanding of the feature changed during the build (almost
   always happens), update the feature's section here.
3. Commit with `docs: update phase-2 roadmap after <feature> shipped`.

When you start a new feature, ask Claude to write the executable plan
for it. The new plan goes in `docs/superpowers/plans/`, dated, and gets
linked from the status table here.

This document does not get deleted when phase 2 finishes. It becomes the
historical record of how phase 2 was scoped, what was built, and what
got reshaped along the way.
