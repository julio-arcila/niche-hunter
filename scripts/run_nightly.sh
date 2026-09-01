#!/usr/bin/env bash
# Cron entry point. Collect, then verify the collection actually happened, and
# only then report success.
#
# The ping is gated on `nh status --check`, not on `nh nightly`'s exit code.
# `nh nightly` exits 0 when a ported source is skipped for want of credentials —
# a green ping there would mean "the process ran", which is not the same as "we
# collected anything", and is exactly how a pipeline dies quietly for a week.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

# One-shot skip. `skip-once` is CONSUMED here whether or not anything else
# succeeds, so a skip cannot become a habit: the act of skipping removes the
# file, and the next cron fire collects normally. This is the safe form of
# "skip tonight" — commenting out the crontab line is the unsafe form, because
# nothing in the system ever reminds anyone to put it back (ADR-0039 is this
# repo's standing example of a change that silently did not take effect).
#
# Why it is ever needed: QuotaLedger's budget is per-RUN, not per-day. A manual
# `nh nightly` and the cron fire in the same Pacific quota day each believe they
# have the full 9,500, so the second one spends into Google's real daily cap and
# takes 403s partway through discovery.
SKIP_ONCE="$(dirname "${BASH_SOURCE[0]}")/../.skip-once"
if [ -f "$SKIP_ONCE" ]; then
  skip_reason="$(cat "$SKIP_ONCE" 2>/dev/null)"   # read BEFORE consuming it
  rm -f "$SKIP_ONCE"
  log "nightly SKIPPED once by request: ${skip_reason:-no reason recorded}; the next fire runs normally"
  ping_hc   # a deliberate skip is not a failure — do not page anyone
  exit 0
fi

ping_hc /start
log "nightly starting"

uv run nh nightly
collect_rc=$?

uv run nh status --check
check_rc=$?

# Bounded retention for bulk raw payloads. Deliberately non-fatal: failing to
# reclaim disk is not a reason to report the night as lost.
uv run nh prune >> logs/prune.log 2>&1 || log "prune failed (non-fatal)"

# The insight rules have written `alerts` rows since Slice 7 and nothing has ever
# read them: the table's only consumer was a web page nobody has open. This is the
# path from a rule firing to a person.
#
# Rule names and counts, never evidence — an alert is a citation surface (ADR-0045)
# and this one lands on a lock screen. `nh alerts` has the detail.
#
# Silent on a quiet night, by design: `--digest` prints nothing when nothing fired,
# so `-n` stays false and no push goes out. A digest that arrives every night is a
# digest nobody reads.
digest="$(uv run nh alerts --digest 2>/dev/null || true)"
if [ -n "$digest" ]; then
  log "alerts: $digest"
  alert "niche-hunter $(date +%F): $digest"
fi

if [ $collect_rc -eq 0 ] && [ $check_rc -eq 0 ]; then
  log "nightly ok"
  ping_hc
  exit 0
fi

log "nightly FAILED (collect=$collect_rc check=$check_rc)"
alert "niche-hunter nightly failed (collect=$collect_rc check=$check_rc) — see logs/nightly.log"
ping_hc /fail
exit 1
