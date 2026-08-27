#!/usr/bin/env bash
# The restore drill, as a command rather than a ritual.
#
# "Restored from backup once, for real" is a Slice 1 exit criterion. Making it
# repeatable is what turns it into something you can keep proving, and it is what
# Slice 8 later automates on a schedule.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -e

DEST="${NH_BACKUP_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/niche-hunter-backups}"
LATEST="$(find "$DEST" -name 'niche_hunter_*.db.gz' -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1)"
[ -n "$LATEST" ] || { log "no backups found in $DEST"; exit 1; }

SCRATCH="$(mktemp -d -t nh_restore)"
trap 'rm -rf "$SCRATCH"' EXIT
gunzip -c "$LATEST" > "$SCRATCH/restored.db"

log "restoring $LATEST"
/usr/bin/sqlite3 "$SCRATCH/restored.db" "PRAGMA integrity_check;" | grep -qx ok || {
  log "RESTORE FAILED: integrity check did not pass"; exit 1; }

NH_DATABASE_URL="sqlite:///$SCRATCH/restored.db" uv run nh doctor
echo
NH_DATABASE_URL="sqlite:///$SCRATCH/restored.db" uv run nh status --days 30 || true
log "restore drill passed for $(basename "$LATEST")"
