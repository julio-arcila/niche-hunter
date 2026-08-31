#!/usr/bin/env bash
# Nightly offsite backup of the snapshot history.
#
# `.backup` rather than `cp`: the database runs in WAL mode, so copying the file
# while anything holds a connection is a corruption lottery.
#
# Verification compares the backup's contents to the source. `PRAGMA
# integrity_check` alone is not enough — it returns "ok" for a perfectly valid
# EMPTY database, so it cannot distinguish a good backup from a backup of
# nothing. That is not hypothetical: an unset NH_DATABASE_URL once produced a
# 113-byte "successful" backup here, because `set -u` does not trip on
# ${VAR#pattern} and sqlite3 creates a database when handed an empty path.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
set -e

DB_URL="${NH_DATABASE_URL:-sqlite:///$NH_ROOT/data/niche_hunter.db}"
case "$DB_URL" in
  sqlite:///*) DB="${DB_URL#sqlite:///}" ;;
  *) log "FAILED: this script backs up SQLite only, got '$DB_URL'"
     alert "niche-hunter backup: unsupported database URL"; exit 1 ;;
esac
[ -s "$DB" ] || { log "FAILED: database missing or empty at '$DB'"
                  alert "niche-hunter backup: database missing at $DB"; exit 1; }

DEST="${NH_BACKUP_DIR:-$HOME/Library/Mobile Documents/com~apple~CloudDocs/niche-hunter-backups}"
TMP="$(mktemp -t nh_backup)"
trap 'rm -f "$TMP"' EXIT
mkdir -p "$DEST"

/usr/bin/sqlite3 "$DB" ".backup '$TMP'"

tables()   { /usr/bin/sqlite3 "$1" "SELECT count(*) FROM sqlite_master WHERE type='table';"; }
snapshots() { /usr/bin/sqlite3 "$1" "SELECT count(*) FROM video_snapshots;" 2>/dev/null || echo -1; }

/usr/bin/sqlite3 "$TMP" "PRAGMA integrity_check;" | grep -qx ok || {
  log "FAILED integrity check — not writing it"
  alert "niche-hunter backup failed integrity check"; exit 1; }

src_t="$(tables "$DB")"; bak_t="$(tables "$TMP")"
src_s="$(snapshots "$DB")"; bak_s="$(snapshots "$TMP")"
if [ "$bak_t" -lt 1 ] || [ "$src_t" != "$bak_t" ] || [ "$src_s" != "$bak_s" ]; then
  log "FAILED: backup does not match source (tables $src_t/$bak_t, snapshots $src_s/$bak_s)"
  alert "niche-hunter backup content mismatch — NOT written"
  exit 1
fi

OUT="$DEST/niche_hunter_$(date +%Y-%m-%d).db.gz"
# Checked explicitly, and the check is not paranoia — it is a regression this
# script actually shipped on 2026-08-30. A redirection failure does NOT reliably
# trip `set -e`, so when TCC denied this write (see the retention comment below)
# the script sailed past it and reported "backup ok -> ... (208M)" — the size
# came from `du` reading YESTERDAY'S file, still sitting at that path. A stale
# backup reported as a fresh one is the worst failure this script has, and it is
# the same class of lie the header warns about for `PRAGMA integrity_check`.
#
# Overwriting an EXISTING file in the TCC-protected destination is the operation
# that gets denied; creating a new one is allowed. Normal daily runs use a new
# date-stamped filename and are unaffected — this bites a same-day re-run.
if ! gzip -c "$TMP" > "$OUT"; then
  log "FAILED: could not write $OUT — the file at that path, if any, is STALE"
  alert "niche-hunter backup: could not write $OUT (stale file may remain)"
  exit 1
fi
# Belt and braces: prove the file we are about to call a backup was written by
# THIS run, not left behind by a previous one.
if [ ! -s "$OUT" ] || [ -n "$(find "$OUT" -mmin +10 2>/dev/null)" ]; then
  log "FAILED: $OUT is empty or was not written by this run"
  alert "niche-hunter backup: $OUT is empty or stale"
  exit 1
fi

# Rolling 30-day window, matching the retention pattern already in your crontab.
#
# Non-fatal, and the `|| log` is load-bearing rather than defensive: under cron
# this `find` cannot traverse iCloud Drive (TCC denies the unattended process,
# giving "Operation not permitted"), it exits non-zero, and `set -e` above then
# killed the script HERE — after the backup was safely written, but before the
# success line below. Measured 2026-08-29: a correct 150MB backup existed on
# disk while backup.log contained nothing but two find errors and no "backup ok"
# at all, so the log could not distinguish a good night from a total failure.
# Failing to reclaim disk is not a reason to report the night as lost — the same
# judgement `run_nightly.sh` already applies to `nh prune`.
find "$DEST" -name 'niche_hunter_*.db.gz' -mtime +30 -delete \
  || log "retention sweep failed (non-fatal) — backups are kept, not pruned"
log "backup ok -> $OUT ($(du -h "$OUT" | cut -f1), $bak_t tables, $bak_s snapshots)"
