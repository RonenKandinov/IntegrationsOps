"""S_(t+1) = T(S_t, a_t, ω_t). In-memory only; does not write the evidence store."""

from __future__ import annotations

import copy

from integrationops.models import ValidationReport
from integrationops.operations.actions import is_feasible
from integrationops.operations.constants import (
    ACTION_ESCALATE,
    ACTION_FIX_CONFIGURATION,
    ACTION_INVESTIGATE,
    ACTION_ONBOARD,
    ACTION_RESOLVE_INCIDENT,
    ACTION_RETRY_REQUEST,
    ACTION_SAFETY_CHECK,
    ACTION_VALIDATE,
    EVENT_API_BEHAVIOR_CHANGE,
    EVENT_CONFIGURATION_CHANGED,
    EVENT_LENDER_RECOVERED,
    EVENT_LENDER_UNAVAILABLE,
    EVENT_MISSING_INFORMATION_ARRIVED,
    EVENT_NEW_INCIDENT,
    EVENT_NEW_MERCHANT,
    EVENT_UNEXPECTED_RESPONSE,
    EVENT_WORK_ARRIVED,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_IN_PROGRESS,
)
from integrationops.operations.snapshot import derive_integrations, make_integration_id
from integrationops.operations.state import SystemState, refresh_derived
from integrationops.operations.types import CandidateAction, OperationalEvent
from integrationops.validation.amount import validate_amount


class InfeasibleActionError(ValueError):
    """Raised when a_t is not in A_f(S_t)."""


def transition(
    state: SystemState,
    action: CandidateAction | None = None,
    event: OperationalEvent | None = None,
    *,
    diagnosis=None,
) -> SystemState:
    """Apply a feasible action and/or new information. Never writes production data."""
    if action is None and event is None:
        raise ValueError("T requires an action and/or an event")
    if action is not None and not is_feasible(state, action):
        raise InfeasibleActionError(
            f"{action.kind} is not feasible for {action.target_id} in the current state"
        )
    nxt = copy.deepcopy(state)
    nxt.time = state.time + 1
    if action is not None:
        _apply_action(nxt, action, diagnosis=diagnosis)
    if event is not None:
        _apply_event(nxt, event)
    refresh_derived(nxt)
    return nxt


def _apply_action(state: SystemState, action: CandidateAction, *, diagnosis) -> None:
    if action.kind == ACTION_INVESTIGATE:
        if diagnosis is None:
            raise ValueError("investigate requires a Diagnosis from the investigation engine")
        state.diagnoses = [
            item for item in state.diagnoses if item.incident_id != diagnosis.incident_id
        ]
        state.diagnoses.append(copy.deepcopy(diagnosis))
        state.set_task_state("investigation", diagnosis.incident_id, TASK_COMPLETED)
        return
    if action.kind == ACTION_FIX_CONFIGURATION:
        _apply_fix_configuration(state, action)
        return
    if action.kind == ACTION_VALIDATE:
        report = _validate_in_state(state, action.target_id)
        state.validations = [item for item in state.validations if item.target_id != report.target_id]
        state.validations.append(report)
        return
    if action.kind == ACTION_ONBOARD:
        state.set_task_state("onboarding", action.target_id, TASK_COMPLETED)
        return
    if action.kind == ACTION_RETRY_REQUEST:
        _apply_retry(state, action)
        return
    if action.kind == ACTION_ESCALATE:
        state.set_task_state("incident", action.target_id, TASK_BLOCKED)
        return
    if action.kind == ACTION_SAFETY_CHECK:
        state.events.append(
            OperationalEvent(
                event_id=f"safety:{action.target_id}:{state.time}",
                kind=ACTION_SAFETY_CHECK,
                subject_id=action.target_id,
                detail="Dry-run safety check recorded. No production change.",
            )
        )
        return
    if action.kind == ACTION_RESOLVE_INCIDENT:
        _apply_resolve(state, action.target_id)


def _apply_fix_configuration(state: SystemState, action: CandidateAction) -> None:
    lender = state.lender(action.target_id)
    if lender is None:
        return
    if "min_amount" in action.parameters:
        lender.min_amount = int(action.parameters["min_amount"])
    if "max_amount" in action.parameters:
        lender.max_amount = int(action.parameters["max_amount"])
    if "currency" in action.parameters:
        lender.currency = str(action.parameters["currency"])
    state.set_task_state("configuration", lender.lender_id, TASK_COMPLETED)


def _apply_retry(state: SystemState, action: CandidateAction) -> None:
    request = state.request(action.target_id)
    if request is None:
        incident = state.incident(action.target_id)
        if incident is not None:
            request = state.request(incident.request_id)
    if request is None:
        return
    if "amount" in action.parameters:
        request.amount = int(action.parameters["amount"])
    state.set_task_state("payment", request.request_id, TASK_IN_PROGRESS)


def _apply_resolve(state: SystemState, incident_id: str) -> None:
    incident = state.incident(incident_id)
    if incident is None:
        return
    state.set_task_state("incident", incident_id, TASK_COMPLETED)
    state.resolved_incident_ids.add(incident_id)
    integration_id = make_integration_id(incident.merchant_id, incident.lender_id)
    integration = state.integration(integration_id)
    if integration is not None:
        integration.operational = True
        state.set_task_state("integration", integration.integration_id, TASK_COMPLETED)


def _validate_in_state(state: SystemState, target_id: str) -> ValidationReport:
    incident = state.incident(target_id)
    request = state.request(target_id)
    lender = state.lender(target_id)
    if incident is not None:
        request = state.request(incident.request_id)
        lender = state.lender(incident.lender_id)
        issues = []
        if request is None or lender is None:
            return ValidationReport(target_id=target_id, valid=False, issues=issues)
        issues.extend(validate_amount(request.amount, lender))
        return ValidationReport(target_id=target_id, valid=not issues, issues=issues)
    if request is not None:
        lender = state.lender(request.lender_id)
        issues = []
        if lender is None:
            return ValidationReport(target_id=target_id, valid=False, issues=issues)
        issues.extend(validate_amount(request.amount, lender))
        return ValidationReport(target_id=target_id, valid=not issues, issues=issues)
    return ValidationReport(target_id=target_id, valid=lender is not None, issues=[])


def _apply_event(state: SystemState, event: OperationalEvent) -> None:
    state.events.append(copy.deepcopy(event))
    if event.kind == EVENT_NEW_MERCHANT and event.merchant is not None:
        if state.merchant(event.merchant.merchant_id) is None:
            state.merchants.append(copy.deepcopy(event.merchant))
            lender_id = event.subject_id
            if lender_id and state.lender(lender_id) is not None:
                existing = {
                    item.integration_id for item in state.integrations
                }
                for item in derive_integrations([event.merchant], lender_id):
                    if item.integration_id not in existing:
                        state.integrations.append(item)
        return
    if event.kind in {EVENT_NEW_INCIDENT, EVENT_WORK_ARRIVED} and event.incident is not None:
        if state.incident(event.incident.incident_id) is None:
            state.incidents.append(copy.deepcopy(event.incident))
        if event.request is not None and state.request(event.request.request_id) is None:
            state.requests.append(copy.deepcopy(event.request))
        if event.response is not None and state.response(event.response.request_id) is None:
            state.responses.append(copy.deepcopy(event.response))
        integration = state.integration(
            make_integration_id(event.incident.merchant_id, event.incident.lender_id)
        )
        if integration is not None:
            integration.operational = False
            state.set_task_state("integration", integration.integration_id, TASK_BLOCKED)
        return
    if event.kind == EVENT_LENDER_UNAVAILABLE:
        for integration in state.integrations:
            if integration.lender_id == event.subject_id:
                integration.operational = False
                state.set_task_state("integration", integration.integration_id, TASK_BLOCKED)
        return
    if event.kind == EVENT_LENDER_RECOVERED:
        return
    if event.kind == EVENT_CONFIGURATION_CHANGED and event.lender is not None:
        current = state.lender(event.lender.lender_id)
        if current is None:
            state.lenders.append(copy.deepcopy(event.lender))
        else:
            current.min_amount = event.lender.min_amount
            current.max_amount = event.lender.max_amount
            current.currency = event.lender.currency
        return
    if event.kind == EVENT_API_BEHAVIOR_CHANGE:
        return
    if event.kind == EVENT_MISSING_INFORMATION_ARRIVED and event.lender is not None:
        if state.lender(event.lender.lender_id) is None:
            state.lenders.append(copy.deepcopy(event.lender))
        return
    if event.kind == EVENT_UNEXPECTED_RESPONSE and event.response is not None:
        existing = state.response(event.response.request_id)
        if existing is None:
            state.responses.append(copy.deepcopy(event.response))
        else:
            existing.status = event.response.status
            existing.error_code = event.response.error_code
            existing.message = event.response.message
            existing.noted_lender_id = event.response.noted_lender_id
