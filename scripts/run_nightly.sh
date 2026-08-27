#!/usr/bin/env bash
# Cron entry point. Collect, then verify the collection actually happened, and
# only then report success.
#
# The ping is gated on `nh status --check`, not on `nh nightly`'s exit code.
# `nh nightly` exits 0 when a ported source is skipped for want of credentials —
# a green ping there would mean "the process ran", which is not the same as "we
# collected anything", and is exactly how a pipeline dies quietly for a week.
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"

ping_hc /start
log "nightly starting"

uv run nh nightly
collect_rc=$?

uv run nh status --check
check_rc=$?

# Bounded retention for bulk raw payloads. Deliberately non-fatal: failing to
# reclaim disk is not a reason to report the night as lost.
uv run nh prune >> logs/prune.log 2>&1 || log "prune failed (non-fatal)"

if [ $collect_rc -eq 0 ] && [ $check_rc -eq 0 ]; then
  log "nightly ok"
  ping_hc
  exit 0
fi

log "nightly FAILED (collect=$collect_rc check=$check_rc)"
alert "niche-hunter nightly failed (collect=$collect_rc check=$check_rc) — see logs/nightly.log"
ping_hc /fail
exit 1
