"""INVALID_AMOUNT investigation: request amount vs lender limits vs API response."""

from __future__ import annotations

from integrationops.investigations.evidence import (
    STATUS_DETERMINED,
    STATUS_INCONSISTENT,
    gap_diagnosis,
    lender_disagreement,
    load_record,
)
from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import append_trace, compare_amount_to_limits, get_lender_config, get_request, get_response


def investigate_invalid_amount(incident: Incident) -> Diagnosis:
    trace: list[str] = []
    append_trace(trace, f"Loaded incident {incident.incident_id}")

    request = load_record(
        trace,
        loaded=f"Loaded request {incident.request_id}",
        missing_fact="request",
        loader=lambda: get_request(incident.request_id),
    )
    if request is None:
        return gap_diagnosis(
            incident,
            trace,
            detail="request evidence is missing.",
            explanation="The incident points at a request that is not in the evidence store.",
            recommended_action="Retrieve the API request record, then re-run the investigation.",
            evidence=[EvidenceItem(source="incident", fact=f"request_id={incident.request_id}")],
        )

    lender = load_record(
        trace,
        loaded=f"Loaded lender configuration {incident.lender_id}",
        missing_fact="lender configuration",
        loader=lambda: get_lender_config(incident.lender_id),
    )
    if lender is None:
        return gap_diagnosis(
            incident,
            trace,
            detail="lender configuration is missing.",
            explanation=(
                "The available evidence is insufficient to verify whether the requested "
                "amount violated lender limits."
            ),
            recommended_action="Retrieve the lender configuration or equivalent limit information.",
            evidence=[
                EvidenceItem(source="request", fact=f"Request amount = {request.amount}"),
                EvidenceItem(source="incident", fact=f"lender_id={incident.lender_id}"),
            ],
        )

    response = load_record(
        trace,
        loaded=f"Loaded response for {incident.request_id}",
        missing_fact="response",
        loader=lambda: get_response(incident.request_id),
    )
    if response is None:
        return gap_diagnosis(
            incident,
            trace,
            detail="response evidence is missing.",
            explanation="The request and lender configuration exist, but there is no API response to compare.",
            recommended_action="Retrieve the API response for this request, then re-run the investigation.",
            evidence=[
                EvidenceItem(source="request", fact=f"Request amount = {request.amount}"),
                EvidenceItem(source="lender", fact=f"Lender maximum = {lender.max_amount}"),
            ],
        )

    evidence = [
        EvidenceItem(source="request", fact=f"Request amount = {request.amount}"),
        EvidenceItem(source="lender", fact=f"Lender minimum = {lender.min_amount}"),
        EvidenceItem(source="lender", fact=f"Lender maximum = {lender.max_amount}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
    ]
    disagreement = lender_disagreement(incident, request, response, trace, evidence)
    if disagreement is not None:
        return disagreement

    comparison = compare_amount_to_limits(request.amount, lender.min_amount, lender.max_amount)
    append_trace(trace, f"Compared request amount to lender limits: {comparison}")

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
            status=STATUS_DETERMINED,
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
            status=STATUS_DETERMINED,
        )

    append_trace(trace, "Request amount is within configured limits")
    append_trace(trace, f"API response indicates {response.error_code}")
    append_trace(trace, "Available evidence does not explain failure")
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
        status=STATUS_INCONSISTENT,
    )
