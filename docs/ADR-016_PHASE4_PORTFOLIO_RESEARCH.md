# ADR-016 — Phase 4 Portfolio Research Boundary

Status: Accepted

Date: 2026-08-25

## Context

Phase 3.5 completed the path from generated feature to PIT-safe materialization, period-level evidence and family-level anti-overfitting controls. The next bottleneck is deterministic transformation from validated research signal to portfolio target.

The earlier reference optimizer intentionally lacked a reusable alpha-calibration layer, shrinkage/factor covariance choices, centralized benchmark-relative/factor/liquidity constraints, stress interfaces and explicit portfolio baselines.

## Decision

Phase 4 is divided into three deterministic layers:

```text
4A  feature/model score -> calibrated AlphaForecast -> alpha ensemble
4B  historical returns -> robust RiskForecast + compiled constraints
4C  aligned forecasts/state -> benchmarked constructors/stress/rebalance -> PortfolioTarget
```

The canonical `AlphaForecast`, `RiskForecast`, `PortfolioState` and `PortfolioTarget` contracts are preserved.

## Alpha calibration

`CrossSectionalLinearAlphaCalibrator` operates on an explicitly supplied `ResearchSplit`. At each timestamp it standardizes the feature cross-section and pools observations into a ridge-regularized mapping:

```text
y(i,t) = intercept + slope * z(feature(i,t)) + error(i,t)
```

The calibrator does not select its own split and does not access outer-test data. `AlphaForecastEnsembler` only combines already-formed forecasts with explicit deterministic weights.

## Risk estimation

Two Phase 4 risk baselines are added.

`OASCovarianceEstimator` shrinks a noisy sample covariance toward a scaled identity target and projects the result onto the PSD cone.

`PCAFactorRiskEstimator` supplies a statistical low-rank factor covariance plus diagonal idiosyncratic variance. It is a research baseline, not a production fundamental industry/style risk model.

Both have builders that emit canonical `RiskForecast` objects.

## Constraint compilation

`PortfolioConstraintSet` supports:

```text
fixed cash/invested-weight accounting identity
long-only or bounded long/short asset weights
per-asset absolute bounds
gross-exposure limit
global turnover limit
group min/max exposure
benchmark-relative active-weight bounds
linear factor/style exposure bounds
per-asset trade-weight limits
```

Per-asset trade-weight limits are a Phase 4 liquidity/participation proxy. They do not yet represent a calibrated nonlinear impact model.

`ConstraintCompiler` translates these rules into SciPy SLSQP bounds/constraints and provides an independent post-solve checker. Constraints are deterministic infrastructure and are not LLM-generated fields.

## Portfolio constructors

Phase 4 adds four reference constructors using the same domain inputs:

```text
EqualWeightOptimizer
MinimumVarianceOptimizer
RiskParityOptimizer
ConstrainedMeanVarianceOptimizer
```

The cost-aware mean-variance objective is:

```text
min_w  -mu'w + 0.5 * lambda * w'Sigma*w + c * turnover(w, w_prev)
```

subject to compiled constraints.

`PortfolioBenchmarkSuite` evaluates constructors on identical `AlphaForecast`, `RiskForecast` and `PortfolioState` inputs. This prevents the most complex optimizer from becoming an assumed winner.

## Stress and rebalance interfaces

`PortfolioStressTester` applies explicit asset-return scenarios to a target and reports the worst scenario.

`DriftRebalancePolicy` makes an explicit rebalance/no-rebalance decision from target/current weight drift and turnover thresholds. It never mutates `PortfolioTarget`.

These interfaces prepare the deterministic evidence surface required by the future low-permission Portfolio Supervisor Agent.

## Consequences

Positive:

- generated features can be translated into expected returns through a typed layer;
- multiple alphas can be combined without changing portfolio contracts;
- covariance choices include shrinkage and statistical factor-risk baselines;
- asset/group/benchmark/factor/liquidity-like constraints are centralized;
- equal weight, minimum variance and risk parity remain explicit baselines;
- stress/rebalance state is explicit rather than buried inside Agent reasoning.

Trade-offs:

- SLSQP is a research-scale optimizer rather than a production QP stack;
- PCA factors are statistical and unstable compared with curated fundamental factor models;
- trade-weight caps are only a liquidity proxy;
- transaction cost remains linear in turnover;
- scenario definitions are externally supplied rather than probabilistically generated.

## Deferred

Deferred to Phase 5-oriented work:

```text
fundamental industry/style risk model
ADV/intraday participation forecasts
nonlinear spread/impact curves
corporate actions and security master
broker reconciliation/state recovery
paper/shadow production supervision
```

The LLM remains outside the numerical portfolio hot path.
