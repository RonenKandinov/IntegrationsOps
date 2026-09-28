"""CLI: investigate incidents or import Olist merchants."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from integrationops.automation.batch import run_batch_workflow
from integrationops.automation.config_change import run_config_change_workflow
from integrationops.automation.format import format_automation_result, format_batch_report
from integrationops.automation.models import AutomationResult
from integrationops.automation.onboarding import run_onboarding_workflow
from integrationops.automation.resolution import run_resolution_workflow
from integrationops.automation.validation_workflow import run_validation_workflow
from integrationops.evaluation.scorer import (
    DEFAULT_GROUND_TRUTH_PATH,
    score_production_events,
    score_scenarios,
)
from integrationops.engine import investigate
from integrationops.events import investigate_event
from integrationops.generators.scenario_generator import (
    DEFAULT_MERCHANTS_PATH,
    DEFAULT_OUTPUT_DIR,
    ScenarioGeneratorError,
    generate_and_write,
)
from integrationops.importers.olist_merchants import (
    DEFAULT_OUTPUT_PATH,
    DEFAULT_RAW_PATH,
    MerchantImportError,
    import_olist_merchants,
)
from integrationops.models import Diagnosis
from integrationops.store import EvidenceNotFound
from integrationops.validation.format import format_validation_report
from integrationops.validation.service import validate_incident, validate_request


def format_diagnosis(diagnosis: Diagnosis) -> str:
    evidence_lines = "\n".join(f"- {item.fact}" for item in diagnosis.evidence)
    trace_lines = "\n".join(f"- {step}" for step in diagnosis.trace)
    return "\n".join(
        [
            f"Incident: {diagnosis.incident_id}",
            f"Failure code: {diagnosis.failure_code}",
            "",
            "Likely root cause:",
            diagnosis.root_cause,
            "",
            "Supporting evidence:",
            evidence_lines,
            "",
            "Why:",
            diagnosis.explanation,
            "",
            "Recommended next action:",
            diagnosis.recommended_action,
            "",
            "Investigation trace:",
            trace_lines,
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="integrationops",
        description="Investigate an integration incident from local evidence.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    investigate_parser = subparsers.add_parser(
        "investigate",
        help="Run the failure-specific investigation for an incident id",
    )
    investigate_parser.add_argument("incident_id", help="Incident id, for example INC-001")

    event_parser = subparsers.add_parser(
        "investigate-event",
        help="Investigate one production-like event from data/production/evidence",
    )
    event_parser.add_argument("event_id", help="Event id, for example EVENT-001")

    evaluate_events_parser = subparsers.add_parser(
        "evaluate-events",
        help="Score production-like investigations against their ground truth",
    )
    evaluate_events_parser.add_argument(
        "--ground-truth",
        type=Path,
        default=None,
        help="Path to data/production/ground_truth.json",
    )

    import_parser = subparsers.add_parser(
        "import-merchants",
        help="Import Olist sellers CSV into normalized merchant JSON",
    )
    import_parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RAW_PATH,
        help="Path to olist_sellers_dataset.csv",
    )
    import_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path to write data/generated/merchants.json",
    )

    generate_parser = subparsers.add_parser(
        "generate-scenarios",
        help="Generate synthetic requests, responses, and incidents from merchants",
    )
    generate_parser.add_argument(
        "--merchants",
        type=Path,
        default=DEFAULT_MERCHANTS_PATH,
        help="Path to generated merchants.json",
    )
    generate_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated scenario JSON",
    )
    generate_parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of merchants to use",
    )
    generate_parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Seed for reproducible generation",
    )

    evaluate_parser = subparsers.add_parser(
        "evaluate-scenarios",
        help="Score investigation diagnoses against generated ground truth",
    )
    evaluate_parser.add_argument(
        "--ground-truth",
        type=Path,
        default=DEFAULT_GROUND_TRUTH_PATH,
        help="Path to data/generated/ground_truth.json",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate a request or incident against Store evidence",
    )
    validate_parser.add_argument(
        "target_id",
        help="Request id (REQ-...) or incident id (INC-...)",
    )

    automate_parser = subparsers.add_parser(
        "automate",
        help="Dry-run configuration validation workflow for a request id",
    )
    automate_parser.add_argument("request_id", help="Request id, for example REQ-000002")

    batch_parser = subparsers.add_parser(
        "automate-batch",
        help="Dry-run configuration validation for each request id",
    )
    batch_parser.add_argument(
        "request_ids",
        nargs="*",
        help="Request ids, for example REQ-000001 REQ-000002",
    )

    onboarding_parser = subparsers.add_parser(
        "automate-onboarding",
        help="Dry-run merchant onboarding checks",
    )
    onboarding_parser.add_argument("merchant_id", help="Merchant id, for example MER-000001")
    onboarding_parser.add_argument(
        "--merchants",
        type=Path,
        default=None,
        help="Path to merchants.json",
    )

    config_parser = subparsers.add_parser(
        "automate-config",
        help="Dry-run evaluation of a proposed lender configuration",
    )
    config_parser.add_argument("lender_id", help="Lender id, for example lender_456")
    config_parser.add_argument("--min-amount", type=int, default=None)
    config_parser.add_argument("--max-amount", type=int, default=None)
    config_parser.add_argument("--currency", default=None)
    config_parser.add_argument(
        "--request",
        action="append",
        dest="request_ids",
        default=None,
        help="Request id to include in the impact check. Repeat for more than one.",
    )

    resolution_parser = subparsers.add_parser(
        "automate-resolution",
        help="Dry-run automation decision from an existing investigation",
    )
    resolution_parser.add_argument("incident_id", help="Incident id, for example INC-001")
    return parser


def _import_merchants(args: argparse.Namespace) -> int:
    try:
        result = import_olist_merchants(raw_path=args.input, output_path=args.output)
    except MerchantImportError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Imported {result.imported} merchants")
    print(f"Skipped {result.skipped} records")
    print(f"Wrote {args.output}")
    return 0


def _generate_scenarios(args: argparse.Namespace) -> int:
    try:
        bundle = generate_and_write(
            merchants_path=args.merchants,
            output_dir=args.output,
            merchant_count=args.count,
            seed=args.seed,
        )
    except ScenarioGeneratorError as exc:
        print(exc, file=sys.stderr)
        return 1
    if bundle.warning:
        print(bundle.warning, file=sys.stderr)
    print(f"Used {bundle.merchants_used} merchants")
    print(f"Generated {len(bundle.requests)} requests")
    print(f"Generated {len(bundle.responses)} responses")
    print(f"Generated {len(bundle.incidents)} incidents")
    print("")
    print("Breakdown:")
    print(f"INVALID_AMOUNT: {bundle.breakdown['INVALID_AMOUNT']}")
    print(f"TIMEOUT: {bundle.breakdown['TIMEOUT']}")
    print(f"AUTHENTICATION_ERROR: {bundle.breakdown['AUTHENTICATION_ERROR']}")
    print(f"EVIDENCE_GAP: {bundle.breakdown['EVIDENCE_GAP']}")
    print(f"Wrote {args.output}")
    return 0


def _evaluate_scenarios(args: argparse.Namespace) -> int:
    try:
        report = score_scenarios(ground_truth_path=args.ground_truth)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Scenario Evaluation")
    print("-------------------")
    print(f"Total cases:       {report.total_cases}")
    print(f"Correct:           {report.correct}")
    print(f"Incorrect:         {report.incorrect}")
    print(f"Not determined:    {report.not_determined}")
    print(f"Accuracy:          {report.accuracy * 100:.2f}%")
    print(f"Determinate acc.:  {report.determinate_accuracy * 100:.2f}%")
    return 0


def format_event_diagnosis(diagnosis: Diagnosis) -> str:
    evidence_lines = "\n".join(f"- {item.fact}" for item in diagnosis.evidence)
    trace_lines = "\n".join(f"- {step}" for step in diagnosis.trace)
    return "\n".join(
        [
            f"Event: {diagnosis.incident_id}",
            f"Investigation status: {diagnosis.status}",
            "",
            "Root cause:",
            diagnosis.root_cause,
            "",
            "Evidence:",
            evidence_lines,
            "",
            "Explanation:",
            diagnosis.explanation,
            "",
            "Recommended action:",
            diagnosis.recommended_action,
            "",
            "Investigation trace:",
            trace_lines,
        ]
    )


def _investigate_event(args: argparse.Namespace) -> int:
    try:
        diagnosis = investigate_event(args.event_id)
    except EvidenceNotFound as exc:
        print(exc, file=sys.stderr)
        return 1
    print(format_event_diagnosis(diagnosis))
    return 0


def _evaluate_events(args: argparse.Namespace) -> int:
    try:
        report = score_production_events(ground_truth_path=args.ground_truth)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("Production Event Evaluation")
    print("---------------------------")
    print(f"Total cases:       {report.total_cases}")
    print(f"Correct:           {report.correct}")
    print(f"Incorrect:         {report.incorrect}")
    print(f"Accuracy:          {report.accuracy * 100:.2f}%")
    return 0 if report.incorrect == 0 else 1


def _validate(args: argparse.Namespace) -> int:
    target_id = args.target_id
    if target_id.startswith("INC-"):
        report = validate_incident(target_id)
    else:
        report = validate_request(target_id)
    print(format_validation_report(report))
    return 0 if report.valid else 1


def _exit_for_result(result: AutomationResult) -> int:
    return 0 if result.status == "READY" else 1


def _automate(args: argparse.Namespace) -> int:
    result = run_validation_workflow(args.request_id)
    print(format_automation_result(result))
    return _exit_for_result(result)


def _automate_batch(args: argparse.Namespace) -> int:
    report = run_batch_workflow(list(args.request_ids))
    print(format_batch_report(report))
    return 0 if report.blocked == 0 else 1


def _automate_onboarding(args: argparse.Namespace) -> int:
    result = run_onboarding_workflow(args.merchant_id, merchants_path=args.merchants)
    print(format_automation_result(result))
    return _exit_for_result(result)


def _automate_config(args: argparse.Namespace) -> int:
    result = run_config_change_workflow(
        args.lender_id,
        min_amount=args.min_amount,
        max_amount=args.max_amount,
        currency=args.currency,
        request_ids=args.request_ids,
    )
    print(format_automation_result(result))
    return _exit_for_result(result)


def _automate_resolution(args: argparse.Namespace) -> int:
    result = run_resolution_workflow(args.incident_id)
    print(format_automation_result(result))
    return _exit_for_result(result)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "investigate-event":
        return _investigate_event(args)
    if args.command == "evaluate-events":
        return _evaluate_events(args)
    if args.command == "import-merchants":
        return _import_merchants(args)
    if args.command == "generate-scenarios":
        return _generate_scenarios(args)
    if args.command == "evaluate-scenarios":
        return _evaluate_scenarios(args)
    if args.command == "validate":
        return _validate(args)
    if args.command == "automate":
        return _automate(args)
    if args.command == "automate-batch":
        return _automate_batch(args)
    if args.command == "automate-onboarding":
        return _automate_onboarding(args)
    if args.command == "automate-config":
        return _automate_config(args)
    if args.command == "automate-resolution":
        return _automate_resolution(args)
    try:
        diagnosis = investigate(args.incident_id)
    except EvidenceNotFound as exc:
        print(exc, file=sys.stderr)
        return 1
    print(format_diagnosis(diagnosis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
