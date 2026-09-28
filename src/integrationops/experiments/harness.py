"""Run methods against the exact same scenario. No algorithm is selected."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Protocol

from integrationops.experiments.metrics import ExperimentMetrics, TraceStep, compute_metrics
from integrationops.experiments.scenario import NullDecisionMethod, Scenario, replay_scenario
from integrationops.experiments.snapshots import freeze_state


@dataclass
class MethodResult:
    method_name: str
    scenario_id: str
    topology: str
    seed: int
    trace: list[TraceStep] = field(default_factory=list)
    metrics: ExperimentMetrics | None = None
    runtime_seconds: float = 0.0
    replanning_count: int = 0
    notes: str = ""


class ResearchMethod(Protocol):
    """Common solve() interface. Implement later; do not encode a winner here."""

    name: str

    def solve(self, scenario: Scenario) -> MethodResult:
        """Consume a copy of the scenario. Must not mutate the caller's original."""


@dataclass
class NullResearchMethod:
    """Events-only baseline. Not an optimizer."""

    name: str = "null"

    def solve(self, scenario: Scenario) -> MethodResult:
        started = time.perf_counter()
        local = copy.deepcopy(scenario)
        trace = replay_scenario(local, NullDecisionMethod())
        final = trace[-1].state if trace else local.initial_state
        metrics = compute_metrics(
            local.initial_state,
            trace,
            final=final,
            work_items=local.work_items,
            capacities=local.capacities,
        )
        metrics.runtime_seconds = time.perf_counter() - started
        return MethodResult(
            method_name=self.name,
            scenario_id=local.scenario_id,
            topology=local.topology,
            seed=local.seed,
            trace=trace,
            metrics=metrics,
            runtime_seconds=metrics.runtime_seconds,
            replanning_count=0,
            notes="Events replayed; no action selection.",
        )


def run_experiment(
    scenario: Scenario,
    methods: list[ResearchMethod] | None = None,
) -> list[MethodResult]:
    """Give each method a deep copy of the same scenario."""
    methods = methods or [NullResearchMethod()]
    baseline = freeze_state(scenario.initial_state)
    results: list[MethodResult] = []
    for method in methods:
        clone = copy.deepcopy(scenario)
        result = method.solve(clone)
        results.append(result)
    if freeze_state(scenario.initial_state) != baseline:
        raise RuntimeError("Harness mutated the original scenario")
    return results
