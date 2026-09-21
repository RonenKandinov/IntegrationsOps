"""Import Olist sellers CSV into IntegrationOps Merchant records.

Expected raw file: data/raw/olist_sellers_dataset.csv
Columns used: seller_id, seller_zip_code_prefix, seller_city, seller_state
Other columns are ignored.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from integrationops.models import Merchant

REQUIRED_COLUMN = "seller_id"
OPTIONAL_COLUMNS = {
    "city": "seller_city",
    "state": "seller_state",
    "zip_code_prefix": "seller_zip_code_prefix",
}

_PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RAW_PATH = _PACKAGE_ROOT / "data" / "raw" / "olist_sellers_dataset.csv"
DEFAULT_OUTPUT_PATH = _PACKAGE_ROOT / "data" / "generated" / "merchants.json"


class MerchantImportError(ValueError):
    """Raised when the raw sellers file cannot be read as a table with seller_id."""


@dataclass
class MerchantImportResult:
    imported: int
    skipped: int
    merchants: list[Merchant]


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def read_olist_sellers(path: Path) -> MerchantImportResult:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise MerchantImportError(f"Raw dataset not found: {path}") from exc
    except OSError as exc:
        raise MerchantImportError(f"Could not read raw dataset: {path}") from exc

    if not raw.strip():
        return MerchantImportResult(imported=0, skipped=0, merchants=[])

    reader = csv.DictReader(raw.splitlines())
    if reader.fieldnames is None:
        raise MerchantImportError(f"{path} is not a CSV table")
    columns = [name.strip() if name else "" for name in reader.fieldnames]
    if REQUIRED_COLUMN not in columns:
        raise MerchantImportError(f"{path} is missing required column {REQUIRED_COLUMN!r}")

    skipped = 0
    by_source_id: dict[str, dict[str, str | None]] = {}
    for row in reader:
        source_id = _blank_to_none(row.get(REQUIRED_COLUMN))
        if source_id is None:
            skipped += 1
            continue
        if source_id in by_source_id:
            skipped += 1
            continue
        by_source_id[source_id] = {
            "city": _blank_to_none(row.get("seller_city")),
            "state": _blank_to_none(row.get("seller_state")),
            "zip_code_prefix": _blank_to_none(row.get("seller_zip_code_prefix")),
        }

    merchants: list[Merchant] = []
    for index, source_id in enumerate(sorted(by_source_id), start=1):
        fields = by_source_id[source_id]
        merchants.append(
            Merchant(
                merchant_id=f"MER-{index:06d}",
                source_id=source_id,
                city=fields["city"],
                state=fields["state"],
                zip_code_prefix=fields["zip_code_prefix"],
            )
        )
    return MerchantImportResult(imported=len(merchants), skipped=skipped, merchants=merchants)


def write_merchants(merchants: list[Merchant], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(merchant) for merchant in merchants]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def import_olist_merchants(
    raw_path: Path | None = None,
    output_path: Path | None = None,
) -> MerchantImportResult:
    source = raw_path or DEFAULT_RAW_PATH
    destination = output_path or DEFAULT_OUTPUT_PATH
    result = read_olist_sellers(source)
    write_merchants(result.merchants, destination)
    return result
