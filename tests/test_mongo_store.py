import mongomock
import pytest

from integrationops.store import EvidenceNotFound, MongoStore


def _seeded_mongo_store() -> MongoStore:
    db = mongomock.MongoClient()["integrationops"]
    db.incidents.insert_one(
        {
            "incident_id": "INC-001",
            "merchant_id": "merchant_123",
            "lender_id": "lender_456",
            "failure_code": "INVALID_AMOUNT",
            "request_id": "REQ-789",
        }
    )
    db.requests.insert_one(
        {
            "request_id": "REQ-789",
            "merchant_id": "merchant_123",
            "lender_id": "lender_456",
            "amount": 5000,
            "currency": "USD",
        }
    )
    db.responses.insert_one(
        {
            "request_id": "REQ-789",
            "status": "FAILED",
            "error_code": "INVALID_AMOUNT",
            "message": "The requested amount is not valid for this lender.",
        }
    )
    db.lenders.insert_one(
        {
            "lender_id": "lender_456",
            "min_amount": 10000,
            "max_amount": 50000,
            "currency": "USD",
        }
    )
    return MongoStore(db)


def test_mongo_store_loads_seed_records():
    store = _seeded_mongo_store()
    incident = store.load_incident("INC-001")
    request = store.get_request("REQ-789")
    response = store.get_response("REQ-789")
    lender = store.get_lender_config("lender_456")
    assert incident.failure_code == "INVALID_AMOUNT"
    assert request.amount == 5000
    assert response.error_code == "INVALID_AMOUNT"
    assert lender.min_amount == 10000


def test_mongo_store_unknown_id():
    store = _seeded_mongo_store()
    with pytest.raises(EvidenceNotFound):
        store.load_incident("INC-MISSING")
