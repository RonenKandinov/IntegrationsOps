import json
from pathlib import Path

from integrationops.automation.config_change import run_config_change_workflow
from integrationops.cli import main
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def _write_store(tmp_path: Path, *, requests, lenders) -> Path:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "requests.json").write_text(json.dumps(requests), encoding="utf-8")
    (generated / "lenders.json").write_text(json.dumps(lenders), encoding="utf-8")
    (generated / "incidents.json").write_text("[]", encoding="utf-8")
    (generated / "responses.json").write_text("[]", encoding="utf-8")
    return generated


LENDER = {
    "lender_id": "lender_456",
    "min_amount": 10000,
    "max_amount": 50000,
    "currency": "USD",
}
OTHER = {
    "lender_id": "lender_other",
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


def _use_store(tmp_path: Path):
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    return previous


def test_raise_max_keeps_in_range_request_ready(tmp_path: Path):
    generated = _write_store(
        tmp_path,
        requests=[_request("REQ-OK", 20000), _request("REQ-OTHER", 20000, "lender_other")],
        lenders=[LENDER, OTHER],
    )
    previous = _use_store(tmp_path)
    before = {path.name: path.read_bytes() for path in generated.iterdir()}
    try:
        result = run_config_change_workflow(
            "lender_456",
            max_amount=100000,
            request_ids=["REQ-OK", "REQ-OTHER"],
        )
        assert result.status == "READY"
        assert result.action == "APPROVE"
        assert result.dry_run is True
        assert result.issues == []
        impact = next(check for check in result.checks if check.name == "impact")
        assert any("unchanged and within proposed limits" in item.fact for item in impact.evidence)
        assert any("ignored REQ-OTHER" in item.fact for item in impact.evidence)
        after = {path.name: path.read_bytes() for path in generated.iterdir()}
        assert after == before
    finally:
        store_mod._store = previous


def test_amount_still_above_proposed_max_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-HIGH", 80000)], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_config_change_workflow(
            "lender_456",
            max_amount=60000,
            request_ids=["REQ-HIGH"],
        )
        assert result.status == "BLOCKED"
        assert result.action == "BLOCK"
        assert any(issue.code == "amount_above_max" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_min_above_max_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_config_change_workflow("lender_456", min_amount=80000, max_amount=1000)
        assert result.status == "BLOCKED"
        assert any(issue.code == "min_exceeds_max" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_currency_change_requires_human_review(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-OK", 20000)], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_config_change_workflow(
            "lender_456",
            currency="EUR",
            request_ids=["REQ-OK"],
        )
        assert result.status == "REVIEW"
        assert result.action == "HUMAN_REVIEW"
        assert any(issue.code == "currency_changed" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_missing_request_ids_requires_human_review(tmp_path: Path):
    _write_store(tmp_path, requests=[_request("REQ-OK", 20000)], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_config_change_workflow("lender_456", max_amount=100000)
        assert result.status == "REVIEW"
        assert result.action == "HUMAN_REVIEW"
        assert any(issue.code == "impact_not_evaluated" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_missing_lender_is_blocked(tmp_path: Path):
    _write_store(tmp_path, requests=[], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        result = run_config_change_workflow("lender_missing", max_amount=100000, request_ids=["REQ-OK"])
        assert result.status == "BLOCKED"
        assert any(issue.code == "missing_lender" for issue in result.issues)
    finally:
        store_mod._store = previous


def test_cli_config_ready(tmp_path: Path, capsys):
    _write_store(tmp_path, requests=[_request("REQ-OK", 20000)], lenders=[LENDER])
    previous = _use_store(tmp_path)
    try:
        code = main(["automate-config", "lender_456", "--max-amount", "100000", "--request", "REQ-OK"])
        out = capsys.readouterr().out
        assert code == 0
        assert "READY" in out
        assert "Dry run: True" in out
    finally:
        store_mod._store = previous
