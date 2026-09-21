"""Backend-agnostic evidence store. Engine and paths must not import JSON or Mongo."""

from typing import Protocol

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig


class EvidenceStore(Protocol):
    def load_incident(self, incident_id: str) -> Incident: ...

    def get_request(self, request_id: str) -> ApiRequest: ...

    def get_response(self, request_id: str) -> ApiResponse: ...

    def get_lender_config(self, lender_id: str) -> LenderConfig: ...
