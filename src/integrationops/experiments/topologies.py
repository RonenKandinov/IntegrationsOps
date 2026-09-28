"""Controlled scenario families. Not random graphs."""

from __future__ import annotations

from integrationops.generators.organization import OrganizationWorld, TOPOLOGIES
from integrationops.models import ApiRequest, ApiResponse, Incident, Merchant
from integrationops.operations.constants import (
    EVENT_API_BEHAVIOR_CHANGE,
    EVENT_CONFIGURATION_CHANGED,
    EVENT_LENDER_RECOVERED,
    EVENT_LENDER_UNAVAILABLE,
    EVENT_NEW_INCIDENT,
    EVENT_NEW_MERCHANT,
    EVENT_UNEXPECTED_RESPONSE,
    EVENT_WORK_ARRIVED,
)
from integrationops.operations.types import OperationalEvent


def timeline_events(
    world: OrganizationWorld,
    rng,
    horizon: int,
    topology: str,
) -> list[tuple[int, OperationalEvent]]:
    if topology not in TOPOLOGIES:
        raise ValueError(f"Unknown topology {topology!r}. Use {', '.join(TOPOLOGIES)}.")
    if topology == "independent":
        return _independent_events(world, rng, horizon)
    if topology == "cascading_failure":
        return _cascading_events(world, rng, horizon)
    if topology == "dynamic_arrival":
        return _arrival_events(world, rng, horizon)
    if topology == "shared_resource_conflict":
        return _conflict_events(world, rng, horizon)
    if topology == "mixed":
        return _mixed_events(world, rng, horizon)
    return _bottleneck_events(world, rng, horizon)


def _bottleneck_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    events: list[tuple[int, OperationalEvent]] = []
    next_seq = len(world.requests) + 1
    primary = world.lenders[0] if world.lenders else None
    healthy = _healthy_merchants(world)
    if healthy and primary is not None and horizon >= 2:
        events.append(_incident_at(2, next_seq, healthy[0], primary, EVENT_NEW_INCIDENT))
        next_seq += 1
    if len(world.lenders) > 1 and horizon >= 4:
        events.append(
            (
                min(4, horizon),
                OperationalEvent(
                    event_id=f"evt-lender-down-{world.lenders[-1].lender_id}",
                    kind=EVENT_LENDER_UNAVAILABLE,
                    subject_id=world.lenders[-1].lender_id,
                    detail="Secondary provider became unavailable.",
                ),
            )
        )
    if primary is not None and horizon >= 5:
        events.append(_new_merchant_at(min(5, horizon), world, primary.lender_id))
    if world.lenders and horizon >= 6:
        target = world.lenders[min(1, len(world.lenders) - 1)].lender_id
        events.append(
            (
                min(6, horizon),
                OperationalEvent(
                    event_id=f"evt-api-change-{target}",
                    kind=EVENT_API_BEHAVIOR_CHANGE,
                    subject_id=target,
                    detail="API behavior changed for this provider.",
                ),
            )
        )
    if world.requests and horizon >= 7:
        sample = rng.choice(world.requests)
        events.append(
            (
                min(7, horizon),
                OperationalEvent(
                    event_id=f"evt-unexpected-{sample.request_id}",
                    kind=EVENT_UNEXPECTED_RESPONSE,
                    subject_id=sample.request_id,
                    detail="An unexpected API response arrived.",
                    response=ApiResponse(
                        request_id=sample.request_id,
                        status="FAILED",
                        error_code="UNEXPECTED",
                        message="Unexpected provider response",
                    ),
                ),
            )
        )
    return [(tick, event) for tick, event in events if tick <= horizon]


def _independent_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    events: list[tuple[int, OperationalEvent]] = []
    next_seq = len(world.requests) + 1
    healthy = _healthy_merchants(world)
    if healthy and world.lenders and horizon >= 2:
        merchant = healthy[0]
        lender = _lender_for(world, merchant.merchant_id) or world.lenders[0]
        events.append(_incident_at(2, next_seq, merchant, lender, EVENT_NEW_INCIDENT))
        next_seq += 1
    if len(world.lenders) > 1 and horizon >= 4:
        isolated = world.lenders[-1]
        events.append(
            (
                min(4, horizon),
                OperationalEvent(
                    event_id=f"evt-lender-down-{isolated.lender_id}",
                    kind=EVENT_LENDER_UNAVAILABLE,
                    subject_id=isolated.lender_id,
                    detail="One independent provider failed; others stay up.",
                ),
            )
        )
    if healthy and horizon >= 6 and world.lenders:
        events.append(_new_merchant_at(min(6, horizon), world, world.lenders[0].lender_id))
    return [(tick, event) for tick, event in events if tick <= horizon]


def _cascading_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    events: list[tuple[int, OperationalEvent]] = []
    next_seq = len(world.requests) + 1
    primary = world.lenders[0] if world.lenders else None
    if primary is None:
        return events
    if horizon >= 2:
        events.append(
            (
                2,
                OperationalEvent(
                    event_id=f"evt-cascade-down-{primary.lender_id}",
                    kind=EVENT_LENDER_UNAVAILABLE,
                    subject_id=primary.lender_id,
                    detail="Shared provider failed; dependents cascade.",
                ),
            )
        )
    healthy = _healthy_merchants(world)
    for offset, merchant in enumerate(healthy[:3]):
        tick = 3 + offset
        if tick > horizon:
            break
        events.append(_incident_at(tick, next_seq, merchant, primary, EVENT_WORK_ARRIVED))
        next_seq += 1
    if horizon >= 8:
        events.append(
            (
                min(8, horizon),
                OperationalEvent(
                    event_id=f"evt-cascade-recover-{primary.lender_id}",
                    kind=EVENT_LENDER_RECOVERED,
                    subject_id=primary.lender_id,
                    detail="Shared provider recovered.",
                ),
            )
        )
    return [(tick, event) for tick, event in events if tick <= horizon]


def _arrival_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    events: list[tuple[int, OperationalEvent]] = []
    next_seq = len(world.requests) + 1
    primary = world.lenders[0] if world.lenders else None
    if primary is None:
        return events
    healthy = list(_healthy_merchants(world))
    for index, merchant in enumerate(healthy):
        tick = 2 + index
        if tick > min(horizon, 7):
            break
        events.append(_incident_at(tick, next_seq, merchant, primary, EVENT_NEW_INCIDENT))
        next_seq += 1
    if horizon >= 3:
        events.append(_new_merchant_at(3, world, primary.lender_id))
    if horizon >= 5:
        joined = Merchant(
            merchant_id=f"MER-{world.organization.organization_id.replace('ORG-', '')}-NEW2",
            source_id=f"src-new2-{world.organization.organization_id}",
            city="recife",
            state="PE",
            zip_code_prefix="50000",
        )
        events.append(
            (
                5,
                OperationalEvent(
                    event_id=f"evt-new-merchant-{joined.merchant_id}",
                    kind=EVENT_NEW_MERCHANT,
                    subject_id=primary.lender_id,
                    detail="Additional merchant onboarding.",
                    merchant=joined,
                ),
            )
        )
    return [(tick, event) for tick, event in events if tick <= horizon]


def _conflict_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    events: list[tuple[int, OperationalEvent]] = []
    next_seq = len(world.requests) + 1
    primary = world.lenders[0] if world.lenders else None
    if primary is None:
        return events
    healthy = _healthy_merchants(world)
    if healthy and horizon >= 2:
        events.append(_incident_at(2, next_seq, healthy[0], primary, EVENT_WORK_ARRIVED))
        next_seq += 1
    if len(healthy) > 1 and horizon >= 3:
        events.append(_incident_at(3, next_seq, healthy[1], primary, EVENT_WORK_ARRIVED))
    if horizon >= 6:
        events.append(
            (
                6,
                OperationalEvent(
                    event_id=f"evt-config-changed-{primary.lender_id}",
                    kind=EVENT_CONFIGURATION_CHANGED,
                    subject_id=primary.lender_id,
                    detail="Shared configuration changed while many merchants still depend on it.",
                    lender=primary,
                ),
            )
        )
    return [(tick, event) for tick, event in events if tick <= horizon]


def _mixed_events(world: OrganizationWorld, rng, horizon: int) -> list[tuple[int, OperationalEvent]]:
    bottleneck = _bottleneck_events(world, rng, horizon)
    extra: list[tuple[int, OperationalEvent]] = []
    primary = world.lenders[0] if world.lenders else None
    if primary is not None and horizon >= 8:
        extra.append(
            (
                min(8, horizon),
                OperationalEvent(
                    event_id=f"evt-recover-{primary.lender_id}",
                    kind=EVENT_LENDER_RECOVERED,
                    subject_id=primary.lender_id,
                    detail="A previously unavailable dependency recovered.",
                ),
            )
        )
    merged = {tick: event for tick, event in bottleneck}
    for tick, event in extra:
        merged[tick] = event
    return sorted(merged.items(), key=lambda item: item[0])


def _healthy_merchants(world: OrganizationWorld) -> list[Merchant]:
    broken = {item.merchant_id for item in world.incidents}
    return [item for item in world.merchants if item.merchant_id not in broken]


def _lender_for(world: OrganizationWorld, merchant_id: str):
    integration = next((item for item in world.integrations if item.merchant_id == merchant_id), None)
    if integration is None:
        return None
    return next((item for item in world.lenders if item.lender_id == integration.lender_id), None)


def _incident_at(
    tick: int,
    sequence: int,
    merchant: Merchant,
    lender,
    kind: str,
) -> tuple[int, OperationalEvent]:
    request_id = f"REQ-E{sequence:06d}"
    incident_id = f"INC-E{sequence:06d}"
    request = ApiRequest(
        request_id=request_id,
        merchant_id=merchant.merchant_id,
        lender_id=lender.lender_id,
        amount=lender.max_amount + 2500,
        currency=lender.currency,
    )
    response = ApiResponse(
        request_id=request_id,
        status="FAILED",
        error_code="INVALID_AMOUNT",
        message="INVALID_AMOUNT from dynamic event",
    )
    incident = Incident(
        incident_id=incident_id,
        merchant_id=merchant.merchant_id,
        lender_id=lender.lender_id,
        failure_code="INVALID_AMOUNT",
        request_id=request_id,
    )
    return (
        tick,
        OperationalEvent(
            event_id=f"evt-{kind}-{incident.incident_id}",
            kind=kind,
            subject_id=incident.incident_id,
            detail="New operational work arrived.",
            incident=incident,
            request=request,
            response=response,
        ),
    )


def _new_merchant_at(tick: int, world: OrganizationWorld, lender_id: str) -> tuple[int, OperationalEvent]:
    org = world.organization
    merchant = Merchant(
        merchant_id=f"MER-{org.organization_id.replace('ORG-', '')}-NEW1",
        source_id=f"src-new-{org.organization_id}",
        city="campinas",
        state="SP",
        zip_code_prefix="13000",
    )
    return (
        tick,
        OperationalEvent(
            event_id=f"evt-new-merchant-{merchant.merchant_id}",
            kind=EVENT_NEW_MERCHANT,
            subject_id=lender_id,
            detail="A new merchant joined the organization.",
            merchant=merchant,
        ),
    )
