#!/usr/bin/env bash
# HUMAN-ONLY. Records the hashes of every protected file OUTSIDE the repo.
# Run once at setup, and again every time YOU edit a protected file
# (Constitution, Genesis, governance/, loop/, .claude/settings.json, .claude/hooks/).
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME"
uv run --quiet python loop/preflight.py --hashes > "$FIRM_HOME/protected.sha256"
chmod 600 "$FIRM_HOME/protected.sha256"
echo "Sealed $(grep -c '"' "$FIRM_HOME/protected.sha256") protected files → $FIRM_HOME/protected.sha256"
