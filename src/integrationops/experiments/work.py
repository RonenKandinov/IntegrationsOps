"""Research-layer work items and capacities. Derived from existing domain records."""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.operations.constants import (
    ACTION_ESCALATE,
    ACTION_FIX_CONFIGURATION,
    ACTION_INVESTIGATE,
    ACTION_RESOLVE_INCIDENT,
    ACTION_RETRY_REQUEST,
    ACTION_VALIDATE,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_PENDING,
    TASK_READY,
)
from integrationops.operations.state import SystemState


WORK_INVESTIGATE = ACTION_INVESTIGATE
WORK_VALIDATE = ACTION_VALIDATE
WORK_RESOLVE = "resolve_integration"
WORK_CONFIG = ACTION_FIX_CONFIGURATION
WORK_RETRY = ACTION_RETRY_REQUEST
WORK_ESCALATE = ACTION_ESCALATE
WORK_REVIEW = "manual_review"


@dataclass
class WorkItem:
    """Operational work derived from incidents and integrations. Not a new store type."""

    work_id: str
    kind: str
    target_id: str
    duration: int
    prerequisites: list[str] = field(default_factory=list)
    resource_ids: list[str] = field(default_factory=list)
    state: str = TASK_PENDING
    arrival_time: int = 0
    deadline: int | None = None


@dataclass
class CapacityConstraint:
    """Generic operational capacity. Not staffing."""

    resource_id: str
    kind: str
    capacity: int
    available: bool = True


def default_capacities(
    state: SystemState,
    *,
    topology: str,
) -> list[CapacityConstraint]:
    items: list[CapacityConstraint] = []
    shared_cap = 1 if topology in {"shared_resource_conflict", "cascading_failure"} else 2
    for lender in state.lenders:
        items.append(
            CapacityConstraint(
                resource_id=lender.lender_id,
                kind="concurrency",
                capacity=shared_cap if topology != "independent" else 2,
                available=state.resource_available("provider_availability", lender.lender_id)
                if state.resources
                else True,
            )
        )
        items.append(
            CapacityConstraint(
                resource_id=f"api:{lender.lender_id}",
                kind="concurrency",
                capacity=1 if topology == "shared_resource_conflict" else shared_cap,
                available=state.resource_available("api_availability", lender.lender_id)
                if state.resources
                else True,
            )
        )
    return items


def derive_work_items(
    state: SystemState,
    *,
    sla_window: int,
    templates: list[WorkItem] | None = None,
) -> list[WorkItem]:
    """Build or refresh work items from the current SystemState."""
    if templates:
        by_id = {item.work_id: item for item in templates}
    else:
        by_id = {}
    items: list[WorkItem] = []
    for incident in state.incidents:
        investigate_id = f"investigate:{incident.incident_id}"
        template = by_id.get(investigate_id)
        diagnosis = state.diagnosis_for(incident.incident_id)
        investigate_state = state.task_state("investigation", incident.incident_id) or TASK_PENDING
        items.append(
            WorkItem(
                work_id=investigate_id,
                kind=WORK_INVESTIGATE,
                target_id=incident.incident_id,
                duration=template.duration if template else 1,
                prerequisites=[],
                resource_ids=[incident.lender_id],
                state=investigate_state,
                arrival_time=template.arrival_time if template else state.time,
                deadline=template.deadline if template else state.time + sla_window,
            )
        )
        if diagnosis is not None and diagnosis.failure_code == "INVALID_AMOUNT":
            config_id = f"fix_configuration:{incident.lender_id}:{incident.incident_id}"
            config_template = by_id.get(config_id)
            items.append(
                WorkItem(
                    work_id=config_id,
                    kind=WORK_CONFIG,
                    target_id=incident.lender_id,
                    duration=config_template.duration if config_template else 2,
                    prerequisites=[investigate_id],
                    resource_ids=[incident.lender_id],
                    state=_config_state(state, incident.lender_id, investigate_state),
                    arrival_time=config_template.arrival_time if config_template else state.time,
                    deadline=config_template.deadline if config_template else state.time + sla_window,
                )
            )
        if incident.failure_code in {"TIMEOUT", "AUTHENTICATION_ERROR"}:
            escalate_id = f"escalate:{incident.incident_id}"
            esc_template = by_id.get(escalate_id)
            items.append(
                WorkItem(
                    work_id=escalate_id,
                    kind=WORK_ESCALATE,
                    target_id=incident.incident_id,
                    duration=esc_template.duration if esc_template else 1,
                    prerequisites=[investigate_id],
                    resource_ids=[incident.lender_id],
                    state=TASK_READY if investigate_state == TASK_COMPLETED else TASK_BLOCKED,
                    arrival_time=esc_template.arrival_time if esc_template else state.time,
                    deadline=esc_template.deadline if esc_template else state.time + sla_window,
                )
            )
            items.append(
                WorkItem(
                    work_id=f"review:{incident.incident_id}",
                    kind=WORK_REVIEW,
                    target_id=incident.incident_id,
                    duration=2,
                    prerequisites=[escalate_id],
                    resource_ids=[incident.lender_id],
                    state=TASK_PENDING,
                    arrival_time=state.time,
                    deadline=state.time + sla_window,
                )
            )
        resolve_id = f"resolve:{incident.incident_id}"
        res_template = by_id.get(resolve_id)
        incident_state = state.task_state("incident", incident.incident_id) or TASK_PENDING
        items.append(
            WorkItem(
                work_id=resolve_id,
                kind=WORK_RESOLVE,
                target_id=incident.incident_id,
                duration=res_template.duration if res_template else 1,
                prerequisites=[investigate_id],
                resource_ids=[incident.lender_id],
                state=incident_state,
                arrival_time=res_template.arrival_time if res_template else state.time,
                deadline=res_template.deadline if res_template else state.time + sla_window,
            )
        )
        validate_id = f"validate:{incident.incident_id}"
        val_template = by_id.get(validate_id)
        val_state = state.task_state("validation", incident.incident_id) or TASK_PENDING
        items.append(
            WorkItem(
                work_id=validate_id,
                kind=WORK_VALIDATE,
                target_id=incident.incident_id,
                duration=val_template.duration if val_template else 1,
                prerequisites=[investigate_id],
                resource_ids=[incident.lender_id],
                state=val_state,
                arrival_time=val_template.arrival_time if val_template else state.time,
                deadline=val_template.deadline if val_template else state.time + sla_window,
            )
        )
        if incident.failure_code == "TIMEOUT":
            retry_id = f"retry:{incident.request_id}"
            items.append(
                WorkItem(
                    work_id=retry_id,
                    kind=WORK_RETRY,
                    target_id=incident.request_id,
                    duration=1,
                    prerequisites=[investigate_id],
                    resource_ids=[incident.lender_id, f"api:{incident.lender_id}"],
                    state=TASK_BLOCKED,
                    arrival_time=state.time,
                    deadline=state.time + sla_window,
                )
            )
    return items


def _config_state(state: SystemState, lender_id: str, investigate_state: str) -> str:
    if investigate_state != TASK_COMPLETED:
        return TASK_BLOCKED
    configured = state.task_state("configuration", lender_id)
    if configured == TASK_COMPLETED:
        return TASK_COMPLETED
    return TASK_READY


def sla_window_for(profile: str) -> int:
    return {"small": 6, "medium": 8, "large": 10}.get(profile, 6)
