from integrationops.models import Diagnosis, Incident, LenderConfig, Merchant, ValidationReport
from integrationops.operations.snapshot import (
    merchants_sharing_lender,
    observe_chain,
    operational_states,
    shared_lender_dependencies,
)


def _merchant(merchant_id: str) -> Merchant:
    return Merchant(merchant_id=merchant_id, source_id=merchant_id.lower())


def test_three_merchants_share_one_lender_configuration():
    dependencies = shared_lender_dependencies(
        ["MERCHANT-A", "MERCHANT-B", "MERCHANT-C"],
        "lender_shared",
    )
    assert merchants_sharing_lender("lender_shared", dependencies) == [
        "MERCHANT-A",
        "MERCHANT-B",
        "MERCHANT-C",
    ]
    assert merchants_sharing_lender("lender_other", dependencies) == []


def test_chain_records_states_events_and_the_diagnosis_action():
    incident = Incident(
        incident_id="INC-CHAIN",
        merchant_id="MERCHANT-A",
        lender_id="lender_shared",
        failure_code="INVALID_AMOUNT",
        request_id="REQ-CHAIN",
    )
    lender = LenderConfig(
        lender_id="lender_shared",
        min_amount=10000,
        max_amount=50000,
        currency="USD",
    )
    diagnosis = Diagnosis(
        incident_id="INC-CHAIN",
        failure_code="INVALID_AMOUNT",
        root_cause="Requested amount is above the lender's maximum allowed amount.",
        explanation="The requested amount violates the lender's configured maximum amount.",
        recommended_action="Check whether the loan amount should be reduced to at most 50000.",
        status="ROOT_CAUSE_DETERMINED",
    )
    validation = ValidationReport(target_id="REQ-CHAIN", valid=False)
    snapshot = observe_chain(
        merchants=[_merchant("MERCHANT-A"), _merchant("MERCHANT-B"), _merchant("MERCHANT-C")],
        lender=lender,
        incident=incident,
        validation=validation,
        diagnosis=diagnosis,
    )

    relations = {item.relation for item in snapshot.dependencies}
    assert "merchant_requires_lender" in relations
    assert "merchant_requires_integration" in relations
    assert "integration_requires_lender" in relations
    assert "integration_requires_api" in relations
    assert "incident_requires_request" in relations
    assert "validation_checks_lender" in relations
    assert len(snapshot.integrations) == 3
    assert snapshot.candidate_actions == [
        "Check whether the loan amount should be reduced to at most 50000."
    ]
    assert snapshot.events[0].fact.startswith("event incident=INC-CHAIN")
    states = dict((item[0], item[2]) for item in operational_states(snapshot))
    assert states["lender_shared"] == "present"
    assert states["REQ-CHAIN"] == "invalid"
    assert states["INC-CHAIN"] == "ROOT_CAUSE_DETERMINED"
    assert diagnosis.root_cause.startswith("Requested amount is above")


def test_missing_lender_is_visible_without_inventing_an_action():
    incident = Incident(
        incident_id="INC-GAP",
        merchant_id="MERCHANT-A",
        lender_id="lender_missing",
        failure_code="INVALID_AMOUNT",
        request_id="REQ-GAP",
    )
    diagnosis = Diagnosis(
        incident_id="INC-GAP",
        failure_code="INVALID_AMOUNT",
        root_cause="Not determined: lender configuration is missing.",
        explanation="Insufficient evidence.",
        recommended_action="Retrieve the lender configuration or equivalent limit information.",
        status="EVIDENCE_GAP",
    )
    snapshot = observe_chain(
        merchants=[_merchant("MERCHANT-A")],
        lender=None,
        incident=incident,
        diagnosis=diagnosis,
    )
    states = dict((item[0], item[2]) for item in operational_states(snapshot))
    assert states["lender_missing"] == "missing"
    assert states["INC-GAP"] == "EVIDENCE_GAP"
    assert len(snapshot.candidate_actions) == 1
