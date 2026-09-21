"""Run the configuration-validation workflow once per request id."""

from __future__ import annotations

from integrationops.automation.models import BatchAutomationReport
from integrationops.automation.validation_workflow import run_validation_workflow

_MISSING_CODES = frozenset({"missing_request", "missing_lender"})


def run_batch_workflow(request_ids: list[str]) -> BatchAutomationReport:
    results = [run_validation_workflow(request_id) for request_id in request_ids]
    ready = sum(1 for result in results if result.status == "READY")
    blocked = sum(1 for result in results if result.status == "BLOCKED")
    missing_data = sum(
        1
        for result in results
        if result.status == "BLOCKED"
        and any(issue.code in _MISSING_CODES for issue in result.issues)
    )
    return BatchAutomationReport(
        results=results,
        total=len(results),
        ready=ready,
        blocked=blocked,
        missing_data=missing_data,
        dry_run=True,
    )
