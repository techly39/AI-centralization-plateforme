#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). The indefinite Builder loop.
#
#   Start:   loop/run_forever.sh            (run it in tmux/screen, or as a launchd job)
#   Stop:    touch governance/HALT          (the loop exits before the next cycle;
#                                            a running cycle stops at its next tool call)
#   Resume:  rm governance/HALT && loop/run_forever.sh
#
# Logs and counters live in $FIRM_HOME (default ~/.firm), outside the repo.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME/logs"

cfg() { uv run --quiet python loop/preflight.py --get "$1"; }

while true; do
  if [ -f governance/HALT ]; then echo "HALT present — loop exits."; exit 0; fi

  out="$(uv run --quiet python loop/preflight.py)"; rc=$?
  echo "$out"
  case $rc in
    0)  prompt="/cycle" ;;
    10) prompt="/cycle DIAGNOSIS MODE: the last cycles failed. Build no features. Find the root cause, write state/BLOCKED.md (cause, evidence, proposed fix, what you need from the Human, if anything). Fix it only if the fix is small and safe." ;;
    20) sleep 1800; continue ;;
    *)  echo "Loop stopped by preflight."; exit 1 ;;
  esac

  ts="$(date +%Y%m%dT%H%M%S)"
  echo "$(date +%F) $ts" >> "$FIRM_HOME/cycles.log"
  echo "[$ts] cycle starting"
  claude -p "$prompt" \
    --permission-mode acceptEdits \
    --max-turns "$(cfg builder.max_turns_per_cycle)" \
    --output-format json \
    > "$FIRM_HOME/logs/cycle-$ts.json" 2>&1
  echo "[$(date +%H:%M:%S)] cycle ended (exit $?)"

  uv run --quiet python loop/preflight.py --post
  sleep "$(cfg builder.cycle_sleep_seconds)"
done
