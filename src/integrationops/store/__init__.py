"""Evidence store facade. Engine and tools do not choose JSON vs Mongo."""

from __future__ import annotations

import os

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig
from integrationops.store.base import EvidenceStore
from integrationops.store.errors import EvidenceNotFound, StoreError
from integrationops.store.json_store import JsonStore
from integrationops.store.mongo_store import MongoStore


def build_store() -> EvidenceStore:
    backend = os.environ.get("INTEGRATIONOPS_STORE", "json").strip().lower()
    if backend in ("", "json"):
        return JsonStore()
    if backend == "mongo":
        return MongoStore.from_env()
    raise StoreError(
        f"Unknown INTEGRATIONOPS_STORE={backend!r}. Use 'json' or 'mongo'."
    )


_store: EvidenceStore = build_store()


def load_incident(incident_id: str) -> Incident:
    return _store.load_incident(incident_id)


def get_request(request_id: str) -> ApiRequest:
    return _store.get_request(request_id)


def get_response(request_id: str) -> ApiResponse:
    return _store.get_response(request_id)


def get_lender_config(lender_id: str) -> LenderConfig:
    return _store.get_lender_config(lender_id)


__all__ = [
    "EvidenceNotFound",
    "EvidenceStore",
    "JsonStore",
    "MongoStore",
    "StoreError",
    "build_store",
    "get_lender_config",
    "get_request",
    "get_response",
    "load_incident",
]
