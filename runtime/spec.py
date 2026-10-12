"""The AgentSpec — an agent's genome (bible/03_WORLD.md §3).

Data the operator (today: the Builder's tests and, later, workflows through the
App) writes; no mind can edit its own. File-backed for now (one YAML file per
agent in a directory); "stored in the App, mirrored to files" comes when the
App grows a spec table.

Fields are 03 §3's, plus ``provider`` (ADR-032 (3): a mind = provider + adapter
+ spec — the gate decides on it) and ``script`` (R-2: which scripted policy).
The spec carries no cost claim: what may run under the cap is the gate's list,
not the spec's word. A spec loads even if its fields contradict each other
(``scripted`` + a model); :mod:`runtime.registry` refuses to build a mind from it.

``role`` is a role a mind may hold: ``system`` is physics' own identity and the
clock-holding ``runtime`` identity (R-3) is the Runtime's, never a mind's.
Ids order the lockstep wake (ADR-032 (5)), so they are unique and plain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from runtime.governance import load_unique_yaml


class SpecError(ValueError):
    """A spec file or directory the Runtime refuses to load. Names the file."""


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,62}$")
    name: str = Field(min_length=1, max_length=64)
    role: Literal["pm", "analyst", "management"]
    pod: int | None = Field(default=None, ge=1)
    parent_id: str | None = None
    generation_born: int = Field(default=0, ge=0)
    provider: str = Field(min_length=1)
    #: For ``provider: scripted`` only: which policy in :data:`runtime.scripted.SCRIPTS`.
    script: str | None = None
    adapter: Literal["native", "openclaw"] = "native"
    model: str | None = None
    charter: str = Field(min_length=1)
    #: ``None`` = the full published tool surface; a list narrows it (R-2).
    tools: tuple[str, ...] | None = None
    memory_policy: Literal["none"] = "none"
    budget_usd: float = Field(default=0.0, ge=0)
    #: Backtest lockstep: wake on every step, or never (a spec kept on file).
    wake_policy: Literal["every_step", "never"] = "every_step"
    mutations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _pod_roles_have_a_pod(self) -> AgentSpec:
        if self.role in {"pm", "analyst"} and self.pod is None:
            raise ValueError(f"a {self.role} belongs to a pod: set `pod`")
        return self


def load_specs(directory: Path) -> list[AgentSpec]:
    """Every ``*.yaml`` spec in ``directory``, in id order (the wake order)."""
    if not directory.is_dir():
        raise SpecError(f"spec directory not found: {directory}")
    specs: dict[str, AgentSpec] = {}
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        if path.suffix != ".yaml":  # a spec that would be silently skipped is refused
            raise SpecError(f"{path.name}: spec files end in `.yaml`")
        try:
            doc = load_unique_yaml(path)
        except Exception as exc:  # noqa: BLE001 - any unreadable spec is refused by name
            raise SpecError(f"{path.name}: unreadable ({exc.__class__.__name__})") from exc
        if not isinstance(doc, dict):
            raise SpecError(f"{path.name}: a spec is a mapping of fields")
        try:
            spec = AgentSpec.model_validate(doc)
        except (ValidationError, TypeError) as exc:  # a non-str key is a TypeError (0012 H5)
            raise SpecError(f"{path.name}: {exc}") from exc
        if spec.id in specs:
            raise SpecError(f"{path.name}: duplicate spec id {spec.id!r}")
        specs[spec.id] = spec
    return [specs[k] for k in sorted(specs)]
