"""Investigation tools selected by a failure-specific path."""

from __future__ import annotations

from typing import Literal

from integrationops.models import ApiRequest, ApiResponse, LenderConfig
from integrationops.store import (
    get_lender_config as store_get_lender_config,
)
from integrationops.store import (
    get_request as store_get_request,
)
from integrationops.store import (
    get_response as store_get_response,
)

AmountLimitResult = Literal["below_min", "above_max", "within_limits"]


def get_request(request_id: str) -> ApiRequest:
    return store_get_request(request_id)


def get_response(request_id: str) -> ApiResponse:
    return store_get_response(request_id)


def get_lender_config(lender_id: str) -> LenderConfig:
    return store_get_lender_config(lender_id)


def compare_amount_to_limits(amount: int, min_amount: int, max_amount: int) -> AmountLimitResult:
    if amount < min_amount:
        return "below_min"
    if amount > max_amount:
        return "above_max"
    return "within_limits"


def append_trace(trace: list[str], step: str) -> None:
    trace.append(step)
