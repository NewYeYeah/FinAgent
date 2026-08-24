# FinAgent Roadmap Rebaseline — After Phase 4.5

Date: 2026-08-25

## Current architectural position

The project has now crossed the boundary from research automation into supervised portfolio operations. Phase 4 made portfolio construction deterministic; Phase 4.5 placed a low-permission Agent on top of that deterministic engine without transferring financial-state ownership to the Agent.

Completed foundation:

```text
Phase 0.5  Domain contracts
Phase 1    Numerical/PIT Quant Kernel
Phase 2    Walk-forward, execution clocks, model governance
Phase 2.5  Nested validation and multiple-testing controls
Phase 3A   Governed Agent tool boundary
Phase 3B   Deterministic ScriptedResearchAgent
Phase 3C   Provider-agnostic LLM planning
Phase 3D   Restricted generated feature code
Phase 3.5  Real generated-feature PIT research integration
Phase 4    Alpha calibration, risk hardening and portfolio benchmarks
Phase 4.5  Low-permission Portfolio Supervisor Agent
```

The critical invariant is now:

```text
Agent may inspect, explain and request.
Deterministic infrastructure owns limits, weights, approvals and financial state.
```

## Phase 5 — Paper Trading / Shadow Production

Priority: highest.

Goal: prove research/backtest/operational semantic consistency without live capital.

Recommended sub-phases:

### Phase 5A — Operational state and paper broker

Deliver:

```text
BrokerOrderId / client idempotency key
PaperBrokerAdapter
OrderState lifecycle
submitted / accepted / partially-filled / filled / cancelled / rejected
PaperAccountSnapshot
position/cash ledger
exchange-session guard
```

The existing `TimedExecutionVenue` remains the research execution abstraction; Phase 5A adds an operational broker abstraction rather than overloading the backtest venue.

### Phase 5B — Approval controller and Supervisor request application

Deliver:

```text
PortfolioOperationRequest
HumanApprovalRecord
OperationalPolicyController
approved rebalance application
approved operating-policy application
kill-switch state
circuit-breaker rules
```

The Phase 4.5 `request_operating_policy` and `request_rebalance` payloads become inputs to this controller. The Agent still cannot approve its own requests.

### Phase 5C — Reconciliation and recovery

Deliver:

```text
expected-vs-observed order reconciliation
expected-vs-observed position reconciliation
idempotent retry
partial-fill reconciliation
restart/recovery checkpoint
cash and realized/unrealized PnL reconciliation
recovery runbook
```

A paper system is not credible until restart/retry behavior is explicitly tested.

### Phase 5D — Market semantics and cost calibration

Deliver:

```text
exchange calendars and sessions
corporate-action adjustments
spread model
ADV / participation estimates
nonlinear market-impact research
paper fill calibration against observed quotes where available
```

Phase 4 trade-weight caps remain a research liquidity proxy until this layer exists.

### Phase 5E — Shadow model lifecycle and observability

Deliver:

```text
shadow target vs paper target comparison
model/data freshness metrics
order/fill/reconciliation metrics
structured alerts
operational incident records
paper-trading reports
minimum sustained shadow-validation criteria
```

No live-capital milestone should precede sustained paper/shadow operation.

## Phase 5.5 — Structured Research Memory and Hypothesis Evolution

Use existing registries as structured Agent memory rather than adding a generic vector database to core state.

Deliver:

```text
feature/model lineage queries
hypothesis -> artifact -> experiment -> result graph
failure taxonomy
experiment similarity / duplicate detection
bounded reflection summaries
research-budget suggestions from historical evidence
```

Vector retrieval remains optional for unstructured papers, filings and notes.

## Phase 6 — Optional Workflow Orchestration Hardening

LangGraph or another graph runtime remains optional. Add it only if measured requirements justify:

```text
long-running resumable workflows
human checkpoints across hours/days
parallel research branches
provider retries with persisted state
complex recovery semantics
```

It must remain an adapter rather than a domain dependency.

## Phase 7 — Optional Advanced Learning

Potential later research:

```text
regime/change-point models
ML alpha models
Bayesian optimization inside frozen ExperimentFamily budgets
RL/MPC portfolio research
text/news/filing features
multi-Agent review
fundamental/style factor-risk model
```

Direct LLM or RL control of live portfolio weights is not a default objective.

## What remains deliberately deferred

Phase 4.5 supervision is not an operational trading system. The following remain unresolved until Phase 5:

```text
broker-specific order semantics
actual approval application
corporate actions
FX/cash accounting across currencies
position reconciliation
kill-switch implementation
restart recovery
production alert transport
operational security/credential handling
```

## Revised success criterion

FinAgent should be judged by whether a novel research hypothesis can be translated into reproducible PIT code and statistically governed evidence, transformed by deterministic alpha/risk/portfolio controls into an auditable target, supervised through immutable health evidence, and then verified through sustained paper/shadow operation before any live-capital path exists.
