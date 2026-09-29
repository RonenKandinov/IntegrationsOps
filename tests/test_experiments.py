"""Organization worlds, dynamic scenarios, snapshots, and experiment metrics."""

from __future__ import annotations

import json
from pathlib import Path

from integrationops.engine import investigate
from integrationops.experiments.metrics import compute_metrics
from integrationops.experiments.scenario import (
    NullDecisionMethod,
    apply_step,
    generate_scenario,
    replay_scenario,
)
from integrationops.experiments.snapshots import dump_scenario, freeze_state
from integrationops.generators.organization import generate_organization, generate_organizations
from integrationops.operations.constants import ACTION_FIX_CONFIGURATION, ACTION_RESOLVE_INCIDENT
from integrationops.operations.snapshot import merchants_sharing_lender
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def test_same_seed_reproduces_the_organization():
    first = generate_organization(profile="small", seed=21, organization_index=1)
    second = generate_organization(profile="small", seed=21, organization_index=1)
    assert [item.merchant_id for item in first.merchants] == [
        item.merchant_id for item in second.merchants
    ]
    assert [item.lender_id for item in first.lenders] == [item.lender_id for item in second.lenders]
    assert [(item.merchant_id, item.lender_id) for item in first.integrations] == [
        (item.merchant_id, item.lender_id) for item in second.integrations
    ]
    assert [item.amount for item in first.requests] == [item.amount for item in second.requests]
    assert [item.incident_id for item in first.incidents] == [
        item.incident_id for item in second.incidents
    ]


def test_different_seeds_change_the_world():
    first = generate_organization(profile="small", seed=3)
    second = generate_organization(profile="small", seed=99)
    assert [item.amount for item in first.requests] != [item.amount for item in second.requests] or [
        item.merchant_id for item in first.merchants
    ] != [item.merchant_id for item in second.merchants]


def test_profiles_grow_in_size_and_share_a_lender():
    small = generate_organization(profile="small", seed=5)
    medium = generate_organization(profile="medium", seed=5)
    large = generate_organization(profile="large", seed=5)
    assert len(small.merchants) < len(medium.merchants) < len(large.merchants)
    assert len(small.lenders) <= len(medium.lenders) <= len(large.lenders)
    state = small.to_system_state()
    primary = small.lenders[0].lender_id
    sharing = merchants_sharing_lender(primary, state.dependencies)
    assert len(sharing) >= 3
    kinds = {item.kind for item in state.entities()}
    assert "organization" in kinds
    assert "integration" in kinds
    assert "payment" in kinds
    assert any(item.operational for item in small.integrations)
    assert any(not item.operational for item in small.integrations)
    assert {inc.failure_code for inc in small.incidents} >= {"INVALID_AMOUNT"}


def test_records_are_linked_not_isolated():
    world = generate_organization(profile="medium", seed=11)
    merchant_ids = {item.merchant_id for item in world.merchants}
    lender_ids = {item.lender_id for item in world.lenders}
    request_ids = {item.request_id for item in world.requests}
    assert all(item.merchant_id in merchant_ids for item in world.integrations)
    assert all(item.lender_id in lender_ids for item in world.integrations)
    assert all(item.merchant_id in merchant_ids for item in world.incidents)
    assert all(item.request_id in request_ids for item in world.incidents)
    assert all(item.lender_id in lender_ids for item in world.requests)
    assert world.organization.merchant_ids == [item.merchant_id for item in world.merchants]


def test_two_methods_receive_the_same_snapshot():
    scenario = generate_scenario(profile="small", seed=8)
    first = scenario.method_input(scenario.initial_state)
    second = scenario.method_input(scenario.initial_state)
    assert freeze_state(first.state) == freeze_state(second.state)
    assert [(item.kind, item.target_id, item.parameters) for item in first.actions] == [
        (item.kind, item.target_id, item.parameters) for item in second.actions
    ]
    assert [(item.kind, item.target_id) for item in first.feasible_actions] == [
        (item.kind, item.target_id) for item in second.feasible_actions
    ]
    dumped = dump_scenario(scenario)
    assert dumped["seed"] == 8
    assert dumped["initial_state"]["time"] == 0
    assert dumped["timeline"]
    json.dumps(dumped)


def test_dynamic_events_are_reproducible_and_change_state():
    first = generate_scenario(profile="small", seed=4, horizon=8)
    second = generate_scenario(profile="small", seed=4, horizon=8)
    assert [(item.time, item.event.kind) for item in first.timeline] == [
        (item.time, item.event.kind) for item in second.timeline
    ]
    steps = replay_scenario(first, NullDecisionMethod())
    assert len(steps) == first.horizon
    later = steps[-1].state
    assert later.time == first.horizon
    assert len(later.events) >= 1
    assert later.merchants != first.initial_state.merchants or later.incidents != first.initial_state.incidents or any(
        not item.available
        for item in later.resources
        if item.kind == "provider_availability"
    )


def test_metrics_track_recovery_blocked_work_and_actions():
    scenario = generate_scenario(profile="small", seed=12, horizon=3)
    initial = scenario.initial_state
    payload = scenario.method_input(initial)
    before = compute_metrics(initial, [])
    assert before.blocked_work > 0
    assert before.constraint_violations > 0
    assert 0 <= before.merchant_recovery < 1

    fix = next(
        item
        for item in payload.feasible_actions
        if item.kind == ACTION_FIX_CONFIGURATION
    )
    after_fix, ok = apply_step(initial, action=fix)
    assert ok is True
    resolve = next(
        (
            item
            for item in scenario.method_input(after_fix).feasible_actions
            if item.kind == ACTION_RESOLVE_INCIDENT
        ),
        None,
    )
    if resolve is not None:
        after_resolve, resolved_ok = apply_step(after_fix, action=resolve)
        assert resolved_ok is True
        end = after_resolve
        action_count = 2
    else:
        end = after_fix
        action_count = 1
    from integrationops.experiments.metrics import TraceStep

    trace = [
        TraceStep(time=after_fix.time, action=fix, event=None, action_succeeded=True, state=after_fix),
    ]
    if resolve is not None:
        trace.append(
            TraceStep(
                time=end.time,
                action=resolve,
                event=None,
                action_succeeded=True,
                state=end,
            )
        )
    metrics = compute_metrics(initial, trace, final=end)
    assert metrics.successful_actions == action_count
    assert metrics.failed_actions == 0
    assert metrics.merchant_recovery >= before.merchant_recovery
    if resolve is not None:
        assert metrics.resolved_incidents >= 1
        assert metrics.mean_resolution_time is not None


def test_generated_invalid_amount_matches_the_engine(tmp_path: Path):
    world = generate_organization(profile="small", seed=2)
    incident = next(item for item in world.incidents if item.failure_code == "INVALID_AMOUNT")
    request = next(item for item in world.requests if item.request_id == incident.request_id)
    response = next(item for item in world.responses if item.request_id == incident.request_id)
    lender = next(item for item in world.lenders if item.lender_id == incident.lender_id)
    diagnosis = next(item for item in world.diagnoses if item.incident_id == incident.incident_id)

    generated = tmp_path / "generated"
    generated.mkdir()
    generated.joinpath("incidents.json").write_text(
        json.dumps(
            [
                {
                    "incident_id": incident.incident_id,
                    "merchant_id": incident.merchant_id,
                    "lender_id": incident.lender_id,
                    "failure_code": incident.failure_code,
                    "request_id": incident.request_id,
                }
            ]
        ),
        encoding="utf-8",
    )
    generated.joinpath("requests.json").write_text(
        json.dumps(
            [
                {
                    "request_id": request.request_id,
                    "merchant_id": request.merchant_id,
                    "lender_id": request.lender_id,
                    "amount": request.amount,
                    "currency": request.currency,
                }
            ]
        ),
        encoding="utf-8",
    )
    generated.joinpath("responses.json").write_text(
        json.dumps(
            [
                {
                    "request_id": response.request_id,
                    "status": response.status,
                    "error_code": response.error_code,
                    "message": response.message,
                }
            ]
        ),
        encoding="utf-8",
    )
    generated.joinpath("lenders.json").write_text(
        json.dumps(
            [
                {
                    "lender_id": lender.lender_id,
                    "min_amount": lender.min_amount,
                    "max_amount": lender.max_amount,
                    "currency": lender.currency,
                }
            ]
        ),
        encoding="utf-8",
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        engine = investigate(incident.incident_id)
        assert engine.root_cause == diagnosis.root_cause
        assert engine.status == diagnosis.status
    finally:
        store_mod._store = previous


def test_multiple_organizations_keep_distinct_ids():
    worlds = generate_organizations(profile="small", seed=6, count=2)
    merchants = [item.merchant_id for world in worlds for item in world.merchants]
    lenders = [item.lender_id for world in worlds for item in world.lenders]
    assert len(merchants) == len(set(merchants))
    assert len(lenders) == len(set(lenders))
    scenario = generate_scenario(profile="small", seed=6, organization_count=2, horizon=4)
    assert len(scenario.initial_state.merchants) == len(merchants)


def test_independent_topology_has_private_lenders():
    from collections import Counter

    world = generate_organization(profile="small", seed=10, topology="independent")
    assert world.topology == "independent"
    assert len(world.merchants) == len(world.lenders)
    assert len(world.integrations) == len(world.merchants)
    state = world.to_system_state()
    sharing = Counter(
        item.prerequisite_id
        for item in state.dependencies
        if item.relation == "merchant_requires_lender"
    )
    assert sharing
    assert max(sharing.values()) == 1
    merchant_ids = {item.merchant_id for item in world.merchants}
    assert all(item.merchant_id in merchant_ids for item in world.incidents)


def test_shared_bottleneck_and_conflict_share_one_lender():
    bottleneck = generate_organization(profile="small", seed=10, topology="shared_bottleneck")
    conflict = generate_organization(profile="small", seed=10, topology="shared_resource_conflict")
    primary = bottleneck.lenders[0].lender_id
    sharing = merchants_sharing_lender(primary, bottleneck.to_system_state().dependencies)
    assert len(sharing) >= 3
    assert all(item.lender_id == conflict.lenders[0].lender_id for item in conflict.integrations)
    assert sum(1 for item in conflict.incidents if item.failure_code == "INVALID_AMOUNT") >= 3


def test_cascading_and_dynamic_families():
    cascade = generate_scenario(profile="small", seed=15, topology="cascading_failure", horizon=8)
    assert cascade.topology == "cascading_failure"
    assert cascade.metadata["topology"] == "cascading_failure"
    kinds = [item.event.kind for item in cascade.timeline]
    assert "lender_unavailable" in kinds
    assert cascade.timeline == sorted(cascade.timeline, key=lambda item: item.time)
    arrivals = generate_scenario(profile="small", seed=15, topology="dynamic_arrival", horizon=8)
    assert any(item.event.kind == "new_incident" for item in arrivals.timeline)
    assert any(item.event.kind == "new_merchant" for item in arrivals.timeline)


def test_ground_truth_is_factual_not_a_policy():
    scenario = generate_scenario(profile="small", seed=9, topology="mixed", horizon=8)
    truth = scenario.ground_truth
    assert truth is not None
    blob = json.dumps(truth.to_dict())
    assert "optimal" not in blob.lower()
    assert "correct action" not in blob.lower()
    assert truth.seed == 9
    assert truth.topology == "mixed"
    assert truth.failures
    assert truth.dependencies
    assert truth.task_facts
    assert truth.resource_capacities
    assert all(item.prerequisites for item in scenario.work_items if item.kind != "investigate")
    times = [item["time"] for item in truth.event_timing]
    assert times == sorted(times)
    assert scenario.chain_snapshot is not None
    assert scenario.chain_snapshot.incident is not None


def test_work_items_and_capacities_are_valid():
    from integrationops.operations.constants import TASK_STATES

    scenario = generate_scenario(profile="small", seed=11, topology="shared_resource_conflict")
    targets = {item.incident_id for item in scenario.initial_state.incidents}
    lender_ids = {item.lender_id for item in scenario.initial_state.lenders}
    for item in scenario.work_items:
        assert item.state in TASK_STATES
        assert item.duration >= 1
        assert item.arrival_time >= 0
        assert item.deadline is None or item.deadline >= item.arrival_time
        assert all(prereq for prereq in item.prerequisites)
        work_ids = {other.work_id for other in scenario.work_items}
        assert all(prereq in work_ids for prereq in item.prerequisites)
        assert all(resource_id in lender_ids or resource_id.startswith("api:") for resource_id in item.resource_ids)
    assert scenario.capacities
    assert all(item.capacity >= 1 for item in scenario.capacities)
    payload = scenario.method_input(scenario.initial_state)
    assert payload.work_items
    assert payload.capacities


def test_harness_gives_methods_the_same_unmutated_scenario():
    from integrationops.experiments.harness import MethodResult, run_experiment
    from integrationops.experiments.metrics import compute_metrics

    scenario = generate_scenario(profile="small", seed=8, topology="independent", horizon=4)
    seen: list[dict] = []

    class Probe:
        name = "probe"

        def __init__(self, label: str) -> None:
            self.name = label

        def solve(self, received):
            snapshot = freeze_state(received.initial_state)
            received.initial_state.merchants.clear()
            seen.append(snapshot)
            return MethodResult(
                method_name=self.name,
                scenario_id=received.scenario_id,
                topology=received.topology,
                seed=received.seed,
                metrics=compute_metrics(received.initial_state, []),
            )

    original = freeze_state(scenario.initial_state)
    results = run_experiment(scenario, [Probe("a"), Probe("b")])
    assert freeze_state(scenario.initial_state) == original
    assert seen[0] == seen[1] == original
    assert [item.method_name for item in results] == ["a", "b"]
    payload = scenario.method_input(scenario.initial_state)
    payload.state.incidents.clear()
    assert scenario.initial_state.incidents


def test_cli_research_commands(capsys):
    from integrationops.cli import main

    assert main(["generate-organization", "--seed", "21", "--topology", "shared_bottleneck"]) == 0
    out = capsys.readouterr().out
    assert "ORG-000001" in out
    assert "shared_bottleneck" in out
    assert main(["generate-scenario", "--seed", "21", "--topology", "independent", "--horizon", "4"]) == 0
    out = capsys.readouterr().out
    assert "scn-independent-small-21" in out
    assert main(["run-experiment", "--seed", "21", "--topology", "independent", "--horizon", "3"]) == 0
    out = capsys.readouterr().out
    assert "Method: null" in out
    assert "Completed tasks:" in out
    assert "Decision runtime seconds: unset" in out
    assert "Objective value" not in out


def test_replay_applies_every_event_at_one_tick_and_keeps_the_original_state():
    from integrationops.experiments.snapshots import freeze_state
    from integrationops.models import ApiRequest, ApiResponse, Incident
    from integrationops.operations.constants import EVENT_NEW_INCIDENT
    from integrationops.operations.types import OperationalEvent
    from integrationops.experiments.scenario import ScheduledEvent

    scenario = generate_scenario(profile="small", seed=21, topology="independent", horizon=2)
    original = freeze_state(scenario.initial_state)
    timeline = [(item.time, item.event.event_id) for item in scenario.timeline]
    host = scenario.initial_state.merchants[0]
    lender_id = scenario.initial_state.lenders[0].lender_id
    tick = 1
    first = OperationalEvent(
        event_id="evt-extra-a",
        kind=EVENT_NEW_INCIDENT,
        subject_id="INC-EXTRA-A",
        incident=Incident(
            incident_id="INC-EXTRA-A",
            merchant_id=host.merchant_id,
            lender_id=lender_id,
            failure_code="TIMEOUT",
            request_id="REQ-EXTRA-A",
        ),
        request=ApiRequest(
            request_id="REQ-EXTRA-A",
            merchant_id=host.merchant_id,
            lender_id=lender_id,
            amount=20000,
            currency="USD",
        ),
        response=ApiResponse(
            request_id="REQ-EXTRA-A",
            status="FAILED",
            error_code="TIMEOUT",
            message="timed out",
        ),
    )
    second = OperationalEvent(
        event_id="evt-extra-b",
        kind=EVENT_NEW_INCIDENT,
        subject_id="INC-EXTRA-B",
        incident=Incident(
            incident_id="INC-EXTRA-B",
            merchant_id=host.merchant_id,
            lender_id=lender_id,
            failure_code="TIMEOUT",
            request_id="REQ-EXTRA-B",
        ),
        request=ApiRequest(
            request_id="REQ-EXTRA-B",
            merchant_id=host.merchant_id,
            lender_id=lender_id,
            amount=22000,
            currency="USD",
        ),
        response=ApiResponse(
            request_id="REQ-EXTRA-B",
            status="FAILED",
            error_code="TIMEOUT",
            message="timed out",
        ),
    )
    scenario.timeline = [
        ScheduledEvent(time=tick, event=first),
        ScheduledEvent(time=tick, event=second),
    ]
    steps = replay_scenario(scenario, NullDecisionMethod())
    assert freeze_state(scenario.initial_state) == original
    assert [(item.time, item.event.event_id) for item in scenario.timeline] == [
        (tick, "evt-extra-a"),
        (tick, "evt-extra-b"),
    ]
    assert timeline  # the generated timeline existed before this replay replaced it
    step = steps[0]
    assert step.time == tick
    assert [item.event_id for item in step.events] == ["evt-extra-a", "evt-extra-b"]
    assert step.state.incident("INC-EXTRA-A") is not None
    assert step.state.incident("INC-EXTRA-B") is not None
    assert step.state.time == tick
    arrivals = {
        item.work_id: item.arrival_time
        for item in scenario.work_items
        if item.work_id in {"investigate:INC-EXTRA-A", "investigate:INC-EXTRA-B"}
    }
    assert arrivals == {"investigate:INC-EXTRA-A": tick, "investigate:INC-EXTRA-B": tick}
    again = replay_scenario(scenario, NullDecisionMethod())
    assert [(item.time, [event.event_id for event in item.events]) for item in again] == [
        (item.time, [event.event_id for event in item.events]) for item in steps
    ]


def test_investigate_action_uses_the_engine_without_scoring_it():
    from integrationops.operations.constants import ACTION_INVESTIGATE
    import integrationops.store as store_mod

    scenario = generate_scenario(profile="small", seed=21, topology="independent", horizon=1)
    incident = next(
        item for item in scenario.initial_state.incidents if item.failure_code == "INVALID_AMOUNT"
    )
    scenario.initial_state.diagnoses = [
        item for item in scenario.initial_state.diagnoses if item.incident_id != incident.incident_id
    ]
    store_before = store_mod._store

    class Once:
        name = "investigate-once"

        def __init__(self) -> None:
            self.done = False

        def choose(self, payload):
            if self.done:
                return None
            self.done = True
            return next(
                item
                for item in payload.feasible_actions
                if item.kind == ACTION_INVESTIGATE and item.target_id == incident.incident_id
            )

    steps = replay_scenario(scenario, Once())
    diagnosis = steps[0].state.diagnosis_for(incident.incident_id)
    assert steps[0].action_succeeded is True
    assert diagnosis is not None
    assert diagnosis.incident_id == incident.incident_id
    assert diagnosis.failure_code == "INVALID_AMOUNT"
    assert diagnosis.root_cause
    assert store_mod._store is store_before
