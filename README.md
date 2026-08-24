# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which language models may plan approved research and generate narrowly constrained feature programs without entering the numerical trading hot path.

Current status: **Phase 4.5 — Low-Permission Portfolio Supervisor Agent** (`0.5.0b1`).

The governing rule is:

```text
LLM / Agent:
  proposes bounded research, feature implementations and supervision requests.

Deterministic Agent/runtime code:
  validates plans/code, executes finite tools and records audit evidence.

Deterministic quantitative/operational code:
  owns PIT data, statistical validation, alpha calibration,
  risk forecasts, constraints, portfolio weights, hard risk approval,
  execution semantics, model lifecycle and any financial-state mutation.
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
                 PortfolioTarget
                        |
                        v
             PortfolioHealthMonitor
                        |
            PortfolioHealthSnapshot
                        |
      Low-Permission Portfolio Supervisor
                        |
      inspect / request / human approval
                        |
                        v
          RiskGate -> Timed Execution
```

The Agent remains outside the numerical portfolio and execution hot path.

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

**Phase 3A** established typed Agent contracts, a finite `ToolRegistry`, deterministic policy and SQLite action audit.

**Phase 3B** added deterministic research plans, budgets, approved templates, scripted execution, plan storage and replay.

**Phase 3C** added provider-neutral LLM planning, telemetry and an optional OpenAI Responses API adapter.

**Phase 3D** added restricted generated numeric feature programs with AST validation and isolated subprocess smoke execution.

**Phase 3.5** connected generated features to real PIT materialization, IC/ICIR, turnover, net-return evidence, immutable research traces and nested walk-forward statistical governance.

## Phase 4 — deterministic portfolio research hardening

Phase 4 added:

```text
CrossSectionalLinearAlphaCalibrator
AlphaForecastEnsembler
OASCovarianceEstimator
PCAFactorRiskEstimator
ConstraintCompiler
EqualWeightOptimizer
MinimumVarianceOptimizer
RiskParityOptimizer
ConstrainedMeanVarianceOptimizer
PortfolioBenchmarkSuite
PortfolioStressTester
DriftRebalancePolicy
```

Alpha calibration, covariance estimation, exposure constraints and portfolio weights remain deterministic numerical responsibilities. The LLM does not set expected returns, covariance matrices, hard limits or portfolio weights.

## Phase 4.5 — low-permission Portfolio Supervisor

Phase 4.5 introduces an Agent-facing supervision boundary over Phase 4 outputs without introducing an LLM portfolio manager.

New components:

```text
HealthLevel / HealthCheck
PortfolioHealthThresholds
PortfolioHealthSnapshot
PortfolioHealthMonitor
SQLitePortfolioSupervisionStore

OperatingMode
OperatingPolicy
OperatingPolicyRegistry
PortfolioSupervisorPolicy
ScriptedPortfolioSupervisorAgent

PortfolioSupervisorToolDependencies
build_portfolio_supervisor_tools
```

### Immutable health evidence

`PortfolioHealthMonitor` converts deterministic Phase 4 outputs into a `PortfolioHealthSnapshot` containing:

```text
forecast/state clock alignment
data and forecast freshness checks
selected portfolio expected net return / volatility / turnover
all benchmark-constructor summaries
stress-scenario results
current-vs-target weight drifts
deterministic rebalance decision
```

Thresholds are explicit configuration, not Agent outputs. `SQLitePortfolioSupervisionStore` persists snapshots immutably.

### Finite Supervisor surface

Read-only tools:

```text
inspect_portfolio_health
inspect_portfolio_benchmarks
inspect_stress_report
inspect_rebalance_decision
list_operating_policies
```

Non-mutating request tools:

```text
request_operating_policy
request_rebalance
request_human_review
```

The Supervisor does **not** have tools to set arbitrary weights, alter hard risk limits, bypass `RiskGate`, choose fill prices or submit broker orders.

`request_operating_policy` and `request_rebalance` require human approval. Their handlers only validate the request and return an auditable payload with:

```text
mutation_performed = false
```

The reference operating-policy registry contains pre-registered identities such as `normal`, `cautious`, `defensive` and `paused`. The Agent may request one of these identities but cannot synthesize new constraint numbers.

### Reference Supervisor behavior

`ScriptedPortfolioSupervisorAgent` provides the deterministic Phase 4.5 acceptance path:

```text
CRITICAL
 -> request defensive policy
 -> request human review
 -> BLOCKED pending approval

WARNING + deterministic rebalance=True
 -> request rebalance
 -> BLOCKED pending approval

WARNING
 -> request human review
 -> BLOCKED

OK
 -> no financial-state request
 -> COMPLETED
```

This proves supervision, audit and approval boundaries before any future LLM explanation/recommendation adapter is attached.

## Persistence and audit

```text
SQLiteResearchRegistry                -> experiments/models/results
SQLiteAgentAuditStore                 -> governed Agent/Supervisor actions and decisions
SQLiteAgentPlanStore                  -> immutable research plans/selections
SQLiteLLMCallStore                    -> provider/model/prompt/token/latency telemetry
SQLiteGeneratedFeatureStore           -> generated feature source and lineage
SQLiteGeneratedFeatureResearchStore   -> real return/IC evidence
SQLitePortfolioSupervisionStore       -> immutable portfolio health snapshots
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

## Roadmap after Phase 4.5

```text
Phase 5    Paper trading / shadow production / reconciliation
Phase 5.5  Structured research memory and hypothesis evolution
Phase 6    Optional graph orchestration, only if operationally justified
Phase 7    Optional advanced ML/RL/text/multi-Agent research
```

The immediate next milestone is Phase 5: attach deterministic operational approval and paper-broker infrastructure to the already separated Supervisor request/application boundary. No live-capital milestone should precede sustained paper/shadow validation.

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`](docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md)
- [`docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`](docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md)
- [`docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md`](docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md)
- [`docs/ADR-016_PHASE4_PORTFOLIO_RESEARCH.md`](docs/ADR-016_PHASE4_PORTFOLIO_RESEARCH.md)
- [`docs/ADR-017_PHASE45_PORTFOLIO_SUPERVISOR.md`](docs/ADR-017_PHASE45_PORTFOLIO_SUPERVISOR.md)
- [`docs/PHASE4_5.md`](docs/PHASE4_5.md)
- [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
