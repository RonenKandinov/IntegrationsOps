"""Readable debug text for a ValidationReport."""

from __future__ import annotations

from integrationops.models import ValidationReport


def format_validation_report(report: ValidationReport) -> str:
    status = "VALID" if report.valid else "INVALID"
    lines = [
        f"Target: {report.target_id}",
        f"Status: {status}",
    ]
    if not report.issues:
        return "\n".join(lines)
    lines.append("")
    for issue in report.issues:
        lines.append(f"Rule: {issue.rule}")
        lines.append(f"Code: {issue.code}")
        lines.append(f"Message: {issue.message}")
        if issue.field:
            lines.append(f"Field: {issue.field}")
        lines.append("Evidence:")
        for item in issue.evidence:
            lines.append(f"- {item.fact}")
        lines.append("")
    return "\n".join(lines).rstrip()
