"""Evaluate a proposed lender configuration. Does not write the Store."""

from __future__ import annotations

from integrationops.automation.models import AutomationCheck, AutomationResult
from integrationops.automation.safety import safety_decision
from integrationops.models import EvidenceItem, LenderConfig, ValidationIssue
from integrationops.validation.amount import validate_amount
from integrationops.validation.references import load_lender_or_issue, load_request_or_issue

WORKFLOW_NAME = "Configuration Change"


def run_config_change_workflow(
    lender_id: str,
    *,
    min_amount: int | None = None,
    max_amount: int | None = None,
    currency: str | None = None,
    request_ids: list[str] | None = None,
) -> AutomationResult:
    lender, lender_issues = load_lender_or_issue(lender_id)
    if lender is None:
        status, action = safety_decision(
            issues=lender_issues,
            evidence_sufficient=True,
            permit_approve=False,
        )
        return AutomationResult(
            target_id=lender_id,
            status=status,
            action=action,
            workflow_name=WORKFLOW_NAME,
            checks=[AutomationCheck(name="config_structure", result="FAIL")],
            issues=lender_issues,
            dry_run=True,
        )

    proposed = LenderConfig(
        lender_id=lender.lender_id,
        min_amount=lender.min_amount if min_amount is None else min_amount,
        max_amount=lender.max_amount if max_amount is None else max_amount,
        currency=lender.currency if currency is None else currency,
    )
    hard_issues: list[ValidationIssue] = []
    review_issues: list[ValidationIssue] = []

    changed = (
        proposed.min_amount != lender.min_amount
        or proposed.max_amount != lender.max_amount
        or proposed.currency != lender.currency
    )
    if not changed:
        review_issues.append(
            ValidationIssue(
                rule="config_change",
                code="no_change",
                message="Proposed lender configuration is identical to the current one.",
                evidence=[
                    EvidenceItem(source="lender", fact=f"lender_id={lender.lender_id}"),
                    EvidenceItem(source="lender", fact=f"min_amount={lender.min_amount}"),
                    EvidenceItem(source="lender", fact=f"max_amount={lender.max_amount}"),
                    EvidenceItem(source="lender", fact=f"currency={lender.currency}"),
                ],
            )
        )
    if proposed.min_amount > proposed.max_amount:
        hard_issues.append(
            ValidationIssue(
                rule="config_structure",
                code="min_exceeds_max",
                message="Proposed minimum is greater than proposed maximum.",
                evidence=[
                    EvidenceItem(source="proposal", fact=f"min_amount={proposed.min_amount}"),
                    EvidenceItem(source="proposal", fact=f"max_amount={proposed.max_amount}"),
                ],
                field="min_amount",
            )
        )
    if proposed.currency != lender.currency:
        review_issues.append(
            ValidationIssue(
                rule="config_change",
                code="currency_changed",
                message=(
                    "Proposed currency differs from the current lender currency. "
                    "No cross-currency amount rule exists."
                ),
                evidence=[
                    EvidenceItem(source="lender", fact=f"currency={lender.currency}"),
                    EvidenceItem(source="proposal", fact=f"currency={proposed.currency}"),
                ],
                field="currency",
            )
        )

    impact_evidence, impact_review, impact_hard, saw_same_lender = _impact(
        lender, proposed, request_ids
    )
    review_issues.extend(impact_review)
    hard_issues.extend(impact_hard)
    impact_failed = bool(impact_review) or any(
        issue.rule == "amount_range" or issue.code.startswith("missing_") for issue in impact_hard
    )

    permit_approve = (
        changed
        and not hard_issues
        and not review_issues
        and proposed.min_amount <= proposed.max_amount
        and proposed.currency == lender.currency
        and saw_same_lender
    )
    status, action = safety_decision(
        issues=hard_issues,
        evidence_sufficient=not review_issues,
        permit_approve=permit_approve,
    )
    return AutomationResult(
        target_id=lender_id,
        status=status,
        action=action,
        workflow_name=WORKFLOW_NAME,
        checks=[
            AutomationCheck(
                name="proposal",
                result="PASS" if changed else "FAIL",
            ),
            AutomationCheck(
                name="config_structure",
                result="FAIL" if proposed.min_amount > proposed.max_amount else "PASS",
            ),
            AutomationCheck(
                name="currency",
                result="FAIL" if proposed.currency != lender.currency else "PASS",
            ),
            AutomationCheck(
                name="impact",
                result="FAIL" if impact_failed else "PASS",
                evidence=impact_evidence,
            ),
        ],
        issues=hard_issues + review_issues,
        dry_run=True,
    )


def _impact(
    lender: LenderConfig,
    proposed: LenderConfig,
    request_ids: list[str] | None,
) -> tuple[list[EvidenceItem], list[ValidationIssue], list[ValidationIssue], bool]:
    evidence: list[EvidenceItem] = [
        EvidenceItem(source="lender", fact=f"current_min={lender.min_amount}"),
        EvidenceItem(source="lender", fact=f"current_max={lender.max_amount}"),
        EvidenceItem(source="proposal", fact=f"proposed_min={proposed.min_amount}"),
        EvidenceItem(source="proposal", fact=f"proposed_max={proposed.max_amount}"),
    ]
    if request_ids is None:
        evidence.append(EvidenceItem(source="impact", fact="request ids were not supplied"))
        return (
            evidence,
            [
                ValidationIssue(
                    rule="config_change",
                    code="impact_not_evaluated",
                    message="No request ids were supplied, so limit impact was not evaluated.",
                    evidence=[EvidenceItem(source="impact", fact="request ids were not supplied")],
                )
            ],
            [],
            False,
        )

    review: list[ValidationIssue] = []
    hard: list[ValidationIssue] = []
    saw_same_lender = False
    for request_id in request_ids:
        request, request_issues = load_request_or_issue(request_id)
        if request is None:
            hard.extend(request_issues)
            continue
        if request.lender_id != lender.lender_id:
            evidence.append(
                EvidenceItem(
                    source="request",
                    fact=(
                        f"ignored {request.request_id}: lender_id={request.lender_id} "
                        f"does not match {lender.lender_id}"
                    ),
                )
            )
            continue
        saw_same_lender = True
        current_issues = validate_amount(request.amount, lender)
        proposed_issues = validate_amount(request.amount, proposed)
        if proposed_issues:
            hard.extend(proposed_issues)
            evidence.append(
                EvidenceItem(
                    source="request",
                    fact=f"{request.request_id} invalid under proposal: {proposed_issues[0].code}",
                )
            )
        elif current_issues:
            evidence.append(
                EvidenceItem(
                    source="request",
                    fact=f"{request.request_id} became valid under proposal",
                )
            )
        else:
            evidence.append(
                EvidenceItem(
                    source="request",
                    fact=f"{request.request_id} unchanged and within proposed limits",
                )
            )
    if not saw_same_lender and not hard:
        evidence.append(
            EvidenceItem(source="impact", fact=f"no request for lender {lender.lender_id} was supplied")
        )
        review.append(
            ValidationIssue(
                rule="config_change",
                code="impact_not_evaluated",
                message=f"No supplied request uses lender {lender.lender_id}.",
                evidence=[
                    EvidenceItem(
                        source="impact",
                        fact=f"no request for lender {lender.lender_id} was supplied",
                    )
                ],
            )
        )
    return evidence, review, hard, saw_same_lender
