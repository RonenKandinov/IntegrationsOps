import json
from pathlib import Path

from integrationops.engine import investigate
from integrationops.evaluation.scorer import score_scenarios
from integrationops.generators.scenario_generator import generate_and_write
from integrationops.models import Diagnosis
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def _write_merchants(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "merchant_id": "MER-000010",
                    "source_id": "src-a",
                    "city": "sao paulo",
                    "state": "SP",
                    "zip_code_prefix": "01000",
                }
            ]
        ),
        encoding="utf-8",
    )


def test_engine_matches_ground_truth_for_generated_paths(tmp_path: Path):
    merchants_path = tmp_path / "merchants.json"
    _write_merchants(merchants_path)
    output = tmp_path / "generated"
    bundle = generate_and_write(
        merchants_path=merchants_path,
        output_dir=output,
        merchant_count=1,
        seed=1,
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        by_code = {}
        gap_id = None
        for truth, incident in zip(bundle.ground_truth, bundle.incidents, strict=True):
            if truth.evidence_gap:
                gap_id = incident.incident_id
                continue
            by_code.setdefault(incident.failure_code, incident.incident_id)

        invalid = investigate(by_code["INVALID_AMOUNT"])
        timeout = investigate(by_code["TIMEOUT"])
        auth = investigate(by_code["AUTHENTICATION_ERROR"])
        gap = investigate(gap_id)

        assert "above the lender's maximum" in invalid.root_cause
        assert "timed out" in timeout.root_cause
        assert "not authenticated" in auth.root_cause
        assert gap.root_cause.startswith("Not determined")
        assert "below" not in gap.root_cause
        assert "above" not in gap.root_cause

        report = score_scenarios(ground_truth_path=output / "ground_truth.json")
        assert report.total_cases == 4
        assert report.correct == 4
        assert report.incorrect == 0
        assert report.not_determined == 0
    finally:
        store_mod._store = previous


def test_scorer_labels_not_determined_only_when_unexpected(tmp_path: Path):
    def fake_investigate(incident_id: str) -> Diagnosis:
        if incident_id == "INC-GAP":
            return Diagnosis(
                incident_id=incident_id,
                failure_code="INVALID_AMOUNT",
                root_cause="Not determined from lender min/max limits.",
                explanation="",
                recommended_action="",
            )
        if incident_id == "INC-WRONG":
            return Diagnosis(
                incident_id=incident_id,
                failure_code="TIMEOUT",
                root_cause="Not determined from the TIMEOUT investigation path.",
                explanation="",
                recommended_action="",
            )
        return Diagnosis(
            incident_id=incident_id,
            failure_code="TIMEOUT",
            root_cause="The lender API did not respond before the request timed out.",
            explanation="",
            recommended_action="",
        )

    truth_path = tmp_path / "ground_truth.json"
    truth_path.write_text(
        json.dumps(
            [
                {
                    "incident_id": "INC-GAP",
                    "expected_failure_code": "INVALID_AMOUNT",
                    "expected_root_cause": "Not determined from lender min/max limits.",
                    "evidence_gap": True,
                },
                {
                    "incident_id": "INC-WRONG",
                    "expected_failure_code": "TIMEOUT",
                    "expected_root_cause": "The lender API did not respond before the request timed out.",
                    "evidence_gap": False,
                },
                {
                    "incident_id": "INC-OK",
                    "expected_failure_code": "TIMEOUT",
                    "expected_root_cause": "The lender API did not respond before the request timed out.",
                    "evidence_gap": False,
                },
            ]
        ),
        encoding="utf-8",
    )
    report = score_scenarios(ground_truth_path=truth_path, investigate_fn=fake_investigate)
    labels = {item.incident_id: item.label for item in report.cases}
    assert labels["INC-GAP"] == "correct"
    assert labels["INC-WRONG"] == "not_determined"
    assert labels["INC-OK"] == "correct"
    assert report.not_determined == 1
    assert report.correct == 2
