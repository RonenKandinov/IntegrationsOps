"""Readable automation output."""

from __future__ import annotations

from integrationops.automation.models import AutomationResult, BatchAutomationReport


def format_automation_result(result: AutomationResult) -> str:
    lines = [
        f"Target: {result.target_id}",
        f"Automation: {result.workflow_name}",
        f"Status: {result.status}",
        f"Action: {result.action}",
        f"Dry run: {result.dry_run}",
        "",
        "Checks:",
    ]
    for check in result.checks:
        lines.append(f"- {check.name}: {check.result}")
        for item in check.evidence:
            lines.append(f"  - {item.fact}")
    lines.append("")
    lines.append("Issues:")
    if not result.issues:
        lines.append("- None")
    else:
        for issue in result.issues:
            lines.append(f"- {issue.code}")
    return "\n".join(lines)


def format_batch_report(report: BatchAutomationReport) -> str:
    lines = [
        "Automation: Batch Operations",
        f"Total: {report.total}",
        f"Ready: {report.ready}",
        f"Blocked: {report.blocked}",
        f"Missing Data: {report.missing_data}",
        f"Dry run: {report.dry_run}",
    ]
    for result in report.results:
        lines.append("")
        lines.append(format_automation_result(result))
    return "\n".join(lines)
