"""JSON evidence store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig
from integrationops.store.errors import EvidenceNotFound, StoreError
from integrationops.store.mapping import (
    incident_from_record,
    lender_from_record,
    request_from_record,
    require_id,
    response_from_record,
)

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]


def default_data_dir() -> Path:
    return _PACKAGE_ROOT / "data"


class JsonStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir or default_data_dir()

    def load_incident(self, incident_id: str) -> Incident:
        require_id(incident_id, "incident_id")
        record = self._find_record("incidents.json", "incident_id", incident_id)
        if record is None:
            raise EvidenceNotFound(f"Incident not found: {incident_id}")
        return incident_from_record(record, incident_id)

    def get_request(self, request_id: str) -> ApiRequest:
        require_id(request_id, "request_id")
        record = self._find_record("requests.json", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Request not found: {request_id}")
        return request_from_record(record, request_id)

    def get_response(self, request_id: str) -> ApiResponse:
        require_id(request_id, "request_id")
        record = self._find_record("responses.json", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Response not found: {request_id}")
        return response_from_record(record, request_id)

    def get_lender_config(self, lender_id: str) -> LenderConfig:
        require_id(lender_id, "lender_id")
        record = self._find_record("lenders.json", "lender_id", lender_id)
        if record is None:
            raise EvidenceNotFound(f"Lender config not found: {lender_id}")
        return lender_from_record(record, lender_id)

    def _evidence_dirs(self) -> list[Path]:
        directories = [self._data_dir]
        generated = self._data_dir / "generated"
        if generated.is_dir() and generated not in directories:
            directories.append(generated)
        return directories

    def _find_record(self, filename: str, key: str, value: str) -> dict[str, Any] | None:
        for record in self._read_records(filename):
            if not isinstance(record, dict):
                raise StoreError(f"{filename} must contain JSON objects")
            if record.get(key) == value:
                return record
        return None

    def _read_records(self, filename: str) -> list[Any]:
        records: list[Any] = []
        found = False
        last_error: StoreError | None = None
        for directory in self._evidence_dirs():
            path = directory / filename
            if not path.exists():
                continue
            found = True
            try:
                raw = path.read_text(encoding="utf-8")
                loaded = json.loads(raw)
            except OSError as exc:
                last_error = StoreError(f"Could not read evidence file: {path}")
                last_error.__cause__ = exc
                continue
            except json.JSONDecodeError as exc:
                last_error = StoreError(f"Invalid JSON in {path}: {exc}")
                last_error.__cause__ = exc
                continue
            if not isinstance(loaded, list):
                raise StoreError(f"{path} must contain a JSON array")
            records.extend(loaded)
        if not found:
            if last_error is not None:
                raise last_error
            raise StoreError(
                f"Evidence file not found: {self._data_dir / filename}"
            )
        return records
