# IntegrationOps — dynamic operational system model

This document defines a mathematical abstraction for a future decision layer. It does not describe an optimizer that exists in the repository.

The current system is an investigation and operations platform. Its working lifecycle is configure, validate, investigate, and name a dry-run action. The Investigation Engine turns an incident into an evidence-based diagnosis.

The operational model now also represents system state, merchant/integration/payment dependencies, operational constraints, candidate resolution actions, and in-memory state transitions. It still does not choose an optimal action, score an objective, allocate people, or execute in production.

The goal of the model is to state the operational problem precisely enough that a later comparison can pick an established problem class and an existing algorithm from the literature. This document does not make that selection.

See [architecture.md](architecture.md) for what the code does today.

## Core problem

Integration-heavy environments contain many concurrent merchants, partners, configurations, incidents, onboarding work, validation work, and other operational work. Those objects depend on each other and are constrained by shared operational limits such as lender configuration, API availability, provider availability, and transaction limits.

Investigation asks why one integration failed. The larger operational question is: given the state right now, what should be done next? The system would investigate, decide, execute, observe, and decide again. Investigation is implemented. State representation, feasible candidate actions, and in-memory `T` are implemented. Action selection, production execution, and re-optimization are not.

## Dynamic system state

The system state at time `t` is:

**S_t = (V_t, E_t, R_t, Q_t, Ω_t)**

This is a dynamic system. Entities, dependencies, operational constraints, task states, and external events may all change from `t` to `t+1`. A decision made for `S_t` is not assumed to remain the right decision after that change.

**In the repository today.** `operations.state.SystemState` is this tuple, assembled from existing records plus an `Integration` derived from merchant and lender. `operations/snapshot.py` remains one observation of the merchant–integration–lender chain. Neither module writes the evidence store.

### V_t — entities and work items

**V_t = {v_1, ..., v_n}**

Examples in the model: organizations, merchants, lenders, integrations, configurations, payments, APIs, incidents, investigations, validation tasks, onboarding tasks.

The set can change: **V_t ≠ V_(t+1)** in general.

**In the repository today.** `Incident`, `Merchant`, `Integration`, `Organization`, `ApiRequest`, `ApiResponse`, and `LenderConfig` in `src/integrationops/models/`. `SystemState.entities()` also names API, investigation, validation, and onboarding work items. There is still no engineer or staffing entity. `experiments/` generates connected organization worlds from these types. Do not treat the JSON store documents as a complete `V_t` by themselves; the operational state is assembled from those records.

### E_t — dependencies

**G_t = (V_t, E_t)**. For `(u, v) ∈ E_t`, `v` depends on `u`.

The chain the model cares about:

```text
Merchant
    ↓
Integration
    ↓
Configuration / API / Payment
    ↓
Incident → Investigation → Diagnosis
    ↓
Candidate resolution → state transition → validation
    ↓
Merchant operational
```

Several merchants can share one lender configuration:

```text
Lender configuration
        ↓
Integration validation
        ↓
Merchant go-live
```

The graph can change: **G_t ≠ G_(t+1)** in general.

**In the repository now.** An incident still stores `request_id` and `lender_id`. `operations/snapshot.py` and `SystemState.dependencies` record edges for the concrete chain, including merchant → integration → lender/API/payment, and several merchants that depend on one lender configuration. `SystemState.graph()` is `G_t = (V_t, E_t)`. A general graph engine that invents arbitrary relation types at runtime is still future work.

### R_t — operational constraints

**R_t = {r_1, ..., r_m}**

`R_t` does **not** represent engineers, staffing, or human resource allocation.

It represents operational and system constraints around merchants, payments, lenders, APIs, providers, transaction limits, configurations, and availability.

Examples: lender `min_amount` / `max_amount`, currency, configuration presence, provider availability, API availability, payment presence.

A simplified capacity constraint, not used as an optimizer constraint:

**Σ_i req(i, j) x_i(t) ≤ Cap_j(t)**

If that expression is used later, `Cap_j` is operational capacity (API, provider, transaction limits), not headcount. The code does not solve it.

**In the repository today.** `SystemState.resources` holds `OperationalConstraint` records (`transaction_limit`, `api_availability`, `provider_availability`, `configuration`, `payment`). Lender min/max remain the amount rule `min_amount ≤ amount ≤ max_amount`. There is no person, team, or staffing object in `R_t`.

### Q_t — operational task states

The model proposes, for a work item `i`:

**q_i(t) ∈ {Pending, Ready, InProgress, Blocked, Completed, Failed}**

**In the repository today.** `SystemState.task_states` uses that set for operational work items (merchant, integration, incident, investigation work, validation, onboarding). This is distinct from investigation outcomes. `Diagnosis.status` remains `ROOT_CAUSE_DETERMINED`, `EVIDENCE_GAP`, `INCONSISTENT_EVIDENCE`, or `NOT_DETERMINED`. Automation still uses `READY`, `BLOCKED`, and `REVIEW` for dry-run results. Those vocabularies are not renamed.

### Ω_t — external events and new information

**ω_t ∈ Ω_t**

Examples in the model: a new merchant, a new incident, a lender becoming unavailable, an API behavior change, missing information arriving, an unexpected response.

**In the repository today.** An incident and the files under `data/production/evidence/` are information the engine can observe. `OperationalEvent` is `ω_t`. `T` can consume an event (for example lender unavailability) without writing the store. There is no production event bus.

## Constraints

**C_t** is the set of constraints at time `t`. The model includes dependency constraints, operational capacity, business and configuration rules, information that must be present before an action, and external partner availability.

**In the repository today.** The amount rule is `min_amount ≤ amount ≤ max_amount`, implemented by comparing a request to a lender configuration. The safety gate refuses to approve when validation issues exist. Missing evidence stops an investigation instead of guessing. `is_feasible` applies the operational subset: provider/API availability, configuration presence, well-formed limit proposals, and amount-within-limits before resolve. Human-resource constraints are not implemented because `R_t` is not staffing.

## Actions

**A(S_t)** is the set of actions the model might consider: investigate, fix a configuration, validate, onboard, retry a request, escalate, run a safety check, resolve an incident.

Assigning a person is not part of the implemented action set. Staffing is not `R_t`, and this layer does not allocate people.

**A_f(S_t) ⊆ A(S_t)** is the feasible subset. A chosen action satisfies **a_t ∈ A_f(S_t)**.

**In the repository today.** `operations.actions.all_actions` is `A(S_t)`. `feasible_actions` / `is_feasible` is `A_f(S_t)`. `Diagnosis.recommended_action` and `AutomationResult.action` (`APPROVE`, `BLOCK`, `HUMAN_REVIEW`, `CANDIDATE`) remain candidate names from investigation and dry-run automation. They are not a policy `π`, and they are not executed against production data. `CANDIDATE` means the diagnosis is specific enough to hand to a person.

## State transition

**S_(t+1) = T(S_t, a_t, ω_t)**

`T` is the transition: current state, selected action, and new external information produce the next state. A plan computed at `t` is not automatically still right at `t+1`.

**In the repository today.** `operations.transition.transition` is `T` in memory. It requires `a_t ∈ A_f(S_t)` when an action is supplied. It does not write store data. Automatic production execution of an approved action is future work.

## Objective

A candidate multi-objective expression is:

**J = w_1·Throughput − w_2·CompletionTime − w_3·BlockedWork − w_4·ResourceCost − w_5·Risk**

A future policy would be judged by:

**max_π J(π)**

subject to the system's dependencies, operational constraints, and state-transition dynamics.

In this setting the terms mean:

- **Throughput** — how much merchant and integration work is successfully progressed or completed.
- **CompletionTime** — time required to complete the relevant operational work.
- **BlockedWork** — work blocked by an unresolved dependency.
- **ResourceCost** — consumption of constrained operational resources (API, provider, limits, configuration), not payroll.
- **Risk** — operational, safety, or downstream risk of the actions under consideration.

The weights are not assigned. `J` is not computed anywhere in the code.

Why the objective is about the system, not one incident:

```text
Merchant A
Merchant B
Merchant C
      ↓
Shared lender configuration
```

If Merchant A, Merchant B, and Merchant C all depend on one lender configuration, a change to that configuration can unblock more than the merchant that raised the incident. `operations/snapshot.py` and `SystemState` record those shared edges. They do not estimate throughput, time, blocked work, cost, or risk, and they do not pick the action that would maximize `J`.

## Decision policy

The model is not a single permanent schedule. A policy maps state to an action:

**π(S_t) → a_t**

and the system repeats:

**S_t → a_t → S_(t+1) → a_(t+1) → ...**

```text
Observe
 ↓
Represent current state
 ↓
Analyze dependencies
 ↓
Analyze operational constraints
 ↓
Generate candidate actions
 ↓
Apply constraints
 ↓
Select action
 ↓
Execute
 ↓
Observe the outcome and any new information
 ↓
Construct the new state
 ↓
Re-evaluate
```

**In the repository today.** Observation, investigation, state representation, dependency recording, operational-constraint recording, candidate-action generation, feasible-set filtering, and in-memory `S_(t+1)` exist. `experiments/` generates reproducible organizations and topology-specific scenarios, hands every method the same `Scenario` / `MethodInput`, and records factual ground truth plus comparable metrics. Policy `π`, objective `J`, production execution, and automatic re-optimization do not. A caller may apply one feasible `a_t` through `T`. That is not action selection.

## Investigation engine inside the model

The Investigation Engine stays a core component. It is not replaced by optimization.

```text
Incident
 ↓
Investigation path
 ↓
Evidence
 ↓
Diagnosis
 ↓
Candidate action
 ↓
In-memory state transition   ← implemented; not production execution
 ↓
Decision layer               ← future (π, J, optimizer)
 ↓
Production execution         ← future
 ↓
New observed system state
```

Investigation answers what happened, why, and which evidence supports that. The operational layer records that diagnosis on `S_t` (`attach_investigation`) and can apply a feasible candidate resolution in memory. The future decision layer would answer which feasible action to take next, given the wider state. Those are different questions.

`INVALID_AMOUNT` still does this, and only this:

1. Load the API request.
2. Load the lender configuration, or stop if it is missing.
3. Compare the requested amount with the configured minimum and maximum.
4. Return evidence and a diagnosis.

If the amount is inside the limits but the response says `INVALID_AMOUNT`, the diagnosis is an inconsistency, not a manufactured cause. If the lender configuration is missing, the diagnosis is an evidence gap.

## Consolidated model

**S_t = (V_t, E_t, R_t, Q_t, Ω_t)**

**G_t = (V_t, E_t)**

**A_f(S_t) ⊆ A(S_t)**

**a_t ∈ A_f(S_t)**

**S_(t+1) = T(S_t, a_t, ω_t)**

**π(S_t) → a_t**

At the highest level, a future optimization problem can be written as **max_π J(π)**, subject to dependencies, operational constraints, and the transition. That expression stays abstract. It is not a solver interface.

## What this document does not claim

- IntegrationOps is not presented as a new mathematical problem.
- A new algorithm is not required by this document.
- RCPSP, MDP, stochastic scheduling, and any other named class are not declared to be the correct model.
- No algorithm is selected or claimed to be optimal.
- The candidate objective is not final.
- The formulation is not empirically validated.
- No particular company is assumed to have exactly this optimization problem.
- `R_t` is not a workforce model.

A company that later uses the system would be an instance of these generic terms: entity, task, dependency, operational constraint, action, state, event, outcome. The core does not grow company-specific types for that, and it does not grow engineer-allocation types for `R_t`.

## Next research step

Compare the formal problem with established literature, including dynamic resource-constrained project scheduling, multi-project scheduling, stochastic resource-constrained scheduling, dynamic resource allocation, Markov decision processes, approximate dynamic programming, rolling-horizon optimization, heuristic and metaheuristic scheduling, and robust or stochastic optimization.

For each candidate, the comparison still to be done is: which assumptions it makes, which assumptions this operational problem makes, which variables and constraints correspond, whether it allows changing state, uncertainty, concurrent work, shared operational constraints, and changing dependencies, which algorithms already exist, and what would have to be adapted.

That comparison is research. It is not an implementation task, and it is not a reason to add a scheduler, optimizer, or human-resource allocator to this repository yet.
