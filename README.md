# FinAgent

FinAgent is a typed, auditable quantitative research and portfolio infrastructure designed to support later Agent-based research and supervision without putting an LLM in the numerical trading hot path.

The repository is currently at **Phase 1: Numerical Quant Kernel**.

The project principle is:

```text
Agent decides what to research / which registered tools to call / how to explain.
Deterministic code decides numerical values / significance / portfolio weights / risk approval / execution.
```

## Architecture

Canonical trading path:

```text
DataAdapter
    -> FeatureWindow / ResearchDataset
    -> AlphaModel
    -> AlphaForecast
    -> RiskModel
    -> RiskForecast
    -> PortfolioOptimizer
    -> PortfolioTarget
    -> RiskGate
    -> RiskDecision
    -> OrderPlanner
    -> OrderIntent
    -> ExecutionVenue
    -> Fill / ExecutionReport
    -> AccountLedger
    -> PortfolioState
```

Canonical research path:

```text
Dataset artifact
    -> ExperimentSpec
    -> ExperimentRun
    -> ExperimentResult
    -> ArtifactRef / model lineage
```

Raw pandas DataFrames are **not** public cross-module contracts. NumPy is used for the Phase 1 numerical kernel, while future pandas/Qlib/Parquet integrations must live behind adapters.

## Frozen Phase 1 numerical interface

See [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md).

The fixed numerical panel layout is:

```text
ResearchSplit.feature_values.shape = (time, asset, feature)
ResearchSplit.label_values.shape   = (time, asset, label)
FeatureWindow.values.shape         = (time, asset, feature)
```

or:

```text
T x N x F
```

Important invariants:

- `TimeRange` is half-open: `[start, end)`;
- numerical arrays are defensive copies and read-only;
- missing observations are `NaN`;
- `+/-inf` is rejected;
- `available_at` is the point-in-time research clock;
- forward labels are not allowed to cross split boundaries;
- `MarketSnapshot` is for valuation/execution;
- `FeatureWindow` is for model inference.

The canonical `DataAdapter` provides:

```python
build_dataset(request) -> ResearchDataset
feature_window(asof, universe, features, lookback) -> FeatureWindow
market_snapshot(asof, universe) -> MarketSnapshot
calendar(start, end, universe) -> tuple[datetime, ...]
```

`AlphaModel` and `RiskModel` expose:

```python
required_features
min_lookback
fit(dataset, split="train") -> ArtifactRef
predict(window) -> AlphaForecast / RiskForecast
```

## Phase 1 implemented components

### Data

- `InMemoryPriceDataAdapter`
- `CSVPriceDataAdapter`
- `SQLitePriceDataAdapter`
- `SQLitePriceStore`
- deterministic dataset SHA-256 digests
- PIT-safe `feature_window`
- split-isolated forward labels

Built-in feature names currently include:

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

### Random-walk benchmark and diagnostics

- `RandomWalkAlphaModel`: zero-drift benchmark
- `RandomWalkDiagnostics`
  - return mean/std
  - ACF
  - Ljung-Box Q
  - Ljung-Box p-value

### Alpha models

- `ARAlphaModel(order=p)`
- `ARMA11AlphaModel`

AR uses explicit feature/forward-label alignment from the DataAdapter. ARMA(1,1) reconstructs residual state from the supplied feature window instead of depending on hidden mutable online state.

### Risk models

- `GARCH11Estimator`
- `GARCH11RiskModel`
- `EWMACovarianceEstimator`

The risk pipeline combines:

```text
GARCH marginal volatility
    +
EWMA/shrunk correlation
    ->
PSD covariance RiskForecast
```

`RiskForecast` validates matrix completeness, symmetry, diagonal/volatility consistency and positive semidefiniteness.

### Portfolio construction

`MeanVarianceOptimizer` implements constrained Markowitz allocation with configurable:

- risk aversion;
- cash weight;
- long-only vs long/short bounds;
- maximum absolute asset weight;
- turnover penalty.

The canonical portfolio accounting identity remains:

```text
sum(asset_weights) + cash_weight = 1
```

Gross and net exposure are tracked separately.

### Hard risk gate

`StaticRiskGate` remains deterministic and non-mutating.

Risk never silently rewrites a target. It returns:

```text
APPROVE
REJECT
REQUIRE_RESOLVE
```

with explicit violations.

### Execution and account simulation

- `SimulatedExchange`
  - fixed commission
  - fixed adverse slippage
- `VolumeAwareSimulatedExchange`
  - maximum participation rate
  - volume clipping / partial fills
  - participation-dependent impact
- `OrderPlanner`
- `AccountLedger`

### Backtest

`EventDrivenBacktestEngine` executes the complete Phase 1 out-of-sample numerical path:

```text
train-only fit
    ->
sequential PIT test windows
    ->
alpha/risk forecasts
    ->
optimizer
    ->
risk gate
    ->
orders/fills
    ->
marked account
```

Reported metrics include:

- total return;
- annualized return;
- annualized volatility;
- Sharpe;
- max drawdown;
- turnover;
- transaction cost.

The current Phase 1 simulator uses an idealised close-on-close research convention. The newly established position affects returns only after the decision timestamp. Finer open/quote availability and next-bar execution semantics are deferred to Phase 2.

### Research registry

`SQLiteResearchRegistry` persists:

- `ArtifactRef`
- `ExperimentSpec`
- `ExperimentRun`
- `ExperimentResult`

This provides the first durable substrate for a later Research Agent.

## Repository layout

```text
FinAgent/
├── src/finagent/
│   ├── analysis/
│   │   └── random_walk.py
│   ├── backtest/
│   │   └── engine.py
│   ├── data/
│   │   ├── adapters.py
│   │   └── store.py
│   ├── domain/
│   │   ├── assets.py
│   │   ├── execution.py
│   │   ├── experiments.py
│   │   ├── forecasts.py
│   │   ├── market.py
│   │   ├── orders.py
│   │   ├── portfolio.py
│   │   └── research.py
│   ├── models/
│   │   ├── alpha/
│   │   │   ├── ar.py
│   │   │   ├── arma.py
│   │   │   └── random_walk.py
│   │   └── risk/
│   │       ├── covariance.py
│   │       └── garch.py
│   ├── portfolio/
│   │   └── mean_variance.py
│   ├── research/
│   │   └── registry.py
│   ├── services/
│   │   ├── execution.py
│   │   └── portfolio.py
│   ├── ports.py
│   └── __init__.py
├── tests/
├── docs/
│   ├── ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md
│   ├── PHASE1.md
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

A source-tree-only run is also supported:

```bash
PYTHONPATH=src pytest -q
```

## Current test status

Phase 0.5 + Phase 1 currently contain **45 tests**.

They cover:

- asset/time/PIT validation;
- immutable numerical panel contracts;
- data adapter feature/label alignment;
- split-boundary leakage prevention;
- SQLite market-data persistence;
- random-walk diagnostics;
- AR fitting/prediction;
- ARMA fitting/prediction;
- GARCH parameter constraints and variance forecasts;
- EWMA covariance and PSD projection;
- PSD `RiskForecast` validation;
- mean-variance optimization;
- explicit risk gating;
- fixed and volume-aware execution costs;
- fill/account accounting;
- experiment/registry persistence;
- complete Phase 1 numerical end-to-end backtest.

Current local result:

```text
45 passed
```

## Current limitations

Phase 1 is a research kernel, not a production trading system. Not yet implemented:

- rolling/expanding model refit;
- purged/embargoed walk-forward validation;
- multiple-testing control / Deflated Sharpe / SPA;
- survivorship-safe historical universe membership;
- corporate actions;
- multi-currency FX accounting;
- short borrow/locate constraints;
- order-book/queue simulation;
- separate open/close/quote availability events;
- persistent binary model serialization;
- live broker adapters;
- Qlib/bt integration adapters;
- LLM Research Agent / Portfolio Supervisor Agent.

These are subsequent phases. Agent code should not be introduced until the quantitative validation and experiment lifecycle are stronger.

## Design documentation

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md): frozen numerical interface.
- [`docs/PHASE1.md`](docs/PHASE1.md): numerical implementation and known limitations.
- [`docs/DEVLOG.md`](docs/DEVLOG.md): chronological development log.
