"""Run validation rules against Store records."""

from __future__ import annotations

from integrationops.models import ValidationReport
from integrationops.validation.amount import validate_amount
from integrationops.validation.consistency import validate_invalid_amount_consistency
from integrationops.validation.references import (
    load_incident_or_issue,
    load_lender_or_issue,
    load_request_or_issue,
)


def validate_request(request_id: str) -> ValidationReport:
    issues = []
    request, request_issues = load_request_or_issue(request_id)
    issues.extend(request_issues)
    if request is None:
        return ValidationReport(target_id=request_id, valid=False, issues=issues)
    lender, lender_issues = load_lender_or_issue(request.lender_id)
    issues.extend(lender_issues)
    if lender is None:
        return ValidationReport(target_id=request_id, valid=False, issues=issues)
    issues.extend(validate_amount(request.amount, lender))
    return ValidationReport(target_id=request_id, valid=not issues, issues=issues)


def validate_incident(incident_id: str) -> ValidationReport:
    issues = []
    incident, incident_issues = load_incident_or_issue(incident_id)
    issues.extend(incident_issues)
    if incident is None:
        return ValidationReport(target_id=incident_id, valid=False, issues=issues)
    request, request_issues = load_request_or_issue(incident.request_id)
    issues.extend(request_issues)
    lender, lender_issues = load_lender_or_issue(incident.lender_id)
    issues.extend(lender_issues)
    if request is None or lender is None:
        return ValidationReport(target_id=incident_id, valid=False, issues=issues)
    issues.extend(validate_amount(request.amount, lender))
    issues.extend(validate_invalid_amount_consistency(incident, request, lender))
    return ValidationReport(target_id=incident_id, valid=not issues, issues=issues)
