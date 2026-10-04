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

# --- wait for the nightly, and hold the Mac awake while waiting (ADR-0067) ---------
#
# The 09:40 cron slot is 30 minutes after the nightly starts, and the nightly has never
# finished by then: measured 2026-09-22..10-04, it ends 10:17-10:50 on an ordinary night
# and ran to 12:53 on 10-01. So `.backup` and `gzip` of a 5.8GB database have overlapped
# clustering and features EVERY night, and on 2026-09-23 features took 62 minutes against
# a usual 18-26 while this script held the disk.
#
# Moving the cron line to 11:00 would trade that for a worse failure. `pmset -g custom`
# reads `sleep 1` on AC as well as battery, the nightly's own `caffeinate` ends when
# `nh nightly` exits, and **cron silently skips a fire the Mac sleeps through** — which is
# exactly how 2026-08-30 was lost. An 11:00 slot would sit after the machine was free to
# doze off again.
#
# So the slot stays at 09:40, inside the nightly's awake window, and the backup WAITS for
# the nightly to finish — holding the Mac awake itself while it does, by re-execing under
# `caffeinate`. The baton passes from one awake window to the next with no gap for sleep.
#
# Bounded, because a frozen nightly must not mean no backup at all: past the bound this
# backs up anyway, and the bracket check below is what makes a mid-run copy honest rather
# than a failure. 150 minutes from 09:40 is 12:10 — 10-01's 12:53 run would have exceeded
# it and been copied mid-features, which is exactly the case the bracket covers.
WAIT_MINUTES="${NH_BACKUP_WAIT_MINUTES:-150}"

# Re-exec under caffeinate unless already inside it. `-i` holds off idle sleep and is
# honoured on battery; `-s` holds off system sleep and is honoured only on AC (ADR-0063
# measured both). The guard variable rather than `pgrep caffeinate`: this must not be
# fooled by the nightly's own caffeinate, or by the four-minute ones some other tool on
# this machine runs.
# `/bin/bash "$0"` rather than `"$0"` alone: re-execing the path directly would need the
# executable bit, which the crontab line happens to rely on anyway (mode 755) but which a
# `bash scripts/backup_db.sh` invocation does not. A backup that silently dies with
# "Permission denied" because someone copied the file without its mode is not a failure
# this script should be able to have. Caught by a test harness whose heredoc produced a
# 644 copy.
if [ -z "${NH_BACKUP_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null 2>&1; then
  export NH_BACKUP_CAFFEINATED=1
  # Resolved absolutely, because `_common.sh` has already `cd`-ed to NH_ROOT: a relative
  # `$0` from anywhere else is gone by the time we get here. Reproduced from the parent
  # directory — `bash niche-hunter/scripts/backup_db.sh` died with "No such file or
  # directory" and took the night's backup with it. The crontab uses an absolute path, so
  # production was never exposed; a hand-run from the wrong directory was.
  exec caffeinate -i -s /bin/bash "$NH_ROOT/scripts/backup_db.sh" "$@"
fi

wait_for_nightly() {
  # `pgrep -f` on the command the launchd agent runs. Matching "nh nightly" rather than a
  # pid file because nothing writes one, and a stale pid file is the class of lie this
  # script already lost a night to.
  local waited=0
  pgrep -qf 'nh nightly' || return 0
  log "nightly still running; waiting up to ${WAIT_MINUTES} min"
  while pgrep -qf 'nh nightly'; do
    if [ "$waited" -ge "$WAIT_MINUTES" ]; then
      log "nightly still running after ${waited} min; backing up anyway (the bracket covers it)"
      alert "niche-hunter backup: nightly still running after ${waited} min, copying anyway"
      return 0
    fi
    sleep 60
    waited=$((waited + 1))
  done
  log "nightly finished; waited ${waited} min"
}
wait_for_nightly

# Local window. Was 30, set when a backup was 26MB; at 2026-09-01 a backup is
# 266MB and growing ~58MB/day, which trends to ~32GB of iCloud. 14 matches
# `nh prune`'s raw-payload retention, so the two windows move together, and it
# is the point past which the daily series stops earning its storage — the
# weekly offsite copy below is what covers anything older.
#
# 7 since 2026-09-15 (Slice 8's "shorten the window", which read open until then).
# Measured that day: the database is 2.7 GB and the folder held 13 files, 7.5 GB;
# the window's total grows by roughly KEEP_DAYS times the nightly delta, so at 14
# it was heading for ~24 GB and climbing ~1.7 GB/night. The coupling to `nh prune`
# is deliberately broken: a restore more than seven days back uses the weekly B2
# copy, which is what it is for. NH_BACKUP_KEEP_DAYS in .env still overrides this.
KEEP_DAYS="${NH_BACKUP_KEEP_DAYS:-7}"
# Weekly offsite copies retained. Four is a month of Sundays.
B2_KEEP="${NH_B2_KEEP:-4}"

_b2_prune() {  # keep the newest $B2_KEEP weekly objects, drop the rest
  local keys
  keys=$(AWS_ACCESS_KEY_ID="$NH_B2_KEY_ID" AWS_SECRET_ACCESS_KEY="$NH_B2_APP_KEY" \
         AWS_DEFAULT_REGION="${NH_B2_REGION:-us-east-005}" \
         /usr/local/bin/aws s3 ls "s3://$NH_B2_BUCKET/weekly/" \
           --endpoint-url "https://${NH_B2_ENDPOINT}" 2>/dev/null \
         | awk '{print $4}' | sort) || return 0
  local n; n=$(printf '%s\n' "$keys" | grep -c . || true)
  [ "$n" -gt "$B2_KEEP" ] || return 0
  printf '%s\n' "$keys" | head -n "$((n - B2_KEEP))" | while read -r old_key; do
    [ -n "$old_key" ] || continue
    AWS_ACCESS_KEY_ID="$NH_B2_KEY_ID" AWS_SECRET_ACCESS_KEY="$NH_B2_APP_KEY" \
    AWS_DEFAULT_REGION="${NH_B2_REGION:-us-east-005}" \
    /usr/local/bin/aws s3 rm "s3://$NH_B2_BUCKET/weekly/$old_key" \
      --endpoint-url "https://${NH_B2_ENDPOINT}" --only-show-errors \
      && log "offsite pruned $old_key" || true
  done
}
TMP="$(mktemp -t nh_backup)"
trap 'rm -f "$TMP"' EXIT
mkdir -p "$DEST"

# Both normalise anything that is not a plain integer to -1, which every
# comparison below rejects. The `|| echo -1` fallback alone is not enough: it
# fires on a nonzero exit, but a zero exit printing nothing would leave an empty
# string, and `[ "" -lt 1 ]` errors with "integer expression expected" instead of
# being false. An erroring test inside an `if` condition is exempt from `set -e`,
# so the guard would be skipped and the script would go on to call an unverified
# copy good — a silent pass, which is worse than the string comparison this
# replaced. Found in review, not in production.
_count() { local n; n=$(/usr/bin/sqlite3 "$1" "$2" 2>/dev/null) || n=-1
           case "$n" in '' | *[!0-9]*) n=-1 ;; esac; printf '%s' "$n"; }
tables()    { _count "$1" "SELECT count(*) FROM sqlite_master WHERE type='table';"; }
snapshots() { _count "$1" "SELECT count(*) FROM video_snapshots;"; }

# Bracket the copy instead of demanding equality with the source afterwards.
#
# `.backup` takes 15-25 minutes on a 4.9GB database, and the nightly writes
# `video_snapshots` for most of that window — RSS alone ran to 09:58 on
# 2026-09-24 against this script's 09:40 cron slot. Comparing a count read
# AFTER the copy against the copy itself therefore compares two different
# instants and fails on every night the collection overruns: measured
# 2,579,131 in the copy against 2,660,720 in the source, and three
# consecutive nights lost that way (2026-09-30, 10-01, 10-02), with the
# equality test passing before that only because RSS usually finished before
# the slot and the later collectors write no snapshot rows. Ordering luck.
#
# What makes a bracket sound rather than merely looser: `video_snapshots` is
# append-only and never pruned (data rules 4 and 5), so its count is monotone
# in time. A copy taken at any instant during the run must land between the
# count before the copy began and the count after it finished. The lower
# bound still catches the failure the header warns about: a backup of nothing
# scores 0 against a source above it. (The 113-byte incident itself is caught
# earlier, by the table check below — an empty database has no tables at all.
# `src_before > 0` is the belt to that braces, for a source that has tables
# and no snapshots.)
src_before="$(snapshots "$DB")"

/usr/bin/sqlite3 "$DB" ".backup '$TMP'"

src_after="$(snapshots "$DB")"

/usr/bin/sqlite3 "$TMP" "PRAGMA integrity_check;" | grep -qx ok || {
  log "FAILED integrity check — not writing it"
  alert "niche-hunter backup failed integrity check"; exit 1; }

src_t="$(tables "$DB")"; bak_t="$(tables "$TMP")"
bak_s="$(snapshots "$TMP")"
# A schema change is a migration, never concurrent with a backup, so tables
# still compare for equality.
if [ "$bak_t" -lt 1 ] || [ "$src_t" != "$bak_t" ]; then
  log "FAILED: backup does not match source (tables $src_t/$bak_t)"
  alert "niche-hunter backup content mismatch — NOT written"
  exit 1
fi
if [ "$src_before" -lt 1 ] || [ "$bak_s" -lt "$src_before" ] || [ "$bak_s" -gt "$src_after" ]; then
  log "FAILED: backup snapshots $bak_s outside [$src_before, $src_after] — NOT written"
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
find "$DEST" -name 'niche_hunter_*.db.gz' -mtime +$KEEP_DAYS -delete \
  || log "retention sweep failed (non-fatal) — backups are kept, not pruned"
log "backup ok -> $OUT ($(du -h "$OUT" | cut -f1), $bak_t tables, $bak_s snapshots in [$src_before, $src_after])"

# ---- offsite copy #2: somewhere that is not iCloud -------------------------
#
# The local backup and the database it protects are one Apple ID apart. This is
# the copy that survives a locked account, and it is deliberately WEEKLY and
# shallow: it is disaster recovery, not point-in-time recovery. iCloud stays the
# daily series.
#
# Silent no-op when unconfigured, so the script behaves identically on a machine
# with no B2 keys — the same posture as `alert()` and `ping_hc()`.
#
# `aws` rather than rclone or the b2 CLI: it is already on this machine, B2 is
# S3-compatible, and this repo does not add a dependency it can avoid. The
# credentials are scoped to the one command rather than exported, so they cannot
# leak into anything else this script runs and cannot collide with a real AWS
# profile the operator may have.
if [ -n "${NH_B2_BUCKET:-}" ] && [ -n "${NH_B2_KEY_ID:-}" ]; then
  if [ "$(date +%u)" = "7" ] || [ -n "${NH_B2_FORCE:-}" ]; then
    KEY="weekly/niche_hunter_$(date +%Y-%m-%d).db.gz"
    if AWS_ACCESS_KEY_ID="$NH_B2_KEY_ID" \
       AWS_SECRET_ACCESS_KEY="$NH_B2_APP_KEY" \
       AWS_DEFAULT_REGION="${NH_B2_REGION:-us-east-005}" \
       /usr/local/bin/aws s3 cp "$OUT" "s3://$NH_B2_BUCKET/$KEY" \
         --endpoint-url "https://${NH_B2_ENDPOINT}" --only-show-errors
    then
      log "offsite ok -> b2://$NH_B2_BUCKET/$KEY"
    else
      # Non-fatal for the same reason the retention sweep is: the night's
      # primary backup is already written and verified. A second-destination
      # failure is worth a push, not a red run.
      log "offsite copy FAILED (non-fatal) — local backup is intact"
      alert "niche-hunter: offsite backup to B2 failed"
    fi
    _b2_prune
  fi
fi
