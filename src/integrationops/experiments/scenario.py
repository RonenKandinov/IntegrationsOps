"""Reusable experiment scenario. Decision methods are not selected here."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Protocol

from integrationops.experiments.ground_truth import ScenarioGroundTruth, build_ground_truth
from integrationops.experiments.metrics import TraceStep
from integrationops.experiments.topologies import timeline_events
from integrationops.experiments.work import (
    CapacityConstraint,
    WorkItem,
    default_capacities,
    derive_work_items,
    sla_window_for,
)
from integrationops.generators.organization import (
    PROFILES,
    OrganizationWorld,
    generate_organization,
    generate_organizations,
)
from integrationops.operations.actions import all_actions, feasible_actions
from integrationops.operations.constants import ACTION_INVESTIGATE
from integrationops.operations.snapshot import ChainSnapshot, observe_chain
from integrationops.operations.state import SystemState
from integrationops.operations.transition import InfeasibleActionError, transition
from integrationops.operations.types import CandidateAction, OperationalEvent
from integrationops.store.errors import EvidenceNotFound


@dataclass
class MethodInput:
    """Exact payload every future decision method receives for one moment."""

    state: SystemState
    actions: list[CandidateAction]
    feasible_actions: list[CandidateAction]
    work_items: list[WorkItem] = field(default_factory=list)
    capacities: list[CapacityConstraint] = field(default_factory=list)


class DecisionMethod(Protocol):
    """Hook for a later established approach. Not implemented in this package."""

    name: str

    def choose(self, payload: MethodInput) -> CandidateAction | None:
        """Return a_t or None. Must not mutate payload.state."""


@dataclass
class NullDecisionMethod:
    """Placeholder that never chooses. Useful to replay events only."""

    name: str = "null"

    def choose(self, payload: MethodInput) -> CandidateAction | None:
        return None


@dataclass
class ScheduledEvent:
    time: int
    event: OperationalEvent


@dataclass
class ScenarioFrame:
    """Serializable snapshot of S_t plus A(S_t) and A_f(S_t)."""

    time: int
    seed: int
    profile: str
    merchant_ids: list[str]
    lender_ids: list[str]
    incident_ids: list[str]
    operational_integrations: int
    blocked_work: int
    actions: list[tuple[str, str]]
    feasible_actions: list[tuple[str, str]]
    task_states: dict[str, str]
    constraint_ids: list[str]


@dataclass
class Scenario:
    """A reproducible experimental case. Methods see the same frames."""

    scenario_id: str
    seed: int
    profile: str
    topology: str
    horizon: int
    world: OrganizationWorld
    initial_state: SystemState
    timeline: list[ScheduledEvent] = field(default_factory=list)
    work_items: list[WorkItem] = field(default_factory=list)
    capacities: list[CapacityConstraint] = field(default_factory=list)
    ground_truth: ScenarioGroundTruth | None = None
    chain_snapshot: ChainSnapshot | None = None
    metadata: dict = field(default_factory=dict)

    def method_input(self, state: SystemState) -> MethodInput:
        frozen = copy.deepcopy(state)
        work_items = derive_work_items(
            frozen,
            sla_window=sla_window_for(self.profile),
            templates=self.work_items,
        )
        return MethodInput(
            state=frozen,
            actions=all_actions(frozen),
            feasible_actions=feasible_actions(frozen),
            work_items=work_items,
            capacities=copy.deepcopy(self.capacities),
        )

    def frame(self, state: SystemState) -> ScenarioFrame:
        payload = self.method_input(state)
        return snapshot_frame(self, payload)

    def events_at(self, time: int) -> list[OperationalEvent]:
        return [item.event for item in self.timeline if item.time == time]


def snapshot_frame(scenario: Scenario, payload: MethodInput) -> ScenarioFrame:
    state = payload.state
    blocked = sum(1 for status in state.task_states.values() if status == "Blocked")
    return ScenarioFrame(
        time=state.time,
        seed=scenario.seed,
        profile=scenario.profile,
        merchant_ids=[item.merchant_id for item in state.merchants],
        lender_ids=[item.lender_id for item in state.lenders],
        incident_ids=[item.incident_id for item in state.incidents],
        operational_integrations=sum(1 for item in state.integrations if item.operational),
        blocked_work=blocked,
        actions=[(item.kind, item.target_id) for item in payload.actions],
        feasible_actions=[(item.kind, item.target_id) for item in payload.feasible_actions],
        task_states=dict(state.task_states),
        constraint_ids=[item.constraint_id for item in state.resources],
    )


def generate_scenario(
    *,
    profile: str = "small",
    seed: int = 1,
    organization_count: int = 1,
    horizon: int | None = None,
    topology: str = "shared_bottleneck",
) -> Scenario:
    """Build a dynamic scenario. Same arguments yield the same S_0 and timeline."""
    if organization_count == 1:
        world = generate_organization(
            profile=profile, seed=seed, organization_index=1, topology=topology
        )
    else:
        worlds = generate_organizations(
            profile=profile, seed=seed, count=organization_count, topology=topology
        )
        world = _merge_worlds(worlds, seed=seed, profile=profile, topology=topology)
    ticks = horizon if horizon is not None else int(PROFILES[profile]["horizon"])
    initial = world.to_system_state(time=0)
    rng = random.Random(seed + 17)
    raw_timeline = timeline_events(world, rng, ticks, topology)
    timeline = [ScheduledEvent(time=tick, event=event) for tick, event in raw_timeline]
    work_items = derive_work_items(initial, sla_window=sla_window_for(profile))
    capacities = default_capacities(initial, topology=topology)
    truth = build_ground_truth(
        topology=topology,
        seed=seed,
        state=initial,
        timeline=raw_timeline,
        work_items=work_items,
        capacities=capacities,
        dependencies=initial.dependencies,
    )
    chain = _primary_chain(world)
    return Scenario(
        scenario_id=f"scn-{topology}-{profile}-{seed}",
        seed=seed,
        profile=profile,
        topology=topology,
        horizon=ticks,
        world=world,
        initial_state=initial,
        timeline=timeline,
        work_items=work_items,
        capacities=capacities,
        ground_truth=truth,
        chain_snapshot=chain,
        metadata={
            "seed": seed,
            "profile": profile,
            "topology": topology,
            "horizon": ticks,
            "organization_id": world.organization.organization_id,
            "generator": "experiments",
        },
    )


def generate_timeline(
    world: OrganizationWorld,
    rng,
    horizon: int,
    topology: str = "shared_bottleneck",
) -> list[ScheduledEvent]:
    """Ω over time. Events are applied later through T; nothing is executed in production."""
    return [
        ScheduledEvent(time=tick, event=event)
        for tick, event in timeline_events(world, rng, horizon, topology)
    ]


def apply_step(
    state: SystemState,
    *,
    action: CandidateAction | None = None,
    event: OperationalEvent | None = None,
    events: list[OperationalEvent] | None = None,
    diagnosis=None,
) -> tuple[SystemState, bool]:
    """Apply one tick of T. Every event in the tick is applied, and time advances once."""
    scheduled = list(events) if events is not None else ([] if event is None else [event])
    tick = state.time + 1
    run_action = action
    action_diagnosis = diagnosis
    succeeded = True
    if action is not None and action.kind == ACTION_INVESTIGATE and diagnosis is None:
        action_diagnosis = _engine_diagnosis(state, action.target_id)
        if action_diagnosis is None:
            run_action = None
            succeeded = False
    if run_action is None and not scheduled:
        nxt = copy.deepcopy(state)
        nxt.time = tick
        return nxt, succeeded
    head = scheduled[0] if scheduled else None
    try:
        nxt = transition(state, run_action, head, diagnosis=action_diagnosis)
    except InfeasibleActionError:
        succeeded = False
        if head is None:
            nxt = copy.deepcopy(state)
            nxt.time = tick
        else:
            nxt = transition(state, None, head)
    nxt.time = tick
    for extra in scheduled[1:]:
        nxt = transition(nxt, None, extra)
        nxt.time = tick
    return nxt, succeeded


def replay_scenario(
    scenario: Scenario,
    method: DecisionMethod | None = None,
) -> list[TraceStep]:
    """Advance through the timeline. `method` may be None (events only).

    All events scheduled at a tick are applied after the method chooses, in
    timeline order. Work items on this scenario object are refreshed from the
    resulting state. The investigation engine runs only when the chosen action
    is investigate.
    """
    chooser = method or NullDecisionMethod()
    state = copy.deepcopy(scenario.initial_state)
    steps: list[TraceStep] = []
    for tick in range(1, scenario.horizon + 1):
        payload = scenario.method_input(state)
        action = chooser.choose(payload)
        events = scenario.events_at(tick)
        state, succeeded = apply_step(state, action=action, events=events)
        scenario.work_items = derive_work_items(
            state,
            sla_window=sla_window_for(scenario.profile),
            templates=scenario.work_items,
        )
        steps.append(
            TraceStep(
                time=state.time,
                action=action,
                event=events[0] if events else None,
                action_succeeded=succeeded,
                state=state,
                events=list(events),
            )
        )
    return steps


def _engine_diagnosis(state: SystemState, incident_id: str):
    """Call the existing engine against this state's evidence. Does not score it."""
    import integrationops.store as store_mod
    from integrationops.engine import investigate

    previous = store_mod._store
    store_mod._store = _StateEvidence(state)
    try:
        return investigate(incident_id)
    except EvidenceNotFound:
        return None
    finally:
        store_mod._store = previous


class _StateEvidence:
    """EvidenceStore view of one SystemState. Not a persistent backend."""

    def __init__(self, state: SystemState) -> None:
        self._state = state

    def load_incident(self, incident_id: str):
        incident = self._state.incident(incident_id)
        if incident is None:
            raise EvidenceNotFound(f"Incident not found: {incident_id}")
        return incident

    def get_request(self, request_id: str):
        request = self._state.request(request_id)
        if request is None:
            raise EvidenceNotFound(f"Request not found: {request_id}")
        return request

    def get_response(self, request_id: str):
        response = self._state.response(request_id)
        if response is None:
            raise EvidenceNotFound(f"Response not found: {request_id}")
        return response

    def get_lender_config(self, lender_id: str):
        lender = self._state.lender(lender_id)
        if lender is None:
            raise EvidenceNotFound(f"Lender config not found: {lender_id}")
        return lender


def _primary_chain(world: OrganizationWorld) -> ChainSnapshot | None:
    if not world.incidents:
        return None
    incident = world.incidents[0]
    sharing = [
        merchant
        for merchant in world.merchants
        if any(
            item.merchant_id == merchant.merchant_id and item.lender_id == incident.lender_id
            for item in world.integrations
        )
    ]
    lender = next((item for item in world.lenders if item.lender_id == incident.lender_id), None)
    request = next((item for item in world.requests if item.request_id == incident.request_id), None)
    response = next((item for item in world.responses if item.request_id == incident.request_id), None)
    diagnosis = next(
        (item for item in world.diagnoses if item.incident_id == incident.incident_id),
        None,
    )
    integrations = [
        item
        for item in world.integrations
        if item.lender_id == incident.lender_id and item.merchant_id in {m.merchant_id for m in sharing}
    ]
    return observe_chain(
        merchants=sharing or world.merchants,
        lender=lender,
        incident=incident,
        request=request,
        response=response,
        diagnosis=diagnosis,
        integrations=integrations or None,
    )


def _merge_worlds(
    worlds: list[OrganizationWorld],
    *,
    seed: int,
    profile: str,
    topology: str = "shared_bottleneck",
) -> OrganizationWorld:
    from integrationops.models import Organization

    merged = Organization(
        organization_id="ORG-MULTI",
        name="Multi-organization experiment world",
        size=profile,
    )
    merchants, lenders, integrations = [], [], []
    requests, responses, incidents, diagnoses = [], [], [], []
    for world in worlds:
        merchants.extend(world.merchants)
        lenders.extend(world.lenders)
        integrations.extend(world.integrations)
        requests.extend(world.requests)
        responses.extend(world.responses)
        incidents.extend(world.incidents)
        diagnoses.extend(world.diagnoses)
        merged.merchant_ids.extend(world.organization.merchant_ids)
        merged.lender_ids.extend(world.organization.lender_ids)
    return OrganizationWorld(
        organization=merged,
        merchants=merchants,
        lenders=lenders,
        integrations=integrations,
        requests=requests,
        responses=responses,
        incidents=incidents,
        diagnoses=diagnoses,
        seed=seed,
        profile=profile,
        topology=topology,
    )
