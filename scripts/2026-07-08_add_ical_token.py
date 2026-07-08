#!/usr/bin/env python3
"""
scripts/2026-07-08_add_ical_token.py

One-off migration: adds the `ical_token` (VARCHAR(36)) column to the
`user` table in the production SQLite database. The column backs the
iCal calendar-feed feature (see docs/superpowers/plans/ for the
in-pocket implementation plan).

Usage:
    cd "/Users/jeff_s/Projects/Vacation Planner"

    # Review what will happen (default: interactive prompt):
    .venv/bin/python scripts/2026-07-08_add_ical_token.py

    # Non-interactive (CI / scripted):
    .venv/bin/python scripts/2026-07-08_add_ical_token.py --yes

    # Test against a throwaway copy:
    cp vacation.db /tmp/vacation_test.db
    .venv/bin/python scripts/2026-07-08_add_ical_token.py \\
        --db /tmp/vacation_test.db --yes
    rm /tmp/vacation_test.db

Rollback (SQLite 3.35+ required for DROP COLUMN):
    Check your version first:  sqlite3 --version
    Then:
        ALTER TABLE "user" DROP COLUMN ical_token;

Data-safety note: this script writes to vacation.db (or --db path).
A backup snapshot is taken before any change is made. The script is
idempotent: a second run exits cleanly if the column already exists.
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Make the project root importable so src/ is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backup import snapshot_sqlite_db_if_due  # noqa: E402

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "vacation.db"
BACKUP_DIR = PROJECT_ROOT / "data" / "backups"

# `user` is a reserved word in SQL — quote it everywhere.
TABLE_NAME = "user"
NEW_COLUMNS: Dict[str, str] = {
    "ical_token": "VARCHAR(36)",
}


def _list_columns(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute(f'PRAGMA table_info("{TABLE_NAME}")').fetchall()
    return [row[1] for row in rows]


def _missing_columns(conn: sqlite3.Connection) -> List[str]:
    existing = set(_list_columns(conn))
    return [name for name in NEW_COLUMNS if name not in existing]


def _take_backup(db_path: Path) -> Optional[Path]:
    """
    Force a snapshot of db_path into BACKUP_DIR regardless of age.

    Passes max_age_hours=0 so the recency check is always satisfied.
    Returns the new snapshot path, or None if the snapshot could not be made.
    """
    return snapshot_sqlite_db_if_due(
        db_path=db_path,
        backup_dir=BACKUP_DIR,
        max_age_hours=0,
    )


def _confirm_interactively(db_path: Path, missing: List[str]) -> bool:
    """Print a warning and return True only if the user types 'y'."""
    print()
    print(f"About to alter {db_path}")
    print(f"  Adding column(s) to '{TABLE_NAME}': {', '.join(missing)}")
    print("Proceed? [y/N] ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = ""
    return answer == "y"


def run_migration(db_path: Path, yes: bool) -> int:
    """
    Apply the migration.  Returns an exit code (0 = success, 1 = aborted).
    """
    if not db_path.exists():
        logger.warning("Database not found: %s", db_path)
        return 1

    # ── 1. Idempotency check ────────────────────────────────────────────
    conn = sqlite3.connect(db_path)
    try:
        missing = _missing_columns(conn)
        if not missing:
            logger.info(
                "Already migrated: columns %s all exist in table '%s'. Nothing to do.",
                list(NEW_COLUMNS),
                TABLE_NAME,
            )
            return 0

        before_count = len(_list_columns(conn))
    finally:
        conn.close()

    # ── 2. Backup snapshot (forced) ─────────────────────────────────────
    logger.info("Taking backup snapshot of %s …", db_path)
    snap = _take_backup(db_path)
    if snap is None:
        logger.warning(
            "Backup snapshot could not be created. Aborting out of caution. "
            "Check that data/backups/ is writable."
        )
        return 1
    logger.info("Snapshot saved: %s", snap)

    # ── 3. Confirmation ─────────────────────────────────────────────────
    if not yes:
        if not _confirm_interactively(db_path, missing):
            logger.info("Aborted by user.")
            return 1

    # ── 4. Apply migration inside a transaction ─────────────────────────
    logger.info("Applying migration (adding %d column(s)) …", len(missing))
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN")
        for name in missing:
            col_type = NEW_COLUMNS[name]
            conn.execute(
                f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN {name} {col_type}'
            )
        # Match the SQLAlchemy model's unique + index constraints. SQLite
        # can't add UNIQUE via ALTER, so we build a unique index instead;
        # UNIQUE INDEX satisfies both the uniqueness constraint and the
        # index=True hint that the model declares.
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS ix_user_ical_token '
            f'ON "{TABLE_NAME}" (ical_token)'
        )
        conn.execute("COMMIT")
        logger.info("Migration committed.")
    except sqlite3.Error as e:
        logger.warning("Migration failed, rolling back: %s", e)
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        return 1
    finally:
        conn.close()

    # ── 5. Summary ──────────────────────────────────────────────────────
    conn = sqlite3.connect(db_path)
    try:
        after_columns = _list_columns(conn)
        after_count = len(after_columns)
    finally:
        conn.close()

    logger.info(
        "Done. user table: %d column(s) → %d column(s). New columns: %s.",
        before_count,
        after_count,
        ", ".join(missing),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Add ical_token column to user table in vacation.db."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt.",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        default=str(DEFAULT_DB_PATH),
        help="Path to the SQLite database file (default: vacation.db).",
    )
    args = parser.parse_args()

    db_path = Path(args.db).resolve()
    return run_migration(db_path=db_path, yes=args.yes)


if __name__ == "__main__":
    sys.exit(main())
