# Vacation Planner

A Flask web app for planning, running, and remembering trips. Multiple
trips can be in flight at once, finished trips become history, and each
trip is shareable with specific people by Google email.

Built using the same patterns as `stock-tracker` so the two apps feel
familiar to work on together.

## What's in v1

- Google OAuth login (any Google account)
- Multiple trips per user, with cover emoji, dates, destination
- Bookings (flights, hotels, cars, activities, restaurants, transport)
- Day-by-day itinerary with timed items
- Smart booking → itinerary auto-link (a hotel booking auto-creates
  "Check in" / "Check out" entries on the right days)
- Budget rollup derived from booking costs
- Packing list with smart defaults
- Per-trip sharing by email (viewer / editor)
- "Today" view that surfaces today's schedule when you're on the trip

## Phase 2 (not yet built)

- Pre-trip checklist (visa / vaccines / currency)
- Document storage with file upload
- Email notifications when collaborators add things
- Public read-only share links
- Map view of pinned locations
- Trip duplication (copy a past trip as a template)

## Setup

```bash
cd "Vacation Planner"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
# fill in SECRET_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET in .env
python app.py
```

Then open http://localhost:5002 and log in with Google.

## Tests

```bash
pytest tests/
```

## Deploy

The app is deploy-ready but not yet deployed. Before deploying:

1. **Remove** `os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"` from
   `app.py`. It exists for localhost HTTP only and will break OAuth on
   any HTTPS host (Railway, Render, Fly).
2. Set `SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
   `DATABASE_URL` (Postgres) as environment variables on the host.
3. Add the deployed domain's `/login/google/authorized` URL to the
   Google OAuth client's "Authorized redirect URIs".
