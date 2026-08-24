# Phase 2.5 — Nested Validation and Anti-Overfitting Controls

Phase 2.5 closes the main statistical-governance gap that remains after point-in-time data, purged walk-forward, timed execution and model lifecycle controls are in place.

## Delivered components

### 1. Nested purged walk-forward

New types:

```text
NestedWalkForwardConfig
NestedWalkForwardFold
NestedWalkForwardDatasets
NestedPurgedWalkForwardSplitter
```

The outer holdout is never available to the inner model-selection process.

Inner datasets use:

```text
train
validation
```

while outer datasets use:

```text
train
test
```

This naming difference is intentional: code should not silently treat an inner tuning holdout as the final test set.

### 2. Experiment-family pre-registration

New domain objects:

```text
ExperimentFamily
ExperimentFamilyStatus
FamilyMembership
CorrectionMethod
```

The SQLite registry now persists:

```text
experiment_families
family_memberships
```

A family must be OPEN to accept a trial and FROZEN before family-level statistical validation.

### 3. Multiple-hypothesis correction

`adjust_pvalues` supports:

```text
bonferroni
holm
benjamini_hochberg
```

All return both adjusted p-values and deterministic rejection decisions.

### 4. Deflated Sharpe Ratio

`deflated_sharpe_ratio` returns:

```text
observed_sharpe
benchmark_sharpe
deflated_probability
sample_size
n_trials
skewness
kurtosis
```

The benchmark may be supplied explicitly or estimated from the declared family of trial Sharpes.

### 5. Probability of Backtest Overfitting

`probability_of_backtest_overfitting` implements a CSCV estimate over a matrix of trial returns.

Output:

```text
probability_of_backtest_overfitting
logits
combinations_evaluated
blocks
```

### 6. White-style reality check

`whites_reality_check` uses a deterministic-seed circular moving-block bootstrap on the demeaned family return matrix.

Output:

```text
observed_statistic
pvalue
bootstrap_samples
block_size
```

### 7. Registry-bound family validation

`ExperimentFamilyValidator` prevents a caller from validating only the most favorable subset of trials.

It requires:

```text
set(trial_returns) == set(pre_registered_family_members)
set(pvalues)       == set(pre_registered_family_members)
family.status      == FROZEN
```

It then returns a `RegisteredFamilyValidation` containing the complete `FamilyValidationReport`.

## Default validation gate

`validate_experiment_family` currently requires all of the following for the selected trial:

```text
corrected p-value rejects at family alpha
Deflated Sharpe probability >= 0.95
PBO <= 0.50
White reality-check p-value <= family alpha
```

These defaults are research-policy defaults, not universal financial laws. Phase 3 must expose them through an approved policy/configuration layer rather than allowing an Agent to rewrite thresholds ad hoc.

## Recommended nested research procedure

```text
1. create ExperimentFamily(OPEN)
2. register every planned/attempted trial
3. run inner walk-forward trials
4. add newly attempted variants while family remains OPEN
5. freeze family before final family-level inference
6. apply family statistics to the complete trial set
7. choose a procedure using only inner evidence
8. evaluate that procedure on the outer test
9. accumulate outer-fold results
10. request model promotion through deterministic governance
11. close the family when the research decision is final
```

If an Agent proposes an extra experiment after seeing results, that experiment must be added to the still-open family and the multiplicity denominator increases accordingly. If the family is already frozen, the new idea starts a new explicitly linked family instead of modifying the old one.

## Tests

Phase 2.5 adds tests for:

- inner/outer temporal isolation;
- inner `validation` vs outer `test` semantics;
- family lifecycle and immutable denominator;
- family membership persistence under idempotent registry writes;
- model-stage history persistence under idempotent model registration;
- Bonferroni/Holm/BH correction;
- Deflated Sharpe trial-count penalty;
- CSCV PBO;
- moving-block White reality check;
- full registered-family validation.

Current full-suite result:

```text
69 passed
```

## Explicitly deferred

Phase 2.5 does not yet implement:

- Hansen SPA;
- effective-number-of-independent-trials estimation;
- Bayesian multiple-testing models;
- cross-family research-budget accounting;
- arbitrary Agent-generated code execution;
- LLM orchestration;
- vector-memory infrastructure;
- live trading.

Those are intentionally separated from the statistical substrate completed here.
