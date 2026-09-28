"""Record the merchant → integration → configuration/API/payment → incident chain.

This is one observation of state. It does not score an objective, choose a
policy, execute an action in production, or replace the investigation engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Diagnosis,
    EvidenceItem,
    Incident,
    Integration,
    LenderConfig,
    Merchant,
    ValidationReport,
)


def make_integration_id(merchant_id: str, lender_id: str) -> str:
    return f"{merchant_id}:{lender_id}"


def api_entity_id(lender_id: str) -> str:
    return f"api:{lender_id}"


def derive_integrations(merchants: list[Merchant], lender_id: str) -> list[Integration]:
    return [
        Integration(
            integration_id=make_integration_id(merchant.merchant_id, lender_id),
            merchant_id=merchant.merchant_id,
            lender_id=lender_id,
        )
        for merchant in merchants
    ]


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
    integrations: list[Integration] = field(default_factory=list)
    lender: LenderConfig | None = None
    request: ApiRequest | None = None
    response: ApiResponse | None = None
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


def world_dependencies(
    *,
    merchants: list[Merchant],
    integrations: list[Integration],
    lenders: list[LenderConfig],
    requests: list[ApiRequest] | None = None,
    incidents: list[Incident] | None = None,
    diagnoses: list[Diagnosis] | None = None,
) -> list[Dependency]:
    """E_t for a full organization world. Deduplicates identical edges."""
    requests = requests or []
    incidents = incidents or []
    diagnoses = diagnoses or []
    edges: list[Dependency] = []
    seen: set[tuple[str, str, str]] = set()

    def add(prerequisite_id: str, dependent_id: str, relation: str) -> None:
        key = (prerequisite_id, dependent_id, relation)
        if key in seen:
            return
        seen.add(key)
        edges.append(Dependency(prerequisite_id, dependent_id, relation))

    merchants_by_lender: dict[str, list[str]] = {}
    for integration in integrations:
        add(
            integration.integration_id,
            integration.merchant_id,
            "merchant_requires_integration",
        )
        add(integration.lender_id, integration.integration_id, "integration_requires_lender")
        add(
            api_entity_id(integration.lender_id),
            integration.integration_id,
            "integration_requires_api",
        )
        merchants_by_lender.setdefault(integration.lender_id, [])
        if integration.merchant_id not in merchants_by_lender[integration.lender_id]:
            merchants_by_lender[integration.lender_id].append(integration.merchant_id)

    for lender in lenders:
        for merchant_id in merchants_by_lender.get(lender.lender_id, []):
            add(lender.lender_id, merchant_id, "merchant_requires_lender")

    integration_by_pair = {
        (item.merchant_id, item.lender_id): item for item in integrations
    }
    for request in requests:
        add(request.lender_id, request.request_id, "request_requires_lender")
        add(request.lender_id, request.request_id, "payment_requires_lender")
        integration = integration_by_pair.get((request.merchant_id, request.lender_id))
        if integration is not None:
            add(integration.integration_id, request.request_id, "payment_requires_integration")

    for incident in incidents:
        add(incident.request_id, incident.incident_id, "incident_requires_request")
        add(incident.lender_id, incident.incident_id, "incident_requires_lender")
        add(incident.request_id, incident.incident_id, "incident_requires_payment")
        integration = integration_by_pair.get((incident.merchant_id, incident.lender_id))
        if integration is not None:
            add(
                integration.integration_id,
                incident.incident_id,
                "incident_requires_integration",
            )

    for diagnosis in diagnoses:
        add(diagnosis.incident_id, diagnosis.incident_id, "investigation_of_incident")

    return edges


def operational_states(snapshot: ChainSnapshot) -> list[tuple[str, str, str]]:
    """Current labels for the records in the snapshot. Not a task-state machine."""
    states: list[tuple[str, str, str]] = []
    for merchant in snapshot.merchants:
        states.append((merchant.merchant_id, "merchant", "present"))
    for integration in snapshot.integrations:
        label = "operational" if integration.operational else "not_operational"
        states.append((integration.integration_id, "integration", label))
    if snapshot.lender is not None:
        states.append((snapshot.lender.lender_id, "lender_configuration", "present"))
    elif snapshot.incident is not None:
        states.append((snapshot.incident.lender_id, "lender_configuration", "missing"))
    if snapshot.request is not None:
        states.append((snapshot.request.request_id, "payment", "present"))
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
    request: ApiRequest | None = None,
    response: ApiResponse | None = None,
    integrations: list[Integration] | None = None,
) -> ChainSnapshot:
    """Assemble one snapshot from records the rest of the system already produced."""
    lender_id = lender.lender_id if lender is not None else incident.lender_id
    resolved = integrations or derive_integrations(merchants, lender_id)
    dependencies = shared_lender_dependencies(
        [merchant.merchant_id for merchant in merchants],
        lender_id,
    )
    dependencies.extend(_integration_dependencies(merchants, resolved, lender_id, incident, request))
    dependencies.extend(
        [
            Dependency(incident.request_id, incident.incident_id, "incident_requires_request"),
            Dependency(lender_id, incident.incident_id, "incident_requires_lender"),
            Dependency(lender_id, incident.request_id, "request_requires_lender"),
        ]
    )
    if request is not None:
        dependencies.append(
            Dependency(lender_id, request.request_id, "payment_requires_lender")
        )
        dependencies.append(
            Dependency(request.request_id, incident.incident_id, "incident_requires_payment")
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
        integrations=list(resolved),
        lender=lender,
        request=request,
        response=response,
        incident=incident,
        validation=validation,
        diagnosis=diagnosis,
        dependencies=dependencies,
        events=events,
        candidate_actions=actions,
    )


def _integration_dependencies(
    merchants: list[Merchant],
    integrations: list[Integration],
    lender_id: str,
    incident: Incident,
    request: ApiRequest | None,
) -> list[Dependency]:
    dependencies: list[Dependency] = []
    by_merchant = {item.merchant_id: item for item in integrations}
    for merchant in merchants:
        integration = by_merchant.get(merchant.merchant_id)
        if integration is None:
            continue
        dependencies.extend(
            [
                Dependency(
                    integration.integration_id,
                    merchant.merchant_id,
                    "merchant_requires_integration",
                ),
                Dependency(lender_id, integration.integration_id, "integration_requires_lender"),
                Dependency(
                    api_entity_id(lender_id),
                    integration.integration_id,
                    "integration_requires_api",
                ),
            ]
        )
    incident_integration = by_merchant.get(incident.merchant_id)
    if incident_integration is not None:
        dependencies.append(
            Dependency(
                incident_integration.integration_id,
                incident.incident_id,
                "incident_requires_integration",
            )
        )
        payment_id = request.request_id if request is not None else incident.request_id
        dependencies.append(
            Dependency(
                incident_integration.integration_id,
                payment_id,
                "payment_requires_integration",
            )
        )
    return dependencies
