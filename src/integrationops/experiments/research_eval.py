"""Measure one research run. Not a rank, a weight, or ExperimentMetrics.

`runtime_seconds` is decision time supplied by the caller. This module does not
time `solve()`, replay, or itself. A later phase can pass choose()-only seconds
through `decision_runtime_seconds`. Until then the field stays None.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.experiments.ground_truth import ScenarioGroundTruth
from integrationops.experiments.metrics import TraceStep
from integrationops.experiments.scenario import Scenario
from integrationops.experiments.work import (
    CapacityConstraint,
    WorkItem,
    derive_work_items,
    sla_window_for,
)
from integrationops.operations.constants import (
    CONSTRAINT_API_AVAILABILITY,
    CONSTRAINT_PROVIDER_AVAILABILITY,
    CONSTRAINT_TRANSACTION_LIMIT,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_IN_PROGRESS,
)
from integrationops.operations.state import SystemState
from integrationops.validation.amount import validate_amount


@dataclass(frozen=True)
class TaskCompletion:
    """One completed work item. `completion_time` is completion_tick - arrival_time."""

    work_id: str
    arrival_time: int
    completion_tick: int
    completion_time: int


@dataclass(frozen=True)
class UtilizationSample:
    """load / capacity for one resource after one transition. Not capped at 1."""

    tick: int
    resource_id: str
    load: int
    capacity: int
    utilization: float


@dataclass
class ResearchReport:
    """Independent outcome counts for one method on one scenario. No winner."""

    method_name: str
    scenario_id: str
    seed: int
    topology: str
    profile: str
    horizon: int
    completed_tasks: int
    failed_tasks: int
    blocked_tasks: int
    sla_violations: int
    constraint_violations: int
    completion_time: float | None
    replanning_count: int
    resource_utilization: float | None
    runtime_seconds: float | None
    task_completion_times: list[TaskCompletion] = field(default_factory=list)
    utilization_samples: list[UtilizationSample] = field(default_factory=list)
    constraint_breaches: list[tuple[int, str]] = field(default_factory=list)


def evaluate_run(
    scenario: Scenario,
    trace: list[TraceStep],
    *,
    method_name: str,
    decision_runtime_seconds: float | None = None,
    replanning_count: int = 0,
) -> ResearchReport:
    """Score a finished trace. Does not choose actions or mutate the scenario.

    `decision_runtime_seconds` is stored as `runtime_seconds`. Pass None until
    decision-only timing exists. `replanning_count` is stored as given; action
    changes in the trace are not treated as replans.
    """
    facts = _task_facts(scenario)
    initial_items = _items_at(scenario, scenario.initial_state, facts)
    completed_at: dict[str, int] = {}
    previous = {item.work_id: item.state for item in initial_items}
    for item in initial_items:
        if item.state == TASK_COMPLETED:
            completed_at[item.work_id] = scenario.initial_state.time

    breaches: list[tuple[int, str]] = []
    samples: list[UtilizationSample] = []
    final_items = initial_items
    for step in trace:
        observed = _items_at(scenario, step.state, facts)
        final_items = observed
        breaches.extend(
            (step.time, constraint_id)
            for constraint_id in sorted(
                _breaches(step.state, observed, scenario.capacities, previous)
            )
        )
        samples.extend(_utilization_samples(step.time, observed, scenario.capacities))
        for item in observed:
            if item.state == TASK_COMPLETED and item.work_id not in completed_at:
                completed_at[item.work_id] = step.time
        previous = {item.work_id: item.state for item in observed}

    completions = _completions(final_items, facts, completed_at)
    return ResearchReport(
        method_name=method_name,
        scenario_id=scenario.scenario_id,
        seed=scenario.seed,
        topology=scenario.topology,
        profile=scenario.profile,
        horizon=scenario.horizon,
        completed_tasks=sum(1 for item in final_items if item.state == TASK_COMPLETED),
        failed_tasks=sum(1 for item in final_items if item.state == TASK_FAILED),
        blocked_tasks=sum(1 for item in final_items if item.state == TASK_BLOCKED),
        sla_violations=_sla_violations(scenario.horizon, final_items, facts, completed_at),
        constraint_violations=len(breaches),
        completion_time=_mean(item.completion_time for item in completions),
        replanning_count=replanning_count,
        resource_utilization=_mean(sample.utilization for sample in samples),
        runtime_seconds=decision_runtime_seconds,
        task_completion_times=completions,
        utilization_samples=samples,
        constraint_breaches=breaches,
    )


def _items_at(
    scenario: Scenario,
    state: SystemState,
    facts: dict[str, tuple[int, int | None]],
) -> list[WorkItem]:
    items = derive_work_items(
        state,
        sla_window=sla_window_for(scenario.profile),
        templates=scenario.work_items,
    )
    for item in items:
        facts.setdefault(item.work_id, (item.arrival_time, item.deadline))
    return items


def _task_facts(scenario: Scenario) -> dict[str, tuple[int, int | None]]:
    facts: dict[str, tuple[int, int | None]] = {
        item.work_id: (item.arrival_time, item.deadline) for item in scenario.work_items
    }
    truth: ScenarioGroundTruth | None = scenario.ground_truth
    if truth is None:
        return facts
    for row in truth.task_facts:
        deadline = row["deadline"]
        facts[str(row["work_id"])] = (
            int(row["arrival_time"]),
            None if deadline is None else int(deadline),
        )
    return facts


def _breaches(
    state: SystemState,
    items: list[WorkItem],
    capacities: list[CapacityConstraint],
    previous: dict[str, str],
) -> set[str]:
    found: set[str] = set()
    for request in state.requests:
        lender = state.lender(request.lender_id)
        if lender is None or not validate_amount(request.amount, lender):
            continue
        limit = state.constraint(CONSTRAINT_TRANSACTION_LIMIT, lender.lender_id)
        if limit is not None:
            found.add(limit.constraint_id)
    for item in items:
        newly_completed = (
            item.state == TASK_COMPLETED and previous.get(item.work_id) != TASK_COMPLETED
        )
        if item.state != TASK_IN_PROGRESS and not newly_completed:
            continue
        for resource_id in item.resource_ids:
            if resource_id.startswith("api:"):
                constraint = state.constraint(
                    CONSTRAINT_API_AVAILABILITY, resource_id.removeprefix("api:")
                )
            else:
                constraint = state.constraint(CONSTRAINT_PROVIDER_AVAILABILITY, resource_id)
            if constraint is not None and not constraint.available:
                found.add(constraint.constraint_id)
    for cap in capacities:
        if _load(items, cap.resource_id) > cap.capacity:
            found.add(f"concurrency:{cap.resource_id}")
    return found


def _utilization_samples(
    tick: int,
    items: list[WorkItem],
    capacities: list[CapacityConstraint],
) -> list[UtilizationSample]:
    samples: list[UtilizationSample] = []
    for cap in capacities:
        if cap.capacity <= 0:
            continue
        load = _load(items, cap.resource_id)
        samples.append(
            UtilizationSample(
                tick=tick,
                resource_id=cap.resource_id,
                load=load,
                capacity=cap.capacity,
                utilization=load / cap.capacity,
            )
        )
    return samples


def _load(items: list[WorkItem], resource_id: str) -> int:
    return sum(
        1
        for item in items
        if item.state == TASK_IN_PROGRESS and resource_id in item.resource_ids
    )


def _completions(
    items: list[WorkItem],
    facts: dict[str, tuple[int, int | None]],
    completed_at: dict[str, int],
) -> list[TaskCompletion]:
    records: list[TaskCompletion] = []
    for item in items:
        if item.state != TASK_COMPLETED or item.work_id not in completed_at:
            continue
        arrival, _deadline = facts[item.work_id]
        tick = completed_at[item.work_id]
        records.append(
            TaskCompletion(
                work_id=item.work_id,
                arrival_time=arrival,
                completion_tick=tick,
                completion_time=tick - arrival,
            )
        )
    records.sort(key=lambda record: record.work_id)
    return records


def _sla_violations(
    horizon: int,
    items: list[WorkItem],
    facts: dict[str, tuple[int, int | None]],
    completed_at: dict[str, int],
) -> int:
    violations = 0
    for item in items:
        _arrival, deadline = facts[item.work_id]
        if deadline is None:
            continue
        if item.state == TASK_COMPLETED:
            tick = completed_at.get(item.work_id)
            if tick is not None and tick > deadline:
                violations += 1
            continue
        if horizon >= deadline:
            violations += 1
    return violations


def _mean(values) -> float | None:
    numbers = list(values)
    if not numbers:
        return None
    return sum(numbers) / len(numbers)
