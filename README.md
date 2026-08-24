# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which an Agent may orchestrate approved research actions without entering the numerical trading hot path.

Current status: **Phase 3B — Deterministic Scripted Research Agent**.

The project rule is:

```text
Agent / future LLM:
  plans research and requests finite registered tools.

Deterministic code:
  owns point-in-time data, numerical models, statistical validation,
  portfolio weights, risk approval, execution semantics and model lifecycle.
```

No LLM or Agent framework is required by the package through Phase 3B.

## Architecture

```text
                       Research Agent layer
                              |
                  ResearchPlan / ToolRegistry
                              |
                  AgentPolicy + Audit / Replay
                              |
                 Research Control Plane
                              |
      ExperimentFamily / Runner / Validation / Registry
                              |
                         Quant Engine
                              |
Data -> Alpha -> Risk -> Portfolio -> RiskGate -> Timed Execution
```

The Agent is intentionally outside the numerical trading hot path.

## Quant Engine

The frozen numerical path remains:

```text
DataAdapter
 -> ResearchDataset / ResearchSplit
 -> FeatureWindow
 -> AlphaModel / RiskModel
 -> AlphaForecast / RiskForecast
 -> PortfolioOptimizer
 -> PortfolioTarget
 -> RiskGate
 -> OrderIntent
 -> TimedExecutionVenue
 -> Fill / PortfolioState
```

Implemented reference components include PIT-safe data adapters, random-walk/AR/ARMA alpha models, GARCH/EWMA covariance risk models, mean-variance optimization, deterministic risk gates, timed execution and event-driven backtesting.

## Research governance

Phase 2/2.5 established:

```text
purged / embargoed walk-forward
nested validation
ExperimentFamily: OPEN -> FROZEN -> CLOSED
multiple-testing correction
Deflated Sharpe Ratio
CSCV Probability of Backtest Overfitting
White-style Reality Check
model lifecycle: CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED
```

Failed trials remain in the research record and frozen family membership cannot be reduced after observing results.

## Phase 3A — governed Agent control surface

Phase 3A added framework-independent Agent contracts and a finite ToolRegistry. The Agent can inspect research state, create/register/run approved experiments, freeze/validate experiment families and request model promotion. It cannot set portfolio weights, bypass the risk gate, choose fills, delete failed experiments, remove frozen family members, directly promote a model or execute broker orders.

`DefaultResearchAgentPolicy` and `SQLiteAgentAuditStore` provide deterministic authorization and durable action logging. `AgentRunContext` is immutable after registration, including tool allowlists and tool-call budgets.

See:

- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/PHASE3A.md`](docs/PHASE3A.md)

## Phase 3B — deterministic scripted Agent

Phase 3B provides the first complete `AgentRuntime` implementation without an LLM.

```text
AgentTask
 -> AgentRunCoordinator
 -> immutable AgentRunContext + ResearchPlan
 -> ScriptedResearchAgent
 -> ToolRegistry
 -> AgentPolicyEngine
 -> Research Control Plane
 -> AgentDecision
```

New components:

```text
ResearchBudget
ExperimentVariant
PromotionIntent
ResearchPlan
SQLiteAgentPlanStore
ExperimentTemplate
ExperimentTemplateRegistry
ScriptedResearchAgent
AgentRunCoordinator
AgentReplayEngine
```

A plan is SHA-256 fingerprinted and bound to the task, planner version, approved template, ordered variants, parameters and immutable search budget. Plans that require more experiments or tool calls than their budget are rejected before execution.

Approved experiment templates own evaluator ids, data/code artifacts, universe, parameter allowlists and seed. Phase 3B still does not permit arbitrary Agent-generated Python.

The reference scripted workflow is:

```text
inspect families
 -> create family
 -> register approved variants
 -> run variants
 -> compare primary metric
 -> compare tie-break metric
 -> seal deterministic winner
 -> freeze family
 -> validate full family
 -> optional model-promotion request
 -> terminal decision
```

Reference winner policy:

```text
primary metric descending
 -> tie-break metric ascending
 -> experiment_id
```

The selection is sealed before family validation. Poor results cannot silently expand the experiment or tool-call budget.

`AgentReplayEngine` reconstructs tool names, arguments, policy outcomes, terminal tool statuses and the sealed selection without re-running mutations. Isolated deterministic runs can be normalized and compared.

See:

- [`docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md`](docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md)
- [`docs/PHASE3B.md`](docs/PHASE3B.md)
- [`docs/PHASE3B_PLAN.md`](docs/PHASE3B_PLAN.md)

## Repository layout

```text
src/finagent/
├── agents/
│   ├── audit.py
│   ├── coordinator.py
│   ├── domain.py
│   ├── planning.py
│   ├── policy.py
│   ├── replay.py
│   ├── runtime.py
│   ├── scripted.py
│   ├── templates/
│   └── tools/
├── analysis/
├── backtest/
├── data/
├── domain/
├── models/
├── portfolio/
├── research/
├── services/
└── ports.py
```

## Development

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest -q
```

GitHub Actions runs the full suite on Python 3.11, 3.12 and 3.13.

Phase 3B's first complete CI validation passed all three environments with **90 tests**.

## Next milestone

The next milestone is **Phase 3C — provider-agnostic LLM Research Agent**. The LLM will replace only the deterministic planning/orchestration intelligence. It must emit the same typed plans/tool requests and remain subject to the same ToolRegistry, research budgets, policy, statistical validation, audit and model-governance boundaries.

Phase 3C should not add portfolio-weight authority, broker access, risk-gate bypasses or arbitrary code execution. Sandboxed feature-code generation remains a later Phase 3D capability.

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md`](docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md)
- [`docs/PHASE1.md`](docs/PHASE1.md)
- [`docs/PHASE2.md`](docs/PHASE2.md)
- [`docs/PHASE2_5.md`](docs/PHASE2_5.md)
- [`docs/PHASE3A.md`](docs/PHASE3A.md)
- [`docs/PHASE3B.md`](docs/PHASE3B.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
