"""Load evidence for a path. A missing record is a gap, not a guessed cause."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from integrationops.models import ApiRequest, ApiResponse, Diagnosis, EvidenceItem, Incident
from integrationops.store import EvidenceNotFound
from integrationops.tools import append_trace

STATUS_DETERMINED = "ROOT_CAUSE_DETERMINED"
STATUS_GAP = "EVIDENCE_GAP"
STATUS_INCONSISTENT = "INCONSISTENT_EVIDENCE"
STATUS_NOT_DETERMINED = "NOT_DETERMINED"

T = TypeVar("T")


def load_record(
    trace: list[str],
    *,
    loaded: str,
    missing_fact: str,
    loader: Callable[[], T],
) -> T | None:
    try:
        value = loader()
    except EvidenceNotFound as exc:
        append_trace(trace, f"Attempted to load {missing_fact}")
        append_trace(trace, str(exc))
        append_trace(trace, "Investigation stopped without assigning a root cause")
        return None
    append_trace(trace, loaded)
    return value


def gap_diagnosis(
    incident: Incident,
    trace: list[str],
    *,
    detail: str,
    explanation: str,
    recommended_action: str,
    evidence: list[EvidenceItem],
) -> Diagnosis:
    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code=incident.failure_code,
        root_cause=f"Not determined: {detail}",
        explanation=explanation,
        recommended_action=recommended_action,
        evidence=evidence,
        trace=trace,
        status=STATUS_GAP,
    )


def lender_disagreement(
    incident: Incident,
    request: ApiRequest,
    response: ApiResponse,
    trace: list[str],
    evidence: list[EvidenceItem],
) -> Diagnosis | None:
    noted = response.noted_lender_id
    if noted is None or noted == request.lender_id:
        return None
    append_trace(trace, f"Response notes lender {noted}")
    append_trace(trace, f"Request references lender {request.lender_id}")
    append_trace(trace, "Available evidence disagrees about the lender")
    append_trace(trace, "Investigation stopped without assigning a root cause")
    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code=incident.failure_code,
        root_cause="Not determined: request and response name different lenders.",
        explanation=(
            "The request and the API response identify different lenders. "
            "This investigation does not choose one of them and continue."
        ),
        recommended_action="Resolve which lender this request was sent to, then re-run the investigation.",
        evidence=[
            *evidence,
            EvidenceItem(source="request", fact=f"Request lender = {request.lender_id}"),
            EvidenceItem(source="response", fact=f"Response noted lender = {noted}"),
        ],
        trace=trace,
        status=STATUS_INCONSISTENT,
    )
