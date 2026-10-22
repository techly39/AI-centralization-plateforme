"""Onboarding.exe: the Runtime hires into a vacancy mid-run (idea: a dead pod is replaced).

Physics opens a vacancy when the risk ladder closes a pod and names the hire (``app.capital.hiring``:
the new pod's and PM's names, the model, the thinking budget, the charter, by the firm's hiring
law). The Runtime carries it out. Every morning of a run given a hiring **template** (the mind's
plumbing the law does not name: provider, adapter, script, tools), before anyone wakes, the
conductor calls :meth:`Onboarding.morning`; for each open vacancy, oldest first:

1. HALT is read (a HALT stops the run ``halted``, as before any wake);
2. the wake gate must open for the template under one read of the law, and a metered hire's
   budget must fit the cap **with every key the firm already holds** (the provisioner's whole
   month where it can count it, else the run's keys). If either fails, the Runtime refuses the
   hire in physics' ledger (``POST /vacancies/{id}/refuse``) and the vacancy stays open;
3. the registrar fills it (``POST /vacancies/{id}/fill``): physics makes the pod and the PM and
   may itself refuse (the firm's pod limit: 409, written by physics);
4. the answer must be the agent the law named; its key's ``/me`` must say so too;
5. a metered mind's key is minted for that agent with the hire's budget as its limit (the
   OpenRouter provisioner mints under its lock and refuses a mint the month cannot hold: then the
   new agent is deactivated, so no PM lives without a mind);
6. the mind joins the roster from this step on. Every wake it is handed, beside the run's input,
   the **post-mortem** of the pod it replaces (it remembers nothing else).

Each decision is a :class:`HireRecord` in the run's record. A **replay** follows the recording's
decisions instead of re-deciding (a replay spends nothing, so it cannot ask the cap the recorded
question): the same refusals posted, the same fills made; physics answering otherwise, or a
vacancy the recording did not act on, ends the run ``diverged:hire:<step>:0:hire``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mcp_server.client import FundAPIError, FundClient
from runtime.gate import METERED_PROVIDERS, decide_batch, decide_wake_under
from runtime.governance import Governance, load_unique_yaml, read_governance
from runtime.lockstep import Mind
from runtime.metering import FakeProvisioner, Meter, usd_to_micros_floor
from runtime.openrouter import OpenRouterProvisioner, OverCap
from runtime.registry import ProviderRefused, check_spec
from runtime.replay import HireRecord, as_cassette
from runtime.spec import AgentSpec, SpecError

#: The prefix of a hired mind's spec id; a run that hires may not use it for its own minds.
HIRE_PREFIX = "hire-"
#: Providers that run no model: a hire through them carries no model.
_NO_MODEL = frozenset({"scripted", "fake-metered"})


class HireTemplate(BaseModel):
    """What the operator gives a run to hire with: the plumbing of the new PM's mind. The law
    (physics) names the rest: name, pod, model, budget, charter."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    adapter: Literal["native", "openclaw"] = "native"
    script: str | None = None
    tools: tuple[str, ...] | None = None
    #: An analyst's plumbing, when a PM's team place is filled (idea: a PM builds its team): its
    #: script (a scripted provider) and its tools; the place names the rest.
    analyst_script: str | None = None
    analyst_tools: tuple[str, ...] | None = None


def load_template(path: Path) -> HireTemplate:
    try:
        return HireTemplate.model_validate(load_unique_yaml(path))
    except (OSError, ValueError, ValidationError) as exc:
        raise SpecError(f"{path}: not a hiring template ({type(exc).__name__})") from exc


def spec_for(template: HireTemplate, hire: Mapping[str, Any], *, spec_id: str,
             pod_id: int) -> AgentSpec:
    """The new PM's spec: the template's plumbing, the law's hire."""
    provider = template.provider
    return AgentSpec(
        id=spec_id, name=hire["pm_name"], role="pm", pod=pod_id, provider=provider,
        script=template.script, adapter=template.adapter,
        model=None if provider in _NO_MODEL else hire["model"], charter=hire["charter"],
        tools=template.tools,
        budget_usd=float(hire["budget_usd"]) if provider in METERED_PROVIDERS else 0.0)


#: What every analyst a PM hires is told before its PM's own words (its charter in the place).
ANALYST_BRIEF = (
    "You are {name}, an analyst in pod {pod} of a hedge fund that trades a simulated market with "
    "fake money. Your PM, {pm}, asked for you and pays for you: every word you think is paid "
    "from your pod. You research (run_research_backtest: every backtest counts as one of your "
    "pod's attempts when your PM pitches), read the firm's library and message your PM (its id "
    "is {pm_id}); you cannot pitch, trade or hire. You remember nothing between days: read your "
    "messages and your pod's research first. When you are done for the day, stop.\n"
    "Your PM's charter for you:\n{charter}")


def analyst_spec(template: HireTemplate, place: Mapping[str, Any], *, name: str,
                 pod_id: int) -> AgentSpec:
    """A hired analyst's spec: the template's analyst plumbing, the place's charter, model and
    budget. Its spec id is its name (physics names it once)."""
    provider = template.provider
    return AgentSpec(
        id=name, name=name, role="analyst", pod=pod_id, provider=provider,
        script=template.analyst_script, adapter=template.adapter,
        model=None if provider in _NO_MODEL else place["model"],
        charter=ANALYST_BRIEF.format(name=name, pod=place["pod_name"], pm=place["asked_by_name"],
                                     pm_id=place["asked_by"], charter=place["charter"]),
        tools=template.analyst_tools,
        budget_usd=float(place["budget_usd"]) if provider in METERED_PROVIDERS else 0.0)


def probe_spec(template: HireTemplate) -> AgentSpec:
    """A spec of the template's kind, for checks that need no vacancy (``mind_kinds``, ``vet``)."""
    return spec_for(template, {"pm_name": "hire-probe", "model": "probe/model", "budget_usd": 0.01,
                               "charter": "probe"}, spec_id="hire-probe", pod_id=1)


def vet_template(template: HireTemplate, law: Governance) -> str | None:
    """Why a hire through ``template`` could never wake under ``law``, else ``None``."""
    spec = probe_spec(template)
    decision = decide_wake_under(spec.provider, spec.adapter, law,
                                 metered=spec.provider in METERED_PROVIDERS)
    if not decision.allowed and decision.reason != "halted":
        return f"hire_template:wake_refused:{decision.reason}"
    try:
        check_spec(spec)
    except ProviderRefused as exc:
        return f"hire_template:provider_refused:{exc.reason}"
    return None


class Onboarding:
    """The hiring a run does. ``minds`` holds every mind it hired (the caller meters and closes
    them); ``inputs`` the post-mortem each one is handed."""

    def __init__(self, template: HireTemplate, registrar: FundClient,
                 connect: Callable[[str], FundClient], *,
                 provisioner: FakeProvisioner | OpenRouterProvisioner | None = None,
                 recorded: Sequence[HireRecord] | None = None) -> None:
        self.template = template
        self.registrar = registrar
        self.connect = connect
        self.provisioner = provisioner
        #: A replay's decisions, by (step, kind, vacancy or place id); ``None`` live.
        self.recorded = (None if recorded is None
                         else {(r.step, r.kind, r.vacancy_id): r for r in recorded})
        self.minds: list[Mind] = []
        self.inputs: dict[str, dict[str, Any]] = {}
        #: Vacancies whose key the month could not hold: refused, not retried, this run.
        self.no_room: set[int] = set()

    async def morning(self, step: int, *, taken: set[str], meters: Sequence[Meter]
                      ) -> tuple[list[HireRecord], list[Mind], tuple[str, str] | None]:
        """Act on every open vacancy: ``(records, new minds, stop)``; ``stop`` ends the run."""
        try:
            listed = await self.registrar.get("/vacancies")
        except FundAPIError as exc:
            return [], [], ("error", f"hiring_unreadable:{exc.status_code}")
        if not isinstance(listed, list):
            return [], [], ("error", "hiring_malformed")
        records: list[HireRecord] = []
        new: list[Mind] = []
        law = read_governance()  # one read of the law for the morning
        open_ = sorted((v for v in listed if isinstance(v, dict) and v.get("status") == "open"),
                       key=lambda v: v.get("id", 0))
        if any(v.get("fill_from") is not None for v in open_):
            # The management law: a listed place waits for the manager's pick until its morning
            # (no record: physics said when, and a replay reads the same vacancy).
            try:
                clock = await self.registrar.get("/clock")
            except FundAPIError as exc:
                return [], [], ("error", f"hiring_unreadable:{exc.status_code}")
            today = str((clock or {}).get("now", ""))[:10] if isinstance(clock, dict) else ""
            if not today:
                return [], [], ("error", "hiring_malformed")
            open_ = [v for v in open_ if v.get("fill_from") is None
                     or (type(v["fill_from"]) is str and v["fill_from"] <= today)]
        for vacancy in open_:
            if not decide_batch().allowed:
                return records, new, ("halted", "halted")
            try:
                record, mind = await self._one(step, vacancy, taken, meters, law)
            except _Diverged:
                return records, new, ("diverged", f"diverged:hire:{step}:0:hire")
            except _Failed as exc:
                if not decide_batch().allowed:   # HALT landed mid-hire: physics refused it (423)
                    return records, new, ("halted", "halted")
                return records, new, ("error", exc.reason)
            records.append(record)
            if mind is not None:
                new.append(mind)
                taken.add(mind.spec.id)
                meters = [*meters, *([mind.meter] if mind.meter is not None else [])]
        team, stop = await self._team_morning(step, taken, meters, law)
        for record, mind in team:
            records.append(record)
            if mind is not None:
                new.append(mind)
        if stop is not None:
            return records, new, stop
        if self.recorded is not None:
            acted = {(r.step, r.kind, r.vacancy_id) for r in records}
            if any(key[0] == step and key not in acted for key in self.recorded):
                return records, new, ("diverged", f"diverged:hire:{step}:0:hire")
        return records, new, None

    async def _one(self, step: int, vacancy: dict[str, Any], taken: set[str],
                   meters: Sequence[Meter], law: Governance) -> tuple[HireRecord, Mind | None]:
        vid, hire = vacancy.get("id"), vacancy.get("hire")
        if type(vid) is not int or not isinstance(hire, dict) or type(vacancy.get("vacancy_no")) is not int:
            raise _Failed("hiring_malformed")
        # The law's names; physics may give the next free ``<base>-<k>`` (app/capital/hiring.py).
        base = f"{HIRE_PREFIX}{vacancy['vacancy_no']}"
        recorded = None
        if self.recorded is not None:
            recorded = self.recorded.get((step, "pm", vid))
            if recorded is None:
                raise _Diverged()
            decision = (recorded.outcome, recorded.reason)
        else:
            decision = await self._population(law) or self._decide(vid, base, hire, meters, law)
        outcome, reason = decision

        def record(spec_id: str, done: str, agent_id: int | None = None,
                   why: str | None = None) -> HireRecord:
            made = HireRecord(step, vid, spec_id, done, agent_id, why)
            if recorded is not None and made != recorded:
                raise _Diverged()
            return made

        if outcome not in ("hired", "refused:physics:409", "refused:key_over_cap"):
            # The Runtime's own refusal, written in physics' ledger; the vacancy stays open.
            try:
                await self.registrar.post(f"/vacancies/{vid}/refuse", {"reason": reason})
            except FundAPIError as exc:
                raise _Failed(f"hire_refusal_failed:{vid}:{exc.status_code}") from exc
            return record(base, outcome, None, reason), None
        try:
            made = await self.registrar.post(f"/vacancies/{vid}/fill", {})
        except FundAPIError as exc:
            if exc.status_code == 409:   # physics refused (its pod limit) and wrote why
                return record(base, "refused:physics:409"), None
            raise _Failed(f"hire_failed:{vid}:{exc.status_code}") from exc
        agent = made.get("agent") if isinstance(made, dict) else None
        filled = ((made.get("vacancy") or {}).get("filled") or {}) if isinstance(made, dict) else {}
        pod_name = filled.get("pod_name")
        if not (isinstance(agent, dict) and type(agent.get("id")) is int
                and type(agent.get("pod_id")) is int and type(pod_name) is str
                and (pod_name == base or pod_name.startswith(base + "-"))
                and agent.get("name") == f"{pod_name}-pm" and filled.get("pod_id") == agent["pod_id"]
                and agent.get("role") == "pm" and type(agent.get("api_key")) is str
                and agent["api_key"]):
            raise _Failed(f"hire_wrong_agent:{vid}")
        # The mind is made from what physics hired (its fill's answer), not from the listing read
        # before it (red-team, a manager chooses the hires: a pick landing between the two).
        answered = made.get("vacancy")
        if isinstance(answered, dict) and isinstance(answered.get("hire"), dict):
            vacancy, hire = answered, answered["hire"]
        spec_id = pod_name   # unique: physics names pods once; the run's own ids cannot be hire-*
        if spec_id in taken:
            raise _Failed(f"hire_spec_taken:{spec_id}")
        spec = spec_for(self.template, {**hire, "pm_name": agent["name"]}, spec_id=spec_id,
                        pod_id=agent["pod_id"])
        if self.recorded is not None:
            spec = as_cassette(spec)
        client = self.connect(agent["api_key"])
        try:
            who = await client.get("/me")
            if not isinstance(who, dict) or (who.get("id"), who.get("name"), who.get("role"),
                                             who.get("pod_id")) != (agent["id"], spec.name, "pm",
                                                                    spec.pod):
                raise _Failed(f"hire_wrong_agent:{vid}")
            meter: Meter | None = None
            if self.recorded is not None:      # a replay mints nothing: its minds are cassettes
                over_cap = outcome == "refused:key_over_cap"
            elif spec.provider in METERED_PROVIDERS:
                meter = await self._mint(spec, agent["id"])
                over_cap = meter is None
            else:
                over_cap = False
            if over_cap:
                # No PM lives without a mind: the new agent is deactivated (physics then closes
                # its empty pod and opens the vacancy again), and the Runtime does not mint for
                # this vacancy again this run.
                await client.aclose()
                await self._deactivate(agent["id"])
                self.no_room.add(vid)
                return record(spec_id, "refused:key_over_cap", agent["id"]), None
            done = record(spec_id, "hired", agent["id"])
        except BaseException:
            await client.aclose()
            raise
        mind = Mind(spec, client, meter)
        self.minds.append(mind)
        self.inputs[spec_id] = {"post_mortem": vacancy.get("post_mortem"), "vacancy_id": vid}
        hire = vacancy.get("hire") or {}
        if hire.get("design") == "child":   # the reproduction law: the child knows its parent
            self.inputs[spec_id] |= {k: hire.get(k) for k in (
                "parent", "family", "change", "inherited_rule", "lineage_attempts")}
        picked = vacancy.get("picked")
        if isinstance(picked, dict):        # the management law: the manager's brief to it
            self.inputs[spec_id]["brief"] = {"text": picked.get("brief"), "by": picked.get("by")}
        return done, mind

    async def _team_morning(self, step: int, taken: set[str], meters: Sequence[Meter],
                            law: Governance
                            ) -> tuple[list[tuple[HireRecord, Mind | None]], tuple[str, str] | None]:
        """Act on every open team place a PM was granted (idea: a PM builds its team), oldest
        first, after the vacancies: ``([(record, mind)], stop)``."""
        try:
            listed = await self.registrar.get("/team/places")
        except FundAPIError as exc:
            return [], ("error", f"hiring_unreadable:{exc.status_code}")
        if not isinstance(listed, list):
            return [], ("error", "hiring_malformed")
        done: list[tuple[HireRecord, Mind | None]] = []
        meters = list(meters)
        for place in sorted((p for p in listed if isinstance(p, dict) and p.get("status") == "open"),
                            key=lambda p: p.get("id", 0)):
            if not decide_batch().allowed:
                return done, ("halted", "halted")
            try:
                record, mind = await self._one_team(step, place, taken, meters, law)
            except _Diverged:
                return done, ("diverged", f"diverged:hire:{step}:0:hire")
            except _Failed as exc:
                if not decide_batch().allowed:
                    return done, ("halted", "halted")
                return done, ("error", exc.reason)
            done.append((record, mind))
            if mind is not None:
                taken.add(mind.spec.id)
                meters += [mind.meter] if mind.meter is not None else []
        return done, None

    async def _one_team(self, step: int, place: dict[str, Any], taken: set[str],
                        meters: Sequence[Meter], law: Governance
                        ) -> tuple[HireRecord, Mind | None]:
        pid, base = place.get("id"), place.get("name")
        if (type(pid) is not int or type(base) is not str or type(place.get("pod_id")) is not int
                or type(place.get("asked_by")) is not int):
            raise _Failed("hiring_malformed")
        recorded = None
        if self.recorded is not None:
            recorded = self.recorded.get((step, "analyst", pid))
            if recorded is None:
                raise _Diverged()
            outcome, reason = recorded.outcome, recorded.reason
        else:
            outcome, reason = (await self._population(law)
                               or self._decide_analyst(pid, place, meters, law))

        def record(spec_id: str, done: str, agent_id: int | None = None,
                   why: str | None = None) -> HireRecord:
            made = HireRecord(step, pid, spec_id, done, agent_id, why, kind="analyst")
            if recorded is not None and made != recorded:
                raise _Diverged()
            return made

        if outcome not in ("hired", "refused:physics:409", "refused:key_over_cap"):
            try:
                await self.registrar.post(f"/team/places/{pid}/refuse", {"reason": reason})
            except FundAPIError as exc:
                raise _Failed(f"hire_refusal_failed:{pid}:{exc.status_code}") from exc
            return record(base, outcome, None, reason), None
        try:
            made = await self.registrar.post(f"/team/places/{pid}/fill", {})
        except FundAPIError as exc:
            if exc.status_code == 409:   # physics refused (the cap) or closed the place: written
                return record(base, "refused:physics:409"), None
            raise _Failed(f"hire_failed:{pid}:{exc.status_code}") from exc
        agent = made.get("agent") if isinstance(made, dict) else None
        name = agent.get("name") if isinstance(agent, dict) else None
        if not (isinstance(agent, dict) and type(agent.get("id")) is int
                and agent.get("pod_id") == place["pod_id"] and type(name) is str
                and (name == base or name.startswith(base + "-"))
                and agent.get("role") == "analyst" and type(agent.get("api_key")) is str
                and agent["api_key"]):
            raise _Failed(f"hire_wrong_agent:{pid}")
        if name in taken:
            raise _Failed(f"hire_spec_taken:{name}")
        spec = analyst_spec(self.template, place, name=name, pod_id=place["pod_id"])
        if self.recorded is not None:
            spec = as_cassette(spec)
        client = self.connect(agent["api_key"])
        try:
            who = await client.get("/me")
            if not isinstance(who, dict) or (who.get("id"), who.get("name"), who.get("role"),
                                             who.get("pod_id")) != (agent["id"], name, "analyst",
                                                                    place["pod_id"]):
                raise _Failed(f"hire_wrong_agent:{pid}")
            meter: Meter | None = None
            if self.recorded is not None:
                over_cap = outcome == "refused:key_over_cap"
            elif spec.provider in METERED_PROVIDERS:
                meter = await self._mint(spec, agent["id"])
                over_cap = meter is None
            else:
                over_cap = False
            if over_cap:
                # No analyst lives without a mind: deactivated (physics lets it go from its place).
                await client.aclose()
                await self._deactivate(agent["id"])
                return record(name, "refused:key_over_cap", agent["id"]), None
            done = record(name, "hired", agent["id"])
        except BaseException:
            await client.aclose()
            raise
        mind = Mind(spec, client, meter)
        self.minds.append(mind)
        self.inputs[name] = {"team_place_id": pid, "hired_by": place["asked_by_name"],
                             "hired_by_id": place["asked_by"]}
        return done, mind

    def _decide_analyst(self, pid: int, place: dict[str, Any], meters: Sequence[Meter],
                        law: Governance) -> tuple[str, str | None]:
        probe = analyst_spec(self.template, place, name="probe-analyst-1", pod_id=1)
        metered = probe.provider in METERED_PROVIDERS
        gate = decide_wake_under(probe.provider, probe.adapter, law, metered=metered)
        if not gate.allowed:
            return (f"refused:wake_gate:{gate.reason}",
                    f"the analyst's mind could not wake under the Human's law ({gate.reason})")
        try:
            check_spec(probe)
        except ProviderRefused as exc:
            raise _Failed(f"hire_template:provider_refused:{exc.reason}") from exc
        if metered:
            cap = usd_to_micros_floor(law.monthly_llm_usd_cap)
            limit = usd_to_micros_floor(probe.budget_usd)
            held = self._held(meters)
            if held is None or held + limit > cap:
                return ("refused:budget_over_cap",
                        f"the analyst's thinking budget (${probe.budget_usd:.2f}) does not fit the "
                        f"monthly cap (${cap / 1e6:.2f}) with the keys the firm already holds")
        return "hired", None

    async def _population(self, law: Governance) -> tuple[str, str] | None:
        """A refusal when one more agent would take the firm past the Human's
        ``firm.max_agents_total`` (alive agents, every role, as physics' directory lists them),
        or when that cap cannot be read; ``None``: the hire may be weighed."""
        if law.agents_problem is not None or law.max_agents_total is None:
            return ("refused:agents_cap_unreadable",
                    f"the Human's agent cap cannot be read ({law.agents_problem})")
        try:
            listed = await self.registrar.get("/agents")
        except FundAPIError as exc:
            raise _Failed(f"directory_unreadable:{exc.status_code}") from exc
        if not isinstance(listed, list):
            raise _Failed("directory_malformed")
        alive = sum(1 for a in listed if not isinstance(a, dict) or a.get("status") != "inactive")
        if alive + 1 > law.max_agents_total:
            return ("refused:agents_over_cap",
                    f"the firm holds {alive} alive agents: one more passes the Human's cap "
                    f"of {law.max_agents_total}")
        return None

    def _decide(self, vid: int, base: str, hire: dict[str, Any], meters: Sequence[Meter],
                law: Governance) -> tuple[str, str | None]:
        if vid in self.no_room:
            return ("refused:no_key_room", "the month could not hold the new PM's key: the "
                    "Runtime does not try this vacancy again this run")
        probe = spec_for(self.template, hire, spec_id=base, pod_id=1)
        metered = probe.provider in METERED_PROVIDERS
        gate = decide_wake_under(probe.provider, probe.adapter, law, metered=metered)
        if not gate.allowed:
            return (f"refused:wake_gate:{gate.reason}",
                    f"the new PM's mind could not wake under the Human's law ({gate.reason})")
        try:
            check_spec(probe)
        except ProviderRefused as exc:
            raise _Failed(f"hire_template:provider_refused:{exc.reason}") from exc
        if metered:
            cap = usd_to_micros_floor(law.monthly_llm_usd_cap)
            limit = usd_to_micros_floor(probe.budget_usd)
            held = self._held(meters)
            if held is None or held + limit > cap:
                return ("refused:budget_over_cap",
                        f"the new PM's thinking budget (${probe.budget_usd:.2f}) does not fit the "
                        f"monthly cap (${cap / 1e6:.2f}) with the keys the firm already holds")
        return "hired", None

    def _held(self, meters: Sequence[Meter]) -> int | None:
        """Micro-dollars the firm's keys already hold: the provisioner's month where it can count
        it (``None``: it cannot, so nothing more is minted), else the run's keys' limits."""
        if self.provisioner is None:
            return None
        month = getattr(self.provisioner, "month_committed", None)
        if month is not None:
            try:
                return int(month())
            except Exception:  # noqa: BLE001 - an unreadable month holds no room
                return None
        return sum(self.provisioner.limit(m.key_ref) for m in meters
                   if m.provisioner is self.provisioner)

    async def _mint(self, spec: AgentSpec, agent_id: int) -> Meter | None:
        """The hire's key; ``None`` when the month cannot hold it (the provisioner's refusal)."""
        if self.provisioner is None:
            raise _Failed(f"hire_no_provisioner:{spec.id}")
        limit = usd_to_micros_floor(spec.budget_usd)
        try:
            if isinstance(self.provisioner, OpenRouterProvisioner):
                key = self.provisioner.create_key(agent_id, limit, spec_id=spec.id)
            else:
                key = self.provisioner.create_key(agent_id, limit)
        except OverCap:
            return None
        except Exception as exc:  # noqa: BLE001 - the agent exists, its key does not
            await self._deactivate(agent_id)
            raise _Failed(f"hire_key_failed:{spec.id}") from exc
        return Meter(self.provisioner, key)

    async def _deactivate(self, agent_id: int) -> None:
        try:
            await self.registrar.post(f"/agents/{agent_id}/deactivate", {})
        except FundAPIError as exc:
            raise _Failed(f"hire_deactivate_failed:{agent_id}:{exc.status_code}") from exc


class _Diverged(Exception):
    pass


class _Failed(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
