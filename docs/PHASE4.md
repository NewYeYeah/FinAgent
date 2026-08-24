# Phase 4 — Alpha Calibration, Risk Hardening and Portfolio Research

Phase 4 moves FinAgent from generated-feature evidence toward a stronger deterministic allocation layer.

## Objectives

```text
4A  Calibrate research signals into AlphaForecast objects and combine alphas.
4B  Improve covariance/risk estimation and centralize portfolio constraints.
4C  Compare portfolio constructors, stress targets and make explicit rebalance decisions.
```

The key architectural invariant remains:

```text
Agent/LLM -> research proposal and supervision
Quant core -> expected returns, covariance, constraints, weights, risk, execution
```

## Phase 4A — alpha calibration and ensemble

`CrossSectionalLinearAlphaCalibrator` consumes a caller-selected `ResearchSplit`, standardizes each feature cross-section and fits a pooled ridge-regularized mapping from score to forward return. It records intercept, slope, residual uncertainty, R² and sample counts and emits canonical `AlphaForecast` objects at inference.

`AlphaForecastEnsembler` requires aligned `asof`, horizon and universe, then combines forecasts using explicit normalized quantitative weights. `quality_weights` is a deterministic helper for validated research-quality scores.

The calibrator never selects training/test windows by itself and the ensemble never grants weight authority to an LLM.

## Phase 4B — risk models

### OAS covariance

`OASCovarianceEstimator`:

```text
drops incomplete aligned rows
centers returns
computes empirical covariance
estimates Oracle-Approximating Shrinkage
shrinks toward scaled identity
symmetrizes and PSD-projects
```

`HistoricalRiskForecastBuilder` translates the result into canonical `RiskForecast`.

### PCA statistical factor risk

`PCAFactorRiskEstimator` decomposes historical covariance into:

```text
low-rank principal-component covariance
+
diagonal idiosyncratic variance
```

and returns factor loadings/variances, residual variances and explained-variance diagnostics. `PCAFactorRiskForecastBuilder` emits the canonical `RiskForecast` contract.

This is deliberately a statistical research factor model, not a production industry/style model.

## Phase 4B — deterministic constraint compiler

`PortfolioConstraintSet` and `ConstraintCompiler` support:

```text
cash/invested-weight identity
long-only or bounded long/short positions
absolute asset bounds
asset-specific bounds
gross exposure
turnover
static group/sector-like exposure
benchmark-relative active-weight bounds
linear factor/style exposure
per-asset trade-weight caps
```

`LinearExposureLimit` can be absolute or benchmark-relative. Per-asset trade-weight caps provide a simple liquidity/participation proxy.

The compiler produces SLSQP-compatible constraints and `CompiledPortfolioConstraints.check(...)` independently verifies a candidate solution.

## Phase 4C — portfolio constructors

Reference implementations:

```text
EqualWeightOptimizer
MinimumVarianceOptimizer
RiskParityOptimizer
ConstrainedMeanVarianceOptimizer
```

All consume the same:

```text
AlphaForecast
RiskForecast
PortfolioState
```

and return `PortfolioTarget`.

The constrained mean-variance objective is:

```text
min_w -mu'w + 0.5 * lambda * w'Sigma*w + turnover_cost
```

subject to compiled policy constraints.

`PortfolioBenchmarkSuite` evaluates all registered constructors under identical data and cost assumptions. Diagnostics include expected return, expected net return, volatility, turnover and gross/net exposure.

## Stress and rebalance research

`PortfolioStressTester` evaluates explicit asset-return scenarios and exposes the worst portfolio scenario.

`DriftRebalancePolicy` compares current and target weights and returns a typed `RebalanceDecision` based on maximum weight drift, minimum meaningful turnover and a force-turnover threshold. It does not change the target.

These deterministic outputs are the intended evidence surface for Phase 4.5 supervision.

## Regression coverage

Phase 4 tests cover:

```text
positive feature-to-return calibration
calibrated AlphaForecast generation
ensemble normalization and uncertainty
quality-score weighting
OAS PSD covariance and metadata
PCA factor-risk decomposition and RiskForecast
asset/group/gross/turnover constraints
benchmark-relative active bounds
linear factor exposure constraints
trade-weight liquidity caps
constrained mean-variance feasibility
four-constructor benchmark suite
turnover transaction-cost penalty
stress-test worst scenario
rebalance decisions
calibration -> ensemble -> risk -> portfolio E2E chain
```

CI continues to run the complete repository suite on Python 3.11, 3.12 and 3.13.

## Known limitations

Phase 4 deliberately does not claim:

```text
production fundamental factor risk
curated sector/security master
ADV and intraday participation forecasts
nonlinear spread/market impact
corporate-action accounting
broker reconciliation
live execution supervision
```

Those belong to operational phases after the deterministic portfolio layer is stable.

## Next milestone

Phase 4.5 should add a **low-permission Portfolio Supervisor Agent** that can inspect alpha/risk health, benchmark comparisons, stress results and rebalance policy state, but cannot calculate arbitrary weights, change hard risk limits or bypass `RiskGate`.
