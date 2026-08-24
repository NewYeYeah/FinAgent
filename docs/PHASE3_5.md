# Phase 3.5 — Real Generated-Feature Research Integration

## Objective

Replace synthetic generated-feature evaluation with a real point-in-time numerical path.

```text
LLM feature
 -> validated GeneratedFeatureArtifact
 -> PIT materialization
 -> ResearchDataset
 -> nested walk-forward diagnostics
 -> IC / ICIR / turnover / cost-adjusted returns
 -> immutable evidence
 -> existing ExperimentFamily validation
```

## Components

```text
GeneratedFeatureMaterializer
GeneratedFeatureEvaluationConfig
GeneratedFeatureResearchTrace
GeneratedFeatureEvaluator
SQLiteGeneratedFeatureResearchStore
GeneratedFeatureFamilyValidationInputProvider
GeneratedFeatureNestedWalkForwardStudy
```

## PIT materialization

A generated program is never run against a complete historical split and then trusted. For every asset/timestamp, the materializer asks the existing `DataAdapter` for a `FeatureWindow` ending at that timestamp and bounded by the declared feature lookback. Missing warm-up windows remain `NaN`.

This matters because AST safety and runtime isolation do not imply statistical causality. Code such as `inputs["close"][-1]` is safe Python but would become a future leak if it received the entire test panel. Window-scoped materialization prevents that class of leakage.

The materialized dataset records:

```text
generated feature digest
source code digest
source dataset digest
materializer version
```

and remains an immutable `ResearchDataset` with `(time, asset, feature)` layout.

## Reference research evaluator

The first evaluator uses cross-sectional rank weights. For valid assets at each timestamp:

```text
rank(feature)
 -> demean ranks
 -> normalize sum(abs(weights)) = 1
 -> realized forward return
 -> turnover
 -> transaction cost
 -> net return
```

Metrics:

```text
mean_ic
icir
annualized_icir
mean_gross_return
mean_net_return
gross_cumulative_return
net_cumulative_return
net_sharpe
mean_turnover
coverage
evaluated_periods
ic_periods
one_sided_net_return_pvalue
```

`ExperimentEvaluation.passed=True` means the deterministic evaluation executed successfully. It does not mean the factor passed family-level statistical promotion.

## Family validation integration

`SQLiteGeneratedFeatureResearchStore` persists period-level net returns and IC traces. `GeneratedFeatureFamilyValidationInputProvider` supplies those traces and p-values to the existing Holm/DSR/PBO/Reality-Check pipeline. Failed/weak features therefore remain in the same ExperimentFamily denominator.

## Nested walk-forward

`GeneratedFeatureNestedWalkForwardStudy` reuses the existing nested purged splitter. Inner folds measure stability; outer folds provide held-out evidence. The feature source and statistical policy are not changed using outer-test results.

## Research findings and engineering implications

Phase 3.5 confirms that the most important generated-code risk is not only process security. A restricted program may still implement a statistically invalid feature if it can see a whole future panel. Causality therefore belongs in the data/materialization boundary, not in the prompt.

The current correctness-first implementation invokes bounded feature execution at each point. This is intentionally conservative. Performance optimization should later use a causal batch/prefix executor or pre-materialized feature cache, but only after equivalence tests prove identical PIT output.

The rank portfolio is a diagnostic bridge, not the final portfolio engine. Phase 4 should replace this reference transformation with calibrated alpha ensembles, portfolio constraints and stronger risk models while preserving the evidence and lineage contracts established here.
