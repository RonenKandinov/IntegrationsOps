"""S_t = (V_t, E_t, R_t, Q_t, Ω_t) assembled from existing IntegrationOps records."""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.investigations.evidence import (
    STATUS_DETERMINED,
    STATUS_GAP,
    STATUS_INCONSISTENT,
    STATUS_NOT_DETERMINED,
)
from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Diagnosis,
    Incident,
    Integration,
    LenderConfig,
    Merchant,
    Organization,
    ValidationReport,
)
from integrationops.operations.constants import (
    CONSTRAINT_API_AVAILABILITY,
    CONSTRAINT_CONFIGURATION,
    CONSTRAINT_PAYMENT,
    CONSTRAINT_PROVIDER_AVAILABILITY,
    CONSTRAINT_TRANSACTION_LIMIT,
    EVENT_API_BEHAVIOR_CHANGE,
    EVENT_LENDER_RECOVERED,
    EVENT_LENDER_UNAVAILABLE,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_PENDING,
    TASK_READY,
)
from integrationops.operations.snapshot import (
    ChainSnapshot,
    Dependency,
    api_entity_id,
    derive_integrations,
    observe_chain,
    world_dependencies,
)
from integrationops.operations.types import (
    EntityRef,
    OperationalConstraint,
    OperationalEvent,
)


@dataclass
class SystemState:
    """S_t. In-memory operational snapshot. Does not write the evidence store."""

    time: int = 0
    merchants: list[Merchant] = field(default_factory=list)
    integrations: list[Integration] = field(default_factory=list)
    lenders: list[LenderConfig] = field(default_factory=list)
    requests: list[ApiRequest] = field(default_factory=list)
    responses: list[ApiResponse] = field(default_factory=list)
    incidents: list[Incident] = field(default_factory=list)
    diagnoses: list[Diagnosis] = field(default_factory=list)
    validations: list[ValidationReport] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    resources: list[OperationalConstraint] = field(default_factory=list)
    task_states: dict[str, str] = field(default_factory=dict)
    events: list[OperationalEvent] = field(default_factory=list)
    resolved_incident_ids: set[str] = field(default_factory=set)
    organizations: list[Organization] = field(default_factory=list)

    def entities(self) -> list[EntityRef]:
        """V_t."""
        items: list[EntityRef] = []
        seen: set[tuple[str, str]] = set()

        def add(entity_id: str, kind: str) -> None:
            key = (entity_id, kind)
            if key in seen:
                return
            seen.add(key)
            items.append(EntityRef(entity_id=entity_id, kind=kind))

        for organization in self.organizations:
            add(organization.organization_id, "organization")
        for merchant in self.merchants:
            add(merchant.merchant_id, "merchant")
        for integration in self.integrations:
            add(integration.integration_id, "integration")
        for lender in self.lenders:
            add(lender.lender_id, "lender_configuration")
        for request in self.requests:
            add(request.request_id, "payment")
        for response in self.responses:
            add(response.request_id, "api_response")
        for incident in self.incidents:
            add(incident.incident_id, "incident")
            add(api_entity_id(incident.lender_id), "api")
        for lender in self.lenders:
            add(api_entity_id(lender.lender_id), "api")
        for diagnosis in self.diagnoses:
            add(diagnosis.incident_id, "investigation")
        for report in self.validations:
            add(report.target_id, "validation")
        for merchant in self.merchants:
            add(merchant.merchant_id, "onboarding")
        return items

    def graph(self) -> tuple[list[EntityRef], list[Dependency]]:
        """G_t = (V_t, E_t)."""
        return self.entities(), list(self.dependencies)

    def constraint(self, kind: str, subject_id: str) -> OperationalConstraint | None:
        for item in self.resources:
            if item.kind == kind and item.subject_id == subject_id:
                return item
        return None

    def resource_available(self, kind: str, subject_id: str) -> bool:
        item = self.constraint(kind, subject_id)
        return item is not None and item.available

    def merchant(self, merchant_id: str) -> Merchant | None:
        return next((item for item in self.merchants if item.merchant_id == merchant_id), None)

    def integration(self, integration_id: str) -> Integration | None:
        return next(
            (item for item in self.integrations if item.integration_id == integration_id),
            None,
        )

    def integrations_for_merchant(self, merchant_id: str) -> list[Integration]:
        return [item for item in self.integrations if item.merchant_id == merchant_id]

    def lender(self, lender_id: str) -> LenderConfig | None:
        return next((item for item in self.lenders if item.lender_id == lender_id), None)

    def request(self, request_id: str) -> ApiRequest | None:
        return next((item for item in self.requests if item.request_id == request_id), None)

    def response(self, request_id: str) -> ApiResponse | None:
        return next((item for item in self.responses if item.request_id == request_id), None)

    def incident(self, incident_id: str) -> Incident | None:
        return next((item for item in self.incidents if item.incident_id == incident_id), None)

    def diagnosis_for(self, incident_id: str) -> Diagnosis | None:
        return next(
            (item for item in self.diagnoses if item.incident_id == incident_id),
            None,
        )

    def validation_for(self, target_id: str) -> ValidationReport | None:
        return next((item for item in self.validations if item.target_id == target_id), None)

    def task_state(self, kind: str, entity_id: str) -> str | None:
        return self.task_states.get(task_key(kind, entity_id))

    def set_task_state(self, kind: str, entity_id: str, status: str) -> None:
        self.task_states[task_key(kind, entity_id)] = status


def task_key(kind: str, entity_id: str) -> str:
    return f"{kind}:{entity_id}"


def merchant_operational(
    state: SystemState,
    merchant_id: str,
    task_states: dict[str, str] | None = None,
) -> bool:
    """True when the merchant's integrations are operational and incidents are completed."""
    q = task_states if task_states is not None else state.task_states
    integrations = state.integrations_for_merchant(merchant_id)
    if not integrations:
        return False
    if not all(item.operational for item in integrations):
        return False
    for incident in state.incidents:
        if incident.merchant_id != merchant_id:
            continue
        if q.get(task_key("incident", incident.incident_id)) != TASK_COMPLETED:
            return False
    return True


def build_system_state(
    *,
    merchants: list[Merchant],
    lender: LenderConfig | None,
    incident: Incident | None = None,
    request: ApiRequest | None = None,
    response: ApiResponse | None = None,
    validation: ValidationReport | None = None,
    diagnosis: Diagnosis | None = None,
    integrations: list[Integration] | None = None,
    events: list[OperationalEvent] | None = None,
    extra_lenders: list[LenderConfig] | None = None,
    extra_requests: list[ApiRequest] | None = None,
    extra_incidents: list[Incident] | None = None,
) -> SystemState:
    """Assemble S_t from records the rest of the system already produced."""
    if incident is None and not merchants:
        raise ValueError("build_system_state needs at least a merchant or an incident")

    if lender is not None:
        lender_id = lender.lender_id
    elif incident is not None:
        lender_id = incident.lender_id
    elif integrations:
        lender_id = integrations[0].lender_id
    else:
        lender_id = ""

    snapshot: ChainSnapshot | None = None
    if incident is not None:
        snapshot = observe_chain(
            merchants=merchants,
            lender=lender,
            incident=incident,
            validation=validation,
            diagnosis=diagnosis,
            request=request,
            response=response,
            integrations=integrations,
        )
        resolved_integrations = snapshot.integrations
        dependencies = list(snapshot.dependencies)
    else:
        resolved_integrations = integrations or derive_integrations(merchants, lender_id)
        dependencies = _standalone_dependencies(merchants, resolved_integrations, lender_id)

    lenders = list(extra_lenders or [])
    if lender is not None and all(item.lender_id != lender.lender_id for item in lenders):
        lenders.append(lender)
    requests = list(extra_requests or [])
    if request is not None and all(item.request_id != request.request_id for item in requests):
        requests.append(request)
    incidents = list(extra_incidents or [])
    if incident is not None and all(item.incident_id != incident.incident_id for item in incidents):
        incidents.append(incident)
    responses = [response] if response is not None else []
    diagnoses = [diagnosis] if diagnosis is not None else []
    validations = [validation] if validation is not None else []
    observed_events = list(events or [])

    state = SystemState(
        time=0,
        merchants=list(merchants),
        integrations=list(resolved_integrations),
        lenders=lenders,
        requests=requests,
        responses=responses,
        incidents=incidents,
        diagnoses=diagnoses,
        validations=validations,
        dependencies=dependencies,
        resources=[],
        task_states={},
        events=observed_events,
    )
    if incident is not None:
        if request is None:
            _ensure_payment_dependency(state, incident)
    state.resources = collect_resources(state)
    state.task_states = collect_task_states(state)
    return state


def system_state_from_snapshot(
    snapshot: ChainSnapshot,
    *,
    request: ApiRequest | None = None,
    response: ApiResponse | None = None,
    events: list[OperationalEvent] | None = None,
) -> SystemState:
    return build_system_state(
        merchants=snapshot.merchants,
        lender=snapshot.lender,
        incident=snapshot.incident,
        request=request or snapshot.request,
        response=response or snapshot.response,
        validation=snapshot.validation,
        diagnosis=snapshot.diagnosis,
        integrations=snapshot.integrations,
        events=events,
    )


def assemble_system_state(
    *,
    merchants: list[Merchant],
    lenders: list[LenderConfig],
    integrations: list[Integration],
    requests: list[ApiRequest] | None = None,
    responses: list[ApiResponse] | None = None,
    incidents: list[Incident] | None = None,
    diagnoses: list[Diagnosis] | None = None,
    events: list[OperationalEvent] | None = None,
    organizations: list[Organization] | None = None,
    time: int = 0,
) -> SystemState:
    """Assemble S_t for a full organization world. Does not write the store."""
    requests = list(requests or [])
    responses = list(responses or [])
    incidents = list(incidents or [])
    diagnoses = list(diagnoses or [])
    state = SystemState(
        time=time,
        merchants=list(merchants),
        integrations=list(integrations),
        lenders=list(lenders),
        requests=requests,
        responses=responses,
        incidents=incidents,
        diagnoses=diagnoses,
        organizations=list(organizations or []),
        dependencies=world_dependencies(
            merchants=merchants,
            integrations=integrations,
            lenders=lenders,
            requests=requests,
            incidents=incidents,
            diagnoses=diagnoses,
        ),
        events=list(events or []),
    )
    refresh_derived(state)
    return state


def collect_resources(state: SystemState) -> list[OperationalConstraint]:
    """R_t from lenders, payments, APIs, providers, and availability events."""
    resources: list[OperationalConstraint] = []
    lender_ids = {lender.lender_id for lender in state.lenders}
    for incident in state.incidents:
        lender_ids.add(incident.lender_id)
    for integration in state.integrations:
        lender_ids.add(integration.lender_id)

    unavailable_lenders: set[str] = set()
    api_changed: set[str] = set()
    for event in state.events:
        if event.kind == EVENT_LENDER_UNAVAILABLE:
            unavailable_lenders.add(event.subject_id)
        elif event.kind == EVENT_LENDER_RECOVERED:
            unavailable_lenders.discard(event.subject_id)
        elif event.kind == EVENT_API_BEHAVIOR_CHANGE:
            api_changed.add(event.subject_id)

    for lender_id in sorted(lender_ids):
        lender = state.lender(lender_id)
        provider_available = lender is not None and lender_id not in unavailable_lenders
        resources.append(
            OperationalConstraint(
                constraint_id=f"provider:{lender_id}",
                kind=CONSTRAINT_PROVIDER_AVAILABILITY,
                subject_id=lender_id,
                available=provider_available,
            )
        )
        timeout = any(
            item.error_code == "TIMEOUT" and _response_lender_id(state, item) == lender_id
            for item in state.responses
        )
        api_available = (
            provider_available and not timeout and lender_id not in api_changed
        )
        resources.append(
            OperationalConstraint(
                constraint_id=f"api:{lender_id}",
                kind=CONSTRAINT_API_AVAILABILITY,
                subject_id=lender_id,
                available=api_available,
            )
        )
        resources.append(
            OperationalConstraint(
                constraint_id=f"configuration:{lender_id}",
                kind=CONSTRAINT_CONFIGURATION,
                subject_id=lender_id,
                available=lender is not None,
                min_amount=lender.min_amount if lender is not None else None,
                max_amount=lender.max_amount if lender is not None else None,
                currency=lender.currency if lender is not None else None,
            )
        )
        if lender is not None:
            resources.append(
                OperationalConstraint(
                    constraint_id=f"transaction_limit:{lender.lender_id}",
                    kind=CONSTRAINT_TRANSACTION_LIMIT,
                    subject_id=lender.lender_id,
                    available=True,
                    min_amount=lender.min_amount,
                    max_amount=lender.max_amount,
                    currency=lender.currency,
                )
            )

    for request in state.requests:
        resources.append(
            OperationalConstraint(
                constraint_id=f"payment:{request.request_id}",
                kind=CONSTRAINT_PAYMENT,
                subject_id=request.request_id,
                available=True,
                currency=request.currency,
            )
        )
    return resources


def collect_task_states(state: SystemState) -> dict[str, str]:
    """Q_t for operational work items. Does not rename Diagnosis.status."""
    q: dict[str, str] = {}
    for merchant in state.merchants:
        q[task_key("onboarding", merchant.merchant_id)] = (
            TASK_COMPLETED if merchant.source_id.strip() else TASK_BLOCKED
        )
        q[task_key("merchant", merchant.merchant_id)] = TASK_BLOCKED

    for incident in state.incidents:
        diagnosis = state.diagnosis_for(incident.incident_id)
        if incident.incident_id in state.resolved_incident_ids:
            q[task_key("investigation", incident.incident_id)] = (
                TASK_COMPLETED if diagnosis is not None else TASK_READY
            )
            q[task_key("incident", incident.incident_id)] = TASK_COMPLETED
        elif diagnosis is None:
            ready = state.lender(incident.lender_id) is not None
            q[task_key("incident", incident.incident_id)] = TASK_PENDING
            q[task_key("investigation", incident.incident_id)] = (
                TASK_READY if ready else TASK_BLOCKED
            )
        elif diagnosis.status == STATUS_DETERMINED:
            q[task_key("investigation", incident.incident_id)] = TASK_COMPLETED
            q[task_key("incident", incident.incident_id)] = TASK_READY
        elif diagnosis.status in {STATUS_GAP, STATUS_INCONSISTENT, STATUS_NOT_DETERMINED}:
            q[task_key("investigation", incident.incident_id)] = TASK_BLOCKED
            q[task_key("incident", incident.incident_id)] = TASK_BLOCKED
        else:
            q[task_key("investigation", incident.incident_id)] = TASK_IN_PROGRESS
            q[task_key("incident", incident.incident_id)] = TASK_IN_PROGRESS

    for integration in state.integrations:
        open_incidents = [
            item
            for item in state.incidents
            if item.merchant_id == integration.merchant_id
            and item.lender_id == integration.lender_id
            and q.get(task_key("incident", item.incident_id)) != TASK_COMPLETED
        ]
        provider_ok = state.resource_available(
            CONSTRAINT_PROVIDER_AVAILABILITY, integration.lender_id
        )
        if integration.operational and not open_incidents:
            q[task_key("integration", integration.integration_id)] = TASK_COMPLETED
        elif not provider_ok or open_incidents:
            q[task_key("integration", integration.integration_id)] = TASK_BLOCKED
        else:
            q[task_key("integration", integration.integration_id)] = TASK_READY

    for report in state.validations:
        q[task_key("validation", report.target_id)] = (
            TASK_COMPLETED if report.valid else TASK_FAILED
        )

    for merchant in state.merchants:
        if merchant_operational(state, merchant.merchant_id, q):
            q[task_key("merchant", merchant.merchant_id)] = TASK_COMPLETED
        elif any(
            item.merchant_id == merchant.merchant_id
            and q.get(task_key("incident", item.incident_id)) != TASK_COMPLETED
            for item in state.incidents
        ):
            q[task_key("merchant", merchant.merchant_id)] = TASK_BLOCKED
        elif merchant.source_id.strip():
            q[task_key("merchant", merchant.merchant_id)] = TASK_READY

    return q


def refresh_derived(state: SystemState) -> None:
    _merge_world_dependencies(state)
    state.resources = collect_resources(state)
    state.task_states = collect_task_states(state)


def _merge_world_dependencies(state: SystemState) -> None:
    extra = world_dependencies(
        merchants=state.merchants,
        integrations=state.integrations,
        lenders=state.lenders,
        requests=state.requests,
        incidents=state.incidents,
        diagnoses=state.diagnoses,
    )
    existing = {
        (item.prerequisite_id, item.dependent_id, item.relation) for item in state.dependencies
    }
    for edge in extra:
        key = (edge.prerequisite_id, edge.dependent_id, edge.relation)
        if key not in existing:
            state.dependencies.append(edge)


def _standalone_dependencies(
    merchants: list[Merchant],
    integrations: list[Integration],
    lender_id: str,
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
    return dependencies


def _ensure_payment_dependency(state: SystemState, incident: Incident) -> None:
    if any(
        item.relation == "incident_requires_request"
        and item.dependent_id == incident.incident_id
        for item in state.dependencies
    ):
        return
    state.dependencies.append(
        Dependency(incident.request_id, incident.incident_id, "incident_requires_request")
    )


def _response_lender_id(state: SystemState, response: ApiResponse) -> str | None:
    if response.noted_lender_id:
        return response.noted_lender_id
    request = state.request(response.request_id)
    if request is not None:
        return request.lender_id
    incident = next(
        (item for item in state.incidents if item.request_id == response.request_id),
        None,
    )
    return incident.lender_id if incident is not None else None
