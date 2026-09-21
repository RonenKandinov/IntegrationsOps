"""CLI: investigate incidents or import Olist merchants."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from integrationops.evaluation.scorer import (
    DEFAULT_GROUND_TRUTH_PATH,
    score_scenarios,
)
from integrationops.engine import investigate
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


def _validate(args: argparse.Namespace) -> int:
    target_id = args.target_id
    if target_id.startswith("INC-"):
        report = validate_incident(target_id)
    else:
        report = validate_request(target_id)
    print(format_validation_report(report))
    return 0 if report.valid else 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "import-merchants":
        return _import_merchants(args)
    if args.command == "generate-scenarios":
        return _generate_scenarios(args)
    if args.command == "evaluate-scenarios":
        return _evaluate_scenarios(args)
    if args.command == "validate":
        return _validate(args)
    try:
        diagnosis = investigate(args.incident_id)
    except EvidenceNotFound as exc:
        print(exc, file=sys.stderr)
        return 1
    print(format_diagnosis(diagnosis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
