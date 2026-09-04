# US-R2 Base-Panel Batch Orchestration

Issue: #158  
Predecessor: merged PR #167 shared annual 15m/60m base panel.  
Project authority remains `US-R1 / research iteration`.

## Purpose

The annual base-panel operator is intentionally immutable: a year refuses to overwrite an existing data/report target. That is the correct evidence boundary for one partition, but a 2001-2026 workstation run also needs safe restart semantics.

This increment adds a thin batch orchestrator. It does **not** change the 15m bar, same-session 60m label, dynamic cross-section, five folds, regime classifier, 37-candidate denominator, statistical thresholds or Alpha gates.

## Annual state machine

For every requested frozen year the orchestrator inspects exactly three local outputs:

```text
data/us_r2/base/year=YYYY/us_r2_15m60m_base.parquet
reports/us_r2/base/year_YYYY/us_r2_base_panel_plan.json
reports/us_r2/base/year_YYYY/us_r2_base_panel_evidence.json
```

A year has only three accepted states:

```text
none exist
    -> invoke the existing annual materializer once

all three exist and validate
    -> skip the year

partial triplet or inconsistent evidence
    -> fail closed
```

The skip path reads only the local Parquet file metadata and JSON reports. It does not construct the Hugging Face source manifest, raw DuckDB minute store, sessionized source query or annual source plan. Therefore already completed years do not rescan raw 1m history.

## Validation of an existing year

Before a year is reused, the batch layer requires:

- annual plan/evidence schema versions;
- requested year identity;
- frozen R2 protocol and XNYS calendar identity;
- reviewed regime v2 evidence identity;
- recomputed content-addressed plan ID;
- one candidate-independent shared source relation in the recorded annual plan;
- recomputed content-addressed evidence ID;
- `passed=true`, empty blockers;
- no candidate/performance read and no stage/Alpha/execution/order authority;
- non-empty Parquet file;
- positive row/formation counts;
- at least one formation reaching the frozen `minimum_cross_section=10` breadth.

A partial triplet is never repaired automatically because the missing component may indicate an interrupted or failed annual COPY/report boundary. The operator leaves it for explicit review.

## Deterministic batch evidence

The batch evidence is derived only from the completed annual evidence set. Operational replay details such as whether a year was pre-existing or newly materialized are printed in the run summary but are excluded from the content-addressed batch evidence identity.

Therefore rerunning the same completed year set produces the same batch evidence ID even though the second run performs zero raw-source invocations.

## Operator

From current `main`:

```powershell
python scripts/materialize_us_r2_base_panel_all_years.py `
  D:\Data\datasets--mito0o852--OHLCV-1m `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --regime-evidence reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --calendar reports/us_calendar/xnys_1992_2026.json `
  --memory-limit 16GB `
  --threads 4 `
  --max-temp-directory-size 40GB `
  --temp-directory data/duckdb_temp/us_r2_base
```

Default requested years are the complete frozen range `2001..2026`. An explicit subset can be supplied for diagnostics:

```powershell
--years 2001 2006 2022 2026
```

The console summary exposes:

```text
requested_years
preexisting_years
materialized_years
raw_source_invocation_count
evidence_id
passed
```

The deterministic all-year evidence defaults to:

```text
reports/us_r2/base/us_r2_base_panel_batch_evidence.json
```

If that file already exists, replay accepts it only when the content-addressed evidence ID is identical.

## Next boundary

The next R2-1b increment may consume only these annual base Parquets plus the reviewed small regime projection and the exact frozen R1 candidate-denominator report. It must not fall back to raw 1m data and must validate denominator identity before evaluating any of the 37 candidates.

This batch layer grants no Alpha, execution, order, PAPER or live-capital authority and does not advance `docs/status.toml`.
