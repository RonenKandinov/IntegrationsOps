from pathlib import Path

from integrationops.cli import main
from integrationops.engine import investigate
from integrationops.evaluation.scorer import score_production_events
from integrationops.events import investigate_event

_ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE = _ROOT / "data" / "production" / "evidence"


def test_determinable_amount_above_max():
    diagnosis = investigate_event("EVENT-001")
    assert diagnosis.status == "ROOT_CAUSE_DETERMINED"
    assert diagnosis.root_cause == "Requested amount is above the lender's maximum allowed amount."
    assert any("above_max" in step for step in diagnosis.trace)


def test_missing_lender_is_an_evidence_gap():
    diagnosis = investigate_event("EVENT-002")
    assert diagnosis.status == "EVIDENCE_GAP"
    assert diagnosis.root_cause == "Not determined: lender configuration is missing."
    assert "50000" not in diagnosis.root_cause
    assert "maximum" not in diagnosis.root_cause.lower()
    assert any("Attempted to load lender configuration" in step for step in diagnosis.trace)
    assert any("stopped without assigning a root cause" in step for step in diagnosis.trace)


def test_amount_inside_limits_is_inconsistent():
    diagnosis = investigate_event("EVENT-003")
    assert diagnosis.status == "INCONSISTENT_EVIDENCE"
    assert diagnosis.root_cause == "Not determined from lender min/max limits."
    assert "above the lender" not in diagnosis.root_cause
    assert any("does not explain failure" in step for step in diagnosis.trace)


def test_missing_response_is_an_evidence_gap():
    diagnosis = investigate_event("EVENT-004")
    assert diagnosis.status == "EVIDENCE_GAP"
    assert diagnosis.root_cause == "Not determined: response evidence is missing."
    assert not diagnosis.root_cause.startswith("Requested amount")


def test_unknown_failure_is_not_determined():
    diagnosis = investigate_event("EVENT-005")
    assert diagnosis.status == "NOT_DETERMINED"
    assert diagnosis.root_cause == "Not determined: no investigation path for this failure code."
    assert any(item.fact == "API response = UNKNOWN_GATEWAY_ERROR" for item in diagnosis.evidence)


def test_lender_disagreement_is_not_diagnosed_as_amount():
    diagnosis = investigate_event("EVENT-006")
    assert diagnosis.status == "INCONSISTENT_EVIDENCE"
    assert diagnosis.root_cause == "Not determined: request and response name different lenders."
    assert "above the lender" not in diagnosis.root_cause
    assert any("disagrees about the lender" in step for step in diagnosis.trace)


def test_unconfirmed_timeout_is_not_determined():
    diagnosis = investigate_event("EVENT-007")
    assert diagnosis.status == "NOT_DETERMINED"
    assert diagnosis.root_cause == "Not determined from the TIMEOUT investigation path."
    assert "did not respond before the request timed out" not in diagnosis.root_cause


def test_investigation_does_not_need_ground_truth(tmp_path: Path):
    dest = tmp_path / "evidence"
    dest.mkdir()
    for name in ("incidents.json", "requests.json", "responses.json", "lenders.json"):
        (dest / name).write_text((_EVIDENCE / name).read_text(encoding="utf-8"), encoding="utf-8")
    diagnosis = investigate_event("EVENT-001", evidence_dir=dest)
    assert diagnosis.status == "ROOT_CAUSE_DETERMINED"
    assert diagnosis.root_cause == "Requested amount is above the lender's maximum allowed amount."


def test_investigation_modules_do_not_name_ground_truth():
    package = _ROOT / "src" / "integrationops"
    for relative in (
        "engine/__init__.py",
        "events.py",
        "investigations/invalid_amount.py",
        "investigations/timeout.py",
        "investigations/authentication_error.py",
        "investigations/evidence.py",
    ):
        assert "ground_truth" not in (package / relative).read_text(encoding="utf-8")


def test_production_score_matches_ground_truth():
    report = score_production_events()
    assert report.total_cases == 7
    assert report.incorrect == 0
    assert report.accuracy == 1.0


def test_seed_incident_still_determines_below_min():
    diagnosis = investigate("INC-001")
    assert diagnosis.root_cause == "Requested amount is below the lender's minimum allowed amount."
    assert diagnosis.status == "ROOT_CAUSE_DETERMINED"


def test_cli_event_and_existing_investigate(capsys):
    event_code = main(["investigate-event", "EVENT-002"])
    event_out = capsys.readouterr().out
    assert event_code == 0
    assert "Investigation status: EVIDENCE_GAP" in event_out
    assert "lender configuration is missing" in event_out

    seed_code = main(["investigate", "INC-001"])
    seed_out = capsys.readouterr().out
    assert seed_code == 0
    assert "below the lender's minimum" in seed_out
    assert "Investigation status:" not in seed_out
