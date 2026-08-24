# FinAgent

FinAgent is a typed, auditable foundation for quantitative research, portfolio construction, risk control, backtesting and future agent orchestration.

The project is currently at **Phase 0.5: Domain Kernel + Test Harness**. This phase intentionally avoids LLM frameworks, pandas-as-contract, broker APIs and heavyweight quantitative frameworks. The purpose is to freeze the internal contracts before AR/GARCH models, portfolio optimizers, research agents and broker adapters are added.

## Phase 0.5 objective

The canonical trading path is:

```text
MarketSnapshot
    -> AlphaForecast
    -> RiskForecast
    -> PortfolioTarget
    -> RiskDecision
    -> OrderIntent
    -> Fill
    -> PortfolioState
```

The canonical research path is:

```text
ResearchDataset
    -> ExperimentSpec
    -> ExperimentRun
    -> ExperimentResult
    -> ArtifactRef / lineage
```

A hard design rule is that **raw pandas DataFrames are not allowed as cross-module public contracts**. Adapters and internal numerical implementations may use pandas later, but module boundaries use explicit typed domain objects.

## What is implemented

### Domain contracts

- `AssetId`, `AssetType`
- `PriceBar`, `MarketSnapshot`
- `ResearchDataset`, `TimeRange`
- `ModelRef`, `AlphaForecast`, `RiskForecast`
- `PortfolioState`, `PortfolioTarget`
- `RiskDecision`, `RiskStatus`, `RiskViolation`
- `OrderIntent`, `OrderSide`, `OrderType`
- `Fill`, `OrderRejection`, `ExecutionReport`
- `ArtifactRef`, `ExperimentSpec`, `ExperimentRun`, `ExperimentResult`

### Ports

`finagent.ports` defines framework-independent protocols for:

- alpha models;
- risk models;
- portfolio optimizers;
- risk gates;
- execution venues.

These protocols are the intended attachment points for later Qlib, bt, LangGraph and broker adapters.

### Phase 0.5 reference services

The package also includes intentionally small deterministic implementations used to prove the contracts work end to end:

- `EqualWeightTargetBuilder`
- `StaticRiskGate`
- `OrderPlanner`
- `SimulatedExchange`
- `AccountLedger`

They are not intended to be production portfolio/risk/execution algorithms. They are a test harness for the architecture.

## Key invariants

### Point-in-time safety

`PriceBar` distinguishes:

- `event_time`: timestamp represented by the observation;
- `available_at`: timestamp when the system could actually know the observation.

`MarketSnapshot` rejects any bar with:

```text
available_at > snapshot.asof
```

This creates an explicit look-ahead guard at the domain boundary.

### Portfolio accounting identity

Every `PortfolioTarget` must satisfy:

```text
sum(asset_weights) + cash_weight = 1
```

Long/short portfolios are supported. Gross exposure is calculated separately as:

```text
sum(abs(asset_weight))
```

Therefore a market-neutral or levered portfolio is not silently normalized as if it were long-only.

### Risk is explicit and non-mutating

The risk layer does not silently rescale a portfolio. It returns one of:

- `APPROVE`
- `REJECT`
- `REQUIRE_RESOLVE`

with explicit `RiskViolation` objects. `OrderPlanner` refuses to create orders from a non-approved target.

### Research reproducibility

`ExperimentSpec.fingerprint` includes:

- hypothesis;
- dataset artifact ID/version/digest;
- code artifact ID/version/digest;
- universe;
- parameters;
- random seed;
- parent artifact lineage.

The result is a SHA-256 fingerprint. This avoids identifying experiments only by a factor name or expression.

## Repository layout

```text
FinAgent/
├── src/finagent/
│   ├── domain/
│   │   ├── _validation.py
│   │   ├── assets.py
│   │   ├── execution.py
│   │   ├── experiments.py
│   │   ├── forecasts.py
│   │   ├── market.py
│   │   ├── orders.py
│   │   ├── portfolio.py
│   │   └── research.py
│   ├── services/
│   │   ├── execution.py
│   │   └── portfolio.py
│   ├── ports.py
│   └── __init__.py
├── tests/
├── docs/
│   └── DEVLOG.md
├── pyproject.toml
└── README.md
```

## Development setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest
```

For a lightweight local run without installation:

```bash
PYTHONPATH=src pytest -q
```

## Current test status

Phase 0.5 currently contains **26 tests** covering:

- asset identity normalization and validation;
- timezone and OHLC validation;
- point-in-time look-ahead rejection;
- immutable mapping boundaries;
- alpha/risk forecast validation;
- covariance completeness and symmetry;
- portfolio NAV and weight accounting;
- long/short target accounting;
- explicit risk decisions;
- order generation and risk approval enforcement;
- simulated slippage and commissions;
- fill-to-ledger accounting;
- research dataset schema contracts;
- experiment fingerprints and run lifecycle validation;
- complete equal-weight smoke path from target to final portfolio state.

Local Phase 0.5 result:

```text
26 passed
```

## Phase 1 direction

The next implementation phase should add numerical research components without changing the contracts above:

1. point-in-time data adapter and local data store;
2. return benchmark and random-walk diagnostics;
3. AR/ARMA short-horizon alpha model;
4. ARCH/GARCH volatility forecast;
5. covariance estimator;
6. first portfolio optimizer;
7. event-driven backtest clock and richer exchange simulator;
8. artifact/experiment registry backed by SQLite;
9. adapters for selected third-party frameworks where justified.

Any third-party code migration should first document source commit, license, input/output schema, side effects, time semantics, hidden state and regression tests.
