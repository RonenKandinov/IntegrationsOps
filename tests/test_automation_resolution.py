import json
from pathlib import Path

from integrationops.automation.resolution import run_resolution_workflow
from integrationops.cli import main
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def _write_store(tmp_path: Path, *, incidents, requests, responses, lenders) -> Path:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "incidents.json").write_text(json.dumps(incidents), encoding="utf-8")
    (generated / "requests.json").write_text(json.dumps(requests), encoding="utf-8")
    (generated / "responses.json").write_text(json.dumps(responses), encoding="utf-8")
    (generated / "lenders.json").write_text(json.dumps(lenders), encoding="utf-8")
    return generated


LENDER = {
    "lender_id": "lender_456",
    "min_amount": 10000,
    "max_amount": 50000,
    "currency": "USD",
}


def _request(request_id: str, amount: int) -> dict:
    return {
        "request_id": request_id,
        "merchant_id": "MER-1",
        "lender_id": "lender_456",
        "amount": amount,
        "currency": "USD",
    }


def _response(request_id: str, error_code: str) -> dict:
    return {
        "request_id": request_id,
        "status": "error",
        "error_code": error_code,
        "message": error_code,
    }


def _incident(incident_id: str, request_id: str, failure_code: str) -> dict:
    return {
        "incident_id": incident_id,
        "merchant_id": "MER-1",
        "lender_id": "lender_456",
        "failure_code": failure_code,
        "request_id": request_id,
    }


def _use_store(tmp_path: Path):
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    return previous


def test_above_max_is_candidate_and_does_not_write(tmp_path: Path):
    generated = _write_store(
        tmp_path,
        incidents=[_incident("INC-HIGH", "REQ-HIGH", "INVALID_AMOUNT")],
        requests=[_request("REQ-HIGH", 80000)],
        responses=[_response("REQ-HIGH", "INVALID_AMOUNT")],
        lenders=[LENDER],
    )
    previous = _use_store(tmp_path)
    before = {path.name: path.read_bytes() for path in generated.iterdir()}
    try:
        result = run_resolution_workflow("INC-HIGH")
        assert result.status == "REVIEW"
        assert result.action == "CANDIDATE"
        assert result.dry_run is True
        assert result.action != "APPROVE"
        assert any(issue.code == "amount_above_max" for issue in result.issues)
        candidate = next(check for check in result.checks if check.name == "resolution_candidate")
        assert candidate.result == "PASS"
        assert any("above the lender's maximum" in item.fact for item in candidate.evidence)
        after = {path.name: path.read_bytes() for path in generated.iterdir()}
        assert after == before
    finally:
        store_mod._store = previous


def test_within_limits_invalid_amount_needs_human_review(tmp_path: Path):
    _write_store(
        tmp_path,
        incidents=[_incident("INC-OK", "REQ-OK", "INVALID_AMOUNT")],
        requests=[_request("REQ-OK", 20000)],
        responses=[_response("REQ-OK", "INVALID_AMOUNT")],
        lenders=[LENDER],
    )
    previous = _use_store(tmp_path)
    try:
        result = run_resolution_workflow("INC-OK")
        assert result.status == "REVIEW"
        assert result.action == "HUMAN_REVIEW"
        assert any(issue.code == "inconsistent_invalid_amount" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_timeout_needs_human_review(tmp_path: Path):
    _write_store(
        tmp_path,
        incidents=[_incident("INC-TIME", "REQ-TIME", "TIMEOUT")],
        requests=[_request("REQ-TIME", 20000)],
        responses=[_response("REQ-TIME", "TIMEOUT")],
        lenders=[LENDER],
    )
    previous = _use_store(tmp_path)
    try:
        result = run_resolution_workflow("INC-TIME")
        assert result.status == "REVIEW"
        assert result.action == "HUMAN_REVIEW"
        assert result.action != "APPROVE"
    finally:
        store_mod._store = previous


def test_missing_incident_is_blocked(tmp_path: Path):
    _write_store(tmp_path, incidents=[], requests=[], responses=[], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_resolution_workflow("INC-MISSING")
        assert result.status == "BLOCKED"
        assert result.action == "BLOCK"
        assert any(issue.code == "missing_incident" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_cli_resolution_candidate_exits_nonzero(tmp_path: Path, capsys):
    _write_store(
        tmp_path,
        incidents=[_incident("INC-HIGH", "REQ-HIGH", "INVALID_AMOUNT")],
        requests=[_request("REQ-HIGH", 80000)],
        responses=[_response("REQ-HIGH", "INVALID_AMOUNT")],
        lenders=[LENDER],
    )
    previous = _use_store(tmp_path)
    try:
        code = main(["automate-resolution", "INC-HIGH"])
        out = capsys.readouterr().out
        assert code == 1
        assert "CANDIDATE" in out
        assert "Dry run: True" in out
    finally:
        store_mod._store = previous
