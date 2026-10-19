Cycle 0050 · building: a dead pod is replaced by a newly hired PM · branch: idea/pod-replacement
Done this session:
- Physics: when the ladder closes a pod, a vacancy opens with the dead pod's post-mortem and the
  hire the hiring law names (config.yaml `hiring:`, frozen at the first vacancy). A registrar fills
  it (new pod + new PM); the pod limit and taken names refuse it in the ledger; the Runtime can
  refuse a hire whose budget does not fit the cap. `GET /mandate`: a seeded pod's orders today.
- Runtime: `fund-runtime backtest --hire TEMPLATE` hires every morning, mid-run, under the cap,
  mints the new PM's own key, hands it the post-mortem; hires are in the cassette; replay and
  `replay --verify` follow them.
- A hosted world can be a made-up market (app/marketdata/made_up.py): a sector crashes, a pod dies.
- Demo part A (scripted firm, 5 pods, limit 4) and B0 (hosted scripted rehearsal, IDENTICAL) pass.
Next: red-team on the diff, fix highs; record the real hire (`uv run python
acceptance/pod_replacement.py --write-world DIR openrouter`, then backtest --world ... --hire
DIR/hire.yaml --steps 24 --max-tool-calls 24 --cassette evidence/pod-replacement/hire.cassette.json
with the world key sha256("fund-pod-replacement/1")); auditor; merge.
Watch out: a reduce-only pod that rotates into cash can stop falling before 10% (realistic): the
hosted world uses a crash, not a slow sink, to close its pod.
Demo: fails only on B (the recorded real hire does not exist yet).
