# IntegrationOps architecture

This page says what the repository does today, and what the dynamic operational model is aiming at. The model is not a second runtime.

## What exists today

IntegrationOps answers three questions with deterministic rules:

- **Investigation** — why did this incident fail?
- **Validation** — do the records and the configuration agree?
- **Automation** — what operational action is safe to name? Every automation result is a dry run. Nothing is applied.

Evaluation asks a fourth question after the fact: did the investigation match ground truth? The engine does not read ground truth.

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

The engine loads one incident, reads `failure_code`, and runs one path. That path loads only the evidence it needs and compares it. A missing record or a contradiction becomes an evidence gap or an inconsistency. The path does not invent a root cause from the failure code alone.

Modules:

- `src/integrationops/cli.py` — commands
- `src/integrationops/engine/` — `failure_code` dispatcher
- `src/integrationops/investigations/` — `INVALID_AMOUNT`, `TIMEOUT`, `AUTHENTICATION_ERROR`
- `src/integrationops/tools/` — fetch records and compare an amount to limits
- `src/integrationops/validation/` — amount, reference, and consistency checks
- `src/integrationops/automation/` — dry-run workflows and `safety_decision`
- `src/integrationops/store/` — JSON by default, MongoDB behind the same lookups
- `src/integrationops/importers/`, `generators/`, `evaluation/` — offline data and scoring

`Diagnosis` is the investigation result: root cause, evidence, explanation, recommended action, trace, and a status (`ROOT_CAUSE_DETERMINED`, `EVIDENCE_GAP`, `INCONSISTENT_EVIDENCE`, `NOT_DETERMINED`).

`ValidationReport` is a list of issues. It is not a diagnosis.

`AutomationResult` names `APPROVE`, `BLOCK`, `HUMAN_REVIEW`, or `CANDIDATE`. `safety_decision` blocks approval when issues exist. `dry_run` stays true. This is a constraint gate, not an optimizer, and it does not write a new system state.

## Two layers

```text
                    IntegrationOps
                          |
          +---------------+---------------+
          |                               |
          ↓                               ↓
  Investigation Layer             Operational Decision Layer
  (implemented)                   (not implemented)
          |                               |
      Incident                         State S_t
          ↓                               |
      Evidence                      Dependencies
          ↓                               |
      Diagnosis                      Resources
          ↓                               |
 Candidate Actions                  Constraints
          |                               |
          +---------------+---------------+
                          ↓
                    Action Selection
                          ↓
                       Execute
                          ↓
                    New System State
                          ↓
                       Re-evaluate
```

The left side is the investigation engine. The right side is described in [INTEGRATIONOPS_SYSTEM_MODEL.md](INTEGRATIONOPS_SYSTEM_MODEL.md). Action selection, execution, and `S_(t+1)` are not implemented. No module selects an optimal action.

Today the handoff stops at a candidate:

```text
Incident
 → one investigation path
 → evidence
 → Diagnosis
 → recommended action
```

`INVALID_AMOUNT` still loads the request, loads the lender configuration, compares the amount with the configured minimum and maximum, and returns a diagnosis. A future decision layer would consume that diagnosis. It would not replace the comparison.

## Implemented now

`src/integrationops/operations/snapshot.py` records one moment of the concrete chain:

```text
Merchant → Lender configuration → Validation → Incident → Investigation → Recommended action
```

It reuses `Merchant`, `LenderConfig`, `Incident`, `ValidationReport`, and `Diagnosis`. It does not introduce a generic entity, task, resource, or optimizer type.

- **V_t / Q_t.** The snapshot lists the merchants, the lender configuration, the incident, the validation result, and the diagnosis status already produced by the engine.
- **E_t.** Dependencies are edges between those ids. Several merchants can depend on one shared lender configuration. That is the structural fact a later objective would use: one configuration change can sit in front of more than one merchant. The snapshot does not score that impact.
- **Ω_t.** The arriving incident is recorded as an evidence fact. There is no event bus.
- **Candidate action.** The only action stored is `Diagnosis.recommended_action`. It is not chosen among alternatives, and it is not executed.

A second call with different records is a later observation. The module does not compute the transition between them.

## Still future

Resources and capacity, the task-state set `{Pending, Ready, InProgress, Blocked, Completed, Failed}`, feasible-action filtering, the policy `π`, execution, `S_(t+1)`, and any scoring of `J`. No problem class has been selected.

## Target loop

This loop is the direction of the model. It is not what a CLI command does today.

```text
S_t
 → decision
 → action
 → new information
 → S_(t+1)
 → re-evaluate
```

A plan made at time `t` is not assumed to still be the right plan after new evidence arrives.

## Boundaries

- Investigation stays evidence-based and deterministic.
- Validation checks records. It does not choose a schedule.
- Automation names a safe dry-run action. It does not execute one.
- A chain snapshot records merchant–lender dependencies and the diagnosis action. It is not a general graph engine, a transition function, or a policy `π`.
- Resources and capacity are not in the repository.
- No algorithm has been selected. RCPSP, MDP, and the other classes in the system-model document are literature to compare later, not an implementation commitment.
- The core stays generic. A particular company would be a later instance of the model, not a set of core types.
