"""Score investigation diagnoses against generator ground truth. Not part of the engine."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from integrationops.engine import investigate
from integrationops.events import investigate_event

DEFAULT_EVENT_TRUTH_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "production" / "ground_truth.json"
)
from integrationops.models import Diagnosis

DEFAULT_GROUND_TRUTH_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "generated" / "ground_truth.json"
)


@dataclass
class CaseScore:
    incident_id: str
    expected_root_cause: str
    actual_root_cause: str
    label: str
    evidence_gap: bool


@dataclass
class EvaluationReport:
    total_cases: int
    correct: int
    incorrect: int
    not_determined: int
    accuracy: float
    determinate_accuracy: float
    cases: list[CaseScore] = field(default_factory=list)


def load_ground_truth(path: Path | None = None) -> list[dict]:
    truth_path = path or DEFAULT_GROUND_TRUTH_PATH
    records = json.loads(truth_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{truth_path} must contain a JSON array")
    return records


def _label_case(expected: str, actual: str, evidence_gap: bool) -> str:
    if actual == expected:
        return "correct"
    if actual.startswith("Not determined") and not evidence_gap:
        return "not_determined"
    return "incorrect"


def score_scenarios(
    ground_truth_path: Path | None = None,
    investigate_fn: Callable[[str], Diagnosis] = investigate,
) -> EvaluationReport:
    records = load_ground_truth(ground_truth_path)
    cases: list[CaseScore] = []
    correct = 0
    incorrect = 0
    not_determined = 0
    determinate_expected = 0
    determinate_correct = 0

    for record in records:
        incident_id = record["incident_id"]
        expected = record["expected_root_cause"]
        evidence_gap = bool(record.get("evidence_gap"))
        diagnosis = investigate_fn(incident_id)
        actual = diagnosis.root_cause
        label = _label_case(expected, actual, evidence_gap)
        cases.append(
            CaseScore(
                incident_id=incident_id,
                expected_root_cause=expected,
                actual_root_cause=actual,
                label=label,
                evidence_gap=evidence_gap,
            )
        )
        if label == "correct":
            correct += 1
        elif label == "not_determined":
            not_determined += 1
        else:
            incorrect += 1
        if not evidence_gap:
            determinate_expected += 1
            if label == "correct":
                determinate_correct += 1

    total = len(cases)
    accuracy = (correct / total) if total else 0.0
    determinate_accuracy = (
        (determinate_correct / determinate_expected) if determinate_expected else 0.0
    )
    return EvaluationReport(
        total_cases=total,
        correct=correct,
        incorrect=incorrect,
        not_determined=not_determined,
        accuracy=accuracy,
        determinate_accuracy=determinate_accuracy,
        cases=cases,
    )


@dataclass
class ProductionCaseScore:
    event_id: str
    expected_status: str
    actual_status: str
    expected_root_cause: str
    actual_root_cause: str
    label: str


@dataclass
class ProductionEvaluationReport:
    total_cases: int
    correct: int
    incorrect: int
    accuracy: float
    cases: list[ProductionCaseScore] = field(default_factory=list)


def score_production_events(
    ground_truth_path: Path | None = None,
    evidence_dir: Path | None = None,
) -> ProductionEvaluationReport:
    truth_path = ground_truth_path or DEFAULT_EVENT_TRUTH_PATH
    records = json.loads(truth_path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError(f"{truth_path} must contain a JSON array")
    cases: list[ProductionCaseScore] = []
    correct = 0
    for record in records:
        diagnosis = investigate_event(record["event_id"], evidence_dir=evidence_dir)
        expected_status = record["expected_status"]
        expected_root_cause = record["expected_root_cause"]
        status_matches = diagnosis.status == expected_status
        cause_matches = diagnosis.root_cause == expected_root_cause
        guessed_cause = expected_status != "ROOT_CAUSE_DETERMINED" and diagnosis.status == "ROOT_CAUSE_DETERMINED"
        label = "correct" if status_matches and cause_matches and not guessed_cause else "incorrect"
        if label == "correct":
            correct += 1
        cases.append(
            ProductionCaseScore(
                event_id=record["event_id"],
                expected_status=expected_status,
                actual_status=diagnosis.status,
                expected_root_cause=expected_root_cause,
                actual_root_cause=diagnosis.root_cause,
                label=label,
            )
        )
    total = len(cases)
    return ProductionEvaluationReport(
        total_cases=total,
        correct=correct,
        incorrect=total - correct,
        accuracy=(correct / total) if total else 0.0,
        cases=cases,
    )
