"""Amount range rule using the existing comparison tool."""

from __future__ import annotations

from integrationops.models import EvidenceItem, LenderConfig, ValidationIssue
from integrationops.tools import compare_amount_to_limits


def validate_amount(amount: int, lender: LenderConfig) -> list[ValidationIssue]:
    comparison = compare_amount_to_limits(amount, lender.min_amount, lender.max_amount)
    evidence = [
        EvidenceItem(source="request", fact=f"requested_amount = {amount}"),
        EvidenceItem(source="lender", fact=f"minimum_allowed = {lender.min_amount}"),
        EvidenceItem(source="lender", fact=f"maximum_allowed = {lender.max_amount}"),
    ]
    if comparison == "above_max":
        return [
            ValidationIssue(
                rule="amount_range",
                code="amount_above_max",
                message="Requested amount is above the lender maximum.",
                evidence=evidence,
                field="amount",
            )
        ]
    if comparison == "below_min":
        return [
            ValidationIssue(
                rule="amount_range",
                code="amount_below_min",
                message="Requested amount is below the lender minimum.",
                evidence=evidence,
                field="amount",
            )
        ]
    return []
