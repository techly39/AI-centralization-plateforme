"""``uv run fund-runtime`` — the Runtime's entry point.

R-1 has one command, and it wakes nothing:

    fund-runtime status [--specs DIR]

prints the law as the Runtime reads it (HALT, cap, any cap problem) and, for
every spec in ``DIR``, what the wake gate would decide right now. Exit 1 if a
spec file is refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from runtime.gate import decide_wake_under
from runtime.governance import read_governance
from runtime.spec import SpecError, load_specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fund-runtime", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    status = sub.add_parser("status", help="show the law and what the gate would wake (wakes nothing)")
    status.add_argument("--specs", type=Path, help="directory of AgentSpec YAML files")
    args = parser.parse_args(argv)

    try:
        specs = load_specs(args.specs) if args.specs else []
    except SpecError as exc:
        print(f"fund-runtime: {exc}", file=sys.stderr)
        return 1
    law = read_governance()  # one read for one report
    wakes = []
    for spec in specs:
        d = decide_wake_under(spec.provider, spec.adapter, law)
        wakes.append({"id": spec.id, "provider": spec.provider, "adapter": spec.adapter,
                      "allowed": d.allowed, "reason": d.reason})
    print(json.dumps({
        "halted": law.halted,
        "monthly_llm_usd_cap": law.monthly_llm_usd_cap,
        "cap_problem": law.cap_problem,
        "wakes": wakes,
        "woke": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
