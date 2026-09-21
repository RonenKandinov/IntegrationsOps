"""AUTHENTICATION_ERROR investigation: request vs lender identity vs API response."""

from __future__ import annotations

from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import append_trace, get_lender_config, get_request, get_response


def investigate_authentication_error(incident: Incident) -> Diagnosis:
    trace: list[str] = []
    append_trace(trace, f"Loaded incident {incident.incident_id}")

    request = get_request(incident.request_id)
    append_trace(trace, f"Loaded request {request.request_id}")

    lender = get_lender_config(incident.lender_id)
    append_trace(trace, f"Loaded lender configuration {lender.lender_id}")

    response = get_response(incident.request_id)
    append_trace(trace, f"Loaded response for {response.request_id}")

    evidence = [
        EvidenceItem(source="request", fact=f"Request merchant = {request.merchant_id}"),
        EvidenceItem(source="request", fact=f"Request lender = {request.lender_id}"),
        EvidenceItem(source="lender", fact=f"Lender config = {lender.lender_id}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
        EvidenceItem(source="response", fact=response.message),
    ]

    if response.error_code == "AUTHENTICATION_ERROR":
        append_trace(trace, "Detected AUTHENTICATION_ERROR in the API response")
        return Diagnosis(
            incident_id=incident.incident_id,
            failure_code=incident.failure_code,
            root_cause="The merchant is not authenticated with this lender.",
            explanation=(
                "The API rejected the request with AUTHENTICATION_ERROR. Amount limits "
                "are not used here; the failure is about identity or credentials."
            ),
            recommended_action=(
                f"Check API credentials and merchant onboarding for {request.merchant_id} "
                f"with lender {lender.lender_id}."
            ),
            evidence=evidence,
            trace=trace,
        )

    append_trace(trace, f"Response error_code={response.error_code} does not confirm AUTHENTICATION_ERROR")
    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code=incident.failure_code,
        root_cause="Not determined from the AUTHENTICATION_ERROR investigation path.",
        explanation=(
            "The incident is labeled AUTHENTICATION_ERROR, but the API response error_code is "
            f"{response.error_code}. This path does not invent an authentication cause."
        ),
        recommended_action="Verify that this incident is mapped to the correct request and response records.",
        evidence=evidence,
        trace=trace,
    )
