import json
from pathlib import Path

from integrationops.automation.validation_workflow import run_validation_workflow
from integrationops.cli import main
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def _write_store(tmp_path: Path, *, requests, lenders) -> Path:
    generated = tmp_path / "generated"
    generated.mkdir()
    requests_path = generated / "requests.json"
    lenders_path = generated / "lenders.json"
    requests_path.write_text(json.dumps(requests), encoding="utf-8")
    lenders_path.write_text(json.dumps(lenders), encoding="utf-8")
    generated.joinpath("incidents.json").write_text("[]", encoding="utf-8")
    generated.joinpath("responses.json").write_text("[]", encoding="utf-8")
    return generated


LENDER = {
    "lender_id": "lender_456",
    "min_amount": 10000,
    "max_amount": 50000,
    "currency": "USD",
}


def _request(request_id: str, amount: int, lender_id: str = "lender_456") -> dict:
    return {
        "request_id": request_id,
        "merchant_id": "MER-1",
        "lender_id": lender_id,
        "amount": amount,
        "currency": "USD",
    }


def test_valid_request_is_ready(tmp_path: Path):
    generated = _write_store(tmp_path, requests=[_request("REQ-OK", 20000)], lenders=[LENDER])
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    before = {path.name: path.read_bytes() for path in generated.iterdir()}
    try:
        result = run_validation_workflow("REQ-OK")
        assert result.status == "READY"
        assert result.action == "APPROVE"
        assert result.dry_run is True
        assert result.target_id == "REQ-OK"
        assert result.issues == []
        assert {check.name: check.result for check in result.checks}["amount_range"] == "PASS"
        after = {path.name: path.read_bytes() for path in generated.iterdir()}
        assert after == before
    finally:
        store_mod._store = previous


def test_above_max_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-HIGH", 80000)], lenders=[LENDER])
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        result = run_validation_workflow("REQ-HIGH")
        assert result.status == "BLOCKED"
        assert result.action == "BLOCK"
        assert result.dry_run is True
        assert any(issue.code == "amount_above_max" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_below_min_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-LOW", 5000)], lenders=[LENDER])
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        result = run_validation_workflow("REQ-LOW")
        assert result.status == "BLOCKED"
        assert any(issue.code == "amount_below_min" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_missing_lender_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-NOLENDER", 20000, "lender_missing")], lenders=[LENDER])
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        result = run_validation_workflow("REQ-NOLENDER")
        assert result.status == "BLOCKED"
        assert result.action == "BLOCK"
        assert any(issue.code == "missing_lender" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_cli_automate_valid_and_invalid(tmp_path: Path, capsys):
    _write_store(
        tmp_path,
        requests=[_request("REQ-OK", 20000), _request("REQ-HIGH", 80000)],
        lenders=[LENDER],
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        ok_code = main(["automate", "REQ-OK"])
        ok_out = capsys.readouterr().out
        assert ok_code == 0
        assert "READY" in ok_out
        assert "APPROVE" in ok_out
        assert "Dry run: True" in ok_out

        bad_code = main(["automate", "REQ-HIGH"])
        bad_out = capsys.readouterr().out
        assert bad_code == 1
        assert "BLOCKED" in bad_out
        assert "amount_above_max" in bad_out
    finally:
        store_mod._store = previous
