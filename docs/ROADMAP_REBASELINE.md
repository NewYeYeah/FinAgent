# FinAgent Roadmap Rebaseline — After Phase 3D

Date: 2026-08-25

## Why the original roadmap should change

The initial roadmap correctly prioritized a deterministic Quant Engine, Research Control Plane and progressively governed Agent layer. After Phase 3D, however, the project has crossed an architectural threshold: it already contains most of the control-plane machinery originally expected much later, while several production-facing quantitative capabilities remain intentionally simplified.

Continuing directly into LangGraph, multi-Agent debate or broader autonomous code generation would therefore optimize orchestration before the generated research path is connected to realistic data, evaluation and portfolio operations.

The roadmap is rebalanced toward **research realism and portfolio productionization**.

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
```

This foundation is sufficient to stop treating additional Agent-framework complexity as the critical path.

## Revised remaining roadmap

### Phase 3.5 — Real Generated-Feature Research Integration

Priority: highest.

Goal: replace synthetic Agent fixtures with a real point-in-time numerical research loop.

Deliverables:

```text
GeneratedFeatureEvaluator
FeatureMaterializer
FeatureArtifact -> ResearchDataset column integration
nested walk-forward model/factor evaluation
IC / ICIR / turnover / net-return metrics
ExperimentResult lineage to generated feature digest
realistic transaction-cost configuration
reference historical-data fixture / reproducible example
```

A generated feature should be able to travel end-to-end:

```text
LLM feature
 -> validated artifact
 -> PIT materialization
 -> nested validation
 -> ExperimentFamily statistics
 -> candidate research result
```

without any synthetic evaluator.

### Phase 4 — Portfolio Research and Construction Hardening

Goal: move from reference allocation code toward a credible multi-asset allocation engine.

Deliverables:

```text
cross-sectional alpha ensemble
forecast calibration / uncertainty
covariance shrinkage + factor-risk option
risk-parity / minimum-variance baselines
constraint compiler
turnover / liquidity / exposure penalties
benchmark-relative and sector/factor constraints
stress/scenario interfaces
rebalancing policy
```

The `PortfolioTarget` contract remains canonical.

### Phase 4.5 — Low-Permission Portfolio Supervisor Agent

Goal: add Agent supervision without giving the LLM direct weight authority.

The Supervisor may:

```text
inspect data/model/risk health
explain forecast and target changes
select among pre-registered operating policies
request a rebalance or defensive mode
raise alerts and human-review requests
```

It may not:

```text
write arbitrary weights
change hard risk limits
bypass RiskGate
choose fills
alter broker state directly
```

### Phase 5 — Paper Trading / Shadow Production

Goal: verify backtest/live semantic consistency.

Deliverables:

```text
broker/paper adapter
exchange calendar handling
corporate-action adjustments
cash/FX accounting where required
order reconciliation
idempotency keys
partial-fill lifecycle
kill switch / circuit breakers
state recovery
observability and runbooks
shadow model lifecycle
```

No live-capital milestone should precede sustained paper/shadow operation.

### Phase 5.5 — Research Memory and Hypothesis Evolution

Goal: use the existing registries as structured Agent memory rather than adding an early vector-memory dependency.

Deliverables:

```text
feature/model lineage queries
failure taxonomy
experiment similarity / duplicate detection
hypothesis -> artifact -> result graph
bounded reflection summaries
research-budget allocation from historical evidence
```

Vector retrieval may be added only for papers/reports/unstructured notes.

### Phase 6 — Optional Workflow Orchestration Hardening

LangGraph or another graph runtime is now explicitly optional.

Introduce it only if measured requirements justify:

```text
long-running resumable research
human-in-the-loop checkpoints
parallel branches
provider retries across multi-hour workflows
complex recovery state
```

It remains an adapter, not a domain dependency.

### Phase 7 — Optional Advanced Learning

Potential later work:

```text
regime models / change-point detection
ML alpha models
Bayesian optimization inside fixed experiment families
RL/MPC portfolio research
text/news/filing features
multi-Agent review
```

Direct LLM or RL control of live portfolio weights is not a default roadmap objective.

## Items intentionally de-prioritized

The following items move later than originally imagined:

1. Multi-Agent TradingAgents-style debate — no demonstrated need yet.
2. LangGraph migration — current deterministic coordinator/replay path is sufficient.
3. Autonomous arbitrary project code generation — feature-only generation is a safer and more useful boundary.
4. RL direct allocation — should wait until execution, cost and paper-trading semantics are credible.
5. Live broker execution — paper/shadow validation comes first.

## Revised project success criterion

The project should no longer be judged by how many Agent components it contains. The primary engineering criterion is now:

> A novel research hypothesis can be translated into reproducible point-in-time code and statistically governed evidence, then—only after deterministic portfolio/risk controls—into an auditable paper-trading target.

That criterion keeps the Agent as a research capability multiplier rather than the owner of financial state.
