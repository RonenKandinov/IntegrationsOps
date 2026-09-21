"""MongoDB evidence store. Same lookup methods as JsonStore; no JSON files."""

from __future__ import annotations

import os
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


class MongoStore:
    def __init__(self, database: Any) -> None:
        self._db = database

    @classmethod
    def from_env(cls) -> MongoStore:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise StoreError(
                "MongoStore requires pymongo. Install with: pip install -e '.[mongo]'"
            ) from exc
        uri = os.environ.get("INTEGRATIONOPS_MONGO_URI", "mongodb://localhost:27017")
        db_name = os.environ.get("INTEGRATIONOPS_MONGO_DB", "integrationops")
        try:
            client = MongoClient(uri)
            return cls(client[db_name])
        except Exception as exc:
            raise StoreError(f"Could not connect to MongoDB at {uri}") from exc

    def load_incident(self, incident_id: str) -> Incident:
        require_id(incident_id, "incident_id")
        record = self._find("incidents", "incident_id", incident_id)
        if record is None:
            raise EvidenceNotFound(f"Incident not found: {incident_id}")
        return incident_from_record(record, incident_id)

    def get_request(self, request_id: str) -> ApiRequest:
        require_id(request_id, "request_id")
        record = self._find("requests", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Request not found: {request_id}")
        return request_from_record(record, request_id)

    def get_response(self, request_id: str) -> ApiResponse:
        require_id(request_id, "request_id")
        record = self._find("responses", "request_id", request_id)
        if record is None:
            raise EvidenceNotFound(f"Response not found: {request_id}")
        return response_from_record(record, request_id)

    def get_lender_config(self, lender_id: str) -> LenderConfig:
        require_id(lender_id, "lender_id")
        record = self._find("lenders", "lender_id", lender_id)
        if record is None:
            raise EvidenceNotFound(f"Lender config not found: {lender_id}")
        return lender_from_record(record, lender_id)

    def _find(self, collection: str, key: str, value: str) -> dict[str, Any] | None:
        try:
            document = self._db[collection].find_one({key: value})
        except Exception as exc:
            raise StoreError(f"MongoDB lookup failed in {collection}") from exc
        if document is None:
            return None
        if not isinstance(document, dict):
            raise StoreError(f"MongoDB {collection} returned a non-object record")
        document.pop("_id", None)
        return document
