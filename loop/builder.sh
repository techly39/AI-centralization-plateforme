#!/usr/bin/env bash
# HUMAN-ONLY (Constitution Art. 6). One command to drive the Builder loop.
#
#   loop/builder.sh start [N]   start a run of N cycles in the background (default: builder.cycles_per_run)
#   loop/builder.sh status      is it running, recent cycles (result, cost, models), last log lines
#   loop/builder.sh stop        finish the current cycle, then stop
#   loop/builder.sh stop now    stop immediately (kills the running cycle; it is counted as failed)
#   loop/builder.sh log         follow the log live (Ctrl-C to leave; the run keeps going)
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

case "${1:-status}" in
  start)
    if running; then echo "A run is already going (pid $(cat "$PID_FILE")). See: loop/builder.sh status"; exit 1; fi
    if [ -f governance/HALT ]; then echo "governance/HALT exists — remove it first if you want the Builder to run."; exit 1; fi
    nohup caffeinate -ims bash loop/run.sh ${2:+"$2"} >> "$LOG" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 3
    if running; then
      echo "Started (pid $!). Check with: loop/builder.sh status"
    else
      echo "The run ended right away. Last log lines:"; tail -8 "$LOG"
    fi
    ;;
  status)
    if running; then echo "RUNNING (pid $(cat "$PID_FILE"))"; else echo "NOT RUNNING"; fi
    [ -f "$FIRM_HOME/stop-after-cycle" ] && echo "Stop requested: it will stop after the current cycle."
    echo "Spent today: \$$(uv run --quiet python loop/preflight.py --spent-today)" \
         "(daily cap \$$(uv run --quiet python loop/preflight.py --get builder.max_usd_per_day))"
    echo "--- recent cycles ---"; tail -5 "$FIRM_HOME/cycles.log" 2>/dev/null
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
      echo "Stopped now. The interrupted cycle may have left a branch or uncommitted work; the next cycle checks for it first."
    else
      touch "$FIRM_HOME/stop-after-cycle"
      echo "OK — it will stop after the current cycle. (Use 'loop/builder.sh stop now' to stop immediately.)"
    fi
    ;;
  log)
    tail -f "$LOG"
    ;;
  *)
    sed -n '3,9p' "$0"; exit 2
    ;;
esac
