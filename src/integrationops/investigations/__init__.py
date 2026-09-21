"""Failure-specific investigation paths."""

from integrationops.investigations.authentication_error import investigate_authentication_error
from integrationops.investigations.invalid_amount import investigate_invalid_amount
from integrationops.investigations.timeout import investigate_timeout

__all__ = [
    "investigate_authentication_error",
    "investigate_invalid_amount",
    "investigate_timeout",
]
