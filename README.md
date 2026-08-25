# FinAgent

FinAgent is a typed, auditable quantitative-research, portfolio and paper-operation infrastructure. Language models may propose bounded research and supervision requests, but deterministic code owns numerical finance, risk, approvals and financial-state mutation.

Current status: **Phase 5 — Paper/Shadow Operations and Reconciliation** (`0.6.0a1`).

## Governing rule

```text
LLM / Agent
  hypothesis, bounded feature code, research plans,
  explanations and non-mutating supervision requests
                |
                v
Deterministic control plane
  PIT validation, research governance, policy checks,
  human-approval application, health monitoring
                |
                v
Deterministic financial-state layer
  alpha, risk, constraints, portfolio weights,
  RiskGate, paper execution, reconciliation, kill switch
```

The Agent never owns portfolio weights, fills, broker/account state or hard risk limits.

## Architecture

```text
Natural-language research
        |
LLMResearchPlanner / LLMFeatureGenerator
        |
PIT generated-feature research
        |
ExperimentFamily statistics
        |
Alpha calibration / ensemble
        |
OAS / PCA risk
        |
ConstraintCompiler
        |
Portfolio benchmark construction
        |
stress + rebalance policy
        |
PortfolioHealthSnapshot
        |
Low-Permission Portfolio Supervisor
        |
non-mutating request
        |
HumanApproval
        |
OperationalApprovalService
        |
TradingSafetyController
        |
PaperBroker
        |
partial fills + durable account
        |
PortfolioReconciler
        |
kill switch / shadow evidence
```

## Quant and research foundation

The numerical research contract remains:

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
```

Research governance includes purged/embargoed and nested walk-forward validation, experiment-family lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO and a White-style Reality Check.

Generated features are materialized point-in-time; safe Python syntax alone is not treated as proof against look-ahead.

## Portfolio layer

Phase 4 added deterministic:

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

`PortfolioTarget` remains canonical.

## Portfolio Supervisor

Phase 4.5 added immutable portfolio-health evidence and a separate low-permission Supervisor policy.

Allowed Supervisor actions include inspection and requests for pre-registered operating policies, rebalances and human review.

The following capabilities are absent:

```text
set arbitrary weights
change hard risk limits
bypass RiskGate
choose fills
submit broker orders
mutate account state
```

Supervisor policy/rebalance request handlers return:

```text
mutation_performed = false
```

## Phase 5 — paper/shadow operations

### Durable paper broker

New operational components:

```text
TradingSessionCalendar

PaperOrder / BrokerOrderStatus
PaperBrokerConfig
PaperBroker
SQLitePaperBrokerStore

HumanApproval
OperationalApprovalService

TradingSafetyController
PortfolioReconciler
ApprovedPaperTradingController

CorporateActionProcessor
ShadowPortfolioMonitor
ExecutionCostCalibrator
```

`client_order_id` is the paper-broker idempotency key. Reusing it for a different order is rejected.

Participation caps create explicit partial-fill lifecycle:

```text
NEW -> PARTIALLY_FILLED -> FILLED
```

Fill, order and account transitions are persisted. Reprocessing the same execution timestamp does not duplicate a fill, and a restarted process recovers account/open-order state from SQLite.

### Request versus application

The operational path is deliberately split:

```text
Supervisor request
    mutation_performed=false
        |
        v
HumanApproval
        |
        v
OperationalApprovalService
        |
        v
registered policy/rebalance authorization
```

A paper rebalance requires the exact stored human approval associated with the immutable health snapshot.

### Safety and reconciliation

Pre-trade checks include:

```text
durable kill switch
per-order notional
batch notional
session loss fraction
critical reconciliation count
```

Reconciliation compares cash, positions, marks and NAV. Critical cash/position mismatches halt paper operation.

The kill switch is durable and is not automatically reset after restart.

### Sessions and corporate actions

`TradingSessionCalendar` supports timezone-aware session hours, weekdays and configured holidays.

Phase 5 corporate-action support is deliberately narrow:

```text
stock split
cash dividend
```

Actions are idempotent by stable action ID.

### Shadow and cost evidence

`ShadowPortfolioMonitor` compares shadow and reference targets without applying the shadow target.

`ExecutionCostCalibrator` reports realized notional-weighted paper slippage, commission and participation observations. These are diagnostics; the Agent does not directly rewrite execution parameters.

## Persistence

```text
SQLiteResearchRegistry                experiment/model/result state
SQLiteAgentAuditStore                 Agent/Supervisor tool audit
SQLiteAgentPlanStore                  immutable research plans
SQLiteLLMCallStore                    provider/token/latency telemetry
SQLiteGeneratedFeatureStore           generated code lineage
SQLiteGeneratedFeatureResearchStore   feature return/IC evidence
SQLitePortfolioSupervisionStore       portfolio-health evidence
SQLitePaperBrokerStore                orders/fills/account/approvals/kill switch/events
```

## Development

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest -q
```

GitHub Actions runs the full suite on Python 3.11, 3.12 and 3.13 without external LLM calls.

## Current limitations

Phase 5 is **paper/shadow only**. It does not claim live-capital readiness.

Still deferred:

```text
live broker adapters and credentials
multi-currency cash/FX ledger
exchange-master calendar feeds
full security master/corporate actions
production nonlinear market impact
full broker reconciliation semantics
live incident response/SLO stack
```

## Roadmap

```text
Phase 5.5  Structured research memory and hypothesis evolution
Phase 6    Operational hardening / optional graph orchestration when justified
Phase 7    Optional advanced ML, regime, text, RL and multi-Agent research
```

Before any live-capital milestone, the project should accumulate sustained paper/shadow evidence and explicit operational acceptance criteria.

## Design documents

- `docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`
- `docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`
- `docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`
- `docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`
- `docs/ADR-014_PHASE3D_SANDBOXED_FEATURE_CODE.md`
- `docs/ADR-015_PHASE35_REAL_FEATURE_RESEARCH.md`
- `docs/ADR-016_PHASE4_PORTFOLIO_RESEARCH.md`
- `docs/ADR-017_PHASE45_PORTFOLIO_SUPERVISOR.md`
- `docs/ADR-018_PHASE5_PAPER_SHADOW_OPERATIONS.md`
- `docs/PHASE5.md`
- `docs/RUNBOOK_PAPER_TRADING.md`
- `docs/ROADMAP_REBASELINE.md`
- `docs/DEVLOG.md`
