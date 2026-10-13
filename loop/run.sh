#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). The Builder loop (v2, ADR-042) — bounded: N sessions, then exit.
# Normally started through loop/builder.sh (start / status / stop); it can also run in the foreground:
#
#   loop/run.sh                N = builder.cycles_per_run in governance/human.yaml
#   loop/run.sh 2              at most 2 sessions
#   loop/run.sh 1 plan         force the first session's mode (plan | build); later ones are chosen
#
# Each session is one `claude -p "/cycle <mode>"`. The mode comes from loop/preflight.py --mode:
# plan when no mission is ready or after every builder.plan_every_missions accepted missions,
# else build; diagnosis after builder.max_consecutive_failures failures.
# Lead model: team.lead for build sessions; team.lead_hard for plan, diagnosis, and after a failure.
#
# After each session the referee (preflight.py --post) verifies main and the mission's acceptance
# check itself, outside the Builder's reach, and logs metrics to $FIRM_HOME/metrics.jsonl.
#
# Limits (builder.*): USD caps are optional (null = none: the subscription's usage limit is the
# real stop). On a usage limit, if wait_for_usage_reset, the run sleeps until the reset (at most
# max_wait_hours) and continues. max_session_hours is a hang guard, not a budget.
# Stop after the current session: loop/builder.sh stop.  Stop everything now: touch governance/HALT.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME/logs"
STOP_FLAG="$FIRM_HOME/stop-after-cycle"
rm -f "$STOP_FLAG"

cfg() { uv run --quiet python loop/preflight.py --get "$1"; }
ge() { awk -v a="$1" -v b="$2" 'BEGIN { exit !(a >= b) }'; }   # float a >= b

sessions="${1:-$(cfg builder.cycles_per_run)}"
case "$sessions" in ''|*[!0-9]*) echo "usage: loop/run.sh [number of sessions] [plan|build]"; exit 2 ;; esac
forced_mode="${2:-}"
case "$forced_mode" in ''|plan|build) ;; *) echo "mode must be plan or build"; exit 2 ;; esac
export CLAUDE_CODE_SUBAGENT_MODEL="$(cfg builder.team.helpers.model)"
export FIRM_BUILDER_SESSION=1          # the Stop hook (.claude/hooks/stop_gate.py) only acts in loop sessions
per_session="$(cfg builder.max_usd_per_cycle)"
per_run="$(cfg builder.max_usd_per_run)"
turns="$(cfg builder.max_turns_per_cycle)"
hang_hours="$(cfg builder.max_session_hours)"
run_spent=0

echo "[$(date '+%F %T')] run starting: $sessions session(s); lead $(cfg builder.team.lead.model)," \
     "hard $(cfg builder.team.lead_hard.model), architect $(cfg builder.team.architect.model)," \
     "auditor $(cfg builder.team.auditor.model), red-team $(cfg builder.team.red-team.model)," \
     "validator $(cfg builder.team.validator.model), helpers $CLAUDE_CODE_SUBAGENT_MODEL;" \
     "caps: session \$${per_session:-none} run \$${per_run:-none}"

i=1
while [ "$i" -le "$sessions" ]; do
  if [ -f governance/HALT ]; then echo "HALT present — stopping."; exit 0; fi
  if [ -f "$STOP_FLAG" ]; then rm -f "$STOP_FLAG"; echo "Stop requested — stopping."; exit 0; fi
  if [ -n "$per_run" ] && ge "$run_spent" "$per_run"; then
    echo "Run budget reached (\$$run_spent of \$$per_run) — stopping."; exit 0
  fi

  out="$(uv run --quiet python loop/preflight.py)"; rc=$?
  echo "$out"
  case $rc in
    0)  mode="${forced_mode:-$(uv run --quiet python loop/preflight.py --mode)}"; forced_mode="" ;;
    10) mode="diagnosis" ;;
    20) echo "Daily limit reached — stopping. Run again tomorrow."; exit 0 ;;
    *)  echo "Stopped by preflight."; exit 1 ;;
  esac

  before="$(uv run --quiet python loop/preflight.py --last-cycle)"
  failures="$(cat "$FIRM_HOME/failures" 2>/dev/null || echo 0)"
  role=lead; why="build"
  if [ "$mode" = "diagnosis" ]; then role=lead_hard; why="diagnosis"
  elif [ "$mode" = "plan" ]; then role=lead_hard; why="plan"
  elif [ "${failures:-0}" -gt 0 ]; then role=lead_hard; why="build after a failure"
  fi
  model="$(cfg "builder.team.$role.model")"
  effort="$(cfg "builder.team.$role.effort")"

  if [ "$mode" = "plan" ]; then
    echo "[$(date +%H:%M:%S)] regression: re-running every done mission's acceptance check on main"
    uv run --quiet python loop/preflight.py --regression
  fi

  args=(-p "/cycle $mode" --permission-mode acceptEdits --model "$model" --effort "$effort" --output-format json)
  [ -n "$per_session" ] && args+=(--max-budget-usd "$per_session")
  [ -n "$turns" ] && args+=(--max-turns "$turns")
  sandbox="$(uv run --quiet python loop/preflight.py --sandbox-settings)"
  [ -n "$sandbox" ] && args+=(--settings "$sandbox")

  ts="$(date +%Y%m%dT%H%M%S)"
  log="$FIRM_HOME/logs/cycle-$ts.json"
  start="$(date +%s)"
  echo "[$ts] session $i/$sessions starting: mode $mode (last finished: $before; lead $model/$effort — $why)"
  claude "${args[@]}" > "$log" 2>&1 &
  pid=$!
  # Hang guard: a session still running after max_session_hours is stopped (counted by --post).
  # The watcher kills its own sleep when stopped (no orphan holding the log open, no stale pid).
  hang_s="$(awk -v h="${hang_hours:-8}" 'BEGIN { printf "%d", h * 3600 }')"
  ( sleep "$hang_s" & s=$!
    trap 'kill "$s" 2>/dev/null; exit 0' TERM
    wait "$s" && kill -TERM "$pid" 2>/dev/null ) >/dev/null 2>&1 &
  guard=$!
  wait "$pid"; code=$?
  kill "$guard" 2>/dev/null; wait "$guard" 2>/dev/null
  echo "[$(date +%H:%M:%S)] session ended (exit $code)"

  cost="$(uv run --quiet python loop/preflight.py --cost "$log")"
  run_spent="$(awk -v a="$run_spent" -v b="$cost" 'BEGIN { printf "%.2f", a + b }')"
  uv run --quiet python loop/preflight.py --post "$before" "$log" "$mode" "$start"
  if [ $? -eq 30 ]; then
    if [ "$(cfg builder.wait_for_usage_reset)" = "True" ]; then
      wait_s="$(uv run --quiet python loop/preflight.py --reset-wait "$log")"
      if [ "${wait_s:--1}" -gt 0 ]; then
        echo "[$(date +%H:%M:%S)] usage limit hit — waiting $((wait_s / 60)) min for the reset, then resuming."
        end=$(( $(date +%s) + wait_s ))
        while [ "$(date +%s)" -lt "$end" ]; do
          if [ -f governance/HALT ] || [ -f "$STOP_FLAG" ]; then echo "Stopped while waiting."; exit 0; fi
          sleep 60
        done
        continue          # same slot: the interrupted session is resumed, not counted
      fi
    fi
    echo "[$(date +%H:%M:%S)] usage limit hit — stopping. Run again after it resets."
    exit 0
  fi
  echo "This run so far: \$$run_spent${per_run:+ of \$$per_run}"
  if [ "$i" -lt "$sessions" ]; then sleep "$(cfg builder.cycle_sleep_seconds)"; fi
  i=$((i + 1))
done
echo "[$(date '+%F %T')] run done: $sessions session(s). This run: \$$run_spent." \
     "Today: \$$(uv run --quiet python loop/preflight.py --spent-today)"
