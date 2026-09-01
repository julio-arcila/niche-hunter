#!/usr/bin/env bash
# The restore drill, as a command rather than a ritual.
#
# "Restored from backup once, for real" is a Slice 1 exit criterion. Making it
# repeatable is what turns it into something you can keep proving, and it is what
# Slice 8 automates on a schedule.
#
#   scripts/restore_check.sh            # newest local (iCloud) backup
#   scripts/restore_check.sh --offsite  # newest B2 object, downloaded first
#
# **The --offsite arm is the one that proves something new.** A local restore
# tests gzip and SQLite; it does not test that the remote copy exists, is
# complete, is readable with the key we actually hold, or that the endpoint and
# bucket in .env are the ones data is going to. Those are the failure modes a
# second destination exists to cover, and they are exactly the ones an untested
# offsite copy hides — a bucket can accept 266MB every Sunday for a year and
# still be unopenable on the day it matters.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -e

SCRATCH="$(mktemp -d -t nh_restore)"
trap 'rm -rf "$SCRATCH"' EXIT

if [ "${1:-}" = "--offsite" ]; then
  [ -n "${NH_B2_BUCKET:-}" ] || { log "no B2 bucket configured"; exit 1; }
  b2() { AWS_ACCESS_KEY_ID="$NH_B2_KEY_ID" AWS_SECRET_ACCESS_KEY="$NH_B2_APP_KEY" \
         AWS_DEFAULT_REGION="${NH_B2_REGION:-us-east-005}" \
         /usr/local/bin/aws "$@" --endpoint-url "https://${NH_B2_ENDPOINT}"; }
  KEY="$(b2 s3 ls "s3://$NH_B2_BUCKET/weekly/" | awk '{print $4}' | sort | tail -1)"
  [ -n "$KEY" ] || { log "no objects under s3://$NH_B2_BUCKET/weekly/"; exit 1; }
  LATEST="$SCRATCH/$KEY"
  log "downloading b2://$NH_B2_BUCKET/weekly/$KEY"
  b2 s3 cp "s3://$NH_B2_BUCKET/weekly/$KEY" "$LATEST" --only-show-errors
else
  DEST="${NH_BACKUP_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/niche-hunter-backups}"
  LATEST="$(find "$DEST" -name 'niche_hunter_*.db.gz' -print0 2>/dev/null | xargs -0 ls -t 2>/dev/null | head -1)"
  [ -n "$LATEST" ] || { log "no backups found in $DEST"; exit 1; }
fi

gunzip -c "$LATEST" > "$SCRATCH/restored.db"

log "restoring $LATEST"
/usr/bin/sqlite3 "$SCRATCH/restored.db" "PRAGMA integrity_check;" | grep -qx ok || {
  log "RESTORE FAILED: integrity check did not pass"; exit 1; }

NH_DATABASE_URL="sqlite:///$SCRATCH/restored.db" uv run nh doctor
echo
NH_DATABASE_URL="sqlite:///$SCRATCH/restored.db" uv run nh status --days 30 || true

# Contents, not just openability. `integrity_check` returns ok for a perfectly
# valid EMPTY database — the same trap `backup_db.sh` documents — so a restore
# that proves only "it opens" proves the one thing that was never in doubt.
snaps="$(/usr/bin/sqlite3 "$SCRATCH/restored.db" 'SELECT count(*) FROM video_snapshots;' 2>/dev/null || echo 0)"
tabs="$(/usr/bin/sqlite3 "$SCRATCH/restored.db" "SELECT count(*) FROM sqlite_master WHERE type='table';")"
[ "$snaps" -gt 0 ] && [ "$tabs" -ge 20 ] || {
  log "RESTORE FAILED: restored db has $tabs tables and $snaps snapshots"; exit 1; }

# Logged, not just printed. "A drill, performed, twice" is a criterion, and a drill
# whose only trace is a terminal someone has since closed cannot evidence it —
# `nh criteria` reads this file. Appended so the series accumulates.
result="restore drill passed for $(basename "$LATEST") ($tabs tables, $snaps snapshots)"
[ "${1:-}" = "--offsite" ] && result="$result [offsite b2://]"
log "$result"
log "$result" >> "$NH_ROOT/logs/restore.log"
