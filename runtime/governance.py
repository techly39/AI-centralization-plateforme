"""The Human's two levers, as the Runtime reads them (Constitution Art. 4–5).

``governance/HALT`` (exists → nothing wakes, no further tool batch runs) and
``governance/human.yaml: firm.monthly_llm_usd_cap`` (``null`` → nothing that
spends wakes, no key is provisioned).

Both paths are constants, not settings, for the reason physics gives in
``app/registry/halt.py``: a path that ``config.yaml`` or an env var could move
would be a way around the Human. The Runtime keeps its own copy instead of
importing physics' constant, because the dependency law (ADR-022) keeps
``runtime`` out of ``app``. Both files are read on every call — no cache — so a
change takes effect at the next wake or tool batch.

**Fail closed.** A cap the reader cannot read as a finite, non-negative number
— missing file, YAML error, duplicate key, missing key, a string, a bool,
``.inf``, a negative, a base-60 ``1:30``, any parser error — is read as ``null``,
with the reason in ``cap_problem``.
HALT counts if *anything* is at that path, a directory or a dangling link too,
and if the path cannot be checked at all (permission denied, ``governance`` not a
directory, or no ``governance/`` directory at all): only "the directory is there
and the file is not" means the world runs.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Tests point these at a temporary directory; nothing else may.
HALT_FILE = REPO_ROOT / "governance" / "HALT"
HUMAN_YAML = REPO_ROOT / "governance" / "human.yaml"


@dataclass(frozen=True)
class Governance:
    halted: bool
    #: ``None`` = the firm's spending agents do not run.
    monthly_llm_usd_cap: float | None
    #: Why the cap was read as ``None`` although the file did not say ``null``.
    cap_problem: str | None = None


def read_governance() -> Governance:
    halted = _halted(HALT_FILE)  # first, and independent of the cap file's health
    cap, problem = _read_cap(HUMAN_YAML)
    return Governance(halted=halted, monthly_llm_usd_cap=cap, cap_problem=problem)


def _halted(path: Path) -> bool:
    """Only a definite "no such file" means running. ``os.path.lexists`` would
    answer ``False`` on *any* error (an unreadable ``governance/``), failing open."""
    try:
        os.lstat(path)
    except FileNotFoundError:
        # Running only if the directory the Human halts in is there. A missing
        # ``governance/`` means REPO_ROOT is not the repo (a non-editable
        # install, a copied tree): the real HALT is unseen (red-team 0012 H3).
        return not path.parent.is_dir()
    except OSError:
        return True
    return True


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that refuses a duplicate key instead of keeping the last one."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark,
            )
        seen.add(key)
    return loader.construct_mapping(node)


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping,
)


def _refuse_sexagesimal(tag: str):
    """YAML 1.1 reads ``1:30`` as 90: a value written like a time must not
    become a number (red-team 0012 H7)."""
    base = yaml.SafeLoader.yaml_constructors[tag]

    def construct(loader: _UniqueKeyLoader, node: yaml.ScalarNode):
        if ":" in str(node.value):
            raise yaml.constructor.ConstructorError(
                None, None, f"base-60 number {node.value!r} refused", node.start_mark,
            )
        return base(loader, node)

    return construct


for _tag in ("tag:yaml.org,2002:int", "tag:yaml.org,2002:float"):
    _UniqueKeyLoader.add_constructor(_tag, _refuse_sexagesimal(_tag))


def load_unique_yaml(path: Path) -> object:
    """Safe-load a YAML file, refusing duplicate keys (the last one would win silently)."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)  # noqa: S506


def _read_cap(path: Path) -> tuple[float | None, str | None]:
    try:
        doc = load_unique_yaml(path)
    except OSError as exc:
        return None, f"cannot read {path.name}: {exc.__class__.__name__}"
    except Exception as exc:  # noqa: BLE001 - fail closed on *any* parse failure
        # YAMLError, UnicodeDecodeError, an unhashable key (TypeError), deep
        # nesting (RecursionError): a reader that raises is a gate that crashes.
        return None, f"{path.name} is not readable YAML: {exc.__class__.__name__}"
    firm = doc.get("firm") if isinstance(doc, dict) else None
    if not isinstance(firm, dict) or "monthly_llm_usd_cap" not in firm:
        return None, "firm.monthly_llm_usd_cap is missing"
    raw = firm["monthly_llm_usd_cap"]
    if raw is None:
        return None, None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, f"firm.monthly_llm_usd_cap is a {type(raw).__name__}, not a number"
    try:
        cap = float(raw)
    except OverflowError:
        return None, "firm.monthly_llm_usd_cap is too large"
    if not math.isfinite(cap) or cap < 0:
        return None, "firm.monthly_llm_usd_cap is not a finite, non-negative number"
    return cap, None
