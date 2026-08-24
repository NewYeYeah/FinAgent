# ADR-010 — Phase 2.5 Research Multiplicity and Nested Validation

Status: **Accepted**

## Context

Phase 2 removed the main forms of chronological leakage and separated information time from execution time. That is necessary but not sufficient for an automated research system.

A human or Agent can still overfit by running many valid backtests and selecting the most attractive result. In that setting every individual experiment may be point-in-time safe while the overall research process is statistically biased.

Phase 2.5 therefore treats **the research search process itself as data that must be governed**.

## Decision 1 — outer test data cannot participate in model selection

Hyperparameter/model selection must use nested chronological validation:

```text
outer train
    -> inner train | purge | embargo | validation
    -> choose model/configuration
outer purge | outer embargo
outer test
    -> one unbiased evaluation of the selected procedure
```

`NestedPurgedWalkForwardSplitter` generates inner folds only from observations contained inside each outer training range. The outer test interval cannot appear in any inner train or validation dataset.

The existing `DataAdapter -> DatasetRequest -> ResearchDataset` contract remains the only data-materialization route.

## Decision 2 — related trials belong to a pre-registered ExperimentFamily

An `ExperimentFamily` records:

- a stable family id;
- the research question;
- the primary metric;
- family-wise alpha;
- the declared multiplicity procedure;
- creation time and metadata.

Lifecycle:

```text
OPEN -> FROZEN -> CLOSED
```

Semantics:

- `OPEN`: related variants may still be registered; every attempted variant remains part of the family denominator.
- `FROZEN`: membership is immutable and family-level statistical evaluation is permitted.
- `CLOSED`: final research decision has been recorded; no further mutation is allowed.

An empty family cannot be frozen.

`ExperimentFamilyValidator` requires the return series and p-values to contain **exactly** the registered family members. Passing a favorable subset is rejected.

## Decision 3 — multiplicity correction is explicit, not implicit

Phase 2.5 implements:

- Bonferroni;
- Holm step-down family-wise error control;
- Benjamini-Hochberg false-discovery-rate control.

The procedure is declared on the family before validation. Holm is the default because the initial use case is conservative model promotion rather than broad factor discovery.

## Decision 4 — Sharpe must be deflated for research selection

`deflated_sharpe_ratio` implements the Bailey/López de Prado style probability that an observed Sharpe exceeds a benchmark adjusted for:

- number of declared trials;
- variance of trial Sharpe ratios;
- sample skewness;
- sample kurtosis.

The implementation operates on **per-observation Sharpe**, not annualized Sharpe. Annualization belongs to reporting and does not change the selection probability when applied consistently.

For one trial, or zero trial-Sharpe variance, the expected maximum null Sharpe reduces to zero.

### Limitation

The expected-maximum approximation treats the trial count as declared independent trials. Correlated strategies can imply a lower effective number of independent trials. Phase 2.5 deliberately uses the full registered family size as a conservative denominator. Estimation of an effective trial count is deferred.

## Decision 5 — PBO is estimated with CSCV

`probability_of_backtest_overfitting` implements Combinatorially Symmetric Cross-Validation:

1. split the strategy-return matrix into an even number of contiguous blocks;
2. use half of the blocks as in-sample and the complement as out-of-sample;
3. select the best in-sample strategy;
4. measure its out-of-sample rank;
5. convert the percentile to a logit;
6. report the fraction of logits at or below zero.

Input contract:

```text
returns.shape = (time, fully_specified_trial)
```

PBO is a family diagnostic. It is not meaningful for a single strategy in isolation.

## Decision 6 — the best backtest must pass a family-level reality check

`whites_reality_check` bootstraps the maximum mean return across all strategy columns after column-wise demeaning.

A circular moving-block bootstrap is used so that:

- serial dependence within a strategy is not destroyed by iid row sampling;
- contemporaneous dependence between strategies is preserved by resampling rows jointly.

The resulting p-value asks whether the best observed mean performance is unusually large relative to the null family.

### Limitation

This is a White-style reality check, not Hansen's SPA test. SPA and alternative bootstrap choices remain valid future extensions.

## Decision 7 — validation output stays decomposed

`FamilyValidationReport` contains separate results for:

- corrected p-values;
- Deflated Sharpe Ratio;
- PBO;
- White reality check;
- final deterministic pass/fail gate.

FinAgent does **not** collapse these into one opaque research score. A future Agent may explain the components but may not replace them with free-form reasoning.

## Decision 8 — SQLite parent records use UPSERT, not REPLACE

Phase 2.5 extends a Phase 2 fix to experiments, experiment families and models.

SQLite `INSERT OR REPLACE` can delete the existing parent row before inserting the replacement. With `ON DELETE CASCADE`, that can silently erase:

- experiment-family memberships;
- model-stage audit history.

Parent lifecycle records therefore use `INSERT ... ON CONFLICT DO UPDATE`.

## Consequences

After Phase 2.5, a valid research path is:

```text
pre-register family
    -> register every attempted variant
    -> nested inner selection only
    -> freeze family
    -> multiplicity / DSR / PBO / reality check
    -> outer evaluation
    -> model-governance request
```

A future Agent can automate this process only through typed tools. It cannot reduce the family denominator, expose outer test data to inner selection, or directly promote a model to live use.
