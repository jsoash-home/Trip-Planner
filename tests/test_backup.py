"""Unit tests for src/backup.py."""

from datetime import datetime, timedelta
from pathlib import Path

from src.backup import (
    DEFAULT_KEEP,
    SNAPSHOT_PREFIX,
    SNAPSHOT_SUFFIX,
    TIMESTAMP_FMT,
    snapshot_sqlite_db_if_due,
)


# ─────────────────────────────  helpers  ─────────────────────────────


def _make_db(path: Path, content: bytes = b"PRETEND-SQLITE") -> None:
    path.write_bytes(content)


def _make_snapshot(backup_dir: Path, when: datetime, content: bytes = b"snap") -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = when.strftime(TIMESTAMP_FMT)
    p = backup_dir / f"{SNAPSHOT_PREFIX}{ts}{SNAPSHOT_SUFFIX}"
    p.write_bytes(content)
    return p


# ─────────────────────────────  source missing  ─────────────────────


def test_returns_none_when_db_does_not_exist(tmp_path):
    db = tmp_path / "vacation.db"  # not created
    backup_dir = tmp_path / "backups"

    result = snapshot_sqlite_db_if_due(db, backup_dir)

    assert result is None
    # Should not create the backup dir for a no-op.
    assert not backup_dir.exists()


# ─────────────────────────────  fresh first backup  ─────────────────


def test_creates_first_snapshot_when_none_exist(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"REAL-DB")
    backup_dir = tmp_path / "backups"

    now = datetime(2026, 6, 9, 12, 0, 0)
    result = snapshot_sqlite_db_if_due(db, backup_dir, now=now)

    assert result is not None
    assert result.exists()
    assert result.parent == backup_dir
    assert result.name == "vacation-2026-06-09-120000.db"
    assert result.read_bytes() == b"REAL-DB"


def test_creates_backup_dir_if_missing(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db)
    backup_dir = tmp_path / "nested" / "backups"  # parents don't exist

    result = snapshot_sqlite_db_if_due(db, backup_dir, now=datetime(2026, 1, 1, 0, 0, 0))

    assert result is not None
    assert backup_dir.is_dir()


# ─────────────────────────────  age gating  ─────────────────────────


def test_skips_when_recent_snapshot_exists(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"

    # A snapshot from 1 hour ago — well under the 6-hour default.
    now = datetime(2026, 6, 9, 12, 0, 0)
    _make_snapshot(backup_dir, now - timedelta(hours=1), content=b"OLD")

    result = snapshot_sqlite_db_if_due(db, backup_dir, max_age_hours=6, now=now)

    assert result is None
    # Existing snapshot must not be touched.
    snaps = list(backup_dir.iterdir())
    assert len(snaps) == 1
    assert snaps[0].read_bytes() == b"OLD"


def test_snapshots_when_latest_is_older_than_window(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"

    now = datetime(2026, 6, 9, 12, 0, 0)
    _make_snapshot(backup_dir, now - timedelta(hours=7), content=b"STALE")

    result = snapshot_sqlite_db_if_due(db, backup_dir, max_age_hours=6, now=now)

    assert result is not None
    assert result.name == "vacation-2026-06-09-120000.db"
    assert result.read_bytes() == b"NEW"


def test_custom_max_age_zero_always_snapshots(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"
    now = datetime(2026, 6, 9, 12, 0, 0)
    _make_snapshot(backup_dir, now - timedelta(minutes=1))

    result = snapshot_sqlite_db_if_due(db, backup_dir, max_age_hours=0, now=now)

    assert result is not None


# ─────────────────────────────  pruning  ────────────────────────────


def test_prunes_to_keep_limit(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"

    now = datetime(2026, 6, 9, 12, 0, 0)
    # Seed 5 older snapshots, then take a 6th. keep=3 → final state has 3.
    for hours_ago in (50, 40, 30, 20, 10):
        _make_snapshot(backup_dir, now - timedelta(hours=hours_ago))

    result = snapshot_sqlite_db_if_due(db, backup_dir, max_age_hours=6, keep=3, now=now)

    assert result is not None
    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert len(remaining) == 3
    # The newest 3 should survive: the 20h-ago, 10h-ago, and the just-created one.
    assert remaining[-1] == "vacation-2026-06-09-120000.db"


def test_does_not_prune_when_under_keep_limit(tmp_path):
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"
    now = datetime(2026, 6, 9, 12, 0, 0)

    # Only one stale snapshot exists; keep default is well above 2.
    _make_snapshot(backup_dir, now - timedelta(hours=24))
    snapshot_sqlite_db_if_due(db, backup_dir, now=now)

    assert len(list(backup_dir.iterdir())) == 2  # old + new


def test_unparseable_snapshot_name_is_ignored_for_age_check(tmp_path):
    """A leftover file in the backup dir with a bad name shouldn't block snapshots."""
    db = tmp_path / "vacation.db"
    _make_db(db, b"NEW")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Matches prefix/suffix but timestamp is junk.
    (backup_dir / "vacation-not-a-timestamp.db").write_bytes(b"junk")

    now = datetime(2026, 6, 9, 12, 0, 0)
    result = snapshot_sqlite_db_if_due(db, backup_dir, now=now)

    # When the latest snapshot's timestamp is unparseable, treat it as "no
    # recent snapshot" and proceed.
    assert result is not None


# ─────────────────────────────  defaults sanity  ────────────────────


def test_default_keep_is_a_reasonable_number():
    # If somebody bumps DEFAULT_KEEP to a wild value, fail loudly.
    assert 5 <= DEFAULT_KEEP <= 100
