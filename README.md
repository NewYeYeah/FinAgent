# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which language models may plan approved research and generate narrowly constrained feature programs without entering the numerical trading hot path.

Current status: **Phase 3D — Restricted Generated Feature Programs** (`0.4.0a1`).

The governing rule is:

```text
LLM:
  proposes bounded research plans and feature implementations.

Deterministic Agent/runtime code:
  validates plans/code and executes finite registered tools.

Deterministic quantitative code:
  owns PIT data, statistical validation, portfolio weights,
  hard risk approval, execution semantics and model lifecycle.
```

## Architecture

```text
Natural-language research task
          |
          +------------------------------+
          |                              |
          v                              v
  LLMResearchPlanner              LLMFeatureGenerator
          |                              |
   strict ResearchPlan            strict FeatureSpec/source
          |                              |
          |                       AST validation
          |                              |
          |                       restricted subprocess
          |                              |
          |                       GeneratedFeatureArtifact
          |                              |
          +-------------+----------------+
                        |
                        v
               ScriptedResearchAgent
                        |
                ToolRegistry + Policy
                        |
               Audit / Replay / Budget
                        |
              Research Control Plane
                        |
       ExperimentFamily / Validation / Registry
                        |
                        v
                    Quant Engine
                        |
Data -> Alpha -> Risk -> Portfolio -> RiskGate -> Timed Execution
```

The LLM remains outside the numerical trading hot path.

## Quant and research foundations

The frozen numerical path is:

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

Reference implementations include PIT-safe data adapters, random-walk/AR/ARMA alpha models, GARCH/EWMA covariance risk models, mean-variance optimization, deterministic risk gates, timed execution and event-driven backtesting.

Research governance includes purged/embargoed and nested walk-forward validation, `ExperimentFamily` lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO, a White-style Reality Check and governed model stages:

```text
CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED
```

Failed trials remain in the research denominator.

## Phase 3A — governed Agent control surface

Phase 3A established typed Agent contracts, a finite ToolRegistry, deterministic policy, immutable registered `AgentRunContext` and SQLite action audit. The Agent cannot set portfolio weights, bypass risk, choose fills, delete failed trials, remove frozen family members, directly promote models or execute broker orders.

## Phase 3B — deterministic scripted Agent

Phase 3B added `ResearchBudget`, `ResearchPlan`, `ExperimentTemplateRegistry`, `ScriptedResearchAgent`, `AgentRunCoordinator`, `SQLiteAgentPlanStore` and `AgentReplayEngine`.

The reference workflow remains deterministic:

```text
inspect families
 -> create family
 -> register approved variants
 -> run variants
 -> compare approved metrics
 -> seal winner
 -> freeze family
 -> validate complete family
 -> optional non-mutating promotion request
```

## Phase 3C — provider-agnostic LLM planning

Phase 3C added:

```text
LLMRequest / LLMResponse / LLMUsage / LLMProvider
SQLiteLLMCallStore
LLMPlanningPolicy
LLMResearchPlanner
LLMResearchAgent
AgentEvaluationMetrics
```

The LLM proposes only bounded approved-template plans. Provider structured output is locally revalidated before any research action occurs.

An optional OpenAI Responses API adapter is installed with:

```bash
python -m pip install -e ".[llm-openai]"
```

The default install and CI do not require a provider SDK or API key.

## Phase 3D — generated feature boundary

Phase 3D allows the LLM to implement one new numeric feature program under a deliberately narrow executable contract:

```python
def compute_feature(inputs):
    ...
    return values
```

Inputs are a policy-approved subset of PIT numeric fields. Output must have the same length and contain only finite numbers or `None`.

New components:

```text
FeatureSpec
FeatureCodePolicy
FeatureCodeValidator
FeatureValidationReport
GeneratedFeatureArtifact
SQLiteGeneratedFeatureStore

FeatureSandboxLimits
FeatureSandboxRequest
FeatureSandboxResult
LocalFeatureSandbox

LLMFeatureGenerationPolicy
LLMFeatureGenerator
generated_feature_template
```

### Static code boundary

Generated code is rejected if it contains imports, general attribute access, dunder traversal, dynamic execution, file access, classes, async constructs, global/nonlocal state, context managers, exception machinery or while loops. Calls are restricted to a finite builtin set and selected `math` members. Source size and AST complexity are bounded.

### Restricted execution

Accepted source is smoke-tested in a separate `python -I -S` process with a reduced builtin namespace and strict JSON I/O. POSIX resource limits are applied for CPU time, address space, file size and file descriptors where available.

**This is a restricted subprocess, not a kernel/container sandbox.** Phase 3D does not claim seccomp, namespaces or container isolation. The narrow AST language is part of the security boundary.

### Artifact lineage

An accepted `GeneratedFeatureArtifact` is fingerprinted from:

```text
FeatureSpec
source digest
validator version
smoke-output digest
generator identity
```

It is persisted by `SQLiteGeneratedFeatureStore` and can be converted into the existing `ExperimentTemplate` contract. Generated features therefore still pass through the same ExperimentFamily, nested-validation and multiple-testing controls.

## Persistence and audit

```text
SQLiteResearchRegistry       -> experiments/models/results
SQLiteAgentAuditStore        -> governed tool actions and decisions
SQLiteAgentPlanStore         -> immutable research plans/selections
SQLiteLLMCallStore           -> provider/model/prompt/token/latency telemetry
SQLiteGeneratedFeatureStore  -> generated feature source and immutable lineage
```

No API key or hidden model reasoning is persisted.

## Repository layout

```text
src/finagent/
├── agents/
│   ├── audit.py
│   ├── coordinator.py
│   ├── domain.py
│   ├── generated_features.py
│   ├── llm_feature.py
│   ├── llm_planner.py
│   ├── llm_research.py
│   ├── metrics.py
│   ├── planning.py
│   ├── policy.py
│   ├── providers/
│   ├── replay.py
│   ├── scripted.py
│   ├── templates/
│   └── tools/
├── sandbox/
│   └── feature.py
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

GitHub Actions runs the complete suite on Python 3.11, 3.12 and 3.13. External provider calls are not required by CI.

## Rebased roadmap

Development has passed the point where more Agent-framework complexity is the main bottleneck. The remaining roadmap has therefore been adjusted:

```text
Phase 3.5  Real generated-feature/PIT evaluator integration
Phase 4    Portfolio research and construction hardening
Phase 4.5  Low-permission Portfolio Supervisor Agent
Phase 5    Paper trading / shadow production / reconciliation
Phase 5.5  Structured research memory and hypothesis evolution
Phase 6    Optional graph orchestration (LangGraph only if justified)
Phase 7    Optional advanced ML/RL/text/multi-Agent research
```

The immediate priority is **Phase 3.5**, not LangGraph or multi-Agent debate. A generated feature must next be evaluated against real PIT numerical datasets, nested walk-forward folds, IC/ICIR, turnover and net-return metrics without synthetic fixtures.

See [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md).

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md`](docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md)
- [`docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`](docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md)
- [`docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`](docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md)
- [`docs/PHASE3D.md`](docs/PHASE3D.md)
- [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
