"""Lightweight pre-flight snapshot of the SQLite database.

Called at app startup. If `vacation.db` exists and the most recent
snapshot in `data/backups/` is older than `max_age_hours`, copy the
live DB to a timestamped file there. Then prune older snapshots beyond
`keep`.

No-op when the app is running on Postgres / a non-SQLite URL, or when
the DB file doesn't exist yet (first run). All failures are logged at
WARNING — a backup that doesn't take should never crash the app.
"""

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_HOURS = 6
DEFAULT_KEEP = 20
SNAPSHOT_PREFIX = "vacation-"
SNAPSHOT_SUFFIX = ".db"
TIMESTAMP_FMT = "%Y-%m-%d-%H%M%S"


def snapshot_sqlite_db_if_due(
    db_path: Path,
    backup_dir: Path,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    keep: int = DEFAULT_KEEP,
    now: Optional[datetime] = None,
) -> Optional[Path]:
    """
    Create a snapshot of db_path if no recent one exists.

    Returns the new snapshot path on success, or None when nothing was
    created (source missing, recent snapshot already present, or copy
    failed).
    """
    moment = now if now is not None else datetime.now()

    if not db_path.exists():
        logger.debug("snapshot skipped: %s does not exist yet", db_path)
        return None

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.warning("could not create backup dir %s: %s", backup_dir, e)
        return None

    latest = _latest_snapshot(backup_dir)
    if latest is not None:
        latest_time = _parse_snapshot_time(latest)
        if latest_time is not None:
            age = moment - latest_time
            if age < timedelta(hours=max_age_hours):
                logger.debug(
                    "snapshot skipped: latest %s is only %s old",
                    latest.name, age,
                )
                return None

    ts = moment.strftime(TIMESTAMP_FMT)
    dest = backup_dir / f"{SNAPSHOT_PREFIX}{ts}{SNAPSHOT_SUFFIX}"
    try:
        shutil.copy2(db_path, dest)
        logger.info("created DB snapshot %s", dest)
    except OSError as e:
        logger.warning("failed to snapshot %s -> %s: %s", db_path, dest, e)
        return None

    _prune_old_snapshots(backup_dir, keep=keep)
    return dest


def _list_snapshots(backup_dir: Path) -> List[Path]:
    if not backup_dir.exists():
        return []
    snaps = [
        p for p in backup_dir.iterdir()
        if p.is_file()
        and p.name.startswith(SNAPSHOT_PREFIX)
        and p.name.endswith(SNAPSHOT_SUFFIX)
    ]
    # Filename embeds the timestamp, so lexical sort == chronological sort.
    snaps.sort(key=lambda p: p.name)
    return snaps


def _latest_snapshot(backup_dir: Path) -> Optional[Path]:
    snaps = _list_snapshots(backup_dir)
    return snaps[-1] if snaps else None


def _parse_snapshot_time(path: Path) -> Optional[datetime]:
    name = path.name[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
    try:
        return datetime.strptime(name, TIMESTAMP_FMT)
    except ValueError:
        logger.warning("snapshot %s has unparseable timestamp", path.name)
        return None


def _prune_old_snapshots(backup_dir: Path, keep: int) -> None:
    snaps = _list_snapshots(backup_dir)
    excess = len(snaps) - keep
    if excess <= 0:
        return
    for old in snaps[:excess]:
        try:
            old.unlink()
            logger.info("pruned old DB snapshot %s", old.name)
        except OSError as e:
            logger.warning("failed to prune %s: %s", old, e)
