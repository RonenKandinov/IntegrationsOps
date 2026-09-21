import json
from pathlib import Path

from integrationops.cli import main
from integrationops.models import LenderConfig
from integrationops.store.json_store import JsonStore
from integrationops.validation.amount import validate_amount
from integrationops.validation.service import validate_incident, validate_request
import integrationops.store as store_mod

LENDER = LenderConfig(lender_id="lender_456", min_amount=10000, max_amount=50000, currency="USD")


def test_amount_valid():
    assert validate_amount(20000, LENDER) == []


def test_amount_above_max():
    issues = validate_amount(80000, LENDER)
    assert len(issues) == 1
    assert issues[0].code == "amount_above_max"
    assert issues[0].rule == "amount_range"
    assert issues[0].field == "amount"
    facts = [item.fact for item in issues[0].evidence]
    assert "requested_amount = 80000" in facts
    assert "maximum_allowed = 50000" in facts


def test_amount_below_min():
    issues = validate_amount(5000, LENDER)
    assert issues[0].code == "amount_below_min"


def _write_store(tmp_path: Path, *, requests, incidents, lenders) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    generated.joinpath("requests.json").write_text(json.dumps(requests), encoding="utf-8")
    generated.joinpath("incidents.json").write_text(json.dumps(incidents), encoding="utf-8")
    generated.joinpath("lenders.json").write_text(json.dumps(lenders), encoding="utf-8")
    generated.joinpath("responses.json").write_text("[]", encoding="utf-8")


def test_missing_and_valid_references(tmp_path: Path):
    _write_store(
        tmp_path,
        requests=[
            {
                "request_id": "REQ-OK",
                "merchant_id": "MER-1",
                "lender_id": "lender_456",
                "amount": 20000,
                "currency": "USD",
            },
            {
                "request_id": "REQ-NOLENDER",
                "merchant_id": "MER-1",
                "lender_id": "lender_missing",
                "amount": 20000,
                "currency": "USD",
            },
        ],
        incidents=[],
        lenders=[
            {
                "lender_id": "lender_456",
                "min_amount": 10000,
                "max_amount": 50000,
                "currency": "USD",
            }
        ],
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        missing_request = validate_request("REQ-MISSING")
        assert missing_request.valid is False
        assert missing_request.issues[0].code == "missing_request"

        missing_lender = validate_request("REQ-NOLENDER")
        assert missing_lender.issues[0].code == "missing_lender"

        ok = validate_request("REQ-OK")
        assert ok.valid is True
        assert ok.issues == []
        assert ok.target_id == "REQ-OK"

        missing_incident = validate_incident("INC-MISSING")
        assert missing_incident.valid is False
        assert missing_incident.issues[0].code == "missing_incident"
    finally:
        store_mod._store = previous


def test_invalid_amount_consistency_is_not_a_root_cause(tmp_path: Path):
    _write_store(
        tmp_path,
        requests=[
            {
                "request_id": "REQ-GAP",
                "merchant_id": "MER-1",
                "lender_id": "lender_456",
                "amount": 20000,
                "currency": "USD",
            }
        ],
        incidents=[
            {
                "incident_id": "INC-GAP",
                "merchant_id": "MER-1",
                "lender_id": "lender_456",
                "failure_code": "INVALID_AMOUNT",
                "request_id": "REQ-GAP",
            }
        ],
        lenders=[
            {
                "lender_id": "lender_456",
                "min_amount": 10000,
                "max_amount": 50000,
                "currency": "USD",
            }
        ],
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        report = validate_incident("INC-GAP")
        assert report.valid is False
        codes = [issue.code for issue in report.issues]
        assert "inconsistent_invalid_amount" in codes
        assert all("root cause" not in issue.message.lower() or "not a root cause" in issue.message.lower() for issue in report.issues)
        joined = " ".join(issue.message for issue in report.issues)
        assert "inconsistency" in joined.lower()
    finally:
        store_mod._store = previous


def test_cli_validate_generated_request_above_max(capsys):
    exit_code = main(["validate", "REQ-000001"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "INVALID" in captured.out
    assert "amount_above_max" in captured.out
    assert "80000" in captured.out
    assert "50000" in captured.out
