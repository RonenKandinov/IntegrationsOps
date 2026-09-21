"""TIMEOUT investigation: request went out, lender API did not answer in time."""

from __future__ import annotations

from integrationops.models import Diagnosis, EvidenceItem, Incident
from integrationops.tools import append_trace, get_request, get_response


def investigate_timeout(incident: Incident) -> Diagnosis:
    trace: list[str] = []
    append_trace(trace, f"Loaded incident {incident.incident_id}")

    request = get_request(incident.request_id)
    append_trace(trace, f"Loaded request {request.request_id}")

    response = get_response(incident.request_id)
    append_trace(trace, f"Loaded response for {response.request_id}")

    evidence = [
        EvidenceItem(source="request", fact=f"Request {request.request_id} was sent to {request.lender_id}"),
        EvidenceItem(source="response", fact=f"API status = {response.status}"),
        EvidenceItem(source="response", fact=f"API response = {response.error_code}"),
        EvidenceItem(source="response", fact=response.message),
    ]

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
        )

    append_trace(trace, f"Response error_code={response.error_code} does not confirm TIMEOUT")
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
    )
