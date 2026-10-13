#!/usr/bin/env bash
# HUMAN-RUN installer for Builder v2 (ADR-042). The Builder cannot run this: it writes protected files.
#
#   bash setup/install.sh
#
# What it does, in order (it stops at the first error, before touching anything it cannot undo):
#   1. checks: no Builder run going, clean working tree, branch builder-v2 exists
#   2. backs up every protected file it will replace → $FIRM_HOME/backups/install-<time>/
#   3. merges branch builder-v2 (the Builder's side: protocol, Bible, state) into main
#   4. copies setup/files/* into .claude/, loop/, governance/
#   5. syntax-checks the scripts, applies the team, seals (loop/seal.sh), checks the preflight
#   6. commits the protected files on main and pushes to origin
# Undo everything: bash setup/rollback.sh $FIRM_HOME/backups/install-<time>
set -eu
if [ -z "${FIRM_INSTALL_COPY:-}" ]; then
  # Run from a temporary copy: switching branches below changes setup/ under a running script.
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  TMP="$(mktemp -d)"
  cp -R "$ROOT/setup" "$TMP/setup"
  FIRM_INSTALL_COPY="$TMP" exec bash "$TMP/setup/install.sh" "$ROOT"
fi
ROOT="$1"
cd "$ROOT"
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
S="$FIRM_INSTALL_COPY/setup/files"

if [ -f "$FIRM_HOME/run.pid" ] && kill -0 "$(cat "$FIRM_HOME/run.pid")" 2>/dev/null; then
  echo "A Builder run is going. Stop it first: loop/builder.sh stop now"; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "The working tree is not clean. Commit or stash first:"; git status --short; exit 1
fi
git rev-parse --verify --quiet builder-v2 >/dev/null || { echo "branch builder-v2 not found"; exit 1; }

TS="$(date +%Y%m%dT%H%M%S)"
BK="$FIRM_HOME/backups/install-$TS"
mkdir -p "$BK"
TARGETS=".claude/settings.json .claude/hooks .claude/commands .claude/agents loop/run.sh loop/builder.sh loop/preflight.py governance/human.yaml"
# shellcheck disable=SC2086
tar -cf "$BK/protected-before.tar" $TARGETS
git rev-parse main > "$BK/main-before"
echo "1/6 backup → $BK"

git switch --quiet main
git merge --no-ff --quiet builder-v2 -m "Builder v2 (ADR-042): missions, acceptance checks, planning sessions — Builder-owned side"
git rev-parse HEAD > "$BK/merge-commit"
echo "2/6 merged builder-v2 into main ($(cat "$BK/merge-commit" | cut -c1-8))"

cp "$S/claude_dir/settings.json"        .claude/settings.json
cp "$S/claude_dir/hooks/guard.py"       .claude/hooks/guard.py
cp "$S/claude_dir/hooks/stop_gate.py"   .claude/hooks/stop_gate.py
cp "$S/claude_dir/commands/cycle.md"    .claude/commands/cycle.md
cp "$S/claude_dir/agents/"*.md          .claude/agents/
cp "$S/loop_dir/run.sh"                 loop/run.sh
cp "$S/loop_dir/builder.sh"             loop/builder.sh
cp "$S/loop_dir/preflight.py"           loop/preflight.py
cp "$S/governance_dir/human.yaml"       governance/human.yaml
chmod +x loop/run.sh loop/builder.sh .claude/hooks/stop_gate.py
echo "3/6 copied the protected files"

bash -n loop/run.sh && bash -n loop/builder.sh
for f in .claude/hooks/guard.py .claude/hooks/stop_gate.py loop/preflight.py; do
  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$f"   # no __pycache__ in sealed dirs
done
python3 -c 'import json; json.load(open(".claude/settings.json"))'
echo "4/6 syntax OK"

bash loop/seal.sh
uv run --quiet python loop/preflight.py --mode >/dev/null
echo 0 > "$FIRM_HOME/failures"
echo "5/6 team applied, sealed, failure counter reset"

git add .claude/settings.json .claude/hooks .claude/commands .claude/agents loop governance/human.yaml
git commit --quiet -m "human: install Builder v2 protected files (ADR-042)

Missions + acceptance checks + planning sessions; validator and worker roles; Stop hook; OS sandbox;
out-of-band referee in loop/preflight.py; no USD caps (the subscription limit is the stop);
wait for usage-limit resets. Backup: $BK"
git push --quiet origin main
echo "6/6 committed and pushed"
echo
echo "Builder v2 is installed. Next session: $(uv run --quiet python loop/preflight.py --mode)."
echo "Start with:  loop/builder.sh start      (or: loop/builder.sh plan  for one planning session)"
echo "Undo with:   bash setup/rollback.sh $BK"
