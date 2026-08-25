# FinAgent

FinAgent is a typed, auditable quantitative-research, portfolio and paper-operation infrastructure. Language models may propose bounded research and supervision requests, but deterministic code owns numerical finance, validation, approvals and financial-state mutation.

Current status: **Phase 5.5 — Structured Evidence and Research Memory** (`0.6.0b1`).

## Governing rule

```text
LLM / Agent
  hypothesis, bounded feature code, research plans,
  explanations, memory queries and non-mutating supervision requests
                |
                v
Deterministic control plane
  PIT validation, research governance, memory/lineage,
  policy checks, human approval, health monitoring
                |
                v
Deterministic financial-state layer
  alpha, risk, constraints, portfolio weights,
  RiskGate, paper execution, reconciliation, kill switch
```

The Agent never owns portfolio weights, fills, broker/account state, hard risk limits, historical memory mutation, or validation thresholds.

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
non-mutating request -> HumanApproval
        |
TradingSafetyController
        |
PaperBroker -> reconciliation / shadow evidence
        |
        +-----------------------------------+
                                            |
                                  Structured Evidence Memory
                                            |
                       hypothesis -> feature -> experiment -> result
                                            |
                         model -> portfolio -> paper/shadow outcome
                                            |
                              bounded read-only Agent queries
```

## Quant and research foundation

The canonical numerical path remains:

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

Research governance includes purged/embargoed and nested walk-forward validation, experiment-family lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO and a White-style Reality Check. Failed trials remain part of the research denominator.

Generated features are materialized point-in-time; safe Python syntax alone is not treated as proof against look-ahead.

## Agent research layer

Phase 3A established typed Agent contracts, finite tools, policy-as-code and durable audit. Phase 3B added deterministic research plans, budgets, approved templates and replay. Phase 3C added provider-neutral LLM planning. Phase 3D added restricted feature-program generation. Phase 3.5 connected generated features to real PIT IC/ICIR, turnover and net-return evidence.

The LLM remains outside the numerical portfolio/execution hot path.

## Portfolio and supervision layer

Phase 4 added deterministic alpha calibration/ensemble, OAS/PCA risk, centralized constraints, equal-weight/minimum-variance/risk-parity/constrained mean-variance constructors, stress testing and rebalance policy.

Phase 4.5 added immutable portfolio-health evidence and a separate low-permission Supervisor. Supervisor policy/rebalance handlers create auditable requests with:

```text
mutation_performed = false
```

They do not set weights, bypass `RiskGate`, choose fills or submit broker orders.

## Paper/shadow operations

Phase 5 added:

```text
TradingSessionCalendar
PaperOrder / BrokerOrderStatus
PaperBroker / SQLitePaperBrokerStore
HumanApproval / OperationalApprovalService
TradingSafetyController / durable kill switch
PortfolioReconciler
ApprovedPaperTradingController
CorporateActionProcessor
ShadowPortfolioMonitor
ExecutionCostCalibrator
```

`client_order_id` is the paper-broker idempotency key. Partial fills persist across snapshots and process restarts. Critical reconciliation mismatches trip a durable kill switch that is not reset by restart.

Phase 5 remains paper/shadow only; no live broker credentials are included.

## Phase 5.5 — structured evidence memory

Phase 5.5 adds a relational memory layer over stable identities rather than a free-form chat-history buffer.

Core components:

```text
ResearchHypothesisRevision / HypothesisDisposition
MemoryNode / LineageEdge
FailureRecord / FailureCategory / FailureStage
SQLiteResearchMemoryStore
ResearchMemoryService
EvidenceAwareBudgetPolicy
```

### Hypothesis evolution

A hypothesis has one stable ID and append-only contiguous revisions. Old claims are never overwritten when rationale, tags or disposition evolve.

```text
OPEN -> later revision may be SUPPORTED / REJECTED / INCONCLUSIVE / RETIRED
```

Disposition is evidence metadata; it does not bypass statistical validation or model-stage governance.

### End-to-end lineage

The memory graph can link:

```text
hypothesis
 -> generated feature
 -> experiment
 -> result
 -> model
 -> portfolio-health snapshot
 -> paper order/fill
 -> reconciliation / shadow outcome
```

The memory store does **not** replace the research registry, supervision store or paper broker store. Those remain authoritative for native state. Memory records immutable cross-registry identities and evidence relationships.

### Failure taxonomy

Normalized failure categories include:

```text
data / leakage / statistical / model_fit / numerical
cost / turnover / liquidity / risk
execution / reconciliation / operational / policy / duplicate / unknown
```

Failures are first-class evidence rather than discarded trials.

### Similarity and duplicate detection

The first implementation is deterministic and dependency-light:

```text
hypothesis similarity  text/tag Jaccard with CJK bigram support
experiment similarity  hypothesis + universe + params + dataset + code
feature similarity     hypothesis + input fields + lookback
```

This is a duplicate-search aid, not proof of economic equivalence. Vector/embedding retrieval may later complement unstructured papers or reports, but relational evidence remains the source of truth.

### Evidence-aware budgets

`EvidenceAwareBudgetPolicy` can only preserve or reduce the caller's requested experiment budget.

Near duplicates may receive zero new trials until existing evidence is reused. Similar hypotheses and repeated failures may reduce the budget. Historical winners never automatically expand it.

This prevents research memory from becoming a new route for adaptive multiple testing.

### Bounded Agent memory tools

Read-only tools:

```text
list_research_hypotheses
inspect_research_hypothesis
find_similar_hypotheses
inspect_research_lineage
inspect_research_failures
recommend_research_budget
```

There is no Agent tool to delete evidence, rewrite an old hypothesis revision, erase failed experiments, expand budgets, change validation thresholds or mutate financial state.

## Persistence

```text
SQLiteResearchRegistry                experiment/model/result state
SQLiteAgentAuditStore                 Agent/Supervisor tool audit
SQLiteAgentPlanStore                  immutable research plans
SQLiteLLMCallStore                    provider/token/latency telemetry
SQLiteGeneratedFeatureStore           generated code lineage
SQLiteGeneratedFeatureResearchStore   feature return/IC evidence
SQLitePortfolioSupervisionStore       portfolio-health evidence
SQLitePaperBrokerStore                paper orders/fills/account/safety state
SQLiteResearchMemoryStore             hypothesis revisions/cross-registry lineage/failures
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

FinAgent is still **paper/shadow only**. Deferred operational work includes:

```text
live broker adapters and credentials
multi-currency cash/FX ledger
exchange/security master feeds
full corporate-action accounting
approval expiry/revocation
session PnL/exposure journals
production nonlinear market impact
operational SLO/alert stack
sustained paper/shadow acceptance statistics
```

Memory similarity is lexical/signature based. It is deliberately not presented as semantic or causal equivalence.

## Roadmap

```text
Phase 6    Operational hardening; graph orchestration only if measured workflows justify it
Phase 7    Optional advanced ML, regime, text, RL and multi-Agent research
```

Before any live-capital milestone, require sustained paper/shadow runtime, reconciliation statistics, kill-switch/restart drills, cost calibration, operational alerts/runbooks and explicit human sign-off.

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
- `docs/ADR-019_PHASE55_EVIDENCE_MEMORY.md`
- `docs/PHASE5_5.md`
- `docs/RUNBOOK_PAPER_TRADING.md`
- `docs/ROADMAP_REBASELINE.md`
- `docs/DEVLOG.md`
