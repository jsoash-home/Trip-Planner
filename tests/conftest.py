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
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
