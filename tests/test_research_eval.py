"""ResearchReport measures a trace. It does not rank methods or replace ExperimentMetrics."""

from __future__ import annotations

import copy

from integrationops.experiments.harness import NullResearchMethod, run_experiment
from integrationops.experiments.metrics import TraceStep, compute_metrics
from integrationops.experiments.research_eval import ResearchReport, evaluate_run
from integrationops.experiments.scenario import NullDecisionMethod, Scenario, generate_scenario, replay_scenario
from integrationops.experiments.work import CapacityConstraint, derive_work_items
from integrationops.generators.organization import OrganizationWorld
from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Incident,
    Integration,
    LenderConfig,
    Merchant,
    Organization,
)
from integrationops.operations.constants import (
    EVENT_LENDER_UNAVAILABLE,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_IN_PROGRESS,
)
from integrationops.operations.state import refresh_derived
from integrationops.operations.types import OperationalEvent


def _fixture_scenario() -> Scenario:
    merchant = Merchant(merchant_id="MER-1", source_id="src-1")
    lender = LenderConfig(lender_id="lender_1", min_amount=100, max_amount=500, currency="USD")
    integration = Integration(
        integration_id="MER-1:lender_1",
        merchant_id="MER-1",
        lender_id="lender_1",
        operational=False,
    )
    request = ApiRequest(
        request_id="REQ-1",
        merchant_id="MER-1",
        lender_id="lender_1",
        amount=1000,
        currency="USD",
    )
    response = ApiResponse(
        request_id="REQ-1",
        status="FAILED",
        error_code="TIMEOUT",
        message="timed out",
    )
    incident = Incident(
        incident_id="INC-1",
        merchant_id="MER-1",
        lender_id="lender_1",
        failure_code="TIMEOUT",
        request_id="REQ-1",
    )
    organization = Organization(
        organization_id="ORG-000001",
        name="Fixture Org",
        size="small",
        merchant_ids=["MER-1"],
        lender_ids=["lender_1"],
    )
    world = OrganizationWorld(
        organization=organization,
        merchants=[merchant],
        lenders=[lender],
        integrations=[integration],
        requests=[request],
        responses=[response],
        incidents=[incident],
        seed=1,
        profile="small",
        topology="independent",
    )
    state = world.to_system_state(time=0)
    work_items = derive_work_items(state, sla_window=6)
    deadlines = {
        "investigate:INC-1": 10,
        "validate:INC-1": 1,
        "resolve:INC-1": 1,
        "retry:REQ-1": 1,
        "escalate:INC-1": 10,
        "review:INC-1": 10,
    }
    for item in work_items:
        item.arrival_time = 0
        item.deadline = deadlines[item.work_id]
    return Scenario(
        scenario_id="scn-independent-small-1",
        seed=1,
        profile="small",
        topology="independent",
        horizon=5,
        world=world,
        initial_state=state,
        work_items=work_items,
        capacities=[
            CapacityConstraint(resource_id="lender_1", kind="concurrency", capacity=1),
        ],
    )


def _controlled_trace(scenario: Scenario) -> list[TraceStep]:
    first = copy.deepcopy(scenario.initial_state)
    first.time = 1
    first.set_task_state("investigation", "INC-1", TASK_IN_PROGRESS)
    second = copy.deepcopy(first)
    second.time = 2
    second.events.append(
        OperationalEvent(
            event_id="evt-lender-down-lender_1",
            kind=EVENT_LENDER_UNAVAILABLE,
            subject_id="lender_1",
            detail="Provider became unavailable.",
        )
    )
    refresh_derived(second)
    second.set_task_state("investigation", "INC-1", TASK_COMPLETED)
    second.set_task_state("incident", "INC-1", TASK_BLOCKED)
    second.set_task_state("validation", "INC-1", TASK_FAILED)
    return [
        TraceStep(time=1, action=None, event=None, action_succeeded=True, state=first),
        TraceStep(time=2, action=None, event=second.events[-1], action_succeeded=True, state=second),
    ]


def test_evaluate_run_counts_states_sla_constraints_and_samples():
    scenario = _fixture_scenario()
    assert {item.work_id for item in scenario.work_items} == {
        "investigate:INC-1",
        "escalate:INC-1",
        "review:INC-1",
        "resolve:INC-1",
        "validate:INC-1",
        "retry:REQ-1",
    }
    empty = evaluate_run(scenario, [], method_name="fixture", replanning_count=4)
    assert empty.completed_tasks == 0
    assert empty.failed_tasks == 0
    assert empty.blocked_tasks == 2
    assert empty.sla_violations == 3
    assert empty.constraint_violations == 0
    assert empty.completion_time is None
    assert empty.task_completion_times == []
    assert empty.resource_utilization is None
    assert empty.utilization_samples == []
    assert empty.runtime_seconds is None
    assert empty.replanning_count == 4
    assert "objective_value" not in ResearchReport.__dataclass_fields__

    report = evaluate_run(
        scenario,
        _controlled_trace(scenario),
        method_name="fixture",
        decision_runtime_seconds=None,
        replanning_count=4,
    )
    assert report.completed_tasks == 1
    assert report.failed_tasks == 1
    assert report.blocked_tasks == 2
    assert report.sla_violations == 3
    assert report.constraint_violations == 3
    assert report.constraint_breaches == [
        (1, "transaction_limit:lender_1"),
        (2, "provider:lender_1"),
        (2, "transaction_limit:lender_1"),
    ]
    assert report.completion_time == 2.0
    assert [(item.work_id, item.arrival_time, item.completion_tick, item.completion_time) for item in report.task_completion_times] == [
        ("investigate:INC-1", 0, 2, 2)
    ]
    assert report.resource_utilization == 0.5
    assert [(item.tick, item.resource_id, item.load, item.capacity, item.utilization) for item in report.utilization_samples] == [
        (1, "lender_1", 1, 1, 1.0),
        (2, "lender_1", 0, 1, 0.0),
    ]
    assert report.runtime_seconds is None
    assert report.replanning_count == 4

    timed = evaluate_run(
        scenario,
        _controlled_trace(scenario),
        method_name="fixture",
        decision_runtime_seconds=0.25,
        replanning_count=0,
    )
    assert timed.runtime_seconds == 0.25
    assert timed.replanning_count == 0


def test_evaluate_run_does_not_use_experiment_metrics_fallback():
    scenario = _fixture_scenario()
    end = copy.deepcopy(scenario.initial_state)
    end.time = 1
    end.resolved_incident_ids.add("INC-1")
    trace = [TraceStep(time=1, action=None, event=None, action_succeeded=True, state=end)]
    old = compute_metrics(
        scenario.initial_state,
        trace,
        final=end,
        work_items=scenario.work_items,
        capacities=scenario.capacities,
    )
    report = evaluate_run(scenario, trace, method_name="fixture")
    assert old.completed_tasks == 1
    assert old.objective_value is None
    assert report.completed_tasks == 0
    assert report.completion_time is None


def test_fixed_scenario_report_is_reproducible_and_ignores_harness_clock():
    scenario = generate_scenario(profile="small", seed=21, topology="independent", horizon=3)
    trace = replay_scenario(scenario, NullDecisionMethod())
    first = evaluate_run(scenario, trace, method_name="null")
    second = evaluate_run(scenario, trace, method_name="null")
    assert first == second
    assert first.scenario_id == "scn-independent-small-21"
    assert first.seed == 21
    assert first.horizon == 3
    assert first.runtime_seconds is None
    assert first.replanning_count == 0
    result = run_experiment(scenario, [NullResearchMethod()])[0]
    assert result.runtime_seconds > 0
    report = evaluate_run(scenario, result.trace, method_name=result.method_name)
    assert report.runtime_seconds is None
    assert report == first
