#!/bin/bash
# Backs up vacation.db to ~/Backups/vacation-planner/ with a timestamp,
# then keeps only the 30 most recent backups.
#
# Run manually:   bash scripts/backup_db.sh
# Or via launchd: scheduled automatically (see com.jeffs.vacation-planner.backup.plist)

# `set -e` makes the script stop immediately if any command fails,
# so a half-broken backup won't quietly succeed.
set -e

# Where the live database lives (resolved relative to this script's location,
# so the script works no matter what folder you run it from).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SOURCE_DB="$PROJECT_DIR/vacation.db"

# Where backups will be stored, and how many to keep.
BACKUP_DIR="$HOME/Backups/vacation-planner"
KEEP_COUNT=30

# Bail out early if the source DB doesn't exist (e.g. fresh install).
if [ ! -f "$SOURCE_DB" ]; then
    echo "[backup] no database found at $SOURCE_DB — nothing to back up"
    exit 0
fi

# Make sure the backup folder exists. -p means "don't error if it's already there".
mkdir -p "$BACKUP_DIR"

# Build a timestamped filename like vacation_2026-05-01_18-00-00.db
TIMESTAMP="$(date +%Y-%m-%d_%H-%M-%S)"
BACKUP_FILE="$BACKUP_DIR/vacation_${TIMESTAMP}.db"

# Use sqlite3's .backup command instead of `cp`. This is the SAFE way:
# it cooperates with anything currently writing to the DB so the backup
# can never end up half-written or corrupted.
sqlite3 "$SOURCE_DB" ".backup '$BACKUP_FILE'"

echo "[backup] wrote $BACKUP_FILE"

# Rotation: list backups newest-first, skip the first KEEP_COUNT, delete the rest.
# `ls -1t` = one per line, sorted by modification time, newest first.
# `tail -n +N` = print starting from line N (so +31 skips the 30 newest).
cd "$BACKUP_DIR"
OLD_BACKUPS=$(ls -1t vacation_*.db 2>/dev/null | tail -n +$((KEEP_COUNT + 1)) || true)

if [ -n "$OLD_BACKUPS" ]; then
    echo "$OLD_BACKUPS" | while read -r old; do
        rm -f "$old"
        echo "[backup] pruned $old"
    done
fi

echo "[backup] done — $(ls -1 vacation_*.db 2>/dev/null | wc -l | tr -d ' ') backup(s) on disk"
