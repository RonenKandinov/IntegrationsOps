"""Investigation engine: load incident, select path from failure_code, run only that path."""

from __future__ import annotations

from integrationops.investigations import (
    investigate_authentication_error,
    investigate_invalid_amount,
    investigate_timeout,
)
from integrationops.models import Diagnosis, EvidenceItem
from integrationops.store import load_incident
from integrationops.tools import append_trace

PATHS = {
    "INVALID_AMOUNT": investigate_invalid_amount,
    "TIMEOUT": investigate_timeout,
    "AUTHENTICATION_ERROR": investigate_authentication_error,
}


def investigate(incident_id: str) -> Diagnosis:
    incident = load_incident(incident_id)
    path = PATHS.get(incident.failure_code)
    if path is None:
        trace: list[str] = []
        append_trace(trace, f"Loaded incident {incident.incident_id}")
        append_trace(trace, f"No investigation path for failure_code={incident.failure_code}")
        return Diagnosis(
            incident_id=incident.incident_id,
            failure_code=incident.failure_code,
            root_cause="Not determined: no investigation path for this failure code.",
            explanation=(
                f"{incident.failure_code} has no registered investigation path. "
                "The engine does not run unrelated tools when the failure type is unknown."
            ),
            recommended_action="Add a failure-specific investigation path for this code, then re-run.",
            evidence=[
                EvidenceItem(source="incident", fact=f"failure_code={incident.failure_code}"),
            ],
            trace=trace,
        )
    return path(incident)
