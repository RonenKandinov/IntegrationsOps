"""JSON-friendly snapshots so later methods can reload the same S_t view."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from integrationops.experiments.scenario import Scenario, ScenarioFrame, snapshot_frame
from integrationops.operations.actions import all_actions, feasible_actions
from integrationops.operations.state import SystemState
from integrationops.operations.types import CandidateAction


@dataclass
class ScenarioSnapshot:
    scenario_id: str
    seed: int
    profile: str
    horizon: int
    frames: list[ScenarioFrame]


def freeze_actions(actions: list[CandidateAction]) -> list[dict]:
    return [
        {
            "kind": item.kind,
            "target_id": item.target_id,
            "reason": item.reason,
            "parameters": dict(item.parameters),
        }
        for item in actions
    ]


def freeze_state(state: SystemState) -> dict:
    """Compact record of S_t. Enough to compare method inputs; not a store dump."""
    return {
        "time": state.time,
        "organizations": [item.organization_id for item in state.organizations],
        "merchants": [item.merchant_id for item in state.merchants],
        "lenders": [
            {
                "lender_id": item.lender_id,
                "min_amount": item.min_amount,
                "max_amount": item.max_amount,
                "currency": item.currency,
            }
            for item in state.lenders
        ],
        "integrations": [
            {
                "integration_id": item.integration_id,
                "merchant_id": item.merchant_id,
                "lender_id": item.lender_id,
                "operational": item.operational,
            }
            for item in state.integrations
        ],
        "requests": [
            {
                "request_id": item.request_id,
                "merchant_id": item.merchant_id,
                "lender_id": item.lender_id,
                "amount": item.amount,
                "currency": item.currency,
            }
            for item in state.requests
        ],
        "incidents": [
            {
                "incident_id": item.incident_id,
                "merchant_id": item.merchant_id,
                "lender_id": item.lender_id,
                "failure_code": item.failure_code,
                "request_id": item.request_id,
            }
            for item in state.incidents
        ],
        "task_states": dict(state.task_states),
        "resolved_incident_ids": sorted(state.resolved_incident_ids),
        "resources": [
            {
                "constraint_id": item.constraint_id,
                "kind": item.kind,
                "subject_id": item.subject_id,
                "available": item.available,
                "min_amount": item.min_amount,
                "max_amount": item.max_amount,
            }
            for item in state.resources
        ],
        "dependencies": [
            {
                "prerequisite_id": item.prerequisite_id,
                "dependent_id": item.dependent_id,
                "relation": item.relation,
            }
            for item in state.dependencies
        ],
        "actions": freeze_actions(all_actions(state)),
        "feasible_actions": freeze_actions(feasible_actions(state)),
    }


def dump_scenario(scenario: Scenario, states: list[SystemState] | None = None) -> dict:
    frames = []
    if states:
        for state in states:
            frames.append(asdict(snapshot_frame(scenario, scenario.method_input(state))))
    else:
        frames.append(asdict(scenario.frame(scenario.initial_state)))
    return {
        "scenario_id": scenario.scenario_id,
        "seed": scenario.seed,
        "profile": scenario.profile,
        "horizon": scenario.horizon,
        "topology": scenario.topology,
        "metadata": dict(scenario.metadata),
        "organization_id": scenario.world.organization.organization_id,
        "ground_truth": scenario.ground_truth.to_dict() if scenario.ground_truth else None,
        "work_items": [
            {
                "work_id": item.work_id,
                "kind": item.kind,
                "target_id": item.target_id,
                "state": item.state,
                "prerequisites": list(item.prerequisites),
                "resource_ids": list(item.resource_ids),
                "arrival_time": item.arrival_time,
                "deadline": item.deadline,
                "duration": item.duration,
            }
            for item in scenario.work_items
        ],
        "capacities": [
            {
                "resource_id": item.resource_id,
                "kind": item.kind,
                "capacity": item.capacity,
                "available": item.available,
            }
            for item in scenario.capacities
        ],
        "initial_state": freeze_state(scenario.initial_state),
        "timeline": [
            {
                "time": item.time,
                "event_id": item.event.event_id,
                "kind": item.event.kind,
                "subject_id": item.event.subject_id,
                "detail": item.event.detail,
            }
            for item in scenario.timeline
        ],
        "frames": frames,
    }
