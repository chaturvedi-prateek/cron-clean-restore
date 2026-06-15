#!/usr/bin/env bash
# restore_databases.sh
#
# Launches a separate mongorestore process (via nohup) for every sub-directory
# found inside BACKUP_DIR.  Each sub-directory is assumed to be a database dump
# created by mongodump (directory name = target database name).
#
# Usage:
#   ATLAS_URI="******cluster.mongodb.net" \
#   BACKUP_DIR="/path/to/dump" \
#   ./restore_databases.sh
#
# Or pass both values as positional arguments:
#   ./restore_databases.sh "******cluster.mongodb.net" "/path/to/dump"
#
# WARNING: DROP MODE (default: disabled)
#   Set DROP_EXISTING=1 to pass --drop to mongorestore, which DELETES all
#   existing documents in each collection before restoring.  Use with caution.
#   DROP_EXISTING=1 ATLAS_URI="..." BACKUP_DIR="..." ./restore_databases.sh
#
# Intended to be scheduled via cron (see README.md).

set -euo pipefail

# Arguments / environment variables
ATLAS_URI="${1:-${ATLAS_URI:-}}"
BACKUP_DIR="${2:-${BACKUP_DIR:-}}"
DROP_EXISTING="${DROP_EXISTING:-0}"

if [[ -z "$ATLAS_URI" ]]; then
  echo "ERROR: MongoDB Atlas connection string not provided." >&2
  echo "Set the ATLAS_URI environment variable or pass it as the first argument." >&2
  exit 1
fi

if [[ -z "$BACKUP_DIR" ]]; then
  echo "ERROR: Backup directory not provided." >&2
  echo "Set the BACKUP_DIR environment variable or pass it as the second argument." >&2
  exit 1
fi

if [[ ! -d "$BACKUP_DIR" ]]; then
  echo "ERROR: Backup directory '$BACKUP_DIR' does not exist." >&2
  exit 1
fi

if ! command -v mongorestore &>/dev/null; then
  echo "ERROR: 'mongorestore' is not installed or not in PATH." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "$LOG_DIR"

MASTER_LOG="${LOG_DIR}/restore_databases.log"

log() {
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$MASTER_LOG"
}

log "Starting restore_databases – scanning '$BACKUP_DIR' for database dumps…"

if [[ "$DROP_EXISTING" == "1" ]]; then
  log "WARNING: DROP_EXISTING=1 – existing collections will be dropped before restore."
fi

shopt -s nullglob
DB_DIRS=("$BACKUP_DIR"/*/)

if [[ ${#DB_DIRS[@]} -eq 0 ]]; then
  log "No sub-directories found in '$BACKUP_DIR'. Nothing to restore."
  exit 0
fi

RESTORE_FLAGS=()
[[ "$DROP_EXISTING" == "1" ]] && RESTORE_FLAGS+=("--drop")

PIDS=()
for DB_PATH in "${DB_DIRS[@]}"; do
  DB_NAME="$(basename "${DB_PATH%/}")"
  DB_LOG="${LOG_DIR}/restore_${DB_NAME}.log"

  log "Launching mongorestore for database '${DB_NAME}' → log: ${DB_LOG}"

  nohup mongorestore \
    --uri="$ATLAS_URI" \
    --db="$DB_NAME" \
    --dir="$DB_PATH" \
    "${RESTORE_FLAGS[@]}" \
    >> "$DB_LOG" 2>&1 &

  PID=$!
  # Brief sleep to allow the process to fail fast if there is an immediate error
  sleep 0.2
  if ps -p "$PID" > /dev/null 2>&1; then
    PIDS+=("$PID")
    log "  PID $PID – restoring '$DB_NAME'"
  else
    log "  WARNING: mongorestore for '$DB_NAME' failed to start (PID $PID not running)."
  fi
done

if [[ ${#PIDS[@]} -eq 0 ]]; then
  log "No mongorestore processes were launched successfully."
  exit 1
fi

log "All mongorestore processes launched. PIDs: ${PIDS[*]}"
log "Monitor individual logs in: $LOG_DIR"

# Uncomment the block below to wait for all restores before the script exits
# (useful when the restore cron job must finish before a subsequent job runs):
#
# log "Waiting for all restore processes to finish…"
# for PID in "${PIDS[@]}"; do
#   wait "$PID" && log "PID $PID finished successfully." \
#                || log "WARNING: PID $PID exited with an error."
# done
# log "All restore processes have completed."

exit 0
