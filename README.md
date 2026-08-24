# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure designed so that a future Agent can orchestrate research without entering the numerical trading hot path.

Current status: **Phase 2.5 — Nested Validation and Anti-Overfitting Controls**.

The architectural rule is:

```text
Agent:
  chooses approved research actions, registered tools and explanations.

Deterministic code:
  owns data timing, statistics, forecasts, portfolio weights,
  risk approval, validation splits, execution and model promotion policy.
```

No LLM or Agent framework is required by the core package.

## Architecture

Research/numerical path:

```text
DataAdapter
    -> ResearchDataset / ResearchSplit
    -> FeatureWindow
    -> AlphaModel / RiskModel
    -> AlphaForecast / RiskForecast
    -> PortfolioOptimizer
    -> PortfolioTarget
    -> RiskGate
    -> RiskDecision
```

Phase 2 timed execution path:

```text
information_at
    -> PIT FeatureWindow + MarketSnapshot
    -> forecasts / target / risk approval
    -> OrderIntent
    -> execution_at > information_at
    -> ExecutionSnapshot
    -> TimedExecutionVenue
    -> Fill / ExecutionReport
    -> AccountLedger
    -> PortfolioState
```

Research-governance path:

```text
ExperimentFamily(OPEN)
    -> ExperimentSpec[]
    -> nested inner validation
    -> ExperimentRunner
    -> ExperimentResult[]
    -> ExperimentFamily(FROZEN)
    -> multiplicity / DSR / PBO / reality check
    -> outer holdout evaluation
    -> RegisteredModel
    -> candidate -> validated -> paper -> shadow -> live -> retired
```

## Frozen Phase 1 numerical interface

See [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md).

Canonical numerical layouts are:

```text
ResearchSplit.feature_values.shape = (time, asset, feature)
ResearchSplit.label_values.shape   = (time, asset, label)
FeatureWindow.values.shape         = (time, asset, feature)
```

The Phase 1 `DataAdapter` remains unchanged:

```python
build_dataset(request) -> ResearchDataset
feature_window(asof, universe, features, lookback) -> FeatureWindow
market_snapshot(asof, universe) -> MarketSnapshot
calendar(start, end, universe) -> tuple[datetime, ...]
```

Important invariants:

- `TimeRange` is half-open: `[start, end)`;
- public numerical arrays are `float64`, defensive-copy and read-only;
- missing values use `NaN`; infinity is rejected;
- `available_at` is the research point-in-time clock;
- forward labels cannot cross split boundaries;
- pandas/Qlib/vendor schemas stay behind adapters rather than becoming public contracts.

## Phase 1 Quant Kernel

### Data

Implemented:

- `InMemoryPriceDataAdapter`
- `CSVPriceDataAdapter`
- `SQLitePriceDataAdapter`
- `SQLitePriceStore`
- deterministic dataset SHA-256 digests
- PIT-safe feature windows
- split-isolated forward labels

Built-in features include:

```text
close
volume
log_return_N
simple_return_N
squared_log_return_N
log_volume_change_N
```

Built-in labels:

```text
forward_log_return_N
forward_simple_return_N
```

### Alpha

- `RandomWalkAlphaModel`
- `RandomWalkDiagnostics` with ACF / Ljung-Box
- `ARAlphaModel(order=p)`
- `ARMA11AlphaModel`

### Risk

- `GARCH11Estimator`
- `GARCH11RiskModel`
- `EWMACovarianceEstimator`
- PSD-validated `RiskForecast`

The default multivariate risk construction is:

```text
GARCH marginal volatility
    +
EWMA/shrunk correlation
    ->
PSD covariance forecast
```

### Portfolio and risk gate

`MeanVarianceOptimizer` supports risk aversion, cash allocation, long-only/long-short bounds, maximum absolute weight and turnover penalty.

The accounting identity is always:

```text
sum(asset_weights) + cash_weight = 1
```

Gross and net exposure are tracked separately. `StaticRiskGate` is deterministic and non-mutating: it returns `APPROVE`, `REJECT`, or `REQUIRE_RESOLVE` with explicit violations.

### Phase 1 execution benchmark

- `SimulatedExchange`
- `VolumeAwareSimulatedExchange`
- `OrderPlanner`
- `AccountLedger`
- `EventDrivenBacktestEngine`

The Phase 1 engine remains available as an idealised close-on-close research benchmark.

## Phase 2: purged walk-forward validation

See [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md).

Implemented:

```text
WalkForwardConfig
WalkForwardFold
PurgedWalkForwardSplitter
minimum_purge_bars
```

Canonical chronological fold:

```text
train | purge | embargo | test
```

For canonical labels such as:

```text
forward_log_return_5
```

Phase 2 requires, by default:

```text
purge_bars >= 5
```

Both rolling and expanding training windows are supported. Fold datasets are materialized through the normal `DataAdapter -> DatasetRequest -> ResearchDataset` path, so walk-forward validation does not introduce a second numerical data contract.

In the strictly forward-only protocol, `embargo_bars` is an additional pre-test exclusion zone. FinAgent does not train on future observations in these folds.

## Phase 2: separate information and execution clocks

Phase 2 adds an execution-specific boundary instead of changing the frozen research `DataAdapter`:

```python
ExecutionDataAdapter.execution_calendar(...)
ExecutionDataAdapter.execution_snapshot(...)
```

New domain objects:

```text
ExecutionQuote
ExecutionSnapshot
```

`ExecutionSnapshot` exposes only the executable field. It does not expose an entire OHLC bar.

For the built-in bar adapter:

```text
open  -> executable at PriceBar.event_time
close -> executable at PriceBar.available_at
```

High/low are intentionally not valid execution fields because the current bar schema has no deterministic timestamp for when those extrema became known.

`TimedEventDrivenBacktestEngine` enforces:

```text
execution_at > information_at
```

and defaults to one executable-event lag using the next open. `TimedSimulatedExchange` supports commission, adverse slippage, participation clipping and participation-based impact on these field-level quotes.

## Phase 2: experiment and model governance

See [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md).

`ExperimentRunner` now owns the durable experiment lifecycle:

```text
register inputs
 -> RUNNING
 -> evaluator
 -> result/artifacts
 -> SUCCEEDED or FAILED
```

Failed runs are persisted before the exception is propagated.

`SQLiteResearchRegistry` now persists:

- artifacts;
- experiment specs;
- experiment runs;
- experiment results;
- registered models;
- model-stage audit events.

Model lifecycle:

```text
CANDIDATE
 -> VALIDATED
 -> PAPER
 -> SHADOW
 -> LIVE
 -> RETIRED
```

Stage skipping is rejected. A model stage cannot be changed by overwriting the registration record; transitions must call the governed promotion API.

Phase 2 also fixes a subtle SQLite lifecycle bug: run-state updates use UPSERT rather than `INSERT OR REPLACE`, because SQLite `REPLACE` can delete the parent run row and cascade-delete its already stored result.

## Phase 2.5: nested validation and research multiplicity

See [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md) and [`docs/PHASE2_5.md`](docs/PHASE2_5.md).

Phase 2.5 governs the research search process itself. A point-in-time-safe backtest can still be overfit if many valid trials are run and only the winner is reported.

Nested chronological validation is now explicit:

```text
outer train
    -> inner train | purge | embargo | validation
    -> model/config selection
outer purge | outer embargo | outer test
```

New walk-forward types:

```text
NestedWalkForwardConfig
NestedWalkForwardFold
NestedWalkForwardDatasets
NestedPurgedWalkForwardSplitter
```

Related research trials are pre-registered as an `ExperimentFamily` with lifecycle:

```text
OPEN -> FROZEN -> CLOSED
```

Only OPEN families may accept new trials. Family-level inference requires FROZEN status, and `ExperimentFamilyValidator` rejects any return/p-value input that does not contain exactly the registered family denominator.

Implemented anti-overfitting statistics:

- Bonferroni, Holm and Benjamini-Hochberg p-value correction;
- Deflated Sharpe Ratio probability;
- CSCV Probability of Backtest Overfitting;
- White-style reality check with circular moving-block bootstrap;
- decomposed `FamilyValidationReport` and deterministic pass/fail gate.

Phase 2.5 also replaces `INSERT OR REPLACE` on experiment/family/model parent records with UPSERT so idempotent registration cannot cascade-delete family membership or model-stage audit history.

## Repository layout

```text
FinAgent/
├── src/finagent/
│   ├── analysis/
│   │   └── random_walk.py
│   ├── backtest/
│   │   ├── engine.py
│   │   ├── timed.py
│   │   └── walk_forward.py
│   ├── data/
│   │   ├── adapters.py
│   │   └── store.py
│   ├── domain/
│   │   ├── assets.py
│   │   ├── execution.py
│   │   ├── experiment_family.py
│   │   ├── experiments.py
│   │   ├── forecasts.py
│   │   ├── market.py
│   │   ├── model_registry.py
│   │   ├── orders.py
│   │   ├── portfolio.py
│   │   └── research.py
│   ├── models/
│   │   ├── alpha/
│   │   └── risk/
│   ├── portfolio/
│   │   └── mean_variance.py
│   ├── research/
│   │   ├── family_validation.py
│   │   ├── registry.py
│   │   ├── runner.py
│   │   └── validation.py
│   ├── services/
│   │   ├── execution.py
│   │   └── portfolio.py
│   ├── ports.py
│   └── __init__.py
├── tests/
├── docs/
│   ├── ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md
│   ├── ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md
│   ├── ADR-009_PHASE2_MODEL_GOVERNANCE.md
│   ├── ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md
│   ├── PHASE1.md
│   ├── PHASE2.md
│   ├── PHASE2_5.md
│   ├── PHASE3_PLAN.md
│   └── DEVLOG.md
├── pyproject.toml
└── README.md
```

## Development setup

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest
```

Source-tree execution is also supported:

```bash
PYTHONPATH=src pytest -q
```

## Test status

Phase 0.5 + Phase 1 + Phase 2 + Phase 2.5 currently contain **69 tests**.

Coverage includes:

- domain and point-in-time validation;
- immutable numerical panels;
- feature/label alignment and split isolation;
- AR/ARMA/GARCH/covariance models;
- mean-variance portfolio constraints;
- risk gating and account accounting;
- fixed, volume-aware and timed execution;
- purged/embargoed walk-forward generation;
- open-vs-close field-level availability;
- information/execution-time separation;
- experiment success/failure lifecycle;
- model promotion policy and audit history;
- complete Phase 1/2 numerical vertical slices;
- nested inner/outer isolation and experiment-family denominator locking;
- multiple-testing, DSR, PBO and White reality-check controls.

Current local result:

```text
69 passed
```

## Current limitations / next engineering layer

Phase 2.5 completes the deterministic statistical substrate required before introducing an LLM Research Agent. Remaining non-Agent quant-platform work includes point-in-time universe membership/corporate actions, exchange-session calendars, multi-currency/borrow constraints, persistent model binaries and broker adapters.

The immediate next engineering layer is **Phase 3 — Research Agent Control Plane**. The implementation order is intentionally:

```text
Agent contracts
 -> deterministic research tools
 -> policy-as-code
 -> single Research Agent
 -> structured Agent audit/memory
 -> sandboxed feature code generation
 -> optional LangGraph adapter
```

The Agent will orchestrate approved experiments and governance requests. It will not calculate weights, bypass the risk gate, select executable prices, reduce a frozen experiment-family denominator or promote a model directly to LIVE. See [`docs/PHASE3_PLAN.md`](docs/PHASE3_PLAN.md).

## Design documentation

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/PHASE1.md`](docs/PHASE1.md)
- [`docs/PHASE2.md`](docs/PHASE2.md)
- [`docs/PHASE2_5.md`](docs/PHASE2_5.md)
- [`docs/PHASE3_PLAN.md`](docs/PHASE3_PLAN.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
