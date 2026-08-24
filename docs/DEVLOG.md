# FinAgent Development Log

This file is the canonical chronological development log. Phase-specific details remain in the corresponding ADR and `PHASE*.md` documents.

## 2026-08-25 — Phase 4: Alpha Calibration, Risk Hardening and Portfolio Research

### Goal

Convert statistically governed research signals into a stronger deterministic portfolio layer without expanding LLM authority into expected-return calibration, covariance estimation, constraints, scenario policy or portfolio weights.

### Delivered

```text
CrossSectionalCalibrationResult
CrossSectionalLinearAlphaCalibrator
AlphaEnsembleResult
AlphaForecastEnsembler

OASCovarianceResult
OASCovarianceEstimator
HistoricalRiskForecastBuilder
PCAFactorRiskResult
PCAFactorRiskEstimator
PCAFactorRiskForecastBuilder

GroupExposureLimit
LinearExposureLimit
PortfolioConstraintSet
ConstraintCompiler
CompiledPortfolioConstraints

EqualWeightOptimizer
MinimumVarianceOptimizer
RiskParityOptimizer
ConstrainedMeanVarianceConfig
ConstrainedMeanVarianceOptimizer

PortfolioBenchmarkMetrics
PortfolioBenchmarkResult
PortfolioBenchmarkSuite
evaluate_portfolio_target

PortfolioScenario
PortfolioStressTester
StressTestReport
DriftRebalancePolicy
RebalanceDecision
```

Phase 4A adds an explicit feature/model-score to expected-return calibration layer. The reference calibrator standardizes feature values cross-sectionally by timestamp and fits a pooled ridge-regularized mapping against forward returns. It consumes only the caller-selected `ResearchSplit`; it does not inspect outer-test data itself.

Phase 4B adds Oracle-Approximating Shrinkage covariance and a PCA statistical factor-risk option. Both produce PSD canonical `RiskForecast` objects. Portfolio constraints are centralized and now cover absolute bounds, gross exposure, turnover, group exposure, benchmark-relative active bounds, linear factor/style exposure and per-asset trade-weight caps as a first liquidity proxy.

Phase 4C adds equal-weight, minimum-variance, risk-parity and cost-aware constrained mean-variance constructors. `PortfolioBenchmarkSuite` evaluates them under identical alpha/risk/state/cost assumptions. Stress scenarios and an explicit drift/turnover rebalance policy are also deterministic and typed.

### Architectural conclusion

The project now has a continuous deterministic chain:

```text
generated feature / model signal
 -> PIT research evidence
 -> expected-return calibration
 -> alpha ensemble
 -> OAS/PCA risk forecast
 -> constraint compiler
 -> benchmarked portfolio construction
 -> stress/rebalance evidence
 -> PortfolioTarget
 -> RiskGate / execution
```

The remaining bottleneck is operational supervision and paper/shadow execution, not additional research-agent autonomy.

### Documentation

- `ADR-016_PHASE4_PORTFOLIO_RESEARCH.md`
- `PHASE4.md`
- `ROADMAP_REBASELINE.md` updated after Phase 4.
- README updated to Phase 4 / `0.5.0a1`.

---

## 2026-08-25 — Phase 3.5: Real Generated-Feature Research Integration

Phase 3.5 connected generated feature artifacts to real point-in-time numerical data and the existing statistical-governance path. Materialization executes each feature only on `FeatureWindow(asof=t)` data to prevent panel look-ahead. The reference evaluator produces rank-IC/ICIR, turnover, gross/net return, cost-adjusted Sharpe and immutable period-level evidence that feeds Holm/DSR/PBO/Reality-Check validation.

---

## 2026-08-25 — Phase 3D: Restricted Generated Feature Programs

Phase 3D added bounded feature code generation, AST validation, restricted subprocess smoke execution, immutable generated-feature lineage and bridging into `ExperimentTemplate`. It explicitly does not claim container-grade isolation.

---

## 2026-08-25 — Phase 3C: Provider-Agnostic LLM Research Planning

Phase 3C introduced provider-neutral LLM contracts, optional OpenAI Responses API integration, strict structured `ResearchPlan` generation, local deterministic validation, durable provider telemetry and Agent-quality metrics. The complete CI suite passed Python 3.11/3.12/3.13 with 95 tests.

---

## 2026-08-24 — Phase 3B: Deterministic Scripted Research Agent

Phase 3B implemented deterministic `ResearchPlan`, `ResearchBudget`, approved experiment templates, `ScriptedResearchAgent`, plan storage and replay. The complete CI suite passed with 90 tests.

---

## 2026-08-24 — Phase 3A: Governed Agent Control Surface

Phase 3A froze typed Agent contracts, finite `AgentAction`, `ToolRegistry`, policy-as-code, immutable registered context and SQLite Agent audit.

---

## 2026-08-24 — Phase 2.5: Research Multiplicity and Anti-Overfitting

Phase 2.5 added nested purged walk-forward validation, `ExperimentFamily` governance, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO and a White-style reality check.

---

## 2026-08-24 — Phase 2: Validation, Execution Timing and Model Governance

Delivered purged walk-forward splitting, explicit execution snapshots, timed simulated execution/backtesting, durable ExperimentRunner lifecycle and model-stage governance. The hard execution invariant is `execution_at > information_at`.

---

## 2026-08-24 — Phase 1: Numerical Data Contract and Quant Kernel

The frozen numerical contract is `DataAdapter -> ResearchDataset / ResearchSplit -> FeatureWindow -> AlphaModel / RiskModel`, with `(time, asset, feature)` numerical layout and `available_at` as the PIT clock.

---

## 2026-08-24 — Phase 0.5: Domain Kernel and Test Harness

Phase 0.5 froze framework-independent contracts for market data, research datasets, forecasts, portfolio targets/states, risk decisions, orders/fills and experiment artifacts.
