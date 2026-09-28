"""TIMEOUT investigation: request went out, lender API did not answer in time."""

from __future__ import annotations

from integrationops.investigations.evidence import (
    STATUS_DETERMINED,
    STATUS_NOT_DETERMINED,
    gap_diagnosis,
    lender_disagreement,
    load_record,
)
from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import append_trace, get_request, get_response


def investigate_timeout(incident: Incident) -> Diagnosis:
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
            explanation=(
                "A request record exists, but there is no API response. "
                "A TIMEOUT label alone does not establish that the lender timed out."
            ),
            recommended_action="Retrieve the API response or timeout record, then re-run the investigation.",
            evidence=[
                EvidenceItem(source="request", fact=f"Request {request.request_id} was sent to {request.lender_id}"),
            ],
        )

    evidence = [
        EvidenceItem(source="request", fact=f"Request {request.request_id} was sent to {request.lender_id}"),
        EvidenceItem(source="response", fact=f"API status = {response.status}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
        EvidenceItem(source="response", fact=response.message),
    ]
    disagreement = lender_disagreement(incident, request, response, trace, evidence)
    if disagreement is not None:
        return disagreement

    if response.error_code == "TIMEOUT":
        append_trace(trace, "Detected TIMEOUT in the API response")
        return Diagnosis(
            incident_id=incident.incident_id,
            failure_code=incident.failure_code,
            root_cause="The lender API did not respond before the request timed out.",
            explanation=(
                "A request was sent, but the recorded API response is TIMEOUT. "
                "This path does not treat amount or authentication rules as the cause."
            ),
            recommended_action=(
                "Check lender availability, network path, and timeout settings, then retry the request."
            ),
            evidence=evidence,
            trace=trace,
            status=STATUS_DETERMINED,
        )

    append_trace(trace, f"Response error_code={response.error_code} does not confirm TIMEOUT")
    append_trace(trace, "Investigation stopped without assigning a root cause")
    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code=incident.failure_code,
        root_cause="Not determined from the TIMEOUT investigation path.",
        explanation=(
            "The incident is labeled TIMEOUT, but the API response error_code is "
            f"{response.error_code}. This path does not invent a timeout cause."
        ),
        recommended_action="Verify that this incident is mapped to the correct request and response records.",
        evidence=evidence,
        trace=trace,
        status=STATUS_NOT_DETERMINED,
    )
