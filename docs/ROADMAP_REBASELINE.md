# FinAgent Roadmap Rebaseline — After Phase 4

Date: 2026-08-25

## Why the roadmap changed

The original plan correctly prioritized a deterministic Quant Engine, Research Control Plane and progressively governed Agent layer. By Phase 3D the control plane was already mature enough that further LangGraph/multi-Agent work would have optimized orchestration before quantitative realism. Phase 3.5 and Phase 4 therefore moved the critical path back to PIT research, expected-return calibration, risk estimation and portfolio construction.

## Completed foundation

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
```

Phase 4 now provides:

```text
cross-sectional feature -> expected-return calibration
explicit alpha forecast ensembles
OAS covariance shrinkage
PCA statistical factor-risk option
asset/group/benchmark-active/factor exposure constraints
turnover and per-asset trade-weight limits
cost-aware constrained mean variance
minimum variance / risk parity / equal-weight baselines
stress-scenario evaluation
explicit drift/turnover rebalance policy
```

`PortfolioTarget` remains canonical and no LLM has direct portfolio-weight authority.

## Remaining roadmap

### Phase 4.5 — Low-Permission Portfolio Supervisor Agent

Goal: supervise deterministic portfolio infrastructure without becoming the portfolio optimizer.

The Supervisor may:

```text
inspect alpha/risk/model/data health
inspect benchmark comparisons and stress results
explain target changes
select among pre-registered operating/rebalance policies
request defensive mode / rebalance / human review
raise alerts
```

It may not:

```text
write arbitrary weights
change hard risk limits
bypass RiskGate
choose fills
mutate broker/account state directly
```

Priority engineering work:

```text
PortfolioHealthSnapshot
SupervisorAction allowlist
policy-selection registry
stress/risk alert rules
supervisor audit/replay
human-review request contract
```

### Phase 5 — Paper Trading / Shadow Production

Goal: verify research/backtest/live semantic consistency before any real capital path.

Deliverables:

```text
paper broker adapter
exchange calendars/sessions
corporate-action adjustments
cash/FX accounting where required
order reconciliation and idempotency
partial-fill lifecycle
kill switch / circuit breakers
state recovery
observability and runbooks
shadow model lifecycle
spread/participation/impact calibration
```

No live-capital milestone should precede sustained paper/shadow operation.

### Phase 5.5 — Research Memory and Hypothesis Evolution

Use existing registries as structured Agent memory:

```text
feature/model lineage queries
failure taxonomy
experiment similarity and duplicate detection
hypothesis -> artifact -> result graph
bounded reflection summaries
research-budget allocation from historical evidence
```

Vector retrieval remains optional for unstructured papers/reports rather than core experiment state.

### Phase 6 — Optional Workflow Orchestration Hardening

LangGraph or another graph runtime remains optional. Add it only if measured requirements justify long-running resumable workflows, human checkpoints, parallel branches or complex provider recovery.

### Phase 7 — Optional Advanced Learning

Potential later work:

```text
regime/change-point models
ML alpha models
Bayesian optimization inside fixed experiment families
RL/MPC portfolio research
text/news/filing features
multi-Agent review
```

Direct LLM or RL control of live portfolio weights is not a default roadmap objective.

## Deliberately deferred production details

Although Phase 4 adds a statistical PCA factor-risk baseline, exposure compiler, trade caps, stress tests and rebalance policy, it does not claim a production institutional stack. The following remain Phase 5-oriented:

```text
fundamental industry/style risk model
security master/corporate actions
ADV and intraday participation forecasts
nonlinear impact curves
broker-specific order semantics
reconciliation and recovery
```

## Project success criterion

FinAgent should be judged by whether a novel research hypothesis can be translated into reproducible PIT code and statistically governed evidence, transformed by deterministic alpha/risk/portfolio controls into an auditable target, and then verified through paper/shadow operation.

The Agent is a research and supervision capability multiplier, not the owner of financial state.
