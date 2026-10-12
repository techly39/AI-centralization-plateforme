#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). The Builder loop — bounded: it runs N cycles, then exits.
# Normally started through loop/builder.sh (start / status / stop); it can also run in the foreground:
#
#   loop/run.sh          N = builder.cycles_per_run in governance/human.yaml
#   loop/run.sh 2        at most 2 cycles
#
# Guard rails, all in governance/human.yaml (builder.*):
#   model / effort / subagent_model   which model does the work, and how hard it thinks
#   max_usd_per_cycle                 a cycle is cut off at this spend (claude --max-budget-usd)
#   max_usd_per_run                   a cycle starts only if its whole budget fits under this
#   max_usd_per_day, max_cycles_per_day   checked by preflight before every cycle (same rule)
# It never retries on its own: a usage limit or any cap ends the run.
# Stop after the current cycle: loop/builder.sh stop.  Stop everything now: touch governance/HALT.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME/logs"
STOP_FLAG="$FIRM_HOME/stop-after-cycle"
rm -f "$STOP_FLAG"

cfg() { uv run --quiet python loop/preflight.py --get "$1"; }
ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a >= b) }'; }   # float a >= b

cycles="${1:-$(cfg builder.cycles_per_run)}"
case "$cycles" in ''|*[!0-9]*) echo "usage: loop/run.sh [number of cycles]"; exit 2 ;; esac
model="$(cfg builder.model)"
effort="$(cfg builder.effort)"
export CLAUDE_CODE_SUBAGENT_MODEL="$(cfg builder.subagent_model)"
per_cycle="$(cfg builder.max_usd_per_cycle)"
per_run="$(cfg builder.max_usd_per_run)"
run_spent=0

echo "[$(date '+%F %T')] run starting: $cycles cycle(s), model=$model effort=$effort" \
     "subagents=$CLAUDE_CODE_SUBAGENT_MODEL, caps \$$per_cycle/cycle \$$per_run/run"

for ((i = 1; i <= cycles; i++)); do
  if [ -f governance/HALT ]; then echo "HALT present — stopping."; exit 0; fi
  if [ -f "$STOP_FLAG" ]; then rm -f "$STOP_FLAG"; echo "Stop requested — stopping."; exit 0; fi
  # A cycle starts only if its whole budget still fits in the run's: the run can never overshoot.
  if ! ge "$per_run" "$(awk -v a="$run_spent" -v b="$per_cycle" 'BEGIN { print a + b }')"; then
    echo "Run budget reached (\$$run_spent spent, a cycle may cost \$$per_cycle, cap \$$per_run) — stopping."; exit 0
  fi

  out="$(uv run --quiet python loop/preflight.py)"; rc=$?
  echo "$out"
  case $rc in
    0)  prompt="/cycle" ;;
    10) prompt="/cycle DIAGNOSIS MODE: the last cycles failed. Build no features. Find the root cause, write state/BLOCKED.md (cause, evidence, proposed fix, what you need from the Human, if anything). Fix it only if the fix is small and safe." ;;
    20) echo "Daily limit reached — stopping. Run again tomorrow."; exit 0 ;;
    *)  echo "Stopped by preflight."; exit 1 ;;
  esac

  ts="$(date +%Y%m%dT%H%M%S)"
  log="$FIRM_HOME/logs/cycle-$ts.json"
  before="$(uv run --quiet python loop/preflight.py --last-cycle)"
  echo "[$ts] cycle $i/$cycles starting (last finished cycle: $before, budget \$$per_cycle)"
  claude -p "$prompt" \
    --permission-mode acceptEdits \
    --model "$model" \
    --effort "$effort" \
    --max-turns "$(cfg builder.max_turns_per_cycle)" \
    --max-budget-usd "$per_cycle" \
    --output-format json \
    > "$log" 2>&1
  echo "[$(date +%H:%M:%S)] cycle ended (exit $?)"

  cost="$(uv run --quiet python loop/preflight.py --cost "$log")"
  run_spent="$(awk -v a="$run_spent" -v b="$cost" 'BEGIN { printf "%.2f", a + b }')"
  uv run --quiet python loop/preflight.py --post "$before" "$log"
  if [ $? -eq 30 ]; then
    echo "[$(date +%H:%M:%S)] usage limit hit — stopping. Run again after it resets."
    exit 0
  fi
  echo "This run so far: \$$run_spent of \$$per_run"
  if [ "$i" -lt "$cycles" ]; then sleep "$(cfg builder.cycle_sleep_seconds)"; fi
done
echo "[$(date '+%F %T')] run done: $cycles cycle(s). This run: \$$run_spent." \
     "Today: \$$(uv run --quiet python loop/preflight.py --spent-today)"
