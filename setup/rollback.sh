#!/usr/bin/env bash
# HUMAN-RUN rollback of a Builder v2 install (ADR-042).
#
#   bash setup/rollback.sh ~/.firm/backups/install-<time>
#
# Restores the protected files saved by setup/install.sh, reverts the merge of builder-v2 (with a new
# commit — history is append-only, Art. 3.3), reseals, commits and pushes. Work the Builder did after
# the install (missions, code) stays in history and on main unless it conflicts.
set -eu
BK="${1:?usage: setup/rollback.sh <backup dir from setup/install.sh>}"
if [ -z "${FIRM_ROLLBACK_COPY:-}" ]; then
  # Run from a temporary copy: the revert below removes setup/ under a running script.
  ROOT="$(cd "$(dirname "$0")/.." && pwd)"
  TMP="$(mktemp -d)"
  cp "$0" "$TMP/rollback.sh"
  FIRM_ROLLBACK_COPY=1 exec bash "$TMP/rollback.sh" "$BK" "$ROOT"
fi
ROOT="$2"
cd "$ROOT"
export FIRM_HOME="${FIRM_HOME:-$HOME/.firm}"
[ -f "$BK/protected-before.tar" ] && [ -f "$BK/merge-commit" ] || { echo "not a backup dir: $BK"; exit 1; }
if [ -f "$FIRM_HOME/run.pid" ] && kill -0 "$(cat "$FIRM_HOME/run.pid")" 2>/dev/null; then
  echo "A Builder run is going. Stop it first: loop/builder.sh stop now"; exit 1
fi
[ -z "$(git status --porcelain)" ] || { echo "The working tree is not clean."; exit 1; }

git switch --quiet main
rm -f .claude/hooks/stop_gate.py .claude/agents/validator.md .claude/agents/worker.md
tar -xf "$BK/protected-before.tar"
git add -A .claude loop governance
git commit --quiet -m "human: roll back Builder v2 protected files (restore $BK)"
git revert --no-edit -m 1 "$(cat "$BK/merge-commit")"
bash loop/seal.sh
echo 0 > "$FIRM_HOME/failures"
git push --quiet origin main
echo "Rolled back to the protected files of $BK and reverted the Builder v2 merge."
