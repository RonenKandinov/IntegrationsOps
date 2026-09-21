"""Build synthetic requests, responses, and incidents from generated merchants.

The investigation engine never reads ground_truth.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from integrationops.models import ApiRequest, ApiResponse, Incident, LenderConfig, Merchant

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MERCHANTS_PATH = _PACKAGE_ROOT / "data" / "generated" / "merchants.json"
DEFAULT_OUTPUT_DIR = _PACKAGE_ROOT / "data" / "generated"

LENDER_ID = "lender_456"
LENDER_MIN = 10000
LENDER_MAX = 50000
CURRENCY = "USD"
WITHIN_LIMITS_AMOUNT = 20000
ABOVE_MAX_AMOUNT = 80000

FAILURE_CODES = ("INVALID_AMOUNT", "TIMEOUT", "AUTHENTICATION_ERROR")


class ScenarioGeneratorError(ValueError):
    """Raised when merchants cannot be loaded or generation cannot run."""


@dataclass
class GroundTruth:
    incident_id: str
    expected_failure_code: str
    expected_root_cause: str
    evidence_gap: bool = False


@dataclass
class ScenarioBundle:
    merchants_used: int
    requests: list[ApiRequest]
    responses: list[ApiResponse]
    incidents: list[Incident]
    lenders: list[LenderConfig]
    ground_truth: list[GroundTruth]
    breakdown: dict[str, int] = field(default_factory=dict)


def load_merchants(path: Path | None = None) -> list[Merchant]:
    merchants_path = path or DEFAULT_MERCHANTS_PATH
    try:
        raw = merchants_path.read_text(encoding="utf-8")
        records = json.loads(raw)
    except FileNotFoundError as exc:
        raise ScenarioGeneratorError(f"Generated merchants not found: {merchants_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ScenarioGeneratorError(f"Could not read merchants: {merchants_path}") from exc
    if not isinstance(records, list):
        raise ScenarioGeneratorError(f"{merchants_path} must contain a JSON array")
    merchants: list[Merchant] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        merchant_id = record.get("merchant_id")
        source_id = record.get("source_id")
        if not isinstance(merchant_id, str) or not merchant_id:
            continue
        if not isinstance(source_id, str) or not source_id:
            continue
        merchants.append(
            Merchant(
                merchant_id=merchant_id,
                source_id=source_id,
                city=record.get("city") if isinstance(record.get("city"), str) else None,
                state=record.get("state") if isinstance(record.get("state"), str) else None,
                zip_code_prefix=(
                    record.get("zip_code_prefix")
                    if isinstance(record.get("zip_code_prefix"), str)
                    else None
                ),
            )
        )
    merchants.sort(key=lambda item: item.merchant_id)
    return merchants


def _lender() -> LenderConfig:
    return LenderConfig(
        lender_id=LENDER_ID,
        min_amount=LENDER_MIN,
        max_amount=LENDER_MAX,
        currency=CURRENCY,
    )


def generate_scenarios(
    merchants: list[Merchant],
    merchant_count: int = 100,
    seed: int = 1,
) -> ScenarioBundle:
    del seed  # Generation is order-based; seed is accepted so reruns stay identical.
    if merchant_count < 1:
        raise ScenarioGeneratorError("merchant_count must be at least 1")
    selected = merchants[:merchant_count]
    if not selected:
        raise ScenarioGeneratorError("No merchants available to generate scenarios")

    requests: list[ApiRequest] = []
    responses: list[ApiResponse] = []
    incidents: list[Incident] = []
    ground_truth: list[GroundTruth] = []
    breakdown = {code: 0 for code in FAILURE_CODES}
    breakdown["EVIDENCE_GAP"] = 0
    sequence = 0

    def add_case(
        merchant: Merchant,
        failure_code: str,
        amount: int,
        error_code: str,
        message: str,
        expected_root_cause: str,
        *,
        evidence_gap: bool = False,
    ) -> None:
        nonlocal sequence
        sequence += 1
        request_id = f"REQ-{sequence:06d}"
        incident_id = f"INC-{sequence:06d}"
        requests.append(
            ApiRequest(
                request_id=request_id,
                merchant_id=merchant.merchant_id,
                lender_id=LENDER_ID,
                amount=amount,
                currency=CURRENCY,
            )
        )
        responses.append(
            ApiResponse(
                request_id=request_id,
                status="FAILED",
                error_code=error_code,
                message=message,
            )
        )
        incidents.append(
            Incident(
                incident_id=incident_id,
                merchant_id=merchant.merchant_id,
                lender_id=LENDER_ID,
                failure_code=failure_code,
                request_id=request_id,
            )
        )
        ground_truth.append(
            GroundTruth(
                incident_id=incident_id,
                expected_failure_code=failure_code,
                expected_root_cause=expected_root_cause,
                evidence_gap=evidence_gap,
            )
        )
        if evidence_gap:
            breakdown["EVIDENCE_GAP"] += 1
        else:
            breakdown[failure_code] += 1

    for merchant in selected:
        add_case(
            merchant,
            "INVALID_AMOUNT",
            ABOVE_MAX_AMOUNT,
            "INVALID_AMOUNT",
            "The requested amount is not valid for this lender.",
            "Requested amount is above the lender's maximum allowed amount.",
        )
        add_case(
            merchant,
            "TIMEOUT",
            WITHIN_LIMITS_AMOUNT,
            "TIMEOUT",
            "The lender API did not respond before the request timed out.",
            "The lender API did not respond before the request timed out.",
        )
        add_case(
            merchant,
            "AUTHENTICATION_ERROR",
            WITHIN_LIMITS_AMOUNT,
            "AUTHENTICATION_ERROR",
            "The merchant is not authenticated with this lender.",
            "The merchant is not authenticated with this lender.",
        )

    add_case(
        selected[0],
        "INVALID_AMOUNT",
        WITHIN_LIMITS_AMOUNT,
        "INVALID_AMOUNT",
        "The requested amount is not valid for this lender.",
        "Not determined from lender min/max limits.",
        evidence_gap=True,
    )

    return ScenarioBundle(
        merchants_used=len(selected),
        requests=requests,
        responses=responses,
        incidents=incidents,
        lenders=[_lender()],
        ground_truth=ground_truth,
        breakdown=breakdown,
    )


def write_scenarios(bundle: ScenarioBundle, output_dir: Path | None = None) -> Path:
    directory = output_dir or DEFAULT_OUTPUT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "requests.json").write_text(
        json.dumps([asdict(item) for item in bundle.requests], indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "responses.json").write_text(
        json.dumps([asdict(item) for item in bundle.responses], indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "incidents.json").write_text(
        json.dumps([asdict(item) for item in bundle.incidents], indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "lenders.json").write_text(
        json.dumps([asdict(item) for item in bundle.lenders], indent=2) + "\n",
        encoding="utf-8",
    )
    (directory / "ground_truth.json").write_text(
        json.dumps([asdict(item) for item in bundle.ground_truth], indent=2) + "\n",
        encoding="utf-8",
    )
    return directory


def generate_and_write(
    merchants_path: Path | None = None,
    output_dir: Path | None = None,
    merchant_count: int = 100,
    seed: int = 1,
) -> ScenarioBundle:
    merchants = load_merchants(merchants_path)
    bundle = generate_scenarios(merchants, merchant_count=merchant_count, seed=seed)
    write_scenarios(bundle, output_dir)
    return bundle
