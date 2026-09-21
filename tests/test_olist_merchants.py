from pathlib import Path

import pytest

from integrationops.importers.olist_merchants import (
    MerchantImportError,
    import_olist_merchants,
    read_olist_sellers,
)

HEADER = "seller_id,seller_zip_code_prefix,seller_city,seller_state"


def _write_csv(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def test_import_valid_merchants_and_stable_ids(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path / "sellers.csv",
        f"{HEADER}\n"
        "bbb,22222,rio de janeiro,RJ\n"
        "aaa,11111,sao paulo,SP\n",
    )
    result = read_olist_sellers(csv_path)
    assert result.imported == 2
    assert result.skipped == 0
    assert result.merchants[0].merchant_id == "MER-000001"
    assert result.merchants[0].source_id == "aaa"
    assert result.merchants[1].merchant_id == "MER-000002"
    assert result.merchants[1].source_id == "bbb"
    assert result.merchants[0].city == "sao paulo"
    assert result.merchants[0].state == "SP"
    assert result.merchants[0].zip_code_prefix == "11111"

    again = read_olist_sellers(csv_path)
    assert [m.merchant_id for m in again.merchants] == ["MER-000001", "MER-000002"]


def test_missing_optional_fields(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path / "sellers.csv",
        f"{HEADER}\n"
        "seller-1,,,\n",
    )
    merchant = read_olist_sellers(csv_path).merchants[0]
    assert merchant.source_id == "seller-1"
    assert merchant.city is None
    assert merchant.state is None
    assert merchant.zip_code_prefix is None


def test_irrelevant_columns_ignored(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path / "sellers.csv",
        "seller_id,seller_city,seller_state,seller_zip_code_prefix,noise,extra\n"
        "seller-1,campinas,SP,13000,ignore-me,also-ignore\n",
    )
    result = read_olist_sellers(csv_path)
    assert result.imported == 1
    merchant = result.merchants[0]
    assert merchant.city == "campinas"
    assert not hasattr(merchant, "noise")


def test_missing_seller_id_skipped(tmp_path: Path):
    csv_path = _write_csv(
        tmp_path / "sellers.csv",
        f"{HEADER}\n"
        ",13000,campinas,SP\n"
        "seller-1,13000,campinas,SP\n",
    )
    result = read_olist_sellers(csv_path)
    assert result.imported == 1
    assert result.skipped == 1
    assert result.merchants[0].source_id == "seller-1"


def test_empty_dataset(tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sellers.csv", f"{HEADER}\n")
    result = read_olist_sellers(csv_path)
    assert result.imported == 0
    assert result.skipped == 0
    assert result.merchants == []


def test_malformed_missing_header(tmp_path: Path):
    csv_path = _write_csv(tmp_path / "sellers.csv", "not_a_sellers_table\n1,2,3\n")
    with pytest.raises(MerchantImportError):
        read_olist_sellers(csv_path)


def test_write_generated_json(tmp_path: Path):
    raw = _write_csv(
        tmp_path / "olist_sellers_dataset.csv",
        f"{HEADER}\n"
        "seller-9,01000,sao paulo,SP\n",
    )
    output = tmp_path / "generated" / "merchants.json"
    result = import_olist_merchants(raw_path=raw, output_path=output)
    assert result.imported == 1
    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert "MER-000001" in text
    assert "seller-9" in text
