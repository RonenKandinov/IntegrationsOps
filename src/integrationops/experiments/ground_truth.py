"""Factual ground truth for a generated scenario. Not a policy answer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from integrationops.experiments.work import CapacityConstraint, WorkItem
from integrationops.operations.snapshot import Dependency
from integrationops.operations.state import SystemState
from integrationops.operations.types import OperationalEvent


@dataclass
class ScenarioGroundTruth:
    """Facts about the world. Does not name an optimal action or algorithm."""

    topology: str
    seed: int
    dependencies: list[dict] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)
    event_timing: list[dict] = field(default_factory=list)
    prerequisites: list[dict] = field(default_factory=list)
    resource_capacities: list[dict] = field(default_factory=list)
    active_constraints: list[dict] = field(default_factory=list)
    task_facts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def build_ground_truth(
    *,
    topology: str,
    seed: int,
    state: SystemState,
    timeline: list[tuple[int, OperationalEvent]],
    work_items: list[WorkItem],
    capacities: list[CapacityConstraint],
    dependencies: list[Dependency],
) -> ScenarioGroundTruth:
    return ScenarioGroundTruth(
        topology=topology,
        seed=seed,
        dependencies=[
            {
                "prerequisite_id": item.prerequisite_id,
                "dependent_id": item.dependent_id,
                "relation": item.relation,
            }
            for item in dependencies
        ],
        failures=[
            {
                "incident_id": item.incident_id,
                "failure_code": item.failure_code,
                "merchant_id": item.merchant_id,
                "lender_id": item.lender_id,
                "request_id": item.request_id,
            }
            for item in state.incidents
        ],
        event_timing=[
            {
                "time": tick,
                "event_id": event.event_id,
                "kind": event.kind,
                "subject_id": event.subject_id,
            }
            for tick, event in timeline
        ],
        prerequisites=[
            {"work_id": item.work_id, "prerequisites": list(item.prerequisites)}
            for item in work_items
            if item.prerequisites
        ],
        resource_capacities=[
            {
                "resource_id": item.resource_id,
                "kind": item.kind,
                "capacity": item.capacity,
                "available": item.available,
            }
            for item in capacities
        ],
        active_constraints=[
            {
                "constraint_id": item.constraint_id,
                "kind": item.kind,
                "subject_id": item.subject_id,
                "available": item.available,
            }
            for item in state.resources
        ],
        task_facts=[
            {
                "work_id": item.work_id,
                "kind": item.kind,
                "target_id": item.target_id,
                "arrival_time": item.arrival_time,
                "deadline": item.deadline,
                "duration": item.duration,
                "initial_state": item.state,
                "resource_ids": list(item.resource_ids),
            }
            for item in work_items
        ],
    )
