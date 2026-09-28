"""A(S_t) and A_f(S_t). Candidate actions only; no policy π and no production execution."""

from __future__ import annotations

from integrationops.investigations.evidence import (
    STATUS_DETERMINED,
    STATUS_GAP,
    STATUS_INCONSISTENT,
    STATUS_NOT_DETERMINED,
)
from integrationops.operations.constants import (
    ACTION_ESCALATE,
    ACTION_FIX_CONFIGURATION,
    ACTION_INVESTIGATE,
    ACTION_ONBOARD,
    ACTION_RESOLVE_INCIDENT,
    ACTION_RETRY_REQUEST,
    ACTION_SAFETY_CHECK,
    ACTION_VALIDATE,
    CONSTRAINT_API_AVAILABILITY,
    CONSTRAINT_CONFIGURATION,
    CONSTRAINT_PROVIDER_AVAILABILITY,
    CONSTRAINT_TRANSACTION_LIMIT,
)
from integrationops.operations.state import SystemState
from integrationops.operations.types import CandidateAction
from integrationops.tools import compare_amount_to_limits
from integrationops.validation.amount import validate_amount


def all_actions(state: SystemState) -> list[CandidateAction]:
    """A(S_t): actions the model might consider for the current entities."""
    actions: list[CandidateAction] = []
    for incident in state.incidents:
        actions.append(
            CandidateAction(
                kind=ACTION_INVESTIGATE,
                target_id=incident.incident_id,
                reason="Investigate the incident with the existing engine path.",
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_ESCALATE,
                target_id=incident.incident_id,
                reason="Escalate when evidence is missing or inconsistent.",
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_SAFETY_CHECK,
                target_id=incident.incident_id,
                reason="Run the dry-run safety check on the current diagnosis.",
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_RESOLVE_INCIDENT,
                target_id=incident.incident_id,
                reason="Close the incident after constraints and validation allow it.",
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_VALIDATE,
                target_id=incident.incident_id,
                reason="Validate the incident against current configuration and payment.",
            )
        )
        diagnosis = state.diagnosis_for(incident.incident_id)
        request = state.request(incident.request_id)
        lender = state.lender(incident.lender_id)
        if diagnosis is not None and request is not None and lender is not None:
            actions.extend(
                _diagnosis_candidates(request.request_id, request.amount, lender)
            )
        if request is not None:
            actions.append(
                CandidateAction(
                    kind=ACTION_RETRY_REQUEST,
                    target_id=request.request_id,
                    reason="Retry the payment request if the API and provider are available.",
                )
            )
            actions.append(
                CandidateAction(
                    kind=ACTION_VALIDATE,
                    target_id=request.request_id,
                    reason="Validate the payment request against current limits.",
                )
            )
    for lender in state.lenders:
        if not any(
            item.kind == ACTION_FIX_CONFIGURATION and item.target_id == lender.lender_id
            for item in actions
        ):
            actions.append(
                CandidateAction(
                    kind=ACTION_FIX_CONFIGURATION,
                    target_id=lender.lender_id,
                    reason="Adjust lender configuration limits or related settings.",
                )
            )
        actions.append(
            CandidateAction(
                kind=ACTION_VALIDATE,
                target_id=lender.lender_id,
                reason="Validate the lender configuration structure.",
            )
        )
    for merchant in state.merchants:
        actions.append(
            CandidateAction(
                kind=ACTION_ONBOARD,
                target_id=merchant.merchant_id,
                reason="Onboard the merchant when required identifiers are present.",
            )
        )
    for request in state.requests:
        if not any(
            item.kind == ACTION_RETRY_REQUEST and item.target_id == request.request_id
            for item in actions
        ):
            actions.append(
                CandidateAction(
                    kind=ACTION_RETRY_REQUEST,
                    target_id=request.request_id,
                    reason="Retry the payment request if the API and provider are available.",
                )
            )
        if not any(
            item.kind == ACTION_VALIDATE and item.target_id == request.request_id
            for item in actions
        ):
            actions.append(
                CandidateAction(
                    kind=ACTION_VALIDATE,
                    target_id=request.request_id,
                    reason="Validate the payment request against current limits.",
                )
            )
    return actions


def feasible_actions(state: SystemState) -> list[CandidateAction]:
    """A_f(S_t) ⊆ A(S_t)."""
    return [action for action in all_actions(state) if is_feasible(state, action)]


def is_feasible(state: SystemState, action: CandidateAction) -> bool:
    """True when a_t satisfies the operational constraints on S_t."""
    if action.kind == ACTION_INVESTIGATE:
        return state.incident(action.target_id) is not None
    if action.kind == ACTION_FIX_CONFIGURATION:
        return _fix_configuration_feasible(state, action)
    if action.kind == ACTION_VALIDATE:
        return _validate_feasible(state, action.target_id)
    if action.kind == ACTION_ONBOARD:
        merchant = state.merchant(action.target_id)
        return merchant is not None and bool(merchant.source_id.strip())
    if action.kind == ACTION_RETRY_REQUEST:
        return _retry_feasible(state, action)
    if action.kind == ACTION_ESCALATE:
        diagnosis = state.diagnosis_for(action.target_id)
        return diagnosis is not None and diagnosis.status in {
            STATUS_GAP,
            STATUS_INCONSISTENT,
            STATUS_NOT_DETERMINED,
        }
    if action.kind == ACTION_SAFETY_CHECK:
        return state.diagnosis_for(action.target_id) is not None
    if action.kind == ACTION_RESOLVE_INCIDENT:
        return _resolve_feasible(state, action.target_id)
    return False


def _diagnosis_candidates(
    request_id: str,
    amount: int,
    lender,
) -> list[CandidateAction]:
    comparison = compare_amount_to_limits(amount, lender.min_amount, lender.max_amount)
    actions: list[CandidateAction] = []
    if comparison == "above_max":
        actions.append(
            CandidateAction(
                kind=ACTION_FIX_CONFIGURATION,
                target_id=lender.lender_id,
                reason="Raise the lender maximum so the current payment fits configured limits.",
                parameters={"max_amount": amount},
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_RETRY_REQUEST,
                target_id=request_id,
                reason="Retry after reducing the payment to the configured maximum.",
                parameters={"amount": lender.max_amount},
            )
        )
    elif comparison == "below_min":
        actions.append(
            CandidateAction(
                kind=ACTION_FIX_CONFIGURATION,
                target_id=lender.lender_id,
                reason="Lower the lender minimum so the current payment fits configured limits.",
                parameters={"min_amount": amount},
            )
        )
        actions.append(
            CandidateAction(
                kind=ACTION_RETRY_REQUEST,
                target_id=request_id,
                reason="Retry after increasing the payment to the configured minimum.",
                parameters={"amount": lender.min_amount},
            )
        )
    return actions


def _fix_configuration_feasible(state: SystemState, action: CandidateAction) -> bool:
    lender = state.lender(action.target_id)
    if lender is None:
        return False
    if not {"min_amount", "max_amount", "currency"} & set(action.parameters):
        return False
    if not state.resource_available(CONSTRAINT_PROVIDER_AVAILABILITY, lender.lender_id):
        return False
    if not state.resource_available(CONSTRAINT_CONFIGURATION, lender.lender_id):
        return False
    min_amount = int(action.parameters.get("min_amount", lender.min_amount))
    max_amount = int(action.parameters.get("max_amount", lender.max_amount))
    if min_amount > max_amount:
        return False
    currency = action.parameters.get("currency")
    if currency is not None and currency != lender.currency:
        return False
    return True


def _validate_feasible(state: SystemState, target_id: str) -> bool:
    if state.incident(target_id) is not None:
        incident = state.incident(target_id)
        assert incident is not None
        return state.request(incident.request_id) is not None or state.lender(incident.lender_id) is not None
    if state.request(target_id) is not None:
        request = state.request(target_id)
        assert request is not None
        return True
    return state.lender(target_id) is not None


def _retry_feasible(state: SystemState, action: CandidateAction) -> bool:
    request = _request_for_retry(state, action)
    if request is None:
        return False
    if not state.resource_available(CONSTRAINT_API_AVAILABILITY, request.lender_id):
        return False
    if not state.resource_available(CONSTRAINT_PROVIDER_AVAILABILITY, request.lender_id):
        return False
    amount = int(action.parameters.get("amount", request.amount))
    lender = state.lender(request.lender_id)
    if lender is None:
        return False
    return compare_amount_to_limits(amount, lender.min_amount, lender.max_amount) == "within_limits"


def _resolve_feasible(state: SystemState, incident_id: str) -> bool:
    incident = state.incident(incident_id)
    diagnosis = state.diagnosis_for(incident_id)
    if incident is None or diagnosis is None or diagnosis.status != STATUS_DETERMINED:
        return False
    if not state.resource_available(CONSTRAINT_PROVIDER_AVAILABILITY, incident.lender_id):
        return False
    request = state.request(incident.request_id)
    lender = state.lender(incident.lender_id)
    if request is None or lender is None:
        return False
    if not state.resource_available(CONSTRAINT_TRANSACTION_LIMIT, lender.lender_id):
        return False
    if validate_amount(request.amount, lender):
        return False
    return True


def _request_for_retry(state: SystemState, action: CandidateAction):
    request = state.request(action.target_id)
    if request is not None:
        return request
    incident = state.incident(action.target_id)
    if incident is None:
        return None
    return state.request(incident.request_id)
