"""Pytest configuration — global test isolation.

Sets DATABASE_URL to in-memory SQLite at MODULE IMPORT TIME, before any
test module imports the Flask app. This forces SQLAlchemy to bind its
engine to an ephemeral DB at app.py import, so tests can never read or
write the real vacation.db.

Why this lives in conftest.py and not in a fixture: by the time a
fixture runs, app.py has already been imported and its engine is
already bound. Changing app.config["SQLALCHEMY_DATABASE_URI"] later
mutates the config string but does NOT rebind the cached engine —
db.drop_all() / db.create_all() still hit whatever the engine was
originally pointed at (i.e. the real vacation.db). The only safe place
to redirect the engine is before the first app import, which conftest
guarantees by virtue of pytest loading it first.

The tripwire below imports the app once the env var is in place and
hard-fails the suite if the engine bound to anything other than an
in-memory DB. Defense in depth — the env var prevents the bug, the
tripwire detects it if prevention ever breaks.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"


# Tripwire: import the app NOW (with the env var safely set above) and
# verify SQLAlchemy bound to an in-memory database. If anything ever
# bypasses the env-var safeguard — a future test that imports app via
# an unusual path, a fixture that rebinds the engine, a stray script
# imported during collection — the entire test suite hard-fails here
# instead of silently writing to vacation.db.
from app import app as _flask_app  # noqa: E402

_uri = _flask_app.config.get("SQLALCHEMY_DATABASE_URI", "")
assert _uri.endswith(":memory:"), (
    "TEST TRIPWIRE FAILED: SQLAlchemy is bound to %r. Tests refuse to "
    "run against anything that isn't an in-memory database. Check that "
    "DATABASE_URL is not being overridden after this conftest loads, and "
    "that no module imports app.py before this file does." % _uri
)
