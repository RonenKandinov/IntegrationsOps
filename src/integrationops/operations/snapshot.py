"""Record the merchant → lender → validation → incident → diagnosis chain.

This is one observation of state. It does not score an objective, choose a
policy, execute an action, or build the next state.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.models import (
    Diagnosis,
    EvidenceItem,
    Incident,
    LenderConfig,
    Merchant,
    ValidationReport,
)


@dataclass(frozen=True)
class Dependency:
    """`dependent_id` depends on `prerequisite_id`."""

    prerequisite_id: str
    dependent_id: str
    relation: str


@dataclass
class ChainSnapshot:
    """Entities, states, dependencies, events, and candidate actions at one moment."""

    merchants: list[Merchant] = field(default_factory=list)
    lender: LenderConfig | None = None
    incident: Incident | None = None
    validation: ValidationReport | None = None
    diagnosis: Diagnosis | None = None
    dependencies: list[Dependency] = field(default_factory=list)
    events: list[EvidenceItem] = field(default_factory=list)
    candidate_actions: list[str] = field(default_factory=list)


def shared_lender_dependencies(merchant_ids: list[str], lender_id: str) -> list[Dependency]:
    """Each merchant depends on the same lender configuration."""
    return [
        Dependency(
            prerequisite_id=lender_id,
            dependent_id=merchant_id,
            relation="merchant_requires_lender",
        )
        for merchant_id in merchant_ids
    ]


def merchants_sharing_lender(lender_id: str, dependencies: list[Dependency]) -> list[str]:
    """Merchant ids whose go-forward work depends on this lender configuration."""
    return [
        item.dependent_id
        for item in dependencies
        if item.prerequisite_id == lender_id and item.relation == "merchant_requires_lender"
    ]


def operational_states(snapshot: ChainSnapshot) -> list[tuple[str, str, str]]:
    """Current labels for the records in the snapshot. Not a task-state machine."""
    states: list[tuple[str, str, str]] = []
    for merchant in snapshot.merchants:
        states.append((merchant.merchant_id, "merchant", "present"))
    if snapshot.lender is not None:
        states.append((snapshot.lender.lender_id, "lender_configuration", "present"))
    elif snapshot.incident is not None:
        states.append((snapshot.incident.lender_id, "lender_configuration", "missing"))
    if snapshot.validation is not None:
        label = "valid" if snapshot.validation.valid else "invalid"
        states.append((snapshot.validation.target_id, "validation", label))
    if snapshot.diagnosis is not None:
        states.append(
            (snapshot.diagnosis.incident_id, "investigation", snapshot.diagnosis.status or "unset")
        )
    return states


def observe_chain(
    *,
    merchants: list[Merchant],
    lender: LenderConfig | None,
    incident: Incident,
    validation: ValidationReport | None = None,
    diagnosis: Diagnosis | None = None,
) -> ChainSnapshot:
    """Assemble one snapshot from records the rest of the system already produced."""
    lender_id = lender.lender_id if lender is not None else incident.lender_id
    dependencies = shared_lender_dependencies(
        [merchant.merchant_id for merchant in merchants],
        lender_id,
    )
    dependencies.extend(
        [
            Dependency(incident.request_id, incident.incident_id, "incident_requires_request"),
            Dependency(lender_id, incident.incident_id, "incident_requires_lender"),
            Dependency(lender_id, incident.request_id, "request_requires_lender"),
        ]
    )
    if validation is not None:
        dependencies.append(
            Dependency(lender_id, validation.target_id, "validation_checks_lender")
        )
    if diagnosis is not None:
        dependencies.append(
            Dependency(incident.incident_id, diagnosis.incident_id, "investigation_of_incident")
        )
    actions: list[str] = []
    if diagnosis is not None and diagnosis.recommended_action:
        actions.append(diagnosis.recommended_action)
    events = [
        EvidenceItem(
            source="incident",
            fact=f"event incident={incident.incident_id} failure_code={incident.failure_code}",
        )
    ]
    return ChainSnapshot(
        merchants=list(merchants),
        lender=lender,
        incident=incident,
        validation=validation,
        diagnosis=diagnosis,
        dependencies=dependencies,
        events=events,
        candidate_actions=actions,
    )
