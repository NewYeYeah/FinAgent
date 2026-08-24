# ADR-015 — Phase 3.5 Real Generated-Feature Research Integration

Status: Accepted

## Context

Phase 3D can generate, validate and persist bounded feature programs, but a smoke-tested feature is not quantitative evidence. The missing path is from a `GeneratedFeatureArtifact` into point-in-time numerical panels, realistic cross-sectional evaluation and the existing family-level anti-overfitting controls.

## Decision

Generated features are materialized through the frozen `DataAdapter` clock. A feature value at timestamp `t` is executed only on `feature_window(asof=t, lookback=FeatureSpec.lookback)`. The generated program never receives later observations. This is stronger than running the program once on a full split because syntactically valid code may index the last element of its input.

The canonical path is:

```text
GeneratedFeatureArtifact
 -> GeneratedFeatureMaterializer
 -> PIT ResearchDataset
 -> IC / ICIR / turnover / net-return evaluation
 -> immutable research trace
 -> ExperimentEvaluation
 -> ExperimentFamily validation
```

`GeneratedFeatureEvaluator` is an approved deterministic evaluator and may be registered in the existing `ExperimentEvaluatorRegistry`. It resolves a generated feature by digest, verifies the experiment code digest, materializes the dataset and emits metrics plus lineage artifacts.

## Evaluation convention

The first reference evaluator is deliberately simple and inspectable. At each timestamp it ranks valid feature values cross-sectionally, demeans ranks and normalizes gross absolute exposure to one. Forward return labels provide the realized outcome. One-way turnover is `0.5 * sum(abs(w_t - w_{t-1}))`; transaction cost is turnover multiplied by configured basis points.

Reported metrics include mean rank IC, ICIR, annualized ICIR, gross/net mean and cumulative return, net Sharpe, mean turnover, coverage and sample counts. A one-sided t-test p-value of net period returns is stored for the existing multiple-testing gate. These metrics are research diagnostics, not a production portfolio policy.

## Evidence persistence

`SQLiteGeneratedFeatureResearchStore` stores the exact net-return and IC traces by experiment id. Evidence is immutable: re-registering identical evidence is idempotent, while changing an existing experiment's evidence is rejected.

`GeneratedFeatureFamilyValidationInputProvider` converts these persisted real return traces into the Phase 2.5 `FamilyValidationInputs` contract, so DSR/PBO/reality-check logic does not require synthetic fixtures.

## Nested validation

`GeneratedFeatureNestedWalkForwardStudy` reuses `NestedPurgedWalkForwardSplitter`. Inner validation folds diagnose feature stability; each outer test fold is materialized and evaluated separately and is not exposed to feature generation or policy mutation.

## Consequences

Phase 3.5 closes the principal gap between Agent-generated code and quantitative evidence. It intentionally does not claim that rank portfolios are the final allocation engine; portfolio construction remains Phase 4. The materializer is correctness-first and may invoke the restricted subprocess many times. A future optimization may batch causal prefix evaluation only if it preserves the same PIT semantics.
