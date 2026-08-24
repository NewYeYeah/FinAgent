# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which language models may plan approved research and generate narrowly constrained feature programs without entering the numerical trading hot path.

Current status: **Phase 3.5 — Real Generated-Feature Research Integration** (`0.4.0b1`).

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
   strict ResearchPlan            FeatureSpec/source
          |                              |
          |                       AST + smoke validation
          |                              |
          |                       GeneratedFeatureArtifact
          |                              |
          +-------------+----------------+
                        |
                        v
              GeneratedFeatureMaterializer
                        |
              PIT ResearchDataset
                        |
       IC / ICIR / turnover / net returns
                        |
              immutable research trace
                        |
               ExperimentFamily gates
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

Research governance includes purged/embargoed and nested walk-forward validation, `ExperimentFamily` lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO, White-style Reality Check and governed model stages:

```text
CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED
```

Failed trials remain in the research denominator.

## Agent layers

**Phase 3A** established typed Agent contracts, finite `ToolRegistry`, deterministic policy, immutable registered `AgentRunContext` and SQLite action audit.

**Phase 3B** added `ResearchBudget`, `ResearchPlan`, `ExperimentTemplateRegistry`, `ScriptedResearchAgent`, `AgentRunCoordinator`, plan storage and replay.

**Phase 3C** added provider-neutral LLM contracts, `LLMResearchPlanner`, `LLMResearchAgent`, provider telemetry and an optional OpenAI Responses API adapter. The default install and CI require no provider SDK or API key.

**Phase 3D** added bounded generated feature programs:

```python
def compute_feature(inputs):
    ...
    return values
```

Generated code is statically restricted and smoke-tested in a separate `python -I -S` subprocess. This is restricted execution, not container-grade isolation.

## Phase 3.5 — real generated-feature research

Phase 3.5 closes the gap between generated code and quantitative evidence.

New components:

```text
GeneratedFeatureMaterializer
GeneratedFeatureEvaluationConfig
GeneratedFeatureResearchTrace
GeneratedFeatureEvaluator
SQLiteGeneratedFeatureResearchStore
GeneratedFeatureFamilyValidationInputProvider
GeneratedFeatureNestedWalkForwardStudy
```

### Causality at the materialization boundary

A generated feature is **not** executed once over a full test panel. For each asset and timestamp `t`, FinAgent requests the existing PIT-safe `FeatureWindow(asof=t)` using the feature's declared lookback, then evaluates the generated program only on that window.

This prevents a subtle leakage class: syntactically safe code such as `inputs["close"][-1]` is harmless only if the supplied input ends at `t`. AST safety, process isolation and statistical causality are separate controls.

Materialized generated datasets remain immutable `ResearchDataset` objects and record:

```text
generated feature digest
source code digest
source dataset digest
materializer version
```

### Reference evaluation

The first real evaluator ranks the generated feature cross-sectionally, demeans ranks and normalizes gross absolute exposure to one. Forward labels provide realized returns. It reports:

```text
mean_ic / icir / annualized_icir
mean gross and net return
cumulative gross and net return
net Sharpe
mean turnover
transaction cost
coverage / sample counts
one-sided net-return p-value
```

Turnover cost is explicitly included. The reference rank portfolio is a research diagnostic bridge, not the final portfolio-construction policy.

### Statistical-governance bridge

`SQLiteGeneratedFeatureResearchStore` persists period-level net-return and IC traces immutably. `GeneratedFeatureFamilyValidationInputProvider` feeds those real traces into the existing Holm/DSR/PBO/Reality-Check family validator, removing the need for synthetic return fixtures in the generated-feature path.

`GeneratedFeatureNestedWalkForwardStudy` reuses the existing `NestedPurgedWalkForwardSplitter`: inner folds diagnose feature stability and outer folds remain held-out evidence.

## Persistence and audit

```text
SQLiteResearchRegistry                -> experiments/models/results
SQLiteAgentAuditStore                 -> governed tool actions and decisions
SQLiteAgentPlanStore                  -> immutable research plans/selections
SQLiteLLMCallStore                    -> provider/model/prompt/token/latency telemetry
SQLiteGeneratedFeatureStore           -> generated feature source and lineage
SQLiteGeneratedFeatureResearchStore   -> real return/IC evidence for generated features
```

No API key or hidden model reasoning is persisted.

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

The project is now intentionally prioritizing quantitative realism over additional Agent-framework complexity:

```text
Phase 4    Portfolio research and construction hardening
Phase 4.5  Low-permission Portfolio Supervisor Agent
Phase 5    Paper trading / shadow production / reconciliation
Phase 5.5  Structured research memory and hypothesis evolution
Phase 6    Optional graph orchestration, only if operationally justified
Phase 7    Optional advanced ML/RL/text/multi-Agent research
```

The next critical milestone is **Phase 4**: cross-sectional alpha ensembles, forecast calibration, stronger covariance/risk models, deterministic constraint compilation, turnover/liquidity/exposure penalties and additional portfolio baselines. `PortfolioTarget` remains canonical.

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`](docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md)
- [`docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`](docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md)
- [`docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md`](docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md)
- [`docs/PHASE3D.md`](docs/PHASE3D.md)
- [`docs/PHASE3_5.md`](docs/PHASE3_5.md)
- [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
