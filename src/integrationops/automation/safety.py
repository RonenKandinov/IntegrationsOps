"""Shared dry-run safety gate. Workflows do not invent a second decision path."""

from __future__ import annotations

from integrationops.models import ValidationIssue


def safety_decision(
    *,
    issues: list[ValidationIssue],
    evidence_sufficient: bool,
    permit_approve: bool,
) -> tuple[str, str]:
    """Return (status, action). Issues always block. Never approve without evidence."""
    if issues:
        return "BLOCKED", "BLOCK"
    if not evidence_sufficient:
        return "REVIEW", "HUMAN_REVIEW"
    if permit_approve:
        return "READY", "APPROVE"
    return "REVIEW", "CANDIDATE"
