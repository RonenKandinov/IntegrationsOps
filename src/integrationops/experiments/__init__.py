"""Experiment harness. Compare future methods against the same scenarios later.

This package does not select RCPSP, MDP, or any other algorithm. It only
generates worlds, exposes MethodInput / solve(), records snapshots, and
computes basic operational metrics.
"""

from integrationops.experiments.harness import (
    MethodResult,
    NullResearchMethod,
    ResearchMethod,
    run_experiment,
)
from integrationops.experiments.metrics import (
    ExperimentMetrics,
    TraceStep,
    compute_metrics,
)
from integrationops.experiments.scenario import (
    DecisionMethod,
    MethodInput,
    NullDecisionMethod,
    Scenario,
    generate_scenario,
    replay_scenario,
)
from integrationops.experiments.snapshots import dump_scenario, freeze_state
from integrationops.generators.organization import TOPOLOGIES, generate_organization

__all__ = [
    "DecisionMethod",
    "ExperimentMetrics",
    "MethodInput",
    "MethodResult",
    "NullDecisionMethod",
    "NullResearchMethod",
    "ResearchMethod",
    "Scenario",
    "TOPOLOGIES",
    "TraceStep",
    "compute_metrics",
    "dump_scenario",
    "freeze_state",
    "generate_organization",
    "generate_scenario",
    "replay_scenario",
    "run_experiment",
]
