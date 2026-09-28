"""Turn store records into existing dataclasses. Known fields only."""

from __future__ import annotations

from typing import Any

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig
from integrationops.store.errors import EvidenceNotFound, StoreError


def require_id(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceNotFound(f"Missing {field_name}")


def incident_from_record(record: dict[str, Any], incident_id: str) -> Incident:
    try:
        return Incident(
            incident_id=_require_str(record, "incident_id"),
            merchant_id=_require_str(record, "merchant_id"),
            lender_id=_require_str(record, "lender_id"),
            failure_code=_require_str(record, "failure_code"),
            request_id=_require_str(record, "request_id"),
        )
    except StoreError as exc:
        raise StoreError(f"Malformed incident {incident_id}: {exc}") from exc


def request_from_record(record: dict[str, Any], request_id: str) -> ApiRequest:
    try:
        return ApiRequest(
            request_id=_require_str(record, "request_id"),
            merchant_id=_require_str(record, "merchant_id"),
            lender_id=_require_str(record, "lender_id"),
            amount=_require_int(record, "amount"),
            currency=_require_str(record, "currency"),
        )
    except StoreError as exc:
        raise StoreError(f"Malformed request {request_id}: {exc}") from exc


def response_from_record(record: dict[str, Any], request_id: str) -> ApiResponse:
    try:
        return ApiResponse(
            request_id=_require_str(record, "request_id"),
            status=_require_str(record, "status"),
            error_code=_require_str(record, "error_code"),
            message=_require_str(record, "message"),
            noted_lender_id=_optional_str(record, "noted_lender_id"),
        )
    except StoreError as exc:
        raise StoreError(f"Malformed response for request {request_id}: {exc}") from exc


def lender_from_record(record: dict[str, Any], lender_id: str) -> LenderConfig:
    try:
        return LenderConfig(
            lender_id=_require_str(record, "lender_id"),
            min_amount=_require_int(record, "min_amount"),
            max_amount=_require_int(record, "max_amount"),
            currency=_require_str(record, "currency"),
        )
    except StoreError as exc:
        raise StoreError(f"Malformed lender config {lender_id}: {exc}") from exc


def _optional_str(record: dict[str, Any], field: str) -> str | None:
    if field not in record or record[field] is None:
        return None
    value = record[field]
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _require_str(record: dict[str, Any], field: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise StoreError(f"missing or invalid field {field!r}")
    return value


def _require_int(record: dict[str, Any], field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StoreError(f"missing or invalid integer field {field!r}")
    return value
