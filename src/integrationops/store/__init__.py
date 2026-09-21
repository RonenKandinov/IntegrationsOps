"""Evidence store facade. Callers do not depend on JSON vs a later backend."""

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig
from integrationops.store.json_store import EvidenceNotFound, JsonStore, StoreError

_store = JsonStore()


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
    "JsonStore",
    "StoreError",
    "get_lender_config",
    "get_request",
    "get_response",
    "load_incident",
]
