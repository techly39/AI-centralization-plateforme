#!/usr/bin/env bash
# Tests setup/install.sh and setup/rollback.sh in a SCRATCH CLONE, never in the real repo.
# Safe for anyone to run (the Builder included): the clone's `origin` is a bare repo in a temp dir and
# its FIRM_HOME is a temp dir, so nothing is pushed to GitHub and the real seal is never touched.
#
#   bash setup/test_install.sh [branch]      (default builder-v3; the branch must be committed)
#
# Checks, in order:
#   1. install: merge + copy + seal + preflight pass; the roles are exactly auditor, red-team, worker;
#      the Constitution, gates and human.yaml are the staged ones (cap still 50)
#   2. guard: protected writes blocked; reads of protected paths, heredocs and `cd … &&` allowed;
#      force-push blocked; HALT allows only reads
#   3. runner with a stub `claude`: one build session → `progress`, metrics row written, main green
#   4. referee: a false `merged` claim → failed (false_done); a usage-limit log → exit 30, no failure
#   5. rollback: the old protected files are back (architect and validator roles included)
set -u
BRANCH="${1:-builder-v3}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
export FIRM_HOME="$T/firm"
mkdir -p "$FIRM_HOME"
pass=0; fail=0
ok()   { echo "  PASS $1"; pass=$((pass + 1)); }
bad()  { echo "  FAIL $1"; fail=$((fail + 1)); }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

echo "scratch: $T"
git clone --quiet --bare "$REPO" "$T/origin.git"
git clone --quiet "$T/origin.git" "$T/repo"
cd "$T/repo" || exit 1
git config user.email test@example.invalid; git config user.name "install test"
git rev-parse --verify --quiet "origin/$BRANCH" >/dev/null || { echo "branch $BRANCH is not committed"; exit 1; }
git switch --quiet main 2>/dev/null || git switch --quiet -c main origin/main
git rev-parse --verify --quiet "$BRANCH" >/dev/null || git branch --quiet "$BRANCH" "origin/$BRANCH"
# The installed human.yaml is not always committed (the Human edits it): use the real one.
cp "$REPO/governance/human.yaml" governance/human.yaml
if [ -n "$(git status --porcelain)" ]; then git commit --quiet -am "test: the Human's installed human.yaml"; fi
uv sync --quiet >/dev/null 2>&1

echo "1. install"
bash setup/install.sh "$BRANCH" > "$T/install.log" 2>&1; rc=$?
check "install.sh exits 0" "[ $rc -eq 0 ]" || tail -20 "$T/install.log"
check "roles are auditor, red-team, worker" "[ \"\$(ls .claude/agents | tr '\n' ' ')\" = 'auditor.md red-team.md worker.md ' ]"
check "Constitution is the staged one" "cmp -s bible/00_CONSTITUTION.md setup/files/bible_dir/00_CONSTITUTION.md"
check "gates are the staged ones" "cmp -s .claude/commands/cycle.md setup/files/claude_dir/commands/cycle.md"
check "cap is still 50" "grep -q 'monthly_llm_usd_cap: 50' governance/human.yaml"
check "lead is opus" "grep -q 'lead: *{model: opus' governance/human.yaml"
check "preflight check passes" "uv run --quiet python loop/preflight.py >/dev/null 2>&1"
check "next mode is build" "[ \"\$(uv run --quiet python loop/preflight.py --mode)\" = build ]"
check "pushed to the scratch origin only" "[ \"\$(git rev-parse main)\" = \"\$(git --git-dir=$T/origin.git rev-parse main)\" ]"
BK="$(ls -d "$FIRM_HOME"/backups/install-* | tail -1)"

echo "2. guard"
python3 setup/test_guard_cases.py "$T/repo" "$FIRM_HOME"
check "guard cases" "[ $? -eq 0 ]"

echo "3. runner + stub claude (one build session; the referee runs the full suite on main, ~2 min)"
mkdir -p "$T/bin"
cat > "$T/bin/claude" <<'STUB'
#!/usr/bin/env bash
# Stub: acts like a build session that made progress, without any model.
n=$(( $(python3 -c 'import json;print(json.load(open("state/loop_status.json"))["cycle"])') + 1 ))
printf '{"cycle": %d, "mode": "build", "mission": "real-agents-backtest", "result": "progress", "branch": "main", "ts": "2026-10-16T00:00:00Z"}\n' "$n" > state/loop_status.json
printf 'Cycle %04d · building: stub\n' "$n" > state/PROGRESS.md
git add state/loop_status.json state/PROGRESS.md && git commit --quiet -m "stub session $n"
echo '{"type":"result","subtype":"success","is_error":false,"num_turns":1,"total_cost_usd":0,"session_id":"stub","result":"stub done","modelUsage":{}}'
STUB
chmod +x "$T/bin/claude"
before="$(uv run --quiet python loop/preflight.py --last-cycle)"
PATH="$T/bin:$PATH" bash loop/run.sh 1 > "$T/run.log" 2>&1; rc=$?
check "run.sh exits 0" "[ $rc -eq 0 ]" || tail -20 "$T/run.log"
check "a metrics row says progress" "tail -1 $FIRM_HOME/metrics.jsonl | grep -q '\"result\": \"progress\"'"
check "main is green in the referee's row" "tail -1 $FIRM_HOME/metrics.jsonl | grep -q '\"main_green\": true'"
check "subagents are never killed (env exported)" "grep -q 'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0' loop/run.sh"

echo "4. referee"
last="$(uv run --quiet python loop/preflight.py --last-cycle)"
printf '{"cycle": %d, "mode": "build", "mission": "real-agents-backtest", "result": "merged", "branch": "main", "ts": "2026-10-16T00:00:00Z"}\n' "$((last + 1))" > state/loop_status.json
git commit --quiet -am "stub: a false merged claim"
echo '{"type":"result","is_error":false,"num_turns":1,"total_cost_usd":0,"session_id":"stub2","modelUsage":{}}' > "$T/false.json"
uv run --quiet python loop/preflight.py --post "$last" "$T/false.json" build "$(date +%s)" >/dev/null 2>&1
check "false merged → failed, false_done" "tail -1 $FIRM_HOME/metrics.jsonl | grep -q 'false_done'"
echo 0 > "$FIRM_HOME/failures"
last="$(uv run --quiet python loop/preflight.py --last-cycle)"
echo '{"type":"result","is_error":true,"num_turns":1,"total_cost_usd":0.1,"session_id":"stub3","result":"You have hit your usage limit · resets 3am"}' > "$T/limit.json"
uv run --quiet python loop/preflight.py --post "$last" "$T/limit.json" build "$(date +%s)" >/dev/null 2>&1; rc=$?
check "usage limit → exit 30" "[ $rc -eq 30 ]"
check "usage limit is not a failure" "[ \"\$(cat $FIRM_HOME/failures)\" = 0 ]"
git checkout --quiet -- state/loop_status.json 2>/dev/null; git status --porcelain | grep -q . && git commit --quiet -am "test: tidy"

echo "5. rollback"
bash setup/rollback.sh "$BK" > "$T/rollback.log" 2>&1; rc=$?
check "rollback.sh exits 0" "[ $rc -eq 0 ]" || tail -20 "$T/rollback.log"
check "architect and validator roles are back" "[ -f .claude/agents/architect.md ] && [ -f .claude/agents/validator.md ]"
check "the old Constitution is back" "grep -q 'Article 1' bible/00_CONSTITUTION.md"
check "preflight passes after rollback" "uv run --quiet python loop/preflight.py >/dev/null 2>&1"

echo
echo "install test: $pass passed, $fail failed  (scratch kept in $T)"
[ "$fail" -eq 0 ]
