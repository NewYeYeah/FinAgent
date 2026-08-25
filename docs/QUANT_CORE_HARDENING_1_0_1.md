# FinAgent 1.0.1 Quant-Core Hardening

Date: 2026-08-25

## Purpose

FinAgent 1.0.1 is the final hardening pass for the 1.0 release line after expert review of the quantitative core. It is a correctness and governance maintenance release, not a feature-expansion release.

The stable scope remains:

```text
governed quantitative research
+ deterministic portfolio construction
+ supervised paper/shadow operations
+ structured evidence lineage
+ measurable operational acceptance
```

It still does **not** claim live-broker or live-capital readiness.

## Expert-review findings and disposition

| Finding | 1.0.1 disposition | Stable invariant |
| --- | --- | --- |
| Forward-label availability could influence generated-feature evaluation/selection semantics | Fixed | PIT eligibility and feature availability form the portfolio; future-label availability never forms the universe |
| A completely unrealized forward-return cross-section at the end of a sample was treated like asset-level missing-return corruption | Fixed | A fully unrealized formation cross-section is an unevaluable horizon boundary and is skipped; partial missing realized returns for formed positions still fail closed by default |
| Static universes do not represent delisting/reconstitution eligibility correctly | Fixed at contract level | `ResearchSplit.eligibility_mask` and `UniverseProvider`/`ScheduledUniverseProvider` provide explicit point-in-time eligibility |
| Per-family multiplicity control can still permit repeated new-family search | Fixed at governance layer | `ResearchProgram` provides durable cross-family family-count, experiment-count and alpha-spending budgets plus one-time sealed-holdout access |
| Metric selection assumed primary metrics are always maximized and tie metrics always minimized | Fixed | `MetricObjective` is explicit and winner selection follows the declared objective |
| Turnover/cost definitions were ambiguous | Fixed | `TradeActivity` distinguishes gross traded weight from one-way turnover; linear bps cost is charged on gross traded weight |
| Generated-feature sandbox process startup is unnecessarily expensive | Mitigated without weakening PIT isolation | independent PIT windows may be batched into one restricted subprocess; each feature invocation still receives only its own historical window |
| Quant research primitives were weaker than the surrounding governance machinery | Improved | canonical momentum, short-term reversal, rolling volatility, winsorization, cross-sectional z-score, linear neutralization and volatility scaling are provided as deterministic primitives |
| Generic order planning could be misread as supporting every `AssetType` in the domain model | Fixed | the 1.0 generic `OrderPlanner` fails closed outside equity/ETF spot-like quantity semantics |
| CI only demonstrated unit-test success | Improved with an explicit baseline | Python 3.11/3.12/3.13 tests, project-wide critical Ruff checks, hardened-surface lint, targeted mypy, coverage floor, build and dependency consistency are release gates |

## Generated-feature missing-return semantics

The formation set at time `t` is:

```text
formation_t = PIT_eligible_t AND finite(feature_t)
```

It is **not**:

```text
PIT_eligible_t AND finite(feature_t) AND finite(forward_return_t)
```

That distinction prevents future label realization from changing which assets receive portfolio weights.

After formation there are two different missing-label cases.

### 1. Entire formation cross-section is unrealized

If no member of the already-defined formation set has a realized forward return, the period is treated as an unevaluable horizon boundary. It is omitted from realized performance and IC evidence. The implementation does not create a fictitious close/reopen trade and does not alter the formation universe.

The trace records:

```text
unrealized_boundary_periods
```

### 2. Only part of a formed portfolio lacks realized return

This is not treated as a convenient universe change. With the default `fail_on_missing_realized_return=True`, evaluation fails and requires one of:

```text
explicit delisting/corporate-action return semantics
or
PIT ineligibility known before formation
```

This preserves the no-look-ahead contract while distinguishing a normal label-horizon boundary from asset-level data/accounting incompleteness.

## Point-in-time universe contract

`ResearchSplit` now carries an explicit `(time, asset)` eligibility mask. `UniverseProvider` supplies eligibility effective at an `asof` timestamp, and `ScheduledUniverseProvider` provides a deterministic reference implementation for reconstitution-style state changes.

The contract is intentionally separate from return labels. A delisted or otherwise ineligible security must become ineligible from information available at or before formation time; a missing future return is not allowed to retroactively justify removal.

## Cross-family research governance

`ExperimentFamily` remains the unit of within-family multiplicity correction. `ResearchProgram` adds the missing higher-level search ledger across families:

```text
program alpha budget
program max family count
program max experiment count
immutable family reservation
one-time sealed holdout consumption
```

A reserved failed research attempt continues to consume program budget. This is intentional: failed trials and abandoned searches are part of the effective search process and must not disappear from the denominator simply because they were inconvenient.

## Metric direction

Research plans now carry:

```text
primary_metric_objective
 tie_break_metric_objective
```

with `MAXIMIZE` and `MINIMIZE` as explicit values. Deterministic winner selection uses the declared objective rather than inferring direction from metric names.

## Turnover and transaction-cost convention

For target-weight change `Δw`:

```text
gross_traded_weight = sum_i |Δw_i|
one_way_turnover    = 0.5 * gross_traded_weight
```

Linear transaction cost at `c` basis points is:

```text
cost_fraction = gross_traded_weight * c / 10_000
```

The backward-compatible `mean_turnover` metric is explicitly one-way turnover. Generated-feature evidence also reports `mean_gross_traded_weight`.

## Execution capability boundary

The domain can represent equities, ETFs, futures, FX, crypto, cash and other instrument identities. Representation is not execution support.

The generic 1.0 `OrderPlanner` supports only `EQUITY` and `ETF` spot-like quantity semantics. It fails closed for futures, FX, crypto, cash instruments and `OTHER` assets. Dedicated planners are required before those asset classes can be executed because their correct semantics may require contract multipliers, margin, settlement, quote/base currency conversion, funding, lot rules and venue-specific behavior.

This boundary prevents a typed `AssetType` enum from being mistaken for production execution capability.

## Generated-feature batching boundary

`LocalFeatureSandbox.run_batch()` reduces subprocess startup overhead while preserving the security and PIT boundary:

```text
one restricted subprocess
  -> compile approved source once
  -> invoke on independent historical windows
  -> no cross-window state exposed to feature code
```

Batching is an implementation optimization, not permission to pass a complete future panel to generated code.

## CI and engineering-quality baseline

The 1.0.1 release gate is deliberately split into two levels.

### Repository-wide critical checks

Ruff runs project-wide for syntax/undefined-name classes that must never regress:

```text
E9, F63, F7, F82
```

### Hardened release-surface checks

The quantitative contracts changed in 1.0.1 receive an additional `E4/E7/E9/F` lint gate. Targeted mypy covers the typed metric, turnover, universe, research-program, alpha-primitive and order-planning surfaces.

The full repository still contains legacy style/lint debt outside this maintenance diff. 1.0.1 does not hide that debt by pretending the entire historical tree is already clean; instead it establishes a ratcheting baseline while blocking correctness regressions on the hardened surface.

The release gate also runs:

```text
pytest on Python 3.11 / 3.12 / 3.13
coverage floor
python -m build
python -m pip check
```

## Regression coverage added for this hardening pass

The dedicated `tests/test_quant_core_hardening_v101.py` suite covers:

```text
partial missing forward labels cannot change formation universe
fully unrealized final cross-section is treated as horizon boundary
PIT eligibility controls formation independently of future labels
gross traded weight vs one-way turnover convention
derivative-like assets are rejected by the generic OrderPlanner
maximize/minimize metric direction
cross-family alpha-spending budget
one-time sealed holdout access
scheduled PIT universe changes
canonical alpha primitives
batched independent sandbox windows
```

## What remains explicitly outside 1.0

The expert review does not justify silently widening the release scope. The following remain deferred:

```text
live broker credentials/adapters
futures/FX/crypto execution semantics
multi-currency cash and settlement accounting
complete security-master and corporate-action feeds
institutional nonlinear impact calibration
unrestricted autonomous code generation
unbounded autonomous research search
LLM ownership of portfolio weights or financial state
```

## Final 1.0 release criterion

The 1.0 line is considered delivered only after the hardening branch passes all configured GitHub Actions gates and is merged to `main` with package version `1.0.1`.

A green release establishes software/research-contract correctness at the tested boundary. It is still not evidence that any strategy is profitable or that the system is safe for live capital without a separate deployment-specific validation program.
