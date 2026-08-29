# Visualization V4-1 — FactorSeriesEvidence

## Status

V4-1 persists the missing factor time series needed by linked quantitative analysis. It is an evidence-stage change, not a chart implementation and not a new research/execution authority.

The source remains the frozen A2.6 ResearchProgram:

```text
A2.6 frozen ResearchProgram
        ↓
verified candidate denominator + generated feature artifacts
        ↓
PIT internal walk-forward test panels
        ↓
frozen train_direction per factor/fold
        ↓
FactorSeries period rows
        ↓
A2.6 reconciliation
        ↓
JSON manifest + ZSTD Parquet
        ↓
verified bounded read projection
```

The original A2.6 JSON report is never rewritten. The production reserve is never read or consumed.

## Why a new evidence layer is required

A2.6 already persists fold-level and candidate-level diagnostics, including RankIC/ICIR, long-short Sharpe, coverage, quantile monotonicity and turnover. The underlying `FactorQuantAnalyzer` computes those metrics from complete point-in-time panels but does not persist the period-level series.

V4-1 therefore does **not** promote V2 presentation output to authoritative evidence and does not reconstruct missing values in React. Instead it deterministically rematerializes the frozen A2.6 factor panels and stores the period evidence before the Factor Tear Sheet is built.

## Row contract

Schema:

```text
finagent.factor-series-row.v1
```

Each long-form row is identified by:

```text
factor identity
+ fold identity
+ session_date
+ series_kind
+ metric
+ horizon/label
+ quantile when applicable
```

Persisted columns:

```text
sequence
row_id
feature_id
feature_digest
fold_id
session_date
train_direction
series_kind
metric
authority
label_name
quantile
value
sample_count
window_count
```

### Series kinds

`coverage`
- `eligible_count`
- `valid_factor_count`
- `coverage`

`ic`
- `pearson_ic_raw`
- `rank_ic_raw`
- `pearson_ic`
- `rank_ic`
- `rolling_pearson_ic`
- `rolling_rank_ic`

`quantile`
- `return`
- `nav`

`long_short`
- `return`
- `nav`

`turnover`
- `one_way_turnover`

## Authority classes

The package itself is authoritative evidence. Individual metric rows additionally declare whether the persisted value is raw/core evidence or a deterministic series transform.

Authoritative rows:

```text
raw Pearson IC / RankIC
train-direction-oriented Pearson IC / RankIC
quantile return
long-short return
one-way turnover
eligible count
valid factor count
coverage
```

Derived rows persisted by the evidence layer:

```text
rolling Pearson IC / RankIC
quantile cumulative NAV
long-short cumulative NAV
```

Derived rows are immutable and identity-bound, but their `authority` field remains `derived`; persistence does not relabel a presentation-style mathematical transform as raw research evidence.

## Direction semantics

A2.6 selects factor sign using the training split only. V4-1 reuses the frozen fold `train_direction` exactly:

```text
oriented_ic_t = train_direction × raw_ic_t
```

Quantile portfolios are oriented in the same way:
- `train_direction = +1`: raw bottom→top buckets are Q1→Qn;
- `train_direction = -1`: bucket order is reversed for Q1→Qn presentation/evidence semantics.

The test period never chooses or flips direction.

## IC semantics

For each period and each configured horizon:

```text
formation mask = eligible_at_t AND finite(factor_t)
realized mask  = formation mask AND finite(forward_label_t)
```

Pearson IC uses the A2.6 winsorized factor cross-section and the forward label. RankIC uses average ranks of the raw factor and label cross-sections. Rows below `min_cross_section` are not emitted as IC observations, matching `FactorQuantAnalyzer`.

Rolling IC is the arithmetic mean of the latest `rolling_window` valid oriented IC observations for the same factor/fold/horizon. The default V4-1 evidence window is 20 observations; no partial-window rolling value is emitted.

## Quantile / long-short semantics

V4-1 reproduces A2.6 quantile construction:

```text
eligible finite factor assets
→ stable factor sort
→ np.array_split into frozen quantile count
→ primary-label mean return per bucket
```

The oriented long-short return is:

```text
Qn return - Q1 return
```

One-way turnover is computed from the same equal-weight ±0.5 long-short portfolio used by A2.6. Portfolio state resets at the start of each walk-forward fold.

Cumulative NAV is persisted as a deterministic transform of the period returns; it is not used to alter any A2.6 statistical decision.

## Coverage semantics

Per period:

```text
eligible_count     = count(A2.6 universe-policy eligible assets)
valid_factor_count = count(eligible assets with finite factor value)
coverage           = valid_factor_count / eligible_count
```

The fold-level A2.6 coverage is recovered from the summed cell counts, not by taking an unweighted mean of daily percentages.

## Mandatory A2.6 reconciliation

`write_factor_series` refuses to emit a manifest or Parquet file unless the rematerialized period rows reproduce the frozen A2.6 report.

Per factor/fold checks include:
- raw test RankIC;
- raw test RankICIR;
- train-direction-oriented test RankIC;
- oriented test RankICIR;
- raw/oriented long-short Sharpe;
- coverage;
- quantile monotonicity;
- mean one-way turnover;
- period count;
- frozen train direction.

Candidate-level checks include:
- pooled RankIC / pooled RankICIR;
- mean/worst fold RankICIR;
- positive fold ratio;
- mean/worst fold long-short Sharpe;
- coverage mean/min;
- mean quantile monotonicity;
- mean one-way turnover;
- dominant direction;
- direction consistency;
- horizon-sign consistency.

Any disagreement fails closed. This prevents V4-1 from silently becoming a second factor-research implementation with different semantics.

## Manifest and storage

Manifest schema:

```text
finagent.factor-series.manifest.v1
```

Storage:

```text
<source>.factor-series.json
<source>.factor-series.parquet
```

The Parquet file uses deterministic long-form ordering and ZSTD compression.

The manifest binds:
- A2.6 `program_result_id`;
- program ID/spec ID;
- walk-forward report ID;
- gate report ID;
- frozen selection ID;
- walk-forward plan ID;
- data version;
- candidate-selection ID;
- universe-policy version;
- complete candidate-denominator feature digests;
- selected factor digests;
- primary/decay labels;
- quantile/min-cross-section/min-period/annualization/winsor settings;
- rolling-window setting;
- deterministic quant-config digest;
- deterministic row digest;
- canonical source-report content digest;
- physical source-report SHA-256;
- physical Parquet SHA-256.

`series_id` is content-addressed from the semantic research identities, frozen quant configuration and row digest. Output filenames and host paths are not evidence identity.

## Materialization command

```bash
python scripts/materialize_factor_series.py \
  configs/local_ashare_robust_research.toml \
  --a2p6-report reports/ashare_a2p6.json \
  --rolling-window 20
```

The TOML is used for frozen-data and feature-store location. Research semantics are recovered from the immutable A2.6 report rather than from mutable current quant/gate settings.

Before materialization the command verifies:
- frozen local data version;
- candidate universe asset identities;
- rebuilt universe-policy identity and report;
- complete candidate denominator;
- generated-feature ID/input/lookback identity;
- fold identities;
- frozen train directions;
- reserve status remains `untouched`.

## Bounded projection

`FactorSeriesProjection` validates all manifest/source/Parquet bindings before serving rows.

Supported filters:

```text
feature_digest
fold_id
series_kind
metric
label_name
quantile
start_date
end_date
offset
limit
```

The hard query bound is:

```text
1 <= limit <= 5000
```

The projection is read-only. V4-1 does not add a Workbench mutation path and does not yet implement the Factor Tear Sheet UI.

## Acceptance

Dedicated test:

```text
tests/test_factor_series_v41.py
```

Acceptance runs the existing synthetic A2.6 workflow and then verifies:
- V4-1 materialization succeeds without changing A2.6 report bytes;
- the complete candidate denominator is persisted;
- primary and decay RankIC series exist;
- rolling IC rows are explicitly derived and use the frozen window;
- quantile returns and long-short NAV are queryable;
- turnover and coverage are bounded/finite;
- a second materialization produces the same semantic `series_id`, `rows_digest` and quant-config digest;
- source-report tampering fails SHA validation;
- Parquet tampering fails SHA validation;
- query bounds fail closed.

Dedicated workflow:

```text
.github/workflows/v4-factor-series.yml
```

It runs Ruff, targeted mypy/import checks, dependency consistency and the same V4-1 acceptance on Ubuntu and Windows.

## Authority boundary

V4-1 does not add:

```text
Factor Tear Sheet UI
Strategy Decision Explorer UI
A2.6 protocol mutation
reserve access
strategy promotion
PAPER mutation
broker/live action
arbitrary shell/Python
new Control command
```

After V4-1, development moves to **V4-2 Strategy Decision Explorer**. V4-2 must consume V4-0 StrategyDecisionSeries directly; the Factor Tear Sheet remains V4-3 and must consume the V4-1 series defined here.
