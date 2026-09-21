"""JSON evidence store. This is the only module that reads evidence files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]


class StoreError(Exception):
    """Raised when evidence files are missing, unreadable, or malformed."""


class EvidenceNotFound(LookupError):
    """Raised when a requested evidence record is missing."""


def default_data_dir() -> Path:
    return _PACKAGE_ROOT / "data"


class JsonStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or default_data_dir()

    def load_incident(self, incident_id: str) -> Incident:
        self._require_id(incident_id, "incident_id")
        record = self._find_record("incidents.json", "incident_id", incident_id)
        if record is None:
            raise EvidenceNotFound(f"Incident not found: {incident_id}")
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

    def get_request(self, request_id: str) -> ApiRequest:
        self._require_id(request_id, "request_id")
        record = self._find_record("requests.json", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Request not found: {request_id}")
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

    def get_response(self, request_id: str) -> ApiResponse:
        self._require_id(request_id, "request_id")
        record = self._find_record("responses.json", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Response not found: {request_id}")
        try:
            return ApiResponse(
                request_id=_require_str(record, "request_id"),
                status=_require_str(record, "status"),
                error_code=_require_str(record, "error_code"),
                message=_require_str(record, "message"),
            )
        except StoreError as exc:
            raise StoreError(f"Malformed response for request {request_id}: {exc}") from exc

    def get_lender_config(self, lender_id: str) -> LenderConfig:
        self._require_id(lender_id, "lender_id")
        record = self._find_record("lenders.json", "lender_id", lender_id)
        if record is None:
            raise EvidenceNotFound(f"Lender config not found: {lender_id}")
        try:
            return LenderConfig(
                lender_id=_require_str(record, "lender_id"),
                min_amount=_require_int(record, "min_amount"),
                max_amount=_require_int(record, "max_amount"),
                currency=_require_str(record, "currency"),
            )
        except StoreError as exc:
            raise StoreError(f"Malformed lender config {lender_id}: {exc}") from exc

    def _require_id(self, value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise EvidenceNotFound(f"Missing {field_name}")

    def _find_record(self, filename: str, key: str, value: str) -> dict[str, Any] | None:
        for record in self._read_records(filename):
            if not isinstance(record, dict):
                raise StoreError(f"{self._data_dir / filename} must contain JSON objects")
            if record.get(key) == value:
                return record
        return None

    def _read_records(self, filename: str) -> list[Any]:
        path = self._data_dir / filename
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StoreError(f"Evidence file not found: {path}") from exc
        except OSError as exc:
            raise StoreError(f"Could not read evidence file: {path}") from exc
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StoreError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(records, list):
            raise StoreError(f"{path} must contain a JSON array")
        return records


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
