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
class Merchant:
    merchant_id: str
    source_id: str
    city: str | None = None
    state: str | None = None
    zip_code_prefix: str | None = None


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


@dataclass
class ValidationIssue:
    rule: str
    code: str
    message: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    field: str | None = None


@dataclass
class ValidationReport:
    target_id: str
    valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
