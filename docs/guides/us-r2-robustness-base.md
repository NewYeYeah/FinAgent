# US-R2-2c1 exact robustness base

US-R2-2c1 prepares the exact data plane required by the preregistered US-R1 frequency and decay robustness checks. It is deliberately candidate-independent and does **not** evaluate the final US-R2 Alpha Gate.

## Bound predecessor

The materialization policy is bound to the reviewed real pooled-inference report:

```text
us-r2-pooled-inference-a0a2e40c2ec246fc607fab92
```

That report retained all 37 frozen R1 candidates, read exactly the 21 reviewed primary metric NPZs, ran the accepted R1 HAC/session-block bootstrap and full-denominator Holm/BH inference, and remained non-authoritative for Alpha/execution/status.

US-R2-2c1 never reads pooled p-values or q-values for candidate filtering. The predecessor identity is a sequencing/evidence gate only.

## Frozen robustness slices

The exact accepted R1 robustness definitions are reused:

```text
frequency_5m_60m
frequency_30m_60m
decay_15m_30m
decay_15m_120m
```

Together with the already reviewed primary `15m/60m` evidence, later R2 robustness statistics will therefore have the same R1 frequency set `{5m,15m,30m}` and decay set `{30m,60m,120m}`.

No robustness slice is approximated from the existing `15m/60m` primary cache. Exact 5m/30m bars and exact same-session 30m/60m/120m labels are derived from the admitted sessionized 1m source.

## Runtime design

For one calendar year, the expensive source appears exactly once:

```text
25-name sessionized RAW 1m source
              |
              v
source_rows AS MATERIALIZED
              |
              v
year_rows AS MATERIALIZED
       /          |          \
      /           |           \
  bars_5       bars_15      bars_30
      \           |           /
       \          |          /
        exact 1m endpoint labels
          30m / 60m / 120m
                  |
                  v
           four frozen slices
                  |
                  v
      one annual robustness Parquet
```

This is a runtime refactor, not a methodology amendment. Focused regression compares every emitted robustness slice against the existing accepted R1 resampling and same-session label builders, including exact availability reasons and IEEE-754 `.hex()` equality for numeric values.

The annual operator intentionally does not count the raw SQL before `COPY`; doing so would execute the expensive annual source twice. Row-free breadth evidence is computed only from the materialized local robustness Parquet.

## Bar and label semantics

Bar semantics remain the accepted canonical session-open anchored resampling semantics:

- first observed open by event time;
- maximum high;
- minimum low;
- last observed close by event time;
- summed volume;
- expected minute count equal to the target bar width;
- `is_complete = observed_minute_count == expected_minute_count`;
- no interior-minute fill.

Labels remain exact same-session simple RAW returns:

```text
target_close / source_close - 1
```

The source close is the exact 1m close whose `available_at` equals the bar `available_at`. The target is the exact same-session source minute offset plus 30, 60 or 120 trading minutes.

Missingness remains three-valued:

- target would cross the session -> `target_crosses_session`;
- exact target minute absent -> `target_minute_missing`;
- exact target exists -> available label.

No approximate nearest-minute target and no cross-session fill are allowed.

## Annual evidence

Each annual Parquet emits row-free evidence for every frozen slice:

- row count;
- asset count;
- complete-bar count;
- available-label count;
- joint complete-bar/available-label count;
- formation count;
- formations reaching frozen `minimum_cross_section=10`;
- minimum and maximum joint breadth.

The annual gate fails closed on empty output, duplicate `(slice_id, asset, available_at)` keys, sessions outside the requested year, an invalid asset count, or any frozen slice that never reaches the existing minimum cross-section.

The resumable inspector validates all three annual artifacts, content-addressed plan/evidence identities, and the actual Parquet SHA-256 through the existing `MinuteMaterialization` identity before a year is skipped. A partial or tampered triplet is never silently overwritten.

## Operators

One year:

```powershell
python scripts/materialize_us_r2_robustness_base_year.py `
  D:\Data\datasets--mito0o852--OHLCV-1m `
  --year 2006 `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --memory-limit 16GB `
  --threads 4 `
  --max-temp-directory-size 40GB `
  --temp-directory data/duckdb_temp/us_r2_robustness_base
```

Resumable full OOS range:

```powershell
python scripts/materialize_us_r2_robustness_base_all_years.py `
  D:\Data\datasets--mito0o852--OHLCV-1m `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --memory-limit 16GB `
  --threads 4 `
  --max-temp-directory-size 40GB `
  --temp-directory data/duckdb_temp/us_r2_robustness_base
```

Default outputs are under ignored local paths:

```text
data/us_r2/robustness/base/year=YYYY/us_r2_robustness_base.parquet
reports/us_r2/robustness/base/year_YYYY/us_r2_robustness_base_plan.json
reports/us_r2/robustness/base/year_YYYY/us_r2_robustness_base_evidence.json
reports/us_r2/robustness/base/us_r2_robustness_base_batch_evidence.json
```

## Authority boundary

A passing robustness-base batch proves only that the four exact R1 robustness data slices are reproducibly available. It does not:

- evaluate any of the 37 candidate features;
- filter or select candidates;
- read pooled performance to change the denominator;
- compute frequency/decay sign consistency;
- evaluate the final Alpha Gate;
- grant stage-exit, Alpha, execution, order, PAPER or live-capital authority;
- create a PIT/survivorship-safe market-universe claim.

The next separate increment may materialize/evaluate the frozen 37 candidates on these exact slices. `docs/status.toml` remains unchanged until a complete reviewed R2 terminal exists.
