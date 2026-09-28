"""AUTHENTICATION_ERROR investigation: request vs lender identity vs API response."""

from __future__ import annotations

from integrationops.investigations.evidence import (
    STATUS_DETERMINED,
    STATUS_NOT_DETERMINED,
    gap_diagnosis,
    lender_disagreement,
    load_record,
)
from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import append_trace, get_lender_config, get_request, get_response


def investigate_authentication_error(incident: Incident) -> Diagnosis:
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
            explanation="The request exists, but there is no lender configuration to confirm identity evidence.",
            recommended_action="Retrieve the lender configuration, then re-run the investigation.",
            evidence=[
                EvidenceItem(source="request", fact=f"Request merchant = {request.merchant_id}"),
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
            explanation="The request and lender exist, but there is no API response to confirm an authentication failure.",
            recommended_action="Retrieve the API response, then re-run the investigation.",
            evidence=[
                EvidenceItem(source="request", fact=f"Request lender = {request.lender_id}"),
                EvidenceItem(source="lender", fact=f"Lender config = {lender.lender_id}"),
            ],
        )

    evidence = [
        EvidenceItem(source="request", fact=f"Request merchant = {request.merchant_id}"),
        EvidenceItem(source="request", fact=f"Request lender = {request.lender_id}"),
        EvidenceItem(source="lender", fact=f"Lender config = {lender.lender_id}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
        EvidenceItem(source="response", fact=response.message),
    ]
    disagreement = lender_disagreement(incident, request, response, trace, evidence)
    if disagreement is not None:
        return disagreement

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
            status=STATUS_DETERMINED,
        )

    append_trace(trace, f"Response error_code={response.error_code} does not confirm AUTHENTICATION_ERROR")
    append_trace(trace, "Investigation stopped without assigning a root cause")
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
        status=STATUS_NOT_DETERMINED,
    )
