"""Survey probe: the Human's OpenClaw, read-only (S-005, cycle 7).

Third survey probe, after ``survey_probe_physics.py`` and ``survey_probe_repo.py``.
It answers the questions ``bible/08_OPENCLAW.md`` §1–2 and §6 ask before any
adapter code exists: which version, which config keys that version really has,
how the Human's agents are set up, and how far each is from the firm standard.

It reads ``~/.openclaw`` and the installed CLI's own JSON schema; it writes
nothing and never runs a command that can change OpenClaw (no ``doctor``: even
without ``--fix`` it may run "safe migrations"). It never prints a secret: config
values under secret-looking keys are replaced by ``<redacted>``, auth profiles
are reported by provider and type only, and the workspace scan prints a path and
a pattern name, never the match.

Usage:
    uv run python scripts/survey_probe_openclaw.py [--state-dir ~/.openclaw]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

SECRET_KEY = re.compile(r"(token|secret|key|password|auth|credential|cookie|bearer)", re.I)
SECRET_VALUE = {
    "openrouter": re.compile(r"sk-or-[A-Za-z0-9\-_]{20,}"),
    "anthropic/openai": re.compile(r"sk-(ant-)?[A-Za-z0-9\-_]{20,}"),
    "fund-env": re.compile(r"\bfk_[A-Za-z0-9_\-]{20,}"),
    "telegram-bot": re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),
}
# Files O6 reads when scanning workspaces for credentials.
TEXT_SUFFIXES = {".md", ".txt", ".json", ".json5", ".yaml", ".yml", ".toml", ".env", ".py", ".sh"}


def openclaw(*args: str) -> str:
    return subprocess.run(
        ["openclaw", *args], capture_output=True, text=True, check=False
    ).stdout


def redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, str) and (SECRET_KEY.search(key) or any(
        p.search(value) for p in SECRET_VALUE.values()
    )):
        return "<redacted>"
    return value


def o1_version() -> None:
    print("O1  version")
    print(f"    {openclaw('--version').strip()}")


def o2_schema(schema: dict) -> None:
    """Which keys does this version's config schema really have?"""
    print("O2  config schema of the installed version (`openclaw config schema`)")
    props = schema["properties"]
    agents = props["agents"]["properties"]
    print(f"    agents.*: {sorted(agents)}")
    item = agents["list"]["items"]["properties"]
    print(f"    agents.list[] keys ({len(item)}): {sorted(item)}")
    print(f"    per-agent mcp key: {'mcp' in item}  (top-level mcp.*: {sorted(props['mcp']['properties'])})")
    print(f"    per-agent tools.*: {sorted(item['tools']['properties'])}")
    sb = item["sandbox"]["properties"]
    for k in ("mode", "workspaceAccess", "scope"):
        print(f"    sandbox.{k}: {[o['const'] for o in sb[k]['anyOf']]}")
    print(f"    top-level tools.*: {sorted(props['tools']['properties'])}")


def o3_config(cfg: dict) -> list[dict]:
    """The Human's agents against the firm standard (08_OPENCLAW §4)."""
    print("O3  ~/.openclaw/openclaw.json (redacted)")
    print(f"    top-level keys: {sorted(cfg)}")
    agents = cfg.get("agents", {}).get("list", [])
    bindings = cfg.get("bindings", [])
    per_agent = Counter(b.get("agentId") for b in bindings)
    defaults = cfg.get("agents", {}).get("defaults", {})
    print(f"    agents.defaults keys: {sorted(defaults)}")
    print(f"    agents.defaults.sandbox: {redact(defaults.get('sandbox'))}")
    print(f"    top-level tools: {json.dumps(redact(cfg.get('tools', {})), sort_keys=True)}")
    for a in agents:
        print(f"    - id={a.get('id')!r} model={a.get('model')!r} bindings={per_agent.get(a.get('id'), 0)}")
        print(f"      tools={json.dumps(redact(a.get('tools')), sort_keys=True)}")
        print(f"      sandbox={json.dumps(redact(a.get('sandbox')), sort_keys=True)}")
    servers = cfg.get("mcp", {}).get("servers", {})
    print(f"    mcp.servers: {len(servers)}")
    for name, s in servers.items():
        print(f"    - {name}: command={s.get('command')!r} url={s.get('url')!r} env_keys={sorted(s.get('env', {}))}")
    print(f"    channels: {sorted(cfg.get('channels', {}))}")
    print(f"    bindings: {len(bindings)} -> {dict(per_agent)}")
    return agents


def o4_workspaces(state: Path, agents: list[dict]) -> None:
    """Workspace + agentDir per agent: unique? which bootstrap files?"""
    print("O4  workspaces and agentDirs")
    seen: Counter[str] = Counter()
    for a in agents:
        ws = Path(a.get("workspace") or state / "workspace").expanduser()
        ad = Path(a.get("agentDir") or state / "agents" / a["id"] / "agent").expanduser()
        seen[str(ws)] += 1
        top = sorted(p.name for p in ws.glob("*.md")) if ws.is_dir() else ["<missing>"]
        print(f"    - {a['id']}: workspace={ws} exists={ws.is_dir()}")
        print(f"      bootstrap *.md: {top}")
        files = sorted(p.name for p in ad.iterdir()) if ad.is_dir() else ["<missing>"]
        print(f"      agentDir={ad} files={files}")
    for ws in seen:
        outer = [o for o in seen if o != ws and ws.startswith(o + "/")]
        if outer:
            print(f"    NOTE {ws} is nested inside another agent's workspace: {outer}")
    shared = [w for w, n in seen.items() if n > 1]
    print(f"    shared workspaces: {shared or 'none'}")


def o5_auth(state: Path, agents: list[dict]) -> None:
    """Does each agent have its own auth profile, or read through to main?"""
    print("O5  auth profiles (provider/type only, never a key)")
    for a in agents:
        ad = Path(a.get("agentDir") or state / "agents" / a["id"] / "agent").expanduser()
        f = ad / "auth-profiles.json"
        if not f.exists():
            print(f"    - {a['id']}: no auth-profiles.json in agentDir")
            continue
        data = json.loads(f.read_text())
        profiles = data.get("profiles", data)
        summary = sorted(
            f"{pid}:{p.get('provider', '?')}/{p.get('type', p.get('mode', '?'))}"
            for pid, p in profiles.items() if isinstance(p, dict)
        )
        print(f"    - {a['id']}: {summary}")


def o6_secret_scan(state: Path, agents: list[dict]) -> None:
    """Credentials written in workspace files (standard: never)."""
    print("O6  credential patterns in workspace files (path + pattern only)")
    roots = {Path(a.get("workspace") or state / "workspace").expanduser() for a in agents}
    hits: Counter[tuple[str, str]] = Counter()
    scanned = 0
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 2_000_000:
                continue
            scanned += 1
            text = p.read_text(errors="ignore")
            for name, rx in SECRET_VALUE.items():
                if rx.search(text):
                    hits[(str(p.relative_to(state)), name)] += 1
    print(f"    text files scanned: {scanned}; files with a credential pattern: {len(hits)}")
    for (path, name) in sorted(hits):
        print(f"    - {path}: {name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default="~/.openclaw")
    state = Path(ap.parse_args().state_dir).expanduser()
    cfg = json.loads((state / "openclaw.json").read_text())
    schema = json.loads(openclaw("config", "schema"))
    o1_version()
    o2_schema(schema)
    agents = o3_config(cfg)
    o4_workspaces(state, agents)
    o5_auth(state, agents)
    o6_secret_scan(state, agents)


if __name__ == "__main__":
    main()
