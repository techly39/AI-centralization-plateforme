#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). The Builder loop — bounded: it runs N cycles, then exits.
# Normally started through loop/builder.sh (start / status / stop); it can also run in the foreground:
#
#   loop/run.sh          N = builder.cycles_per_run in governance/human.yaml
#   loop/run.sh 2        at most 2 cycles
#
# The team (builder.team): the lead session runs on team.lead, or on team.lead_hard for a
# diagnosis cycle, a retrospective (every 10th cycle) and the cycle after a failure. Architect,
# auditor and red-team models live in their sealed agent files (loop/seal.sh writes them from
# builder.team); every other subagent runs on team.helpers.
#
# Dollar guard rails (builder.*): a cycle is cut off at max_usd_per_cycle, and starts only if
# that whole budget still fits under max_usd_per_run and max_usd_per_day — no cap is overshot.
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
export CLAUDE_CODE_SUBAGENT_MODEL="$(cfg builder.team.helpers.model)"
per_cycle="$(cfg builder.max_usd_per_cycle)"
per_run="$(cfg builder.max_usd_per_run)"
run_spent=0

echo "[$(date '+%F %T')] run starting: $cycles cycle(s); lead $(cfg builder.team.lead.model)," \
     "hard cycles $(cfg builder.team.lead_hard.model), architect $(cfg builder.team.architect.model)," \
     "auditor $(cfg builder.team.auditor.model), red-team $(cfg builder.team.red-team.model)," \
     "helpers $CLAUDE_CODE_SUBAGENT_MODEL; caps \$$per_cycle/cycle \$$per_run/run"

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

  # Choose the lead: hard cycles get the strongest model.
  before="$(uv run --quiet python loop/preflight.py --last-cycle)"
  failures="$(cat "$FIRM_HOME/failures" 2>/dev/null || echo 0)"
  role=lead; why="routine"
  if [ "$rc" -eq 10 ]; then role=lead_hard; why="diagnosis"
  elif [ $(( (before + 1) % 10 )) -eq 0 ]; then role=lead_hard; why="retrospective"
  elif [ "${failures:-0}" -gt 0 ]; then role=lead_hard; why="previous cycle failed"
  fi
  model="$(cfg "builder.team.$role.model")"
  effort="$(cfg "builder.team.$role.effort")"

  ts="$(date +%Y%m%dT%H%M%S)"
  log="$FIRM_HOME/logs/cycle-$ts.json"
  echo "[$ts] cycle $i/$cycles starting (last finished: $before; lead $model/$effort — $why; budget \$$per_cycle)"
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
