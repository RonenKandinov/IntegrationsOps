"""Operational system model: S_t, A_f(S_t), and in-memory T(S_t, a_t, ω_t)."""

from __future__ import annotations

import json
from pathlib import Path

from integrationops.engine import investigate
from integrationops.investigations.evidence import STATUS_DETERMINED, STATUS_GAP
from integrationops.models import (
    ApiRequest,
    ApiResponse,
    Incident,
    LenderConfig,
    Merchant,
)
from integrationops.operations.actions import all_actions, feasible_actions, is_feasible
from integrationops.operations.constants import (
    ACTION_ESCALATE,
    ACTION_FIX_CONFIGURATION,
    ACTION_INVESTIGATE,
    ACTION_RESOLVE_INCIDENT,
    ACTION_RETRY_REQUEST,
    ACTION_VALIDATE,
    CONSTRAINT_API_AVAILABILITY,
    CONSTRAINT_PROVIDER_AVAILABILITY,
    CONSTRAINT_TRANSACTION_LIMIT,
    EVENT_LENDER_UNAVAILABLE,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_PENDING,
    TASK_READY,
    TASK_STATES,
)
from integrationops.operations.cycle import attach_investigation
from integrationops.operations.state import (
    SystemState,
    build_system_state,
    merchant_operational,
)
from integrationops.operations.transition import InfeasibleActionError, transition
from integrationops.operations.types import CandidateAction, OperationalEvent
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod


def _merchant(merchant_id: str) -> Merchant:
    return Merchant(merchant_id=merchant_id, source_id=merchant_id.lower())


def _lender() -> LenderConfig:
    return LenderConfig(
        lender_id="lender_456",
        min_amount=10000,
        max_amount=50000,
        currency="USD",
    )


def _request(amount: int = 80000) -> ApiRequest:
    return ApiRequest(
        request_id="REQ-HIGH",
        merchant_id="MERCHANT-A",
        lender_id="lender_456",
        amount=amount,
        currency="USD",
    )


def _response(error_code: str = "INVALID_AMOUNT") -> ApiResponse:
    return ApiResponse(
        request_id="REQ-HIGH",
        status="error",
        error_code=error_code,
        message=error_code,
    )


def _incident() -> Incident:
    return Incident(
        incident_id="INC-HIGH",
        merchant_id="MERCHANT-A",
        lender_id="lender_456",
        failure_code="INVALID_AMOUNT",
        request_id="REQ-HIGH",
    )


def _amount_state(*, lender: LenderConfig | None = ..., amount: int = 80000) -> SystemState:
    resolved = _lender() if lender is ... else lender
    return build_system_state(
        merchants=[_merchant("MERCHANT-A"), _merchant("MERCHANT-B"), _merchant("MERCHANT-C")],
        lender=resolved,
        incident=_incident(),
        request=_request(amount),
        response=_response(),
    )


def _write_store(tmp_path: Path, *, incidents, requests, responses, lenders) -> Path:
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "incidents.json").write_text(json.dumps(incidents), encoding="utf-8")
    (generated / "requests.json").write_text(json.dumps(requests), encoding="utf-8")
    (generated / "responses.json").write_text(json.dumps(responses), encoding="utf-8")
    (generated / "lenders.json").write_text(json.dumps(lenders), encoding="utf-8")
    return generated


def test_system_state_has_v_e_r_q_omega():
    state = _amount_state()
    kinds = {item.kind for item in state.entities()}
    assert kinds >= {
        "merchant",
        "integration",
        "lender_configuration",
        "payment",
        "incident",
        "api",
    }
    relations = {item.relation for item in state.dependencies}
    assert "merchant_requires_integration" in relations
    assert "integration_requires_lender" in relations
    assert "integration_requires_api" in relations
    assert "payment_requires_integration" in relations
    assert {item.kind for item in state.resources} == {
        CONSTRAINT_TRANSACTION_LIMIT,
        CONSTRAINT_API_AVAILABILITY,
        CONSTRAINT_PROVIDER_AVAILABILITY,
        "configuration",
        "payment",
    }
    assert all("engineer" not in item.kind and "staff" not in item.kind for item in state.resources)
    assert state.task_state("incident", "INC-HIGH") in TASK_STATES
    assert state.task_state("incident", "INC-HIGH") == TASK_PENDING
    assert state.task_state("integration", "MERCHANT-A:lender_456") == TASK_BLOCKED
    assert state.events == []
    vertices, edges = state.graph()
    assert vertices == state.entities()
    assert edges == state.dependencies


def test_shared_lender_is_a_dependency_not_an_objective():
    state = _amount_state()
    merchants = [
        item.dependent_id
        for item in state.dependencies
        if item.relation == "merchant_requires_lender"
    ]
    assert merchants == ["MERCHANT-A", "MERCHANT-B", "MERCHANT-C"]


def test_feasible_actions_are_a_subset_and_exclude_staffing():
    state = _amount_state()
    actions = all_actions(state)
    feasible = feasible_actions(state)
    assert all(item in actions for item in feasible)
    assert any(item.kind == ACTION_INVESTIGATE for item in feasible)
    assert all(item.kind != "assign_person" for item in actions)
    assert not any(item.kind == ACTION_FIX_CONFIGURATION for item in feasible)
    assert not any(item.kind == ACTION_RESOLVE_INCIDENT for item in feasible)


def test_investigate_then_fix_configuration_then_validate_then_operational():
    initial = _amount_state()
    diagnosis = _determined_above_max()
    after_invest = attach_investigation(initial, "INC-HIGH", diagnosis=diagnosis)

    assert initial.diagnoses == []
    assert after_invest.time == 1
    assert after_invest.diagnoses[0].status == STATUS_DETERMINED
    assert after_invest.task_state("investigation", "INC-HIGH") == TASK_COMPLETED
    assert after_invest.task_state("incident", "INC-HIGH") == TASK_READY

    feasible = feasible_actions(after_invest)
    fix = next(item for item in feasible if item.kind == ACTION_FIX_CONFIGURATION)
    assert fix.parameters["max_amount"] == 80000
    assert is_feasible(after_invest, fix)

    after_fix = transition(after_invest, fix)
    assert after_fix.lender("lender_456").max_amount == 80000
    limit = after_fix.constraint(CONSTRAINT_TRANSACTION_LIMIT, "lender_456")
    assert limit is not None
    assert limit.max_amount == 80000
    assert after_invest.lender("lender_456").max_amount == 50000

    validate = CandidateAction(
        kind=ACTION_VALIDATE,
        target_id="INC-HIGH",
        reason="Validate after the in-memory configuration change.",
    )
    after_validate = transition(after_fix, validate)
    report = after_validate.validation_for("INC-HIGH")
    assert report is not None and report.valid is True
    assert after_validate.task_state("validation", "INC-HIGH") == TASK_COMPLETED

    resolve = CandidateAction(
        kind=ACTION_RESOLVE_INCIDENT,
        target_id="INC-HIGH",
        reason="Close the incident after validation.",
    )
    assert is_feasible(after_validate, resolve)
    after_resolve = transition(after_validate, resolve)
    assert after_resolve.task_state("incident", "INC-HIGH") == TASK_COMPLETED
    assert after_resolve.integration("MERCHANT-A:lender_456").operational is True
    assert merchant_operational(after_resolve, "MERCHANT-A")
    assert after_resolve.task_state("merchant", "MERCHANT-A") == TASK_COMPLETED


def test_infeasible_resolve_before_limits_are_fixed():
    state = attach_investigation(_amount_state(), "INC-HIGH", diagnosis=_determined_above_max())
    resolve = CandidateAction(
        kind=ACTION_RESOLVE_INCIDENT,
        target_id="INC-HIGH",
        reason="Attempt to resolve while the payment still violates limits.",
    )
    assert not is_feasible(state, resolve)
    try:
        transition(state, resolve)
    except InfeasibleActionError:
        return
    raise AssertionError("expected InfeasibleActionError")


def test_missing_lender_blocks_configuration_fix_and_allows_escalate():
    state = attach_investigation(
        _amount_state(lender=None),
        "INC-HIGH",
        diagnosis=_gap_missing_lender(),
    )
    assert state.task_state("investigation", "INC-HIGH") == TASK_BLOCKED
    assert not any(item.kind == ACTION_FIX_CONFIGURATION for item in feasible_actions(state))
    assert any(item.kind == ACTION_ESCALATE for item in feasible_actions(state))


def test_lender_unavailable_event_blocks_resolution():
    diagnosed = attach_investigation(
        _amount_state(),
        "INC-HIGH",
        diagnosis=_determined_above_max(),
    )
    unavailable = OperationalEvent(
        event_id="omega-1",
        kind=EVENT_LENDER_UNAVAILABLE,
        subject_id="lender_456",
        detail="Provider stopped accepting requests.",
    )
    blocked = transition(diagnosed, event=unavailable)
    assert blocked.resource_available(CONSTRAINT_PROVIDER_AVAILABILITY, "lender_456") is False
    assert blocked.task_state("integration", "MERCHANT-A:lender_456") == TASK_BLOCKED
    assert not any(item.kind == ACTION_FIX_CONFIGURATION for item in feasible_actions(blocked))


def test_engine_invalid_amount_feeds_the_model_without_writing_the_store(tmp_path: Path):
    generated = _write_store(
        tmp_path,
        incidents=[
            {
                "incident_id": "INC-HIGH",
                "merchant_id": "MERCHANT-A",
                "lender_id": "lender_456",
                "failure_code": "INVALID_AMOUNT",
                "request_id": "REQ-HIGH",
            }
        ],
        requests=[
            {
                "request_id": "REQ-HIGH",
                "merchant_id": "MERCHANT-A",
                "lender_id": "lender_456",
                "amount": 80000,
                "currency": "USD",
            }
        ],
        responses=[
            {
                "request_id": "REQ-HIGH",
                "status": "error",
                "error_code": "INVALID_AMOUNT",
                "message": "INVALID_AMOUNT",
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
    before = {path.name: path.read_bytes() for path in generated.iterdir()}
    try:
        diagnosis = investigate("INC-HIGH")
        assert diagnosis.status == STATUS_DETERMINED
        assert diagnosis.root_cause.startswith("Requested amount is above")

        state = build_system_state(
            merchants=[_merchant("MERCHANT-A")],
            lender=_lender(),
            incident=_incident(),
            request=_request(),
            response=_response(),
        )
        after = attach_investigation(state, "INC-HIGH")
        assert after.diagnoses[0].status == STATUS_DETERMINED
        assert after.diagnoses[0].trace == diagnosis.trace
        fix = next(
            item
            for item in feasible_actions(after)
            if item.kind == ACTION_FIX_CONFIGURATION
        )
        after_fix = transition(after, fix)
        after_validate = transition(
            after_fix,
            CandidateAction(kind=ACTION_VALIDATE, target_id="INC-HIGH", reason="validate"),
        )
        after_resolve = transition(
            after_validate,
            CandidateAction(
                kind=ACTION_RESOLVE_INCIDENT,
                target_id="INC-HIGH",
                reason="resolve",
            ),
        )
        assert merchant_operational(after_resolve, "MERCHANT-A")
        after_bytes = {path.name: path.read_bytes() for path in generated.iterdir()}
        assert after_bytes == before
    finally:
        store_mod._store = previous


def test_retry_with_reduced_amount_is_an_alternative_candidate():
    state = attach_investigation(_amount_state(), "INC-HIGH", diagnosis=_determined_above_max())
    retry = next(
        item
        for item in feasible_actions(state)
        if item.kind == ACTION_RETRY_REQUEST and "amount" in item.parameters
    )
    nxt = transition(state, retry)
    assert nxt.request("REQ-HIGH").amount == 50000
    assert state.request("REQ-HIGH").amount == 80000
    assert is_feasible(
        nxt,
        CandidateAction(
            kind=ACTION_RESOLVE_INCIDENT,
            target_id="INC-HIGH",
            reason="resolve after payment adjustment",
        ),
    )


def _determined_above_max():
    from integrationops.models import Diagnosis

    return Diagnosis(
        incident_id="INC-HIGH",
        failure_code="INVALID_AMOUNT",
        root_cause="Requested amount is above the lender's maximum allowed amount.",
        explanation="The requested amount violates the lender's configured maximum amount.",
        recommended_action="Check whether the loan amount should be reduced to at most 50000.",
        status=STATUS_DETERMINED,
    )


def _gap_missing_lender():
    from integrationops.models import Diagnosis

    return Diagnosis(
        incident_id="INC-HIGH",
        failure_code="INVALID_AMOUNT",
        root_cause="Not determined: lender configuration is missing.",
        explanation="Insufficient evidence.",
        recommended_action="Retrieve the lender configuration or equivalent limit information.",
        status=STATUS_GAP,
    )
