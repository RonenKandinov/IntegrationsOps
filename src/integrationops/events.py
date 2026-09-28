"""Run investigate against production-like evidence."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from integrationops.engine import investigate
from integrationops.models import Diagnosis
from integrationops.store.json_store import JsonStore
import integrationops.store as store_mod

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = _PACKAGE_ROOT / "data" / "production" / "evidence"


@contextmanager
def use_evidence_store(evidence_dir: Path | None = None) -> Iterator[None]:
    previous = store_mod._store
    store_mod._store = JsonStore(evidence_dir or DEFAULT_EVIDENCE_DIR)
    try:
        yield
    finally:
        store_mod._store = previous


def investigate_event(event_id: str, evidence_dir: Path | None = None) -> Diagnosis:
    with use_evidence_store(evidence_dir):
        return investigate(event_id)
