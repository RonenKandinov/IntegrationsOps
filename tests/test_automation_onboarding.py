import json
from pathlib import Path

from integrationops.automation.onboarding import run_onboarding_workflow
from integrationops.cli import main


def _write_merchants(path: Path, records: list[dict]) -> None:
    path.write_text(json.dumps(records), encoding="utf-8")


def test_complete_merchant_is_ready(tmp_path: Path):
    path = tmp_path / "merchants.json"
    _write_merchants(
        path,
        [
            {
                "merchant_id": "MER-000001",
                "source_id": "seller-1",
                "city": "sao paulo",
                "state": "SP",
                "zip_code_prefix": "01000",
            }
        ],
    )
    before = path.read_bytes()
    result = run_onboarding_workflow("MER-000001", merchants_path=path)
    assert result.status == "READY"
    assert result.action == "APPROVE"
    assert result.dry_run is True
    assert result.workflow_name == "Merchant Onboarding"
    assert result.issues == []
    checks = {check.name: check.result for check in result.checks}
    assert checks["required_merchant"] == "PASS"
    assert checks["optional_location"] == "PASS"
    assert path.read_bytes() == before


def test_missing_optional_city_is_still_ready(tmp_path: Path):
    path = tmp_path / "merchants.json"
    _write_merchants(
        path,
        [
            {
                "merchant_id": "MER-000002",
                "source_id": "seller-2",
                "city": None,
                "state": "SP",
                "zip_code_prefix": "01000",
            }
        ],
    )
    result = run_onboarding_workflow("MER-000002", merchants_path=path)
    assert result.status == "READY"
    assert result.action == "APPROVE"
    location = next(check for check in result.checks if check.name == "optional_location")
    assert location.result == "PASS"
    assert any(item.fact == "optional absent: city" for item in location.evidence)


def test_blank_source_id_is_blocked(tmp_path: Path):
    path = tmp_path / "merchants.json"
    _write_merchants(
        path,
        [{"merchant_id": "MER-BLANK", "source_id": "", "city": "x", "state": "y", "zip_code_prefix": "1"}],
    )
    before = path.read_bytes()
    result = run_onboarding_workflow("MER-BLANK", merchants_path=path)
    assert result.status == "BLOCKED"
    assert result.action == "BLOCK"
    assert any(issue.code == "missing_source_id" for issue in result.issues)
    assert path.read_bytes() == before


def test_unknown_merchant_is_blocked(tmp_path: Path):
    path = tmp_path / "merchants.json"
    _write_merchants(
        path,
        [{"merchant_id": "MER-000001", "source_id": "seller-1", "city": "a", "state": "b", "zip_code_prefix": "1"}],
    )
    result = run_onboarding_workflow("MER-NOPE", merchants_path=path)
    assert result.status == "BLOCKED"
    assert any(issue.code == "missing_merchant" for issue in result.issues)


def test_cli_onboarding(tmp_path: Path, capsys):
    path = tmp_path / "merchants.json"
    _write_merchants(
        path,
        [{"merchant_id": "MER-000001", "source_id": "seller-1", "city": "a", "state": "b", "zip_code_prefix": "1"}],
    )
    code = main(["automate-onboarding", "MER-000001", "--merchants", str(path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "READY" in out
    assert "APPROVE" in out
    assert "Dry run: True" in out
