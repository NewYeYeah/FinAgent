# Phase 1 — Numerical Quant Kernel

Phase 1 implements the first complete numerical vertical slice behind the Phase 0.5 domain contracts.

## Implemented pipeline

```text
PIT OHLCV
  -> DataAdapter
  -> ResearchDataset (T x N x F)
  -> Random-walk diagnostics / benchmark
  -> AR(p) / ARMA(1,1) alpha
  -> GARCH(1,1) volatility
  -> EWMA + shrinkage covariance/correlation
  -> Mean-Variance PortfolioTarget
  -> StaticRiskGate
  -> OrderPlanner
  -> SimulatedExchange / VolumeAwareSimulatedExchange
  -> AccountLedger
  -> EventDrivenBacktestEngine
  -> SQLite research registry
```

## Data subsystem

Implemented adapters:

- `InMemoryPriceDataAdapter`
- `CSVPriceDataAdapter`
- `SQLitePriceDataAdapter`

Implemented local store:

- `SQLitePriceStore`

PIT rules are based on `PriceBar.available_at`, not only the economic/event timestamp.

## Alpha subsystem

### Random walk

`RandomWalkAlphaModel` emits zero expected return and serves as the null benchmark.

`RandomWalkDiagnostics` reports:

- mean/std;
- autocorrelation;
- Ljung-Box Q statistic;
- Ljung-Box p-value.

### AR(p)

`ARAlphaModel` estimates per-asset:

```text
r[t+1] = c + beta[1] r[t] + ... + beta[p] r[t-p+1] + e[t+1]
```

using OLS and emits residual standard deviation as forecast uncertainty.

### ARMA(1,1)

`ARMA11AlphaModel` estimates by conditional sum of squares:

```text
r[t] = c + phi r[t-1] + theta e[t-1] + e[t]
```

Prediction reconstructs residual state from the supplied PIT feature window rather than storing hidden online state.

## Risk subsystem

### GARCH(1,1)

`GARCH11Estimator` estimates:

```text
sigma[t]^2 = omega + alpha * r[t-1]^2 + beta * sigma[t-1]^2
```

under Gaussian quasi-maximum likelihood with the stationarity constraint:

```text
alpha + beta < 1
```

### Covariance

`EWMACovarianceEstimator`:

- drops rows with incomplete multi-asset observations;
- applies exponentially decaying weights;
- supports diagonal shrinkage;
- projects the result to the PSD cone.

`GARCH11RiskModel` combines GARCH marginal volatility with EWMA correlation to produce a full `RiskForecast` covariance matrix.

`RiskForecast` now rejects non-PSD covariance matrices at the domain boundary.

## Portfolio subsystem

`MeanVarianceOptimizer` solves a constrained Markowitz problem:

```text
min  -mu' w + 0.5 * lambda * w' Sigma w + gamma * turnover(w, w_prev)
```

subject to a fixed invested weight and configurable long-only/weight bounds.

The result is always the canonical `PortfolioTarget`; the optimizer never talks directly to execution code.

## Backtest subsystem

`EventDrivenBacktestEngine`:

- fits alpha/risk models on the configured train split only;
- iterates test timestamps sequentially;
- requests only PIT-safe feature windows;
- marks the account before each decision;
- constructs a target;
- runs the hard risk gate;
- creates broker-agnostic orders;
- simulates fills and updates the account;
- reports return, volatility, Sharpe, drawdown, turnover and transaction cost.

### Phase 1 execution convention

The backtest currently uses an idealised close-on-close convention: a signal may use the bar available at time `t` and the rebalance is applied at that same observed close. The new position affects P&L only after `t`.

This is suitable for architecture and daily research tests but is not a production microstructure assumption. Phase 2 should add separate quote/open/close availability and next-bar execution semantics.

## Execution models

`SimulatedExchange` supports fixed adverse slippage and commissions.

`VolumeAwareSimulatedExchange` additionally implements:

- maximum participation rate;
- partial fills through volume clipping;
- participation-dependent market impact.

## Research registry

`SQLiteResearchRegistry` persists and round-trips:

- `ArtifactRef`;
- `ExperimentSpec`;
- `ExperimentRun`;
- `ExperimentResult`.

The model/dataset/code digests already flow into experiment fingerprints established in Phase 0.5.

## Explicit limitations / deferred work

Phase 1 does **not** claim production trading readiness. The following are intentionally deferred:

- rolling/expanding walk-forward refitting;
- purge/embargo and nested CV;
- multiple-testing correction / Deflated Sharpe / SPA;
- corporate actions and survivorship-safe equity universe history;
- multi-currency accounting;
- borrow/short locate constraints;
- order book and queue simulation;
- next-bar/open execution timestamp semantics;
- persistent model binary serialization;
- broker APIs;
- Qlib/bt adapters (not yet justified by a missing core capability);
- LLM/Agent orchestration.

These belong to subsequent phases and should not alter ADR-007 without an explicit architecture decision.
