"""Shared store exceptions. Backends must not invent missing records."""


class StoreError(Exception):
    """Raised when evidence cannot be read or a record is malformed."""


class EvidenceNotFound(LookupError):
    """Raised when a requested evidence record is missing."""
