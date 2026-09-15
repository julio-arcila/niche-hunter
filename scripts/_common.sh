#!/usr/bin/env bash
# Shared prelude for the cron entry points. Source this, don't run it.
#
# `mkdir -p logs` happens HERE rather than in the crontab line. A redirect into a
# missing directory is how the four auto-helpdesk jobs on this machine died
# silently — cron could not even write the error that would have told anyone.
set -uo pipefail

NH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$NH_ROOT" || exit 1
mkdir -p logs

# uv lives in /usr/local/bin; cron's PATH has neither that nor the login shell's
# additions. sqlite3 is pinned to /usr/bin below because the first match on an
# interactive PATH here is miniconda's, which cron will not have.
export PATH="/usr/local/bin:/usr/bin:/bin"

# .env values are quoted (see .env.example) precisely so this is safe.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

log()   { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

alert() {  # fail-soft push; alerting must never be what breaks the job
  [ -n "${NH_NTFY_TOPIC:-}" ] &&
    curl -fs -m 5 -d "$1" "https://ntfy.sh/${NH_NTFY_TOPIC}" >/dev/null 2>&1 || true
}

wait_for_network() {  # bounded; returns 1 and lets the caller run anyway
  # 2026-09-13 the Mac woke late and `nh nightly` fired before DNS was up: the first
  # search.list died with ConnectionError and the night was recorded as failed — one
  # collection short, unrecoverably, for want of thirty seconds. Any HTTP answer at all
  # counts as "up" (no -f): reachability is the question, not a 200. Bounded at ten
  # minutes so a wait can never push a late start far past the 19:00-local observed_date
  # boundary; past the bound the caller proceeds, the collector records the failure and
  # the gate pages, which is the correct outcome and better than a silent skip.
  local i
  for i in $(seq 1 40); do
    if curl -s -m 10 -o /dev/null https://www.googleapis.com/ 2>/dev/null; then
      [ "$i" -gt 1 ] && log "network up after $(( (i - 1) * 15 ))s"
      return 0
    fi
    [ "$i" -eq 1 ] && log "network unreachable; waiting up to 10 min"
    sleep 15
  done
  log "network still unreachable after 10 min; running anyway so the failure is recorded"
  return 1
}

ping_hc() {  # $1 = "" | /start | /fail | /<exit-code>
  [ -n "${NH_HEALTHCHECK_URL:-}" ] &&
    curl -fsS -m 10 --retry 3 "${NH_HEALTHCHECK_URL}${1:-}" >/dev/null 2>&1 || true
}
