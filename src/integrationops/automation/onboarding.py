"""Dry-run merchant onboarding. Reads merchants.json; does not write it."""

from __future__ import annotations

import json
from pathlib import Path

from integrationops.automation.models import AutomationCheck, AutomationResult
from integrationops.automation.safety import safety_decision
from integrationops.generators.scenario_generator import (
    DEFAULT_MERCHANTS_PATH,
    ScenarioGeneratorError,
    load_merchants,
)
from integrationops.models import EvidenceItem, Merchant, ValidationIssue

WORKFLOW_NAME = "Merchant Onboarding"


def run_onboarding_workflow(
    merchant_id: str,
    merchants_path: Path | None = None,
) -> AutomationResult:
    path = merchants_path or DEFAULT_MERCHANTS_PATH
    if not isinstance(merchant_id, str) or not merchant_id.strip():
        return _blocked(
            merchant_id,
            [
                ValidationIssue(
                    rule="required_merchant",
                    code="missing_merchant_id",
                    message="merchant_id is blank.",
                    evidence=[EvidenceItem(source="merchant", fact="merchant_id is blank")],
                    field="merchant_id",
                )
            ],
        )

    try:
        merchants = load_merchants(path)
    except ScenarioGeneratorError as exc:
        return _blocked(
            merchant_id,
            [
                ValidationIssue(
                    rule="required_merchant",
                    code="missing_merchant",
                    message=str(exc),
                    evidence=[EvidenceItem(source="merchants", fact=str(exc))],
                    field="merchant_id",
                )
            ],
        )

    merchant = next((item for item in merchants if item.merchant_id == merchant_id), None)
    if merchant is None:
        return _blocked(merchant_id, [_unloaded_merchant_issue(path, merchant_id)])

    issues: list[ValidationIssue] = []
    if not merchant.merchant_id.strip():
        issues.append(
            ValidationIssue(
                rule="required_merchant",
                code="missing_merchant_id",
                message="merchant_id is blank.",
                field="merchant_id",
            )
        )
    if not merchant.source_id.strip():
        issues.append(
            ValidationIssue(
                rule="required_merchant",
                code="missing_source_id",
                message="source_id is blank.",
                evidence=[EvidenceItem(source="merchant", fact=f"merchant_id={merchant.merchant_id}")],
                field="source_id",
            )
        )
    if issues:
        return _blocked(merchant_id, issues)

    status, action = safety_decision(issues=[], evidence_sufficient=True, permit_approve=True)
    return AutomationResult(
        target_id=merchant_id,
        status=status,
        action=action,
        workflow_name=WORKFLOW_NAME,
        checks=[
            AutomationCheck(
                name="required_merchant",
                result="PASS",
                evidence=[
                    EvidenceItem(source="merchant", fact=f"merchant_id={merchant.merchant_id}"),
                    EvidenceItem(source="merchant", fact=f"source_id={merchant.source_id}"),
                ],
            ),
            _optional_location_check(merchant),
        ],
        issues=[],
        dry_run=True,
    )


def _blocked(merchant_id: str, issues: list[ValidationIssue]) -> AutomationResult:
    status, action = safety_decision(issues=issues, evidence_sufficient=True, permit_approve=False)
    return AutomationResult(
        target_id=merchant_id,
        status=status,
        action=action,
        workflow_name=WORKFLOW_NAME,
        checks=[AutomationCheck(name="required_merchant", result="FAIL")],
        issues=issues,
        dry_run=True,
    )


def _unloaded_merchant_issue(path: Path, merchant_id: str) -> ValidationIssue:
    record = _raw_record(path, merchant_id)
    if record is not None:
        source_id = record.get("source_id")
        if not isinstance(source_id, str) or not source_id.strip():
            return ValidationIssue(
                rule="required_merchant",
                code="missing_source_id",
                message=f"Merchant {merchant_id} has no source_id.",
                evidence=[EvidenceItem(source="merchant", fact=f"merchant_id={merchant_id}")],
                field="source_id",
            )
    return ValidationIssue(
        rule="required_merchant",
        code="missing_merchant",
        message=f"Merchant not found: {merchant_id}",
        evidence=[EvidenceItem(source="merchants", fact=f"merchant_id={merchant_id}")],
        field="merchant_id",
    )


def _raw_record(path: Path, merchant_id: str) -> dict | None:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(records, list):
        return None
    for record in records:
        if isinstance(record, dict) and record.get("merchant_id") == merchant_id:
            return record
    return None


def _optional_location_check(merchant: Merchant) -> AutomationCheck:
    absent = [
        name
        for name, value in (
            ("city", merchant.city),
            ("state", merchant.state),
            ("zip_code_prefix", merchant.zip_code_prefix),
        )
        if value is None
    ]
    if absent:
        evidence = [
            EvidenceItem(source="merchant", fact=f"optional absent: {name}") for name in absent
        ]
    else:
        evidence = [
            EvidenceItem(
                source="merchant",
                fact="city, state, and zip_code_prefix are present",
            )
        ]
    return AutomationCheck(name="optional_location", result="PASS", evidence=evidence)
