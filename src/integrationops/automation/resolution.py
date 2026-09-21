"""Turn an existing diagnosis into a dry-run automation decision. Never approves a fix."""

from __future__ import annotations

from integrationops.automation.models import AutomationCheck, AutomationResult
from integrationops.automation.safety import safety_decision
from integrationops.engine import investigate
from integrationops.models import EvidenceItem, ValidationIssue
from integrationops.store import EvidenceNotFound
from integrationops.validation.references import load_incident_or_issue
from integrationops.validation.service import validate_incident

WORKFLOW_NAME = "Investigation Resolution"

_DETERMINATE_INVALID_AMOUNT = (
    "Requested amount is below the lender's minimum allowed amount.",
    "Requested amount is above the lender's maximum allowed amount.",
)


def run_resolution_workflow(incident_id: str) -> AutomationResult:
    incident, incident_issues = load_incident_or_issue(incident_id)
    if incident is None:
        status, action = safety_decision(
            issues=incident_issues,
            evidence_sufficient=True,
            permit_approve=False,
        )
        return AutomationResult(
            target_id=incident_id,
            status=status,
            action=action,
            workflow_name=WORKFLOW_NAME,
            checks=[AutomationCheck(name="required_references", result="FAIL")],
            issues=incident_issues,
            dry_run=True,
        )

    diagnosis = None
    try:
        diagnosis = investigate(incident_id)
    except EvidenceNotFound as exc:
        evidence_error: EvidenceNotFound | None = exc
    else:
        evidence_error = None

    report = validate_incident(incident_id)
    issues = list(report.issues)
    if evidence_error is not None:
        issues.extend(_evidence_gap_issues(evidence_error, issues))

    hard = [issue for issue in issues if issue.code.startswith("missing_")]
    inconsistent = any(issue.code == "inconsistent_invalid_amount" for issue in issues)
    root_cause = diagnosis.root_cause if diagnosis is not None else ""
    not_determined = root_cause.startswith("Not determined")
    response_present = bool(
        diagnosis and any(item.source == "response" for item in diagnosis.evidence)
    )
    determinate = root_cause in _DETERMINATE_INVALID_AMOUNT
    candidate = (
        diagnosis is not None
        and incident.failure_code == "INVALID_AMOUNT"
        and determinate
        and response_present
        and not hard
        and not inconsistent
        and not not_determined
    )

    if hard:
        status, action = safety_decision(
            issues=hard,
            evidence_sufficient=True,
            permit_approve=False,
        )
    elif candidate:
        status, action = safety_decision(
            issues=[],
            evidence_sufficient=True,
            permit_approve=False,
        )
    else:
        status, action = safety_decision(
            issues=[],
            evidence_sufficient=False,
            permit_approve=False,
        )

    check_evidence: list[EvidenceItem] = []
    if diagnosis is not None:
        check_evidence = [
            EvidenceItem(source="diagnosis", fact=diagnosis.root_cause),
            EvidenceItem(source="diagnosis", fact=diagnosis.recommended_action),
        ]
    return AutomationResult(
        target_id=incident_id,
        status=status,
        action=action,
        workflow_name=WORKFLOW_NAME,
        checks=[
            AutomationCheck(name="required_references", result="FAIL" if hard else "PASS"),
            AutomationCheck(
                name="resolution_candidate",
                result="PASS" if candidate else "FAIL",
                evidence=check_evidence,
            ),
        ],
        issues=issues,
        dry_run=True,
    )


def _evidence_gap_issues(
    exc: EvidenceNotFound,
    existing: list[ValidationIssue],
) -> list[ValidationIssue]:
    message = str(exc)
    if message.startswith("Response not found") and not any(
        issue.code == "missing_response" for issue in existing
    ):
        return [
            ValidationIssue(
                rule="required_references",
                code="missing_response",
                message=message,
                evidence=[EvidenceItem(source="store", fact=message)],
                field="request_id",
            )
        ]
    if any(issue.code.startswith("missing_") for issue in existing):
        return []
    return [
        ValidationIssue(
            rule="required_references",
            code="missing_evidence",
            message=message,
            evidence=[EvidenceItem(source="store", fact=message)],
        )
    ]
