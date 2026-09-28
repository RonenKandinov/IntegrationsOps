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
- `src/integrationops/operations/` — `SystemState`, feasible actions, in-memory `T`
- `src/integrationops/experiments/` — organization scenarios, `MethodInput`, snapshots, metrics
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
  Investigation Layer             Operational State Layer
  (implemented)                   (state, A_f, in-memory T)
          |                               |
      Incident                         State S_t
          ↓                               |
      Evidence                      Dependencies
          ↓                               |
      Diagnosis               Operational constraints
          ↓                               |
 Candidate Actions                  Constraints
          |                               |
          +---------------+---------------+
                          ↓
                    Action Selection   ← future
                          ↓
                  Production execute   ← future
                          ↓
                    New System State
                          ↓
                       Re-evaluate     ← future
```

The left side is the investigation engine. The right side is described in [INTEGRATIONOPS_SYSTEM_MODEL.md](INTEGRATIONOPS_SYSTEM_MODEL.md). `SystemState`, feasible actions, and in-memory `T` exist. Policy `π`, objective `J`, and production execution do not. No module selects an optimal action.

Today the investigation handoff is still a candidate. The operational layer can record that diagnosis on `S_t` and apply a feasible in-memory transition. It does not execute in production.

```text
Incident
 → one investigation path
 → evidence
 → Diagnosis
 → recommended action
```

`INVALID_AMOUNT` still loads the request, loads the lender configuration, compares the amount with the configured minimum and maximum, and returns a diagnosis. A future decision layer would consume that diagnosis. It would not replace the comparison.

## Implemented now

`src/integrationops/operations/` records the operational model on top of existing records:

```text
Merchant → Integration → Configuration / API / Payment
 → Incident → Investigation → Diagnosis → Candidate resolution
 → in-memory T → Validation → Merchant operational
```

It reuses `Merchant`, `LenderConfig`, `Incident`, `ApiRequest`, `ApiResponse`, `ValidationReport`, and `Diagnosis`, and adds `Integration`.

- **V_t / Q_t.** `SystemState` lists merchants, integrations, lender configuration, payment, incident, validation, and investigation work. `task_states` uses `{Pending, Ready, InProgress, Blocked, Completed, Failed}` for those operational work items. `Diagnosis.status` is unchanged.
- **E_t.** Dependencies are edges between those ids, including merchant → integration → lender/API/payment. Several merchants can depend on one shared lender configuration.
- **R_t.** Operational constraints: transaction limits, configuration presence, API availability, provider availability, payment. Not engineers or staffing.
- **Ω_t.** `OperationalEvent` is new information. `T` can apply it in memory. There is no production event bus.
- **A / A_f.** `all_actions` / `feasible_actions` name investigate, fix configuration, validate, onboard, retry, escalate, safety check, and resolve. They are not executed against the store.
- **T.** `transition(state, action, event)` is `S_(t+1) = T(S_t, a_t, ω_t)` in memory. Infeasible actions are rejected. The evidence store is not written.

`operations/snapshot.py` remains the smaller chain snapshot used to assemble those records.

`src/integrationops/experiments/` is the research/benchmark layer. It sits on the existing domain models and `ChainSnapshot`; it is not a second investigation engine.

```text
Existing IntegrationOps
        ↓
Research Layer
        ↓
Organization Generator
        ↓
Dynamic Scenarios (explicit topology)
        ↓
Experiment Harness  (solve(scenario) -> MethodResult)
        ↓
Method A / B / C
```

Generate the environment first. Then compare solution methods on the exact same scenario. Families: `independent`, `shared_bottleneck`, `cascading_failure`, `dynamic_arrival`, `shared_resource_conflict`, `mixed`. Ground truth is factual (dependencies, failures, event timing, capacities, constraints, task properties). It does not name an optimal action.

`generate-organization`, `generate-scenario`, and `run-experiment` are CLI entry points. The existing `generate-scenarios` command remains the narrow investigation benchmark from Olist merchants.

The existing `generators/scenario_generator.py` still builds investigation-evaluation cases from Olist merchants. It is separate from the organization experiment generator.

## Still future

Policy `π`, any scoring of `J`, an optimizer, RCPSP/MDP/RL/MILP, human resource allocation, production execution, and automatic re-evaluation after real-world execution. No problem class has been selected.

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
- A chain snapshot and `SystemState` record merchant–integration–lender–payment dependencies, operational constraints, feasible candidate actions, and in-memory `T`. They are not a general graph engine, a policy `π`, or an optimizer.
- `R_t` is operational/system constraints (limits, APIs, providers, configuration, availability). It is not staffing.
- No algorithm has been selected. RCPSP, MDP, and the other classes in the system-model document are literature to compare later, not an implementation commitment.
- The core stays generic. A particular company would be a later instance of the model, not a set of core types.
