"""Generate connected synthetic organizations for experiments.

This is not the investigation-evaluation generator in scenario_generator.py.
It builds merchants, lenders, integrations, payments, incidents, and constraints
as one organization, not isolated random records.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from integrationops.investigations.evidence import STATUS_DETERMINED
from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Diagnosis,
    EvidenceItem,
    Incident,
    Integration,
    LenderConfig,
    Merchant,
    Organization,
)
from integrationops.operations.snapshot import make_integration_id
from integrationops.operations.state import SystemState, assemble_system_state

PROFILES: dict[str, dict[str, tuple[int, int] | int]] = {
    "small": {
        "merchants": (5, 8),
        "lenders": (2, 3),
        "extra_integrations": (0, 1),
        "shared_cluster": (3, 4),
        "timeouts": (1, 1),
        "auth_errors": (0, 1),
        "horizon": 8,
    },
    "medium": {
        "merchants": (14, 22),
        "lenders": (3, 5),
        "extra_integrations": (0, 2),
        "shared_cluster": (4, 7),
        "timeouts": (1, 2),
        "auth_errors": (1, 2),
        "horizon": 12,
    },
    "large": {
        "merchants": (32, 48),
        "lenders": (6, 9),
        "extra_integrations": (1, 2),
        "shared_cluster": (6, 10),
        "timeouts": (2, 4),
        "auth_errors": (2, 3),
        "horizon": 16,
    },
}

LOCATIONS = [
    ("sao paulo", "SP", "01000"),
    ("rio de janeiro", "RJ", "20000"),
    ("belo horizonte", "MG", "30000"),
    ("curitiba", "PR", "80000"),
    ("porto alegre", "RS", "90000"),
    ("salvador", "BA", "40000"),
    ("brasilia", "DF", "70000"),
    ("recife", "PE", "50000"),
]

ORG_NAMES = [
    "Coastal Merchant Network",
    "Plateau Payments Group",
    "Harbor Integration Collective",
    "Granite Lending Alliance",
    "Riverbend Commerce Hub",
]

LENDER_TEMPLATES = [
    ("USD", 10000, 50000),
    ("USD", 5000, 25000),
    ("USD", 20000, 150000),
    ("USD", 1000, 12000),
    ("USD", 15000, 80000),
]

TOPOLOGIES = (
    "independent",
    "shared_bottleneck",
    "cascading_failure",
    "dynamic_arrival",
    "shared_resource_conflict",
    "mixed",
)


@dataclass
class OrganizationWorld:
    """One generated organization and the operational records it owns."""

    organization: Organization
    merchants: list[Merchant]
    lenders: list[LenderConfig]
    integrations: list[Integration]
    requests: list[ApiRequest]
    responses: list[ApiResponse]
    incidents: list[Incident]
    diagnoses: list[Diagnosis] = field(default_factory=list)
    seed: int = 0
    profile: str = "small"
    topology: str = "shared_bottleneck"

    def to_system_state(self, time: int = 0) -> SystemState:
        return assemble_system_state(
            merchants=self.merchants,
            lenders=self.lenders,
            integrations=self.integrations,
            requests=self.requests,
            responses=self.responses,
            incidents=self.incidents,
            diagnoses=self.diagnoses,
            organizations=[self.organization],
            time=time,
        )


def generate_organization(
    *,
    profile: str = "small",
    seed: int = 1,
    organization_index: int = 1,
    topology: str = "shared_bottleneck",
    merchant_count: int | None = None,
    lender_count: int | None = None,
) -> OrganizationWorld:
    """Build a connected organization. Same profile+seed+index+topology is reproducible."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile {profile!r}. Use small, medium, or large.")
    if topology not in TOPOLOGIES:
        raise ValueError(f"Unknown topology {topology!r}. Use {', '.join(TOPOLOGIES)}.")
    rng = random.Random(seed)
    spec = PROFILES[profile]
    n_merchants = merchant_count if merchant_count is not None else rng.randint(*spec["merchants"])
    n_lenders = lender_count if lender_count is not None else rng.randint(*spec["lenders"])
    if n_merchants < 1 or n_lenders < 1:
        raise ValueError("merchant_count and lender_count must be at least 1")
    if topology == "independent":
        n_lenders = n_merchants
    organization_id = f"ORG-{organization_index:06d}"
    organization = Organization(
        organization_id=organization_id,
        name=ORG_NAMES[(seed + organization_index) % len(ORG_NAMES)],
        size=profile,
    )

    lenders = _lenders(rng, organization_id, n_lenders)
    merchants = _merchants(rng, organization_id, n_merchants)
    organization.merchant_ids = [item.merchant_id for item in merchants]
    organization.lender_ids = [item.lender_id for item in lenders]

    primary = lenders[0]
    integrations = _integrations(rng, merchants, lenders, primary, spec, topology)
    requests, responses, incidents, diagnoses = _flows(
        rng, merchants, lenders, primary, integrations, spec, topology
    )
    _mark_operational(integrations, incidents)

    return OrganizationWorld(
        organization=organization,
        merchants=merchants,
        lenders=lenders,
        integrations=integrations,
        requests=requests,
        responses=responses,
        incidents=incidents,
        diagnoses=diagnoses,
        seed=seed,
        profile=profile,
        topology=topology,
    )


def generate_organizations(
    *,
    profile: str = "small",
    seed: int = 1,
    count: int = 1,
    topology: str = "shared_bottleneck",
) -> list[OrganizationWorld]:
    if count < 1:
        raise ValueError("count must be at least 1")
    worlds = []
    for index in range(1, count + 1):
        worlds.append(
            generate_organization(
                profile=profile,
                seed=seed + (index - 1) * 1009,
                organization_index=index,
                topology=topology,
            )
        )
    return worlds


def _lenders(rng: random.Random, organization_id: str, n_lenders: int) -> list[LenderConfig]:
    lenders: list[LenderConfig] = []
    tag = organization_id.replace("ORG-", "")
    for index in range(n_lenders):
        currency, min_amount, max_amount = LENDER_TEMPLATES[index % len(LENDER_TEMPLATES)]
        jitter = rng.randint(0, 4) * 1000
        lenders.append(
            LenderConfig(
                lender_id=f"lender_{tag}_{index + 1:02d}",
                min_amount=min_amount,
                max_amount=max_amount + jitter,
                currency=currency,
            )
        )
    return lenders


def _merchants(rng: random.Random, organization_id: str, n_merchants: int) -> list[Merchant]:
    merchants: list[Merchant] = []
    org_tag = organization_id.replace("ORG-", "")
    for index in range(n_merchants):
        city, state, zip_code = LOCATIONS[rng.randrange(len(LOCATIONS))]
        merchants.append(
            Merchant(
                merchant_id=f"MER-{org_tag}-{index + 1:04d}",
                source_id=f"src-{org_tag}-{index + 1:04d}",
                city=city,
                state=state,
                zip_code_prefix=zip_code,
            )
        )
    return merchants


def _integrations(
    rng: random.Random,
    merchants: list[Merchant],
    lenders: list[LenderConfig],
    primary: LenderConfig,
    spec: dict,
    topology: str,
) -> list[Integration]:
    if topology == "independent":
        return [
            Integration(
                integration_id=make_integration_id(merchant.merchant_id, lender.lender_id),
                merchant_id=merchant.merchant_id,
                lender_id=lender.lender_id,
                operational=False,
            )
            for merchant, lender in zip(merchants, lenders, strict=True)
        ]
    extras = lenders[1:]
    allow_extra = topology in {"shared_bottleneck", "mixed"}
    integrations: list[Integration] = []
    for merchant in merchants:
        integrations.append(
            Integration(
                integration_id=make_integration_id(merchant.merchant_id, primary.lender_id),
                merchant_id=merchant.merchant_id,
                lender_id=primary.lender_id,
                operational=False,
            )
        )
        if not extras or not allow_extra:
            continue
        extra_count = rng.randint(*spec["extra_integrations"])
        extra_count = min(extra_count, len(extras))
        if extra_count <= 0:
            continue
        for lender in rng.sample(extras, extra_count):
            integrations.append(
                Integration(
                    integration_id=make_integration_id(merchant.merchant_id, lender.lender_id),
                    merchant_id=merchant.merchant_id,
                    lender_id=lender.lender_id,
                    operational=False,
                )
            )
    return integrations


def _flows(
    rng: random.Random,
    merchants: list[Merchant],
    lenders: list[LenderConfig],
    primary: LenderConfig,
    integrations: list[Integration],
    spec: dict,
    topology: str,
) -> tuple[list[ApiRequest], list[ApiResponse], list[Incident], list[Diagnosis]]:
    requests: list[ApiRequest] = []
    responses: list[ApiResponse] = []
    incidents: list[Incident] = []
    diagnoses: list[Diagnosis] = []
    sequence = 0
    used_pairs: set[tuple[str, str]] = set()

    if topology == "independent":
        for index, (merchant, lender) in enumerate(zip(merchants, lenders, strict=True)):
            sequence += 1
            if index % 2 == 0:
                amount = lender.max_amount + 1 + rng.randint(500, 20000)
                request, response, incident = _payment_case(
                    sequence, merchant, lender, amount, "INVALID_AMOUNT", "FAILED", "INVALID_AMOUNT"
                )
                incidents.append(incident)
                diagnoses.append(_above_max_diagnosis(incident, request, lender))
            else:
                request, response, _incident = _payment_case(
                    sequence, merchant, lender, _within(rng, lender), "OK", "SUCCEEDED", ""
                )
            requests.append(request)
            responses.append(response)
        return requests, responses, incidents, diagnoses

    cluster_size = _cluster_size(rng, spec, topology, len(merchants))
    cluster = merchants[:cluster_size]
    for merchant in cluster:
        sequence += 1
        amount = primary.max_amount + 1 + rng.randint(500, 20000)
        request, response, incident = _payment_case(
            sequence,
            merchant,
            primary,
            amount,
            "INVALID_AMOUNT",
            "FAILED",
            "INVALID_AMOUNT",
        )
        requests.append(request)
        responses.append(response)
        incidents.append(incident)
        diagnoses.append(_above_max_diagnosis(incident, request, primary))
        used_pairs.add((merchant.merchant_id, primary.lender_id))

    if topology == "cascading_failure":
        merchant = merchants[0]
        pair = (merchant.merchant_id, primary.lender_id)
        if pair not in used_pairs:
            sequence += 1
            request, response, incident = _payment_case(
                sequence,
                merchant,
                primary,
                _within(rng, primary),
                "TIMEOUT",
                "FAILED",
                "TIMEOUT",
            )
            requests.append(request)
            responses.append(response)
            incidents.append(incident)
            used_pairs.add(pair)
    elif topology != "dynamic_arrival":
        timeout_lenders = lenders[1:] or lenders
        timeout_count = rng.randint(*spec["timeouts"])
        if topology == "shared_resource_conflict":
            timeout_count = 0
        for _ in range(timeout_count):
            merchant = rng.choice(merchants)
            lender = rng.choice(timeout_lenders)
            pair = (merchant.merchant_id, lender.lender_id)
            if pair in used_pairs:
                continue
            sequence += 1
            request, response, incident = _payment_case(
                sequence,
                merchant,
                lender,
                _within(rng, lender),
                "TIMEOUT",
                "FAILED",
                "TIMEOUT",
            )
            requests.append(request)
            responses.append(response)
            incidents.append(incident)
            used_pairs.add(pair)

        auth_count = rng.randint(*spec["auth_errors"])
        if topology == "shared_resource_conflict":
            auth_count = 0
        for _ in range(auth_count):
            merchant = rng.choice(merchants)
            lender = rng.choice(lenders)
            pair = (merchant.merchant_id, lender.lender_id)
            if pair in used_pairs:
                continue
            sequence += 1
            request, response, incident = _payment_case(
                sequence,
                merchant,
                lender,
                _within(rng, lender),
                "AUTHENTICATION_ERROR",
                "FAILED",
                "AUTHENTICATION_ERROR",
            )
            requests.append(request)
            responses.append(response)
            incidents.append(incident)
            used_pairs.add(pair)

    integration_pairs = {(item.merchant_id, item.lender_id) for item in integrations}
    for merchant_id, lender_id in sorted(integration_pairs):
        if (merchant_id, lender_id) in used_pairs:
            continue
        merchant = next(item for item in merchants if item.merchant_id == merchant_id)
        lender = next(item for item in lenders if item.lender_id == lender_id)
        sequence += 1
        request, response, _incident = _payment_case(
            sequence,
            merchant,
            lender,
            _within(rng, lender),
            "OK",
            "SUCCEEDED",
            "",
        )
        requests.append(request)
        responses.append(response)

    return requests, responses, incidents, diagnoses


def _cluster_size(rng: random.Random, spec: dict, topology: str, n_merchants: int) -> int:
    if topology == "dynamic_arrival":
        return min(1, n_merchants)
    if topology == "cascading_failure":
        return 0
    if topology == "shared_resource_conflict":
        return min(max(n_merchants - 1, 3), n_merchants)
    return min(rng.randint(*spec["shared_cluster"]), n_merchants)


def _payment_case(
    sequence: int,
    merchant: Merchant,
    lender: LenderConfig,
    amount: int,
    failure_code: str,
    status: str,
    error_code: str,
) -> tuple[ApiRequest, ApiResponse, Incident]:
    request_id = f"REQ-E{sequence:06d}"
    incident_id = f"INC-E{sequence:06d}"
    request = ApiRequest(
        request_id=request_id,
        merchant_id=merchant.merchant_id,
        lender_id=lender.lender_id,
        amount=amount,
        currency=lender.currency,
    )
    response = ApiResponse(
        request_id=request_id,
        status=status,
        error_code=error_code,
        message=f"{error_code or 'OK'} for {merchant.merchant_id} via {lender.lender_id}",
    )
    incident = Incident(
        incident_id=incident_id,
        merchant_id=merchant.merchant_id,
        lender_id=lender.lender_id,
        failure_code=failure_code,
        request_id=request_id,
    )
    return request, response, incident


def _within(rng: random.Random, lender: LenderConfig) -> int:
    span = max(lender.max_amount - lender.min_amount, 1)
    return lender.min_amount + rng.randint(0, span)


def _above_max_diagnosis(
    incident: Incident,
    request: ApiRequest,
    lender: LenderConfig,
) -> Diagnosis:
    return Diagnosis(
        incident_id=incident.incident_id,
        failure_code="INVALID_AMOUNT",
        root_cause="Requested amount is above the lender's maximum allowed amount.",
        explanation="The requested amount violates the lender's configured maximum amount.",
        recommended_action=(
            f"Check whether the loan amount should be reduced to at most {lender.max_amount} "
            "or whether the lender configuration is incorrect."
        ),
        evidence=[
            EvidenceItem(source="request", fact=f"Request amount = {request.amount}"),
            EvidenceItem(source="lender", fact=f"Lender minimum = {lender.min_amount}"),
            EvidenceItem(source="lender", fact=f"Lender maximum = {lender.max_amount}"),
            EvidenceItem(source="response", fact="API response = INVALID_AMOUNT"),
        ],
        status=STATUS_DETERMINED,
    )


def _mark_operational(integrations: list[Integration], incidents: list[Incident]) -> None:
    blocked = {(item.merchant_id, item.lender_id) for item in incidents}
    for integration in integrations:
        integration.operational = (integration.merchant_id, integration.lender_id) not in blocked
