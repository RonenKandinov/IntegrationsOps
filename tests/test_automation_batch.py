import json
from pathlib import Path

from integrationops.automation.batch import run_batch_workflow
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


def test_batch_mixes_outcomes_and_does_not_write(tmp_path: Path):
    generated = _write_store(
        tmp_path,
        requests=[
            _request("REQ-OK", 20000),
            _request("REQ-HIGH", 80000),
            _request("REQ-LOW", 5000),
            _request("REQ-NOLENDER", 20000, "lender_missing"),
        ],
        lenders=[LENDER],
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    before = {path.name: path.read_bytes() for path in generated.iterdir()}
    try:
        report = run_batch_workflow(
            ["REQ-OK", "REQ-OK", "REQ-HIGH", "REQ-LOW", "REQ-NOLENDER", "REQ-MISSING"]
        )
        assert report.dry_run is True
        assert report.total == 6
        assert report.ready == 2
        assert report.blocked == 4
        assert report.missing_data == 2
        assert report.ready + report.blocked == report.total
        assert [result.target_id for result in report.results] == [
            "REQ-OK",
            "REQ-OK",
            "REQ-HIGH",
            "REQ-LOW",
            "REQ-NOLENDER",
            "REQ-MISSING",
        ]
        assert any(issue.code == "amount_above_max" for issue in report.results[2].issues)
        assert any(issue.code == "amount_below_min" for issue in report.results[3].issues)
        assert any(issue.code == "missing_lender" for issue in report.results[4].issues)
        assert any(issue.code == "missing_request" for issue in report.results[5].issues)
        after = {path.name: path.read_bytes() for path in generated.iterdir()}
        assert after == before
    finally:
        store_mod._store = previous


def test_empty_batch():
    report = run_batch_workflow([])
    assert report.total == 0
    assert report.ready == 0
    assert report.blocked == 0
    assert report.missing_data == 0
    assert report.results == []


def test_cli_batch_exit_codes(tmp_path: Path, capsys):
    _write_store(
        tmp_path,
        requests=[_request("REQ-OK", 20000), _request("REQ-HIGH", 80000)],
        lenders=[LENDER],
    )
    previous = store_mod._store
    store_mod._store = JsonStore(tmp_path)
    try:
        ok_code = main(["automate-batch", "REQ-OK"])
        ok_out = capsys.readouterr().out
        assert ok_code == 0
        assert "Ready: 1" in ok_out
        assert "Blocked: 0" in ok_out

        bad_code = main(["automate-batch", "REQ-OK", "REQ-HIGH"])
        bad_out = capsys.readouterr().out
        assert bad_code == 1
        assert "Blocked: 1" in bad_out
        assert "amount_above_max" in bad_out
    finally:
        store_mod._store = previous
