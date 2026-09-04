# US-R2 Reusable Regime / Session Projection — R2-1a

Issue: #158  
Predecessor: merged R2-0b frozen multi-regime protocol.  
Project authority remains `US-R1 / research iteration`.

R2-1a materializes the ex-ante market-state layer once so later 37-candidate evaluation can join a small frozen session map instead of recomputing regimes per candidate.

## 1. Runtime objective

The regime classifier depends only on IWM. Therefore this increment must not scan the complete 25-name panel and must not evaluate any candidate.

```text
IWM 1m source rows
      ↓ existing calendar sessionization
one SQL aggregation per session
      ↓
regular-session open→close return
      ↓ calendar left join
explicit missing sessions retained
      ↓
20-session rolling direction / volatility
      ↓ lag one session
fold TRAIN-only volatility median
      ↓
small evaluation session map (~5k rows)
```

The expensive source plan is executed once when copied to Parquet. Evidence summaries are built by rereading that small local Parquet, not by executing the IWM source plan a second time.

## 2. Why no intermediate 15m IWM cube

The frozen regime definition needs only regular-session open and close. Generating 15m bars first would create roughly 26 times more intermediate rows on normal sessions and would not add information to the market-state classifier.

R2-1a therefore aggregates sessionized 1m data directly. The 15m all-asset transformation remains for R2-1b, where candidate features and formation breadth actually need it.

## 3. Session completeness

A session return is admitted only when the source contains the full calendar regular session:

```text
observed_regular_minute_count == expected_regular_minute_count
minimum_minute_offset == 0
maximum_minute_offset == expected_regular_minute_count - 1
```

The calendar is the row spine. Missing source sessions remain calendar rows with `session_return = NULL`.

The 20-session state uses a calendar `ROWS` window and `count(session_return)`. Therefore a missing source session makes the affected rolling state unavailable instead of silently converting a 20-session requirement into 20 observed rows over a longer elapsed period.

## 4. No current-session leakage

For evaluation session `T`, the projection emits market state ending at the prior calendar session only:

```text
regime_source_end_session < session_date
availability_lag_sessions = 1
```

The current session's open→close return is **not** included in the output schema. Later 15m candidate formations can safely join the session label without gaining information from the remainder of that trading day.

## 5. Fold-specific training threshold

The four-state classifier keeps the R2-0b policy:

```text
direction threshold = 0
volatility threshold = median(regime_volatility) fitted on that fold TRAIN only
```

The threshold relation never reads candidate values, candidate RankIC, labels, PnL or evaluation outcomes.

Evaluation output includes:

```text
fold_id
session_date
regime_source_end_session
regime_direction
regime_volatility
train_volatility_threshold
train_volatility_observation_count
regime_label
regime_available
unavailable_reason
frozen_protocol_id
data_version
```

No source price or current-session return is emitted.

## 6. Evidence gate

The row-free evidence summary verifies:

- exactly the calendar-expected number of evaluation sessions per frozen fold;
- no duplicate `(fold_id, session_date)` rows;
- typed available/unavailable semantics;
- only the four frozen regime labels;
- every evaluation fold actually contains all four expected regimes.

If one of the four states is absent in a real fold, R2-1a fails closed. The fold or regime policy must not be adjusted after seeing candidate performance.

## 7. Local operator

`data/` and `reports/` remain gitignored.

```powershell
python scripts/materialize_us_r2_regime_projection.py `
  D:\path\to\OHLCV-1m-snapshot `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --data-output data/us_r2/regime/us_r2_regime_projection.parquet `
  --plan-output reports/us_r2/us_r2_regime_projection_plan.json `
  --evidence-output reports/us_r2/us_r2_regime_projection_evidence.json `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB
```

The console reports selected source bytes, output Parquet bytes, row count and evidence ID. This provides a real runtime profile before broader all-asset materialization.

## 8. Next increment

R2-1b should materialize candidate-ready 15m inputs in bounded fold/partition chunks and join the already materialized regime Parquet. It must not recompute IWM rolling states 37 times.

The complete 37-candidate denominator, R1 statistical thresholds, dynamic 25-name eligibility and `minimum_cross_section=10` remain unchanged. R2-1a grants no Alpha, stage-exit, execution, order, PAPER or live-capital authority.
