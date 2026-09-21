# IntegrationOps

Shorten the path from “we have an integration failure” to “we know what probably caused it, why, and what should be checked or fixed next.”

This repository currently has package layout, dataclasses, seeded JSON evidence, a JSON store, investigation tools, and the INVALID_AMOUNT investigation path. Engine and CLI are not implemented yet.

## Approved architecture

```
CLI → Engine → Investigation Path → Tools → Store → JSON Evidence
```

MVP path: **INVALID_AMOUNT** only.

## Setup

Python 3.12+.

```bash
cd IntegrationOps
python -m pip install -e .
```

## Current layout

- `data/` — local JSON evidence (`incidents`, `requests`, `responses`, `lenders`)
- `src/integrationops/models/` — dataclasses
- `src/integrationops/store/` — JSON lookups that return dataclasses
- `src/integrationops/tools/` — investigation actions (`get_request`, `compare_amount_to_limits`, …)
- `src/integrationops/investigations/` — INVALID_AMOUNT path (`investigate_invalid_amount`)
- `src/integrationops/engine/` — package placeholder

## Out of scope (this MVP)

FastAPI, MongoDB, frontend, LLM, TIMEOUT / AUTHENTICATION_ERROR paths, cloud, external APIs.
