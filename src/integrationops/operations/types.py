"""Typed pieces of S_t = (V_t, E_t, R_t, Q_t, Ω_t). Reuses existing domain records."""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Diagnosis,
    Incident,
    LenderConfig,
    Merchant,
)


@dataclass(frozen=True)
class EntityRef:
    """A member of V_t."""

    entity_id: str
    kind: str


@dataclass
class OperationalConstraint:
    """One element of R_t: an operational/system constraint, not a person."""

    constraint_id: str
    kind: str
    subject_id: str
    available: bool
    min_amount: int | None = None
    max_amount: int | None = None
    currency: str | None = None


@dataclass
class OperationalEvent:
    """ω_t ∈ Ω_t. New information, not a scheduled job."""

    event_id: str
    kind: str
    subject_id: str
    detail: str = ""
    merchant: Merchant | None = None
    incident: Incident | None = None
    request: ApiRequest | None = None
    response: ApiResponse | None = None
    lender: LenderConfig | None = None


@dataclass
class CandidateAction:
    """An element of A(S_t) or A_f(S_t). Named, not executed in production."""

    kind: str
    target_id: str
    reason: str
    parameters: dict[str, int | str | bool] = field(default_factory=dict)
