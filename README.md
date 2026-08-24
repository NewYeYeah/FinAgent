# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which language models may plan approved research and generate narrowly constrained feature programs without entering the numerical trading hot path.

Current status: **Phase 4 — Alpha Calibration, Risk Hardening and Portfolio Research** (`0.5.0a1`).

The governing rule is:

```text
LLM:
  proposes bounded research plans and feature implementations.

Deterministic Agent/runtime code:
  validates plans/code and executes finite registered tools.

Deterministic quantitative code:
  owns PIT data, statistical validation, alpha calibration,
  risk forecasts, constraints, portfolio weights,
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
               ExperimentFamily gates
                        |
                        v
              Alpha calibration / ensemble
                        |
       OAS / PCA factor risk estimation
                        |
                ConstraintCompiler
                        |
      PortfolioBenchmarkSuite / stress tests
                        |
                RebalancePolicy
                        |
                        v
                 PortfolioTarget
                        |
          RiskGate -> Timed Execution
```

The LLM remains outside the numerical trading hot path.

## Frozen numerical path

```text
DataAdapter
 -> ResearchDataset / ResearchSplit
 -> FeatureWindow
 -> AlphaModel / GeneratedFeature
 -> AlphaForecast
 -> RiskForecast
 -> PortfolioOptimizer
 -> PortfolioTarget
 -> RiskGate
 -> OrderIntent
 -> TimedExecutionVenue
 -> Fill / PortfolioState
```

Canonical research arrays remain `(time, asset, feature)` and `(time, asset, label)`. `available_at` remains the point-in-time clock.

Research governance includes purged/embargoed and nested walk-forward validation, `ExperimentFamily` lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO, White-style Reality Check and governed model stages:

```text
CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED
```

Failed trials remain in the research denominator.

## Agent and generated-feature layers

**Phase 3A** established typed Agent contracts, finite `ToolRegistry`, deterministic policy and SQLite action audit.

**Phase 3B** added deterministic research plans, budgets, approved templates, scripted execution, plan storage and replay.

**Phase 3C** added provider-neutral LLM planning, telemetry and an optional OpenAI Responses API adapter.

**Phase 3D** added restricted generated numeric feature programs with AST validation and isolated subprocess smoke execution.

**Phase 3.5** connected generated features to real PIT materialization, IC/ICIR, turnover, net-return evidence, immutable research traces and nested walk-forward statistical governance.

## Phase 4A — alpha calibration and ensemble

New components:

```text
CrossSectionalCalibrationResult
CrossSectionalLinearAlphaCalibrator
AlphaEnsembleResult
AlphaForecastEnsembler
```

The reference calibrator standardizes feature scores within each training timestamp and fits a pooled ridge-regularized mapping:

```text
forward return = intercept + slope * standardized feature + residual
```

It only consumes the explicitly supplied `ResearchSplit`; it does not choose or inspect outer-test data.

`AlphaForecastEnsembler` combines aligned `AlphaForecast` objects using explicit deterministic weights. Quality-score helpers may transform validated research scores into normalized weights, but the LLM never writes portfolio weights.

## Phase 4B — risk and constraint hardening

Risk baselines now include:

```text
EWMACovarianceEstimator
OASCovarianceEstimator
HistoricalRiskForecastBuilder
PCAFactorRiskEstimator
PCAFactorRiskForecastBuilder
```

OAS shrinks noisy sample covariance toward a scaled identity target. PCA factor risk supplies a low-rank statistical factor covariance plus diagonal idiosyncratic risk. Both produce PSD canonical `RiskForecast` objects. PCA is explicitly a research baseline, not a production fundamental factor model.

Portfolio constraints are centralized in:

```text
PortfolioConstraintSet
GroupExposureLimit
LinearExposureLimit
ConstraintCompiler
CompiledPortfolioConstraints
```

Supported controls include:

```text
cash/invested-weight identity
long-only or bounded long/short weights
asset-specific bounds
gross exposure
turnover limit
group/sector-like min-max exposure
benchmark-relative active-weight bounds
linear factor/style exposure bounds
per-asset trade-weight caps as a liquidity/participation proxy
```

Constraints are deterministic infrastructure and are not mutable LLM outputs.

## Phase 4C — portfolio construction and evaluation

Reference constructors:

```text
EqualWeightOptimizer
MinimumVarianceOptimizer
RiskParityOptimizer
ConstrainedMeanVarianceOptimizer
```

The cost-aware mean-variance objective is:

```text
min_w  -mu'w + 0.5 * lambda * w'Sigma*w + cost(turnover)
```

subject to compiled constraints.

`PortfolioBenchmarkSuite` runs multiple constructors on the same `AlphaForecast`, `RiskForecast` and marked `PortfolioState`, reporting:

```text
expected return
expected net return after turnover cost
volatility
turnover
gross exposure
net exposure
```

Markowitz is therefore a candidate rather than an assumed winner; equal weight, minimum variance and risk parity remain explicit baselines.

Additional deterministic portfolio-research components:

```text
PortfolioScenario
PortfolioStressTester
StressTestReport
DriftRebalancePolicy
RebalanceDecision
```

Stress tests apply explicit asset-return scenarios to a `PortfolioTarget`. Rebalance policy decides whether a target should be acted on from weight drift/turnover thresholds; it does not rewrite the target.

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

## Roadmap after Phase 4

```text
Phase 4.5  Low-permission Portfolio Supervisor Agent
Phase 5    Paper trading / shadow production / reconciliation
Phase 5.5  Structured research memory and hypothesis evolution
Phase 6    Optional graph orchestration, only if operationally justified
Phase 7    Optional advanced ML/RL/text/multi-Agent research
```

Phase 4 does not yet claim production-grade fundamental factor risk, nonlinear market impact, corporate-action accounting or broker reconciliation. Those remain operational-phase work.

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`](docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md)
- [`docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`](docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md)
- [`docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md`](docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md)
- [`docs/ADR-016_PHASE4_PORTFOLIO_RESEARCH.md`](docs/ADR-016_PHASE4_PORTFOLIO_RESEARCH.md)
- [`docs/PHASE3_5.md`](docs/PHASE3_5.md)
- [`docs/PHASE4.md`](docs/PHASE4.md)
- [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
