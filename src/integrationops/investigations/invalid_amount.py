"""INVALID_AMOUNT investigation: request amount vs lender limits vs API response."""

from __future__ import annotations

from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import (
    append_trace,
    compare_amount_to_limits,
    get_lender_config,
    get_request,
    get_response,
)


def investigate_invalid_amount(incident: Incident) -> Diagnosis:
    trace: list[str] = []
    append_trace(trace, f"Loaded incident {incident.incident_id}")

    request = get_request(incident.request_id)
    append_trace(trace, f"Loaded request {request.request_id}")

    lender = get_lender_config(incident.lender_id)
    append_trace(trace, f"Loaded lender configuration {lender.lender_id}")

    response = get_response(incident.request_id)
    append_trace(trace, f"Loaded response for {response.request_id}")

    comparison = compare_amount_to_limits(request.amount, lender.min_amount, lender.max_amount)
    append_trace(trace, f"Compared request amount to lender limits: {comparison}")

    evidence = [
        EvidenceItem(source="request", fact=f"Request amount = {request.amount}"),
        EvidenceItem(source="lender", fact=f"Lender minimum = {lender.min_amount}"),
        EvidenceItem(source="lender", fact=f"Lender maximum = {lender.max_amount}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
    ]

    if comparison == "below_min":
        return Diagnosis(
            incident_id=incident.incident_id,
            failure_code=incident.failure_code,
            root_cause="Requested amount is below the lender's minimum allowed amount.",
            explanation="The requested amount violates the lender's configured minimum amount.",
            recommended_action=(
                f"Check whether the loan amount should be increased to at least {lender.min_amount} "
                "or whether the lender configuration is incorrect."
            ),
            evidence=evidence,
            trace=trace,
        )

    if comparison == "above_max":
        return Diagnosis(
            incident_id=incident.incident_id,
            failure_code=incident.failure_code,
            root_cause="Requested amount is above the lender's maximum allowed amount.",
            explanation="The requested amount violates the lender's configured maximum amount.",
            recommended_action=(
                f"Check whether the loan amount should be reduced to at most {lender.max_amount} "
                "or whether the lender configuration is incorrect."
            ),
            evidence=evidence,
            trace=trace,
        )

    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code=incident.failure_code,
        root_cause="Not determined from lender min/max limits.",
        explanation=(
            "The API returned INVALID_AMOUNT, but the requested amount is within the "
            "configured lender minimum and maximum. Those limits do not explain this response."
        ),
        recommended_action=(
            "Investigate other possible causes, such as amount mapping, currency handling, "
            "or another system that rejects this amount."
        ),
        evidence=evidence,
        trace=trace,
    )
