"""Load required entities from the Store. Missing records are issues, not diagnoses."""

from __future__ import annotations

from integrationops.models import ApiRequest, EvidenceItem, Incident, LenderConfig, ValidationIssue
from integrationops.store import EvidenceNotFound, get_lender_config, get_request, load_incident


def load_request_or_issue(request_id: str) -> tuple[ApiRequest | None, list[ValidationIssue]]:
    try:
        return get_request(request_id), []
    except EvidenceNotFound:
        return None, [
            ValidationIssue(
                rule="required_references",
                code="missing_request",
                message=f"Request not found: {request_id}",
                evidence=[EvidenceItem(source="store", fact=f"request_id={request_id}")],
                field="request_id",
            )
        ]


def load_lender_or_issue(lender_id: str) -> tuple[LenderConfig | None, list[ValidationIssue]]:
    try:
        return get_lender_config(lender_id), []
    except EvidenceNotFound:
        return None, [
            ValidationIssue(
                rule="required_references",
                code="missing_lender",
                message=f"Lender config not found: {lender_id}",
                evidence=[EvidenceItem(source="store", fact=f"lender_id={lender_id}")],
                field="lender_id",
            )
        ]


def load_incident_or_issue(incident_id: str) -> tuple[Incident | None, list[ValidationIssue]]:
    try:
        return load_incident(incident_id), []
    except EvidenceNotFound:
        return None, [
            ValidationIssue(
                rule="required_references",
                code="missing_incident",
                message=f"Incident not found: {incident_id}",
                evidence=[EvidenceItem(source="store", fact=f"incident_id={incident_id}")],
                field="incident_id",
            )
        ]
