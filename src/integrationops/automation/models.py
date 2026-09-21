"""Structured automation results. Reuses ValidationIssue; does not duplicate it."""

from __future__ import annotations

from dataclasses import dataclass, field

from integrationops.models import EvidenceItem, ValidationIssue


@dataclass
class AutomationCheck:
    name: str
    result: str
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass
class AutomationResult:
    target_id: str
    status: str
    action: str
    workflow_name: str
    checks: list[AutomationCheck] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    dry_run: bool = True


@dataclass
class BatchAutomationReport:
    results: list[AutomationResult] = field(default_factory=list)
    total: int = 0
    ready: int = 0
    blocked: int = 0
    missing_data: int = 0
    dry_run: bool = True
