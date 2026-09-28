# IntegrationOps

Shorten the path from “we have an integration failure” to “we know what probably caused it, why, and what should be checked or fixed next.”

Rules are deterministic. A failure code selects one investigation path. The path compares evidence. Nothing here writes a fix.

## Architecture map

This grouping is a way to read the project. The folders on disk are not arranged this way.

```text
IntegrationOps
│
├── CLI
│
├── Investigation
│   ├── Engine
│   ├── Investigation Paths
│   └── Tools
│
├── Validation
│
├── Automation
│   ├── Validation Workflow
│   ├── Batch
│   ├── Onboarding
│   ├── Configuration Change
│   └── Resolution
│
├── Persistence
│   └── Store
│
├── Data
│   ├── Seed Data
│   └── Generated Data
│
└── Offline / Evaluation
    ├── Importers
    ├── Generators
    └── Evaluation
```

Three runtime questions:

- **Investigation** — Why did it fail?
- **Validation** — Are the records and configuration consistent?
- **Automation** — What operational action is safe? Every automation result is a dry run.

**Evaluation** asks a fourth question after the fact: was the investigation correct? It compares the engine’s root cause with `data/generated/ground_truth.json`. The engine never reads that file.

A later decision layer would observe a wider operational state, choose a feasible action, and re-evaluate when new information arrives. What exists now is a snapshot of the merchant → lender → validation → incident → diagnosis chain, including several merchants that share one lender configuration. It records dependencies and the diagnosis action. It does not score them or execute them. No optimizer or scheduling algorithm has been selected. See [docs/architecture.md](docs/architecture.md) and [docs/INTEGRATIONOPS_SYSTEM_MODEL.md](docs/INTEGRATIONOPS_SYSTEM_MODEL.md).

Runtime flow:

```text
CLI
 ↓
Investigation / Validation / Automation
 ↓
Tools / Store
 ↓
JSON
 ↓
Result
```

The engine does not run every tool. It loads the incident, reads `failure_code`, and dispatches to one path. Engine and tools do not know whether evidence is JSON or MongoDB. The default store is JSON.

### Three result types

- **Diagnosis** — one investigation path’s answer: root cause, why, what to check next, evidence, and a trace.
- **ValidationReport** — whether a request or incident matches the records. Issues such as `amount_above_max` or `missing_lender`. No root cause.
- **AutomationResult** — the safe action: `APPROVE`, `BLOCK`, `HUMAN_REVIEW`, or `CANDIDATE`. `CANDIDATE` means the diagnosis is specific enough to hand to a person. It is not an approval, and it does not change data.

### Follow a command

`python -m integrationops investigate INC-000001`

```text
CLI (cli.py)
 → engine.investigate
 → investigations/invalid_amount.py
 → tools
 → store
 → data/generated/
 → Diagnosis
 → CLI output
```

`INC-000001` is generated `INVALID_AMOUNT` evidence (request `REQ-000001`, amount above the lender maximum).

`python -m integrationops automate-resolution INC-000001`

```text
CLI
 → automation/resolution.py
 → investigate  and  validate_incident
 → automation/safety.py
 → AutomationResult (CANDIDATE, exit 1)
```

Resolution calls the existing investigation and validation. It does not reimplement them. Exit code 0 is only for status `READY`.

### Production-like events

`data/production/evidence/` holds messy cases. The incident has a failure code and ids only. Amounts, limits, and error codes are on the request, lender, and response. Expected outcomes live only in `data/production/ground_truth.json`, which the investigation does not read.

```bash
python -m integrationops investigate-event EVENT-001
python -m integrationops evaluate-events
```

`investigate-event` prints a status: `ROOT_CAUSE_DETERMINED`, `EVIDENCE_GAP`, `INCONSISTENT_EVIDENCE`, or `NOT_DETERMINED`. A missing lender or response is a gap. A response that disagrees with the limits or names another lender is an inconsistency. The engine does not invent a cause from the failure code alone.

## Where the files actually are

```text
IntegrationOps/
│
├── README.md
├── pyproject.toml
├── .gitignore
│
├── data/
│
├── src/
│   └── integrationops/
│       ├── models/
│       ├── store/
│       ├── tools/
│       ├── engine/
│       ├── investigations/
│       ├── validation/
│       ├── automation/
│       ├── generators/
│       ├── importers/
│       ├── evaluation/
│       └── cli.py
│
└── tests/
```

- `data/` — seed JSON: `incidents`, `requests`, `responses`, `lenders` (`INC-001`, `INC-002`, `INC-003`)
- `data/generated/` — `merchants.json` plus generated requests, responses, incidents, lenders, and ground truth
- `data/raw/` — unmodified Olist CSV

Merchants are not Store records. Onboarding and the generator read `data/generated/merchants.json` directly.

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

## Validate

Validation does not invent a root cause.

Rules: amount range (`amount_below_min`, `amount_above_max`); required Store references (`missing_request`, `missing_lender`, `missing_incident`); `INVALID_AMOUNT` labeled on an in-range amount (`inconsistent_invalid_amount`).

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

## Automate (dry-run)

Approve only when validation has no issues. None of these commands write Store data.

```bash
python -m integrationops automate REQ-000001
python -m integrationops automate REQ-000002
```

`REQ-000001` is above max → BLOCKED. `REQ-000002` is in range → READY.

```text
Target: REQ-000001
Automation: Configuration Validation
Status: BLOCKED
Action: BLOCK
Dry run: True

Checks:
- required_references: PASS
- amount_range: FAIL

Issues:
- amount_above_max
```

Batch runs that same request workflow once per id:

```bash
python -m integrationops automate-batch REQ-000001 REQ-000002
```

Merchant onboarding checks `merchant_id` and `source_id`. City, state, and zip are optional.

```bash
python -m integrationops automate-onboarding MER-000001
```

Configuration change evaluates a proposed lender min, max, or currency in memory. Approve only when the proposal is valid, currency is unchanged, and every supplied request for that lender still passes the existing amount rule.

```bash
python -m integrationops automate-config lender_456 --max-amount 100000 --request REQ-000002
```

Resolution hands a determinate `INVALID_AMOUNT` diagnosis back as `CANDIDATE`. Timeout, authentication, and undetermined cases need human review.

```bash
python -m integrationops automate-resolution INC-001
```

## Merchant data (Olist)

The full unmodified Kaggle archive lives under `data/raw/` (customers, geolocation, orders, payments, reviews, products, sellers, category translation).

**Today only sellers are imported.** Place/keep:

```text
data/raw/olist_sellers_dataset.csv
```

Columns used: `seller_id`, `seller_zip_code_prefix`, `seller_city`, `seller_state`. Extra columns and the other Olist tables are ignored by the importer. This dataset has no merchant name, category, or currency fields.

```bash
python -m integrationops import-merchants
```

Normalized merchants are written to `data/generated/merchants.json` with stable ids (`MER-000001`, …). Raw files stay in `data/raw/`.

## Generate and score scenarios

```bash
python -m integrationops generate-scenarios --seed 123 --count 100
python -m integrationops evaluate-scenarios
python -m integrationops investigate INC-000001
```

`--seed` is a local generator RNG (merchant shuffle and amount variation). `--count` larger than the merchant list is capped with a warning. Amounts stay within each failure class; city, state, and `source_id` only vary the amount and appear in the API response message. Currency remains USD against `lender_456`.

## Tests

```bash
python -m pytest
```

## Later

FastAPI, UI, LLM, cloud.
