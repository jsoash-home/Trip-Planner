#!/bin/bash
# Starts the Vacation Planner dev server, but first frees port 5002
# if a previous run left something behind. Save you the "Address already
# in use" dance every time.
#
# Run with:   ./scripts/dev.sh
#             (or: bash scripts/dev.sh)
#
# Stop the server normally with Ctrl+C in this terminal.

# `set -e` makes the script stop immediately if any command fails.
set -e

# Which port the Flask app listens on (defined in app.py).
PORT=5002

# Resolve the project directory from this script's own location, so the
# script works no matter what folder you run it from.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Step 1: free the port if it's being held by a leftover process ---
#
# `lsof -tiTCP:$PORT -sTCP:LISTEN` prints just the PIDs of anything
# currently *listening* on that port. The `-t` flag means "terse" —
# PIDs only, nothing else, which is exactly what `kill` wants as input.
HOLDERS="$(lsof -tiTCP:$PORT -sTCP:LISTEN || true)"

if [ -n "$HOLDERS" ]; then
    echo "[dev] port $PORT is held by PID(s): $HOLDERS — killing them"
    # `kill -9` = force-kill. Safe here because the only thing on this
    # port should be a previous run of *this same dev server*, and the
    # database is on disk, not in memory.
    echo "$HOLDERS" | xargs kill -9
    # Give the OS a moment to actually release the port.
    sleep 1
else
    echo "[dev] port $PORT is free"
fi

# --- Step 2: hop into the project, activate the virtualenv ---
cd "$PROJECT_DIR"

if [ ! -f ".venv/bin/activate" ]; then
    echo "[dev] no virtualenv found at .venv — run setup first (see README)"
    exit 1
fi

# shellcheck source=/dev/null
source .venv/bin/activate

# --- Step 3: clear any HTTP proxy variables ---
#
# If this script ever gets launched from an environment that has these
# set (e.g. a Cursor agent shell), they'd break Google OAuth at login
# time. Clearing them here is harmless under normal use and prevents
# that whole class of surprises.
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy

# --- Step 4: launch the app ---
#
# `exec` replaces this shell process with python, so when you hit
# Ctrl+C the signal goes straight to Flask and shuts it down cleanly.
echo "[dev] starting Flask on http://localhost:$PORT"
exec python app.py
