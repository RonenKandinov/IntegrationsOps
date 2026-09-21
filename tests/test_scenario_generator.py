import json
from pathlib import Path

import pytest

from integrationops.generators.scenario_generator import (
    ScenarioGeneratorError,
    generate_and_write,
    generate_scenarios,
    load_merchants,
)
from integrationops.models import Merchant

HEADER = "seller_id,seller_zip_code_prefix,seller_city,seller_state"


def _merchants() -> list[Merchant]:
    return [
        Merchant("MER-000010", "src-a", "sao paulo", "SP", "01000"),
        Merchant("MER-000011", "src-b", "rio de janeiro", "RJ", "20000"),
        Merchant("MER-000012", "src-c", "campinas", "SP", "13000"),
    ]


def test_requests_and_incidents_are_unique_and_linked():
    bundle = generate_scenarios(_merchants(), merchant_count=3, seed=1)
    request_ids = [item.request_id for item in bundle.requests]
    incident_ids = [item.incident_id for item in bundle.incidents]
    assert len(request_ids) == len(set(request_ids))
    assert len(incident_ids) == len(set(incident_ids))
    merchant_ids = {item.merchant_id for item in _merchants()}
    assert all(item.merchant_id in merchant_ids for item in bundle.requests)
    assert all(item.merchant_id in merchant_ids for item in bundle.incidents)
    request_id_set = set(request_ids)
    assert all(item.request_id in request_id_set for item in bundle.incidents)
    assert all(item.request_id in request_id_set for item in bundle.responses)
    assert all(item.failure_code in {"INVALID_AMOUNT", "TIMEOUT", "AUTHENTICATION_ERROR"} for item in bundle.incidents)


def test_ground_truth_matches_scenario():
    bundle = generate_scenarios(_merchants(), merchant_count=1, seed=1)
    by_id = {item.incident_id: item for item in bundle.ground_truth}
    invalid = next(
        item
        for item in bundle.incidents
        if item.failure_code == "INVALID_AMOUNT" and not by_id[item.incident_id].evidence_gap
    )
    request = next(item for item in bundle.requests if item.request_id == invalid.request_id)
    assert request.amount > 50000
    assert by_id[invalid.incident_id].expected_root_cause.startswith("Requested amount is above")
    timeout = next(item for item in bundle.incidents if item.failure_code == "TIMEOUT")
    response = next(item for item in bundle.responses if item.request_id == timeout.request_id)
    assert response.error_code == "TIMEOUT"
    assert "source_id=" in response.message
    gap = next(item for item in bundle.ground_truth if item.evidence_gap)
    gap_request = next(
        item
        for item in bundle.requests
        if item.request_id == next(i.request_id for i in bundle.incidents if i.incident_id == gap.incident_id)
    )
    assert 10000 <= gap_request.amount <= 50000
    assert gap.expected_root_cause.startswith("Not determined")


def test_generation_is_deterministic_with_fixed_seed():
    first = generate_scenarios(_merchants(), merchant_count=2, seed=7)
    second = generate_scenarios(_merchants(), merchant_count=2, seed=7)
    assert [item.request_id for item in first.requests] == [item.request_id for item in second.requests]
    assert [item.merchant_id for item in first.requests] == [item.merchant_id for item in second.requests]
    assert [item.amount for item in first.requests] == [item.amount for item in second.requests]


def test_different_seeds_produce_different_scenarios():
    first = generate_scenarios(_merchants(), merchant_count=2, seed=123)
    second = generate_scenarios(_merchants(), merchant_count=2, seed=999)
    assert [item.merchant_id for item in first.requests] != [item.merchant_id for item in second.requests] or [
        item.amount for item in first.requests
    ] != [item.amount for item in second.requests]


def test_count_caps_to_available_merchants():
    bundle = generate_scenarios(_merchants(), merchant_count=50, seed=1)
    assert bundle.merchants_used == 3
    assert bundle.warning is not None
    assert "50" in bundle.warning
    assert "3" in bundle.warning


def test_invalid_count_raises():
    with pytest.raises(ScenarioGeneratorError):
        generate_scenarios(_merchants(), merchant_count=0, seed=1)
    with pytest.raises(ScenarioGeneratorError):
        generate_scenarios(_merchants(), merchant_count=-2, seed=1)


def test_write_does_not_touch_raw(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    sellers = raw / "olist_sellers_dataset.csv"
    sellers.write_text(f"{HEADER}\nseller-1,01000,sao paulo,SP\n", encoding="utf-8")
    original = sellers.read_bytes()
    merchants_path = tmp_path / "merchants.json"
    merchants_path.write_text(
        json.dumps([{"merchant_id": "MER-000001", "source_id": "src-1", "city": "sao paulo", "state": "SP", "zip_code_prefix": "01000"}]),
        encoding="utf-8",
    )
    output = tmp_path / "generated"
    generate_and_write(merchants_path=merchants_path, output_dir=output, merchant_count=1, seed=1)
    assert sellers.read_bytes() == original
    assert (output / "requests.json").is_file()
    assert (output / "ground_truth.json").is_file()
    loaded = load_merchants(merchants_path)
    assert loaded[0].merchant_id == "MER-000001"
