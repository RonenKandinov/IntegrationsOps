# IntegrationOps

Shorten the path from “we have an integration failure” to “we know what probably caused it, why, and what should be checked or fixed next.”

This is a deterministic investigation engine. The failure type selects an investigation path. The path selects tools. The diagnosis comes from comparing evidence.

## Architecture

```
CLI → Engine → Investigation Path → Tools → Store facade → JsonStore or MongoStore
```

The engine does not run every tool. It loads the incident, reads `failure_code`, and dispatches to one path. Engine and tools do not know whether evidence is JSON or MongoDB.

## Setup

Python 3.12+.

```bash
cd IntegrationOps
python -m pip install -e ".[dev]"
```

Default store is JSON under `data/`. To use MongoDB later:

```bash
python -m pip install -e ".[mongo]"
set INTEGRATIONOPS_STORE=mongo
set INTEGRATIONOPS_MONGO_URI=mongodb://localhost:27017
```

## Merchant data (Olist)

The full unmodified Kaggle archive lives under `data/raw/` (customers, geolocation, orders, payments, reviews, products, sellers, category translation).

**Today only sellers are imported.** Place/keep:

```text
data/raw/olist_sellers_dataset.csv
```

Columns used: `seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state`. Extra columns and the other Olist tables are ignored by the importer. This dataset has no merchant name, category, or currency fields.

Import and normalize:

```bash
python -m integrationops import-merchants
```

Normalized merchants are written to `data/generated/merchants.json` with stable ids (`MER-000001`, …). Raw files stay in `data/raw/` so they are never mixed with application-generated data or with Phase 1 investigation JSON under `data/`.

The investigation engine does not read Kaggle files. MongoDB is planned later behind the existing store facade; it is not used for this import.

## Generate investigation scenarios

```bash
python -m integrationops generate-scenarios --seed 123 --count 100
python -m integrationops evaluate-scenarios
python -m integrationops investigate INC-000001
```

`--seed` is a local generator RNG (merchant shuffle and amount variation). `--count` larger than the merchant list is capped with a warning. Evaluation compares engine `root_cause` to `data/generated/ground_truth.json` and does not feed answers into the engine.

Amounts stay within each failure class; city/state/source_id only vary the amount and appear in the API response message. Currency remains USD against `lender_456`.

## Phase 2 — Validation vs investigation

Investigation asks why a failure happened (failure-specific path + evidence → diagnosis).

Validation asks whether a request or configuration is valid. It does not invent a root cause.

Rules: amount range (`amount_below_min`, `amount_above_max`); required Store references (`missing_request`, `missing_lender`, `missing_incident`); INVALID_AMOUNT vs in-range amount (`inconsistent_invalid_amount`).

```bash
python -m integrationops validate REQ-000001
python -m integrationops validate INC-000301
```

Example:

```text
Target: REQ-000001
Status: INVALID
Rule: amount_range
Code: amount_above_max
Message: Requested amount is above the lender maximum.
Field: amount
Evidence:
- requested_amount = 80000
- minimum_allowed = 10000
- maximum_allowed = 50000
```

## Investigate an incident

```bash
python -m integrationops investigate INC-001
python -m integrationops investigate INC-002
python -m integrationops investigate INC-003
```

Seeded cases:

- `INC-001` `INVALID_AMOUNT` — amount `5000` vs minimum `10000`
- `INC-002` `TIMEOUT` — lender API did not respond in time
- `INC-003` `AUTHENTICATION_ERROR` — merchant is not authenticated with the lender

## Tests

```bash
python -m pytest
```

## Layout

- `data/` — Phase 1 investigation JSON (`incidents`, `requests`, `responses`, `lenders`)
- `data/raw/` — unmodified Olist CSV
- `data/generated/` — `merchants.json` plus generated requests, responses, incidents, lenders, ground truth
- `src/integrationops/generators/` — synthetic scenario generator
- `src/integrationops/importers/` — Olist merchant importer
- `src/integrationops/models/` — dataclasses
- `src/integrationops/store/` — facade, `JsonStore`, `MongoStore`
- `src/integrationops/tools/` — investigation actions
- `src/integrationops/investigations/` — INVALID_AMOUNT, TIMEOUT, AUTHENTICATION_ERROR
- `src/integrationops/engine/` — `failure_code` dispatcher
- `src/integrationops/validation/` — amount, reference, and consistency rules
- `src/integrationops/cli.py` — command line

## Later (not in this phase)

FastAPI, UI, LLM, automation, cloud.
