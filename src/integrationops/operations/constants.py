"""Names used by the operational system model. Not an optimizer vocabulary."""

# Q_t — operational work-item states. Distinct from Diagnosis.status.
TASK_PENDING = "Pending"
TASK_READY = "Ready"
TASK_IN_PROGRESS = "InProgress"
TASK_BLOCKED = "Blocked"
TASK_COMPLETED = "Completed"
TASK_FAILED = "Failed"

TASK_STATES = (
    TASK_PENDING,
    TASK_READY,
    TASK_IN_PROGRESS,
    TASK_BLOCKED,
    TASK_COMPLETED,
    TASK_FAILED,
)

# R_t — operational/system constraints. Not engineers or staffing.
CONSTRAINT_TRANSACTION_LIMIT = "transaction_limit"
CONSTRAINT_API_AVAILABILITY = "api_availability"
CONSTRAINT_PROVIDER_AVAILABILITY = "provider_availability"
CONSTRAINT_CONFIGURATION = "configuration"
CONSTRAINT_PAYMENT = "payment"
CONSTRAINT_CONCURRENCY = "concurrency"
CONSTRAINT_SLA = "sla"

# A(S_t) kinds from the model, excluding person assignment.
ACTION_INVESTIGATE = "investigate"
ACTION_FIX_CONFIGURATION = "fix_configuration"
ACTION_VALIDATE = "validate"
ACTION_ONBOARD = "onboard"
ACTION_RETRY_REQUEST = "retry_request"
ACTION_ESCALATE = "escalate"
ACTION_SAFETY_CHECK = "run_safety_check"
ACTION_RESOLVE_INCIDENT = "resolve_incident"

# Ω_t
EVENT_NEW_MERCHANT = "new_merchant"
EVENT_NEW_INCIDENT = "new_incident"
EVENT_LENDER_UNAVAILABLE = "lender_unavailable"
EVENT_API_BEHAVIOR_CHANGE = "api_behavior_change"
EVENT_MISSING_INFORMATION_ARRIVED = "missing_information_arrived"
EVENT_UNEXPECTED_RESPONSE = "unexpected_response"
EVENT_LENDER_RECOVERED = "lender_recovered"
EVENT_CONFIGURATION_CHANGED = "configuration_changed"
EVENT_WORK_ARRIVED = "work_arrived"
