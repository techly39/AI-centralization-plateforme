#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). One command to drive the Builder loop (v2, ADR-042).
#
#   loop/builder.sh start [N] [plan|build]   start a run of N sessions in the background
#                                            (default: builder.cycles_per_run; mode: chosen by the runner)
#   loop/builder.sh plan                     start one planning session now
#   loop/builder.sh status                   running?, recent sessions, missions, last log lines
#   loop/builder.sh stop                     finish the current session, then stop
#   loop/builder.sh stop now                 stop immediately (the next session resumes the work)
#   loop/builder.sh log                      follow the log live (Ctrl-C to leave; the run keeps going)
#
# Only one run at a time. You can close the terminal after `start`.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME"
PID_FILE="$FIRM_HOME/run.pid"
LOG="$FIRM_HOME/loop.log"

running() { [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; }

start_run() {
  if running; then echo "A run is already going (pid $(cat "$PID_FILE")). See: loop/builder.sh status"; exit 1; fi
  if [ -f governance/HALT ]; then echo "governance/HALT exists — remove it first if you want the Builder to run."; exit 1; fi
  nohup caffeinate -ims bash loop/run.sh "$@" >> "$LOG" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 3
  if running; then
    echo "Started (pid $!). Check with: loop/builder.sh status"
  else
    echo "The run ended right away. Last log lines:"; tail -8 "$LOG"
  fi
}

case "${1:-status}" in
  start)
    shift
    start_run "$@"
    ;;
  plan)
    start_run 1 plan
    ;;
  status)
    if running; then echo "RUNNING (pid $(cat "$PID_FILE"))"; else echo "NOT RUNNING"; fi
    [ -f "$FIRM_HOME/stop-after-cycle" ] && echo "Stop requested: it will stop after the current session."
    echo "Spent today (list price): \$$(uv run --quiet python loop/preflight.py --spent-today)"
    echo "Next session mode: $(uv run --quiet python loop/preflight.py --mode)"
    echo "--- missions ---"
    uv run --quiet python -c 'import json; [print(f"  {m[\"id\"]:6} {m.get(\"status\",\"?\"):8} {m.get(\"title\",\"\")}") for m in json.load(open("state/missions.json"))["missions"]]' 2>/dev/null
    echo "--- recent sessions ---"; tail -5 "$FIRM_HOME/cycles.log" 2>/dev/null
    echo "--- last log lines ---"; tail -8 "$LOG" 2>/dev/null
    ;;
  stop)
    if ! running; then echo "Nothing is running."; rm -f "$PID_FILE"; exit 0; fi
    if [ "${2:-}" = "now" ]; then
      pid="$(cat "$PID_FILE")"
      pkill -TERM -P "$pid" 2>/dev/null          # caffeinate's child: run.sh
      pkill -TERM -f "claude -p /cycle" 2>/dev/null
      kill "$pid" 2>/dev/null
      rm -f "$PID_FILE"
      echo "Stopped now. Unfinished work stays on the mission branch; the next session resumes it."
    else
      touch "$FIRM_HOME/stop-after-cycle"
      echo "OK — it will stop after the current session. (Use 'loop/builder.sh stop now' to stop immediately.)"
    fi
    ;;
  log)
    tail -f "$LOG"
    ;;
  *)
    sed -n '3,11p' "$0"; exit 2
    ;;
esac
