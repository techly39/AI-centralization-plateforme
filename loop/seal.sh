#!/usr/bin/env bash
# HUMAN-ONLY. Applies the Builder team, then records the hashes of every protected file OUTSIDE
# the repo. Run once at setup, and again every time YOU edit a protected file
# (Constitution, Genesis, governance/, loop/, .claude/settings.json, .claude/hooks/,
# .claude/commands/, .claude/agents/).
#
# The team: builder.team in governance/human.yaml is the single place where models are chosen.
# This script writes the architect / auditor / red-team models and efforts into their
# .claude/agents/*.md frontmatter, so the file you edit and the files Claude Code reads never drift.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
mkdir -p "$FIRM_HOME"
uv run --quiet python loop/preflight.py --apply-team
uv run --quiet python loop/preflight.py --hashes > "$FIRM_HOME/protected.sha256"
chmod 600 "$FIRM_HOME/protected.sha256"
echo "Sealed $(grep -c '"' "$FIRM_HOME/protected.sha256") protected files → $FIRM_HOME/protected.sha256"
