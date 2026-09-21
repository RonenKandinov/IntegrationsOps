"""Configuration validation workflow. Dry-run; never writes Store data."""

from __future__ import annotations

from integrationops.automation.models import AutomationCheck, AutomationResult
from integrationops.automation.safety import safety_decision
from integrationops.models import ValidationReport
from integrationops.validation.service import validate_request

WORKFLOW_NAME = "Configuration Validation"
CHECK_NAMES = ("required_references", "amount_range")


def _checks_from_report(report: ValidationReport) -> list[AutomationCheck]:
    failed_rules = {issue.rule for issue in report.issues}
    return [
        AutomationCheck(name=name, result="FAIL" if name in failed_rules else "PASS")
        for name in CHECK_NAMES
    ]


def run_validation_workflow(request_id: str) -> AutomationResult:
    report = validate_request(request_id)
    status, action = safety_decision(
        issues=list(report.issues),
        evidence_sufficient=True,
        permit_approve=report.valid,
    )
    return AutomationResult(
        target_id=request_id,
        status=status,
        action=action,
        workflow_name=WORKFLOW_NAME,
        checks=_checks_from_report(report),
        issues=list(report.issues),
        dry_run=True,
    )
