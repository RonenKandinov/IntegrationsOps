# IntegrationOps — dynamic operational system model

This document defines a mathematical abstraction for a future decision layer. It does not describe an optimizer that exists in the repository.

The current system is an investigation and operations platform. Its working lifecycle is configure, validate, investigate, and name a dry-run action. The Investigation Engine turns an incident into an evidence-based diagnosis.

The goal of the model is to state the operational problem precisely enough that a later comparison can pick an established problem class and an existing algorithm from the literature. This document does not make that selection.

See [architecture.md](architecture.md) for what the code does today.

## Core problem

Integration-heavy environments contain many concurrent merchants, partners, configurations, incidents, onboarding work, validation work, and other operational work. Those objects depend on each other and compete for limited capacity.

Investigation asks why one integration failed. The larger operational question is: given the state right now, what should be done next? The system would investigate, decide, execute, observe, and decide again. Only the investigation half of that sentence is implemented.

## Dynamic system state

The system state at time `t` is:

**S_t = (V_t, E_t, R_t, Q_t, Ω_t)**

This is a dynamic system. Entities, dependencies, resources, task states, and external events may all change from `t` to `t+1`. A decision made for `S_t` is not assumed to remain the right decision after that change.

### V_t — entities and work items

**V_t = {v_1, ..., v_n}**

Examples in the model: merchants, lenders, integrations, configurations, incidents, investigations, validation tasks, onboarding tasks, engineering tasks.

The set can change: **V_t ≠ V_(t+1)** in general.

**In the repository today.** `Incident`, `Merchant`, `ApiRequest`, `ApiResponse`, and `LenderConfig` in `src/integrationops/models/`. There is no Task type, no Integration type, and no engineer or work-item entity. Do not treat the existing records as a complete `V_t`.

### E_t — dependencies

**G_t = (V_t, E_t)**. For `(u, v) ∈ E_t`, `v` depends on `u`.

Example of a dependency the model cares about. The snapshot stores merchant-to-lender edges. It does not store this longer chain:

```text
Lender configuration
        ↓
Integration validation
        ↓
Merchant go-live
```

The graph can change: **G_t ≠ G_(t+1)** in general.

**In the repository now.** An incident still stores `request_id` and `lender_id`. `operations/snapshot.py` also records edges for the concrete chain, including several merchants that depend on one lender configuration. That is not a general graph that changes itself over time. A full `G_t` that appears and disappears as operations change is still future work.

### R_t — resources

**R_t = {r_1, ..., r_m}**

Examples in the model: engineers, QA, integration specialists, operations staff, partner availability, API capacity.

A simplified capacity constraint, not enforced by the code:

**Σ_i req(i, j) x_i(t) ≤ Cap_j(t)**

**In the repository today.** Resources are not represented.

### Q_t — operational task states

The model proposes, for a task `i`:

**q_i(t) ∈ {Pending, Ready, InProgress, Blocked, Completed, Failed}**

**In the repository today.** Status fields exist, and they use a different vocabulary. `Diagnosis.status` is `ROOT_CAUSE_DETERMINED`, `EVIDENCE_GAP`, `INCONSISTENT_EVIDENCE`, or `NOT_DETERMINED`. Automation uses `READY`, `BLOCKED`, and `REVIEW`. These are investigation and dry-run outcomes, not the task-state set above. That set is not implemented.

### Ω_t — external events and new information

**ω_t ∈ Ω_t**

Examples in the model: a new merchant, a new incident, a lender becoming unavailable, an API behavior change, missing information arriving, an unexpected response.

**In the repository today.** An incident and the files under `data/production/evidence/` are information the engine can observe. There is no event stream and no transition that consumes `ω_t`.

## Constraints

**C_t** is the set of constraints at time `t`. The model includes dependency constraints, resource capacity, business and configuration rules, information that must be present before an action, and external partner availability.

**In the repository today.** The amount rule is `min_amount ≤ amount ≤ max_amount`, implemented by comparing a request to a lender configuration. The safety gate refuses to approve when validation issues exist. Missing evidence stops an investigation instead of guessing. Resource and dependency constraints are not implemented.

## Actions

**A(S_t)** is the set of actions the model might consider: investigate, fix a configuration, validate, onboard, assign a person, retry a request, escalate, run a safety check, resolve an incident.

**A_f(S_t) ⊆ A(S_t)** is the feasible subset. A chosen action satisfies **a_t ∈ A_f(S_t)**.

**In the repository today.** `Diagnosis.recommended_action` and `AutomationResult.action` (`APPROVE`, `BLOCK`, `HUMAN_REVIEW`, `CANDIDATE`) name a next step. They are candidate actions. They are not a feasible set computed from `S_t`, and they are not executed. `CANDIDATE` means the diagnosis is specific enough to hand to a person.

## State transition

**S_(t+1) = T(S_t, a_t, ω_t)**

`T` is the transition: current state, selected action, and new external information produce the next state. A plan computed at `t` is not automatically still right at `t+1`.

**In the repository today.** `T` is not implemented. Automation does not write store data. Execution of an approved action is future work.

## Objective

A candidate multi-objective expression is:

**J = w_1·Throughput − w_2·CompletionTime − w_3·BlockedWork − w_4·ResourceCost − w_5·Risk**

A future policy would be judged by:

**max_π J(π)**

subject to the system's dependencies, resource constraints, operational constraints, and state-transition dynamics.

In this setting the terms mean:

- **Throughput** — how much merchant and integration work is successfully progressed or completed.
- **CompletionTime** — time required to complete the relevant operational work.
- **BlockedWork** — work blocked by an unresolved dependency.
- **ResourceCost** — consumption of constrained operational resources.
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

If Merchant A, Merchant B, and Merchant C all depend on one lender configuration, a change to that configuration can unblock more than the merchant that raised the incident. `operations/snapshot.py` records those shared edges. It does not estimate throughput, time, blocked work, cost, or risk, and it does not pick the action that would maximize `J`.

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
Analyze resources
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

**In the repository now.** Observation and investigation exist. `operations/snapshot.py` records the entities, states, dependencies, incident event, and candidate action for one merchant–lender chain. Resources, action selection, execution, and re-evaluation of `S_(t+1)` do not exist. The snapshot is one moment. Entities, dependencies, resources, task states, and external events are allowed to differ at the next moment; the code does not yet apply that change.

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
Decision layer   ← future
 ↓
Execution        ← future
 ↓
New system state ← future
```

Investigation answers what happened, why, and which evidence supports that. The decision layer would answer which feasible action to take next, given the wider state. Those are different questions.

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

At the highest level, a future optimization problem can be written as **max_π J(π)**, subject to dependencies, resources, operational constraints, and the transition. That expression stays abstract. It is not a solver interface.

## What this document does not claim

- IntegrationOps is not presented as a new mathematical problem.
- A new algorithm is not required by this document.
- RCPSP, MDP, stochastic scheduling, and any other named class are not declared to be the correct model.
- No algorithm is selected or claimed to be optimal.
- The candidate objective is not final.
- The formulation is not empirically validated.
- No particular company is assumed to have exactly this optimization problem.

A company that later uses the system would be an instance of these generic terms: entity, task, dependency, resource, constraint, action, state, event, outcome. The core does not grow company-specific types for that.

## Next research step

Compare the formal problem with established literature, including dynamic resource-constrained project scheduling, multi-project scheduling, stochastic resource-constrained scheduling, dynamic resource allocation, Markov decision processes, approximate dynamic programming, rolling-horizon optimization, heuristic and metaheuristic scheduling, and robust or stochastic optimization.

For each candidate, the comparison still to be done is: which assumptions it makes, which assumptions this operational problem makes, which variables and constraints correspond, whether it allows changing state, uncertainty, concurrent work, shared resources, and changing dependencies, which algorithms already exist, and what would have to be adapted.

That comparison is research. It is not an implementation task, and it is not a reason to add a scheduler to this repository yet.
