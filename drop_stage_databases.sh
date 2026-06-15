#!/usr/bin/env bash
# drop_stage_databases.sh
#
# Connects to a MongoDB Atlas cluster and drops every database whose name
# starts with "stage" (case-insensitive).
#
# Usage:
#   ATLAS_URI="******cluster.mongodb.net" ./drop_stage_databases.sh
#
# Or pass the connection string as the first argument:
#   ./drop_stage_databases.sh "******cluster.mongodb.net"
#
# Set DRY_RUN=1 to list matching databases without dropping them:
#   DRY_RUN=1 ATLAS_URI="..." ./drop_stage_databases.sh
#
# Intended to be scheduled via cron (see README.md).

set -euo pipefail

# ── Connection string ──────────────────────────────────────────────────────────
ATLAS_URI="${1:-${ATLAS_URI:-}}"
DRY_RUN="${DRY_RUN:-0}"

if [[ -z "$ATLAS_URI" ]]; then
  echo "ERROR: MongoDB Atlas connection string not provided." >&2
  echo "Set the ATLAS_URI environment variable or pass it as the first argument." >&2
  exit 1
fi

# ── Dependency check ───────────────────────────────────────────────────────────
if ! command -v mongosh &>/dev/null; then
  echo "ERROR: 'mongosh' is not installed or not in PATH." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/logs/drop_stage_databases.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" | tee -a "$LOG_FILE"
}

log "Starting drop_stage_databases – listing databases on cluster…"
[[ "$DRY_RUN" == "1" ]] && log "DRY_RUN mode – no databases will be dropped."

# ── Retrieve databases that start with "stage" (case-insensitive) ─────────────
# Exit code is captured separately so set -e does not mask mongosh errors.
STAGE_DBS=""
if ! STAGE_DBS=$(mongosh "$ATLAS_URI" --quiet --eval '
  db.adminCommand({ listDatabases: 1 })
    .databases
    .map(d => d.name)
    .filter(n => /^stage/i.test(n))
    .join("\n")
' 2>&1); then
  log "ERROR: mongosh failed to list databases. Output: $STAGE_DBS"
  exit 1
fi

# Guard against mongosh returning an error message instead of a database list.
# Valid MongoDB database names contain only alphanumeric chars, hyphens,
# underscores, and dots – reject anything else.
VALID_DBS=""
while IFS= read -r db_name; do
  [[ -z "$db_name" ]] && continue
  if [[ ! "$db_name" =~ ^[a-zA-Z0-9_\.\-]+$ ]]; then
    log "WARNING: Skipping unexpected value '$db_name' (not a valid database name)."
    continue
  fi
  VALID_DBS+="${db_name}"$'\n'
done <<< "$STAGE_DBS"

# Remove trailing newline
VALID_DBS="${VALID_DBS%$'\n'}"

if [[ -z "$VALID_DBS" ]]; then
  log "No databases starting with 'stage' found. Nothing to drop."
  exit 0
fi

log "Databases to drop:"
while IFS= read -r db_name; do
  log "  - $db_name"
done <<< "$VALID_DBS"

if [[ "$DRY_RUN" == "1" ]]; then
  log "DRY_RUN: exiting without dropping any databases."
  exit 0
fi

# ── Drop each database ─────────────────────────────────────────────────────────
# The database name has been validated above to contain only safe characters,
# making direct interpolation into the eval string safe.
while IFS= read -r db_name; do
  log "Dropping database: $db_name"
  if mongosh "$ATLAS_URI" --quiet --eval "db.getSiblingDB('${db_name}').dropDatabase()" >> "$LOG_FILE" 2>&1; then
    log "Dropped: $db_name"
  else
    log "ERROR: Failed to drop database '$db_name'. See log for details."
  fi
done <<< "$VALID_DBS"

log "drop_stage_databases complete."
