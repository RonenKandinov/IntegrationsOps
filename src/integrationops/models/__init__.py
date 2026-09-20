from dataclasses import dataclass, field


@dataclass
class Incident:
    incident_id: str
    merchant_id: str
    lender_id: str
    failure_code: str
    request_id: str


@dataclass
class ApiRequest:
    request_id: str
    merchant_id: str
    lender_id: str
    amount: int
    currency: str


@dataclass
class ApiResponse:
    request_id: str
    status: str
    error_code: str
    message: str


@dataclass
class LenderConfig:
    lender_id: str
    min_amount: int
    max_amount: int
    currency: str


@dataclass
class EvidenceItem:
    source: str
    fact: str


@dataclass
class Diagnosis:
    incident_id: str
    failure_code: str
    root_cause: str
    explanation: str
    recommended_action: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
