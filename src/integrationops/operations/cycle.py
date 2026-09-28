"""Connect the investigation engine to the operational state model.

The engine still produces the diagnosis. This module records it on S_t and
applies in-memory transitions. It does not choose an optimal action, allocate
people, or write the evidence store.
"""

from __future__ import annotations

from integrationops.engine import investigate
from integrationops.models import Diagnosis
from integrationops.operations.constants import ACTION_INVESTIGATE
from integrationops.operations.state import SystemState, merchant_operational
from integrationops.operations.transition import transition
from integrationops.operations.types import CandidateAction


def attach_investigation(
    state: SystemState,
    incident_id: str,
    diagnosis: Diagnosis | None = None,
) -> SystemState:
    """Run or accept an investigation diagnosis, then T(S_t, investigate, ·)."""
    if diagnosis is None:
        diagnosis = investigate(incident_id)
    action = CandidateAction(
        kind=ACTION_INVESTIGATE,
        target_id=incident_id,
        reason="Attach the existing investigation-engine diagnosis to S_t.",
    )
    return transition(state, action, diagnosis=diagnosis)


__all__ = [
    "attach_investigation",
    "merchant_operational",
]
