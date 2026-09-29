"""Basic experiment metrics. Not the candidate objective J and not a scorer for π."""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.experiments.work import CapacityConstraint, WorkItem
from integrationops.operations.constants import (
    CONSTRAINT_API_AVAILABILITY,
    CONSTRAINT_PROVIDER_AVAILABILITY,
    CONSTRAINT_TRANSACTION_LIMIT,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_READY,
    TASK_IN_PROGRESS,
)
from integrationops.operations.state import SystemState, merchant_operational
from integrationops.operations.types import CandidateAction, OperationalEvent
from integrationops.validation.amount import validate_amount


@dataclass
class TraceStep:
    time: int
    action: CandidateAction | None
    event: OperationalEvent | None
    action_succeeded: bool
    state: SystemState
    events: list[OperationalEvent] = field(default_factory=list)


@dataclass
class ExperimentMetrics:
    merchants: int
    operational_merchants: int
    merchant_recovery: float
    blocked_work: int
    open_incidents: int
    resolved_incidents: int
    mean_resolution_time: float | None
    successful_actions: int
    failed_actions: int
    constraint_violations: int
    runtime_seconds: float = 0.0
    completed_tasks: int = 0
    blocked_tasks: int = 0
    sla_violations: int = 0
    resource_utilization: float = 0.0
    replanning_count: int = 0
    objective_value: float | None = None


def blocked_work_count(state: SystemState) -> int:
    return sum(1 for status in state.task_states.values() if status == TASK_BLOCKED)


def constraint_violation_count(state: SystemState) -> int:
    """Count operational constraint breaches visible in S_t."""
    violations = 0
    for request in state.requests:
        lender = state.lender(request.lender_id)
        if lender is None:
            violations += 1
            continue
        if validate_amount(request.amount, lender):
            violations += 1
        limit = state.constraint(CONSTRAINT_TRANSACTION_LIMIT, lender.lender_id)
        if limit is not None and not limit.available:
            violations += 1
    for integration in state.integrations:
        if not state.resource_available(
            CONSTRAINT_PROVIDER_AVAILABILITY, integration.lender_id
        ):
            violations += 1
        if not state.resource_available(CONSTRAINT_API_AVAILABILITY, integration.lender_id):
            violations += 1
    return violations


def compute_metrics(
    initial: SystemState,
    trace: list[TraceStep],
    final: SystemState | None = None,
    work_items: list[WorkItem] | None = None,
    capacities: list[CapacityConstraint] | None = None,
) -> ExperimentMetrics:
    end = final if final is not None else (trace[-1].state if trace else initial)
    operational = sum(
        1 for merchant in end.merchants if merchant_operational(end, merchant.merchant_id)
    )
    merchants = len(end.merchants)
    resolved = len(end.resolved_incident_ids)
    open_incidents = sum(
        1
        for incident in end.incidents
        if end.task_state("incident", incident.incident_id) != TASK_COMPLETED
    )
    successful = sum(1 for step in trace if step.action is not None and step.action_succeeded)
    failed = sum(1 for step in trace if step.action is not None and not step.action_succeeded)
    appeared = {incident.incident_id: initial.time for incident in initial.incidents}
    resolved_at: dict[str, int] = {}
    for step in trace:
        for incident in step.state.incidents:
            appeared.setdefault(incident.incident_id, step.time)
        for incident_id in step.state.resolved_incident_ids:
            resolved_at.setdefault(incident_id, step.time)
    durations = [
        resolved_at[incident_id] - appeared.get(incident_id, initial.time)
        for incident_id in resolved_at
    ]
    mean_time = (sum(durations) / len(durations)) if durations else None
    items = work_items or []
    completed_tasks = sum(1 for item in items if item.state == TASK_COMPLETED)
    if not completed_tasks:
        completed_tasks = resolved
    blocked_tasks = blocked_work_count(end)
    sla_violations = 0
    for item in items:
        if item.deadline is None:
            continue
        if end.time < item.deadline:
            continue
        if item.kind in {"resolve_integration", "investigate"} and item.target_id not in end.resolved_incident_ids:
            if end.task_state("incident", item.target_id) != TASK_COMPLETED:
                sla_violations += 1
    utilization = _utilization(end, items, capacities or [])
    return ExperimentMetrics(
        merchants=merchants,
        operational_merchants=operational,
        merchant_recovery=(operational / merchants) if merchants else 0.0,
        blocked_work=blocked_work_count(end),
        open_incidents=open_incidents,
        resolved_incidents=resolved,
        mean_resolution_time=mean_time,
        successful_actions=successful,
        failed_actions=failed,
        constraint_violations=constraint_violation_count(end),
        completed_tasks=completed_tasks,
        blocked_tasks=blocked_tasks,
        sla_violations=sla_violations,
        resource_utilization=utilization,
        replanning_count=0,
        objective_value=None,
    )


def _utilization(
    state: SystemState,
    work_items: list[WorkItem],
    capacities: list[CapacityConstraint],
) -> float:
    if not capacities:
        return 0.0
    busy = [
        item
        for item in work_items
        if item.state in {TASK_READY, TASK_IN_PROGRESS, TASK_BLOCKED}
    ]
    ratios: list[float] = []
    for cap in capacities:
        if cap.capacity <= 0:
            continue
        load = sum(1 for item in busy if cap.resource_id in item.resource_ids)
        ratios.append(min(load / cap.capacity, 1.0))
    return sum(ratios) / len(ratios) if ratios else 0.0
