# US-R2 Regime Projection v2 — Endpoint-Observation Amendment

Issue: #158  
Predecessor: merged PR #165 (`3d6a4f7ff9d2dded778689b2cc7df67967a5c0a6`).  
Project authority remains `US-R1 / research iteration`.

## Why v1 failed

The first real R2-1a operator run failed closed in fold 01 before any candidate performance was evaluated. The v1 implementation required every regular-session 1m bar to be present before admitting an IWM same-session open→close return.

The corpus inventory shows that this implementation rule is structurally incompatible with early IWM history: 2001 has observed sessions but every month has zero fully complete sessions and only roughly 20%-45% regular-minute coverage. The frozen R2-0b regime definition, however, uses only same-session open and close endpoints. Interior 1m completeness is not an input to that statistic.

The failed v1 data/report files are retained as immutable local evidence. v2 uses new filenames and content-addressed identities.

## Frozen amendment

The five walk-forward folds, IWM anchor, four regime labels, 20-session lookback, one-session lag, TRAIN-only volatility median and complete 37-candidate denominator remain unchanged.

A session return is admitted when:

```text
observed regular-minute rows >= 2
first observed minute_offset < 15
last observed minute_offset >= expected_regular_minutes - 15
first/last endpoint prices are positive and finite
```

The 15-minute endpoint band is not tuned from the failed regime result. It is inherited from the already frozen canonical 15m signal interval.

The return remains:

```text
last observed regular-minute close
---------------------------------- - 1
first observed regular-minute open
```

No cross-session price is used. No current-session return or source price is emitted to the reusable session map.

## Missingness remains fail-closed

The calendar remains the row spine. If either endpoint falls outside its 15m boundary band, that session return is null. The 20-session rolling state still requires exactly 20 non-null returns across 20 consecutive calendar sessions.

Therefore v2 does **not** skip a missing session and pull in an older observed day. It changes only the irrelevant interior-minute requirement.

## Stronger evidence gate

The v2 evidence records per-fold unavailable-reason counts and requires at least 20 independent sessions for each of the four regime labels in every evaluation fold. The value 20 is inherited from the accepted US-R1 minimum OOS periods per fold rather than selected from R2 candidate performance.

Possible projection-level unavailable reasons remain:

```text
REGIME_LOOKBACK_INCOMPLETE
REGIME_STATE_NUMERIC_UNAVAILABLE
TRAIN_VOLATILITY_THRESHOLD_UNAVAILABLE
```

A fold with fewer than 20 sessions in any regime fails closed with `insufficient_regime_sessions`.

## Operator

Keep the failed v1 outputs. Run v2 to separate files:

```powershell
python scripts/materialize_us_r2_regime_projection_v2.py `
  D:\Data\datasets--mito0o852--OHLCV-1m `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --data-output data/us_r2/regime/us_r2_regime_projection_v2.parquet `
  --plan-output reports/us_r2/us_r2_regime_projection_plan_v2.json `
  --evidence-output reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --memory-limit 16GB `
  --threads 4 `
  --max-temp-directory-size 40GB `
  --temp-directory data/duckdb_temp/us_r2_regime_v2
```

Acceptance before R2-1b:

1. `passed=true`;
2. no `insufficient_regime_sessions` blockers;
3. every regime has at least 20 sessions in every fold;
4. `source_asset=IWM` and the scan remains candidate-independent;
5. row count remains within 10,000;
6. v1 failed evidence remains untouched.

No Alpha, stage-exit, execution, order, PAPER or live-capital authority is granted by this amendment.
