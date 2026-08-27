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

ping_hc() {  # $1 = "" | /start | /fail | /<exit-code>
  [ -n "${NH_HEALTHCHECK_URL:-}" ] &&
    curl -fsS -m 10 --retry 3 "${NH_HEALTHCHECK_URL}${1:-}" >/dev/null 2>&1 || true
}
