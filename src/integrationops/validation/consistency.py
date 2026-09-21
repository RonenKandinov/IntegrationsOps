"""Detect INVALID_AMOUNT labeled when amount is within lender limits. No root cause."""

from __future__ import annotations

from integrationops.models import ApiRequest, EvidenceItem, Incident, LenderConfig, ValidationIssue
from integrationops.tools import compare_amount_to_limits


def validate_invalid_amount_consistency(
    incident: Incident,
    request: ApiRequest,
    lender: LenderConfig,
) -> list[ValidationIssue]:
    if incident.failure_code != "INVALID_AMOUNT":
        return []
    comparison = compare_amount_to_limits(request.amount, lender.min_amount, lender.max_amount)
    if comparison != "within_limits":
        return []
    return [
        ValidationIssue(
            rule="failure_consistency",
            code="inconsistent_invalid_amount",
            message=(
                "failure_code is INVALID_AMOUNT but the requested amount is within "
                "lender min/max. This is an evidence inconsistency, not a root cause."
            ),
            evidence=[
                EvidenceItem(source="incident", fact=f"failure_code={incident.failure_code}"),
                EvidenceItem(source="request", fact=f"requested_amount = {request.amount}"),
                EvidenceItem(source="lender", fact=f"minimum_allowed = {lender.min_amount}"),
                EvidenceItem(source="lender", fact=f"maximum_allowed = {lender.max_amount}"),
            ],
            field="failure_code",
        )
    ]
