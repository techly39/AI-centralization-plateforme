#!/usr/bin/env bash
# HUMAN-RUN rollback of a Builder install (setup/install.sh).
#
#   bash setup/rollback.sh ~/.firm/backups/install-<time>
#
# Restores the protected files saved by setup/install.sh, reverts the merge it made (with a new
# commit — history is append-only), reseals, commits and pushes. Work the Builder did after the
# install stays in history and on main unless it conflicts.
set -eu
BK="${1:?usage: setup/rollback.sh <backup dir from setup/install.sh>}"
if [ -z "${FIRM_ROLLBACK_COPY:-}" ]; then
  # Run from a temporary copy: the revert below can remove setup/ under a running script.
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
# Whole directories come back exactly as they were (roles added or removed by the install included).
for d in .claude/hooks .claude/commands .claude/agents; do
  if tar -tf "$BK/protected-before.tar" | grep -q "^$d/"; then rm -rf "$d"; fi
done
tar -xf "$BK/protected-before.tar"
git add -A .claude loop governance bible/00_CONSTITUTION.md bible/01_GENESIS.md
git commit --quiet -m "human: roll back the Builder install's protected files (restore $BK)"
reverted=yes
if ! git revert --no-edit -m 1 "$(cat "$BK/merge-commit")" >/dev/null 2>&1; then
  # The Builder changed the same files after the install: keep its work, restore only your files.
  git revert --abort
  reverted=no
fi
bash loop/seal.sh
echo 0 > "$FIRM_HOME/failures"
git push --quiet origin main
echo "Rolled back to the protected files of $BK."
if [ "$reverted" = yes ]; then
  echo "The install's merge (the Builder-owned side) was reverted too."
else
  echo "The Builder-owned side (ideas book, protocol, state) was NOT reverted: the Builder changed those"
  echo "files after the install. Your protected files are back and sealed; ask Claude to undo the rest."
fi
