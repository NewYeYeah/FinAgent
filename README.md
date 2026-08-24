# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure designed so that a future Agent can orchestrate research without entering the numerical trading hot path.

Current status: **Phase 2 — Validation, Execution Timing, and Model Governance**.

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
ArtifactRef + ExperimentSpec
    -> ExperimentRunner
    -> RUNNING
    -> numerical evaluator
    -> ExperimentResult
    -> SUCCEEDED / FAILED
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
│   │   ├── registry.py
│   │   └── runner.py
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
│   ├── PHASE1.md
│   ├── PHASE2.md
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

Phase 0.5 + Phase 1 + Phase 2 currently contain **55 tests**.

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
- complete Phase 1 and Phase 2 numerical vertical slices.

Current local result:

```text
55 passed
```

## Current limitations / next engineering layer

Phase 2 is still research infrastructure, not a live trading platform. The next priority is statistical model-selection control rather than adding more predictors:

- nested walk-forward hyperparameter selection;
- multiple-hypothesis correction and experiment-family tracking;
- Deflated Sharpe Ratio / Probability of Backtest Overfitting;
- White Reality Check / SPA-style benchmark comparison;
- point-in-time universe membership and corporate actions;
- exchange calendars and session-aware clocks;
- multi-currency and borrow/locate constraints;
- persistent model binary serialization;
- live broker adapters.

The first Research Agent should be added only after those controls provide a deterministic tool surface. The Agent should orchestrate approved experiments and model-governance calls; it should not calculate weights, bypass the risk gate, select executable prices, or mutate model stages directly.

## Design documentation

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/PHASE1.md`](docs/PHASE1.md)
- [`docs/PHASE2.md`](docs/PHASE2.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
