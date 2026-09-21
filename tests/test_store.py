from integrationops.store import (
    EvidenceNotFound,
    get_lender_config,
    get_request,
    get_response,
    load_incident,
)
import pytest


def test_load_existing_incident():
    incident = load_incident("INC-001")
    assert incident.incident_id == "INC-001"
    assert incident.request_id == "REQ-789"
    assert incident.lender_id == "lender_456"
    assert incident.failure_code == "INVALID_AMOUNT"


def test_load_existing_request():
    request = get_request("REQ-789")
    assert request.request_id == "REQ-789"
    assert request.amount == 5000
    assert request.currency == "USD"


def test_load_existing_response():
    response = get_response("REQ-789")
    assert response.request_id == "REQ-789"
    assert response.error_code == "INVALID_AMOUNT"
    assert response.status == "FAILED"


def test_load_existing_lender_config():
    lender = get_lender_config("lender_456")
    assert lender.lender_id == "lender_456"
    assert lender.min_amount == 10000
    assert lender.max_amount == 50000


def test_unknown_ids_raise_evidence_not_found():
    with pytest.raises(EvidenceNotFound):
        load_incident("INC-MISSING")
    with pytest.raises(EvidenceNotFound):
        get_request("REQ-MISSING")
    with pytest.raises(EvidenceNotFound):
        get_response("REQ-MISSING")
    with pytest.raises(EvidenceNotFound):
        get_lender_config("lender_missing")
