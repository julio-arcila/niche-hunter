#!/bin/bash
# Wait for the YouNiverse video dump, then run Gate E end to end.
#
# Aborts rather than continues on any failure: a backtest built on a truncated
# corpus or a half-loaded database produces a number, and a number is worse than
# nothing here because it will be believed.
set -uo pipefail
cd /Users/mac/Projects/youtube/niche-hunter
export NH_DATABASE_URL="sqlite:///data/backtest.db"

FILE=data/youniverse/yt_metadata_en.jsonl.gz
EXPECTED=13636127630
EXPECTED_MD5=0514b2ee52ffaa2c9c27c539038feb60
LOG_DIR="$(dirname "$0")"

say() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { say "ABORT: $*"; exit 1; }

# ---- 1. wait for the download -------------------------------------------
say "waiting for $FILE to reach $EXPECTED bytes"
stall=0
while true; do
  size=$(stat -f%z "$FILE" 2>/dev/null || echo 0)
  [ "$size" -ge "$EXPECTED" ] && break
  if pgrep -f "yt_metadata_en.jsonl.gz" >/dev/null 2>&1; then
    stall=0
  else
    # curl gone but file short: a dropped connection. curl was invoked with
    # `-C -`, so resuming is the same command again; do not silently proceed.
    stall=$((stall + 1))
    [ "$stall" -ge 3 ] && die "downloader exited at $size of $EXPECTED bytes. Resume with the same curl -C - command, then re-run this script."
  fi
  sleep 120
done
say "download complete: $(stat -f%z "$FILE") bytes"

# ---- 2. verify it ---------------------------------------------------------
# Five minutes of hashing against 5.2 hours of scanning a corrupt file.
say "verifying md5 (a few minutes)"
actual=$(md5 -q "$FILE")
[ "$actual" = "$EXPECTED_MD5" ] || die "md5 mismatch: got $actual, want $EXPECTED_MD5"
say "md5 ok"

# ---- 3. the chain ---------------------------------------------------------
run() {
  local name=$1; shift
  say "START $name"
  if ! "$@" >"$LOG_DIR/gate_e_$name.log" 2>&1; then
    tail -30 "$LOG_DIR/gate_e_$name.log"
    die "$name failed — see $LOG_DIR/gate_e_$name.log"
  fi
  say "DONE $name"
  tail -12 "$LOG_DIR/gate_e_$name.log"
}

run scan   uv run nh backtest scan
run load   uv run nh backtest load
run replay uv run nh backtest replay --start 2015-07-01 --end 2019-03-01
run score  uv run nh backtest score --start 2015-07-01 --end 2019-03-01

say "GATE E COMPLETE"
