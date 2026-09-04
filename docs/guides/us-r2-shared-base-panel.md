# US-R2 Shared Annual Base Panel — R2-1b / Base Layer

Issue: #158  
Predecessors: merged R2-0b protocol freeze and passing real R2-1a v2 regime evidence.  
Project authority remains `US-R1 / research iteration`.

This increment isolates the expensive historical minute-data scan from the 37-candidate denominator. It materializes the canonical 15m signal bars and the accepted same-session 60-trading-minute raw label once per calendar year. Candidate features are deliberately not evaluated in this layer.

## 1. Runtime architecture

The selected source corpus is roughly 82.4 GB across the R2 regime horizon. Repeating that scan by fold or candidate would dominate runtime.

The base layer therefore uses annual immutable partitions:

```text
25-name minute source for one calendar year
        ↓
existing cleaning + XNYS sessionization
        ↓
source_rows AS MATERIALIZED       ← source plan appears once
        ├──────── canonical 15m bars
        └──────── exact same-session 60m labels
                         ↓
              one annual Parquet
```

Later candidate materialization reads these Parquets. It must not return to raw 1m simply because a factor implementation changes.

Annual partitioning is a recovery boundary, not a statistical fold. A failed 2018 run does not invalidate immutable 2001–2017 outputs, and the five frozen R2 folds remain unchanged.

## 2. Why bars and labels share one source CTE

The accepted R1 implementation builds 15m bars and 60m labels from the same sessionized 1m source. Naively composing the two SQL plans can embed the expensive source query twice.

R2 uses one explicit DuckDB `AS MATERIALIZED` source CTE and derives both branches from it. The operator also intentionally does **not** call `count_plan_rows()` before `COPY`; doing so would execute the annual source plan twice. Row counts and diagnostics are computed only from the newly materialized annual Parquet.

## 3. Semantic parity with R1

This is a runtime refactor, not a research-method amendment.

15m bars preserve the accepted resampling semantics:

- session-open anchored buckets;
- `arg_min(open, event_time)`;
- `max(high)` / `min(low)`;
- `arg_max(close, event_time)`;
- summed volume;
- expected 15 observed minutes for `is_complete=true`;
- bucket-end `available_at`.

The label remains the canonical raw same-session 60-trading-minute simple return. The source minute is the exact 1m row whose `available_at` equals the 15m bucket end and the target is exactly `source_minute_offset + 60` in the same session.

The focused regression compares the shared plan against the existing resampling and labeling implementations row by row, including floating-point hex identity.

R1 three-valued label availability is also preserved. If the exact source endpoint minute does not exist, the joined row has:

```text
label_row_present = false
label_available = NULL
unavailable_reason = NULL
```

It is not rewritten into a new unavailable terminal.

## 4. Dynamic cross-section remains unchanged

All 25 frozen EngineeringUniverse names are requested from the source. The base layer does not statically delete symbols with short history.

Evidence records per-year:

- observed asset count;
- complete 15m bar count;
- available 60m label count;
- joint complete-bar + label rows;
- duplicate `(asset, available_at)` keys;
- unexpected assets;
- formation breadth;
- number of formations reaching the frozen `minimum_cross_section=10`.

A year with no formation reaching breadth 10 fails closed. No minimum percentage of formations is introduced here; candidate-specific history requirements are evaluated in the next layer.

## 5. Bound real regime predecessor

R2-1b binds the passing real v2 evidence:

```text
evidence_id = us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b
plan_id = us-r2-regime-projection-plan-v2-1dc872be45ecbfb49107a7c0
materialization_id = minute-materialization-938010968243986f7129bae8
endpoint_policy_id = us-r2-regime-endpoint-policy-4f11ebc379c0658861d984ab
```

The validator requires five folds, all four frozen regimes, at least 20 sessions per regime, no blockers, and `candidate_performance_read=false`.

## 6. Operator

`data/` and `reports/` remain gitignored. Run one year at a time:

```powershell
python scripts/materialize_us_r2_base_panel_year.py `
  D:\Data\datasets--mito0o852--OHLCV-1m `
  --year 2001 `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --regime-evidence reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --memory-limit 16GB `
  --threads 4 `
  --max-temp-directory-size 40GB `
  --temp-directory data/duckdb_temp/us_r2_base
```

Outputs are immutable:

```text
data/us_r2/base/year=YYYY/us_r2_15m60m_base.parquet
reports/us_r2/base/year_YYYY/us_r2_base_panel_plan.json
reports/us_r2/base/year_YYYY/us_r2_base_panel_evidence.json
```

For the first workstation validation, profile representative years before launching the whole range: 2001 (sparse early history), 2006 (first OOS year), 2022 (latest fold start), and 2026 (partial source year). Record wall-clock time and any DuckDB spill. Do not set a wall-clock research threshold from those profiles.

After representative years pass, a PowerShell loop may materialize the remaining years. The annual boundary provides resumability without overwrite semantics.

## 7. Next layer

The next R2-1b increment will consume only the annual base Parquets plus the small v2 regime Parquet. The 37 frozen candidates should be compiled together so shared primitive computations are reused; the A1 shared-DAG materializer already provides the relevant deterministic single-asset execution machinery for the legacy factor family.

No new A1 Agent candidate may enter the R2 denominator. No Alpha, stage-exit, execution, order, PAPER or live-capital authority is granted by this base-panel materialization.
