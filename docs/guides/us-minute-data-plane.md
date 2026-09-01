# U.S. minute Data Plane

US-D1 introduces the first out-of-core read path over the admitted `mito0o852/OHLCV-1m` local snapshot. The Data Plane is intentionally narrower than later US-D2 semantics: it reads source-native 1-minute rows, applies the accepted cleaning/quarantine stack, preserves explicit PIT clocks, and keeps session classification/resampling/corporate-action adjustment out of this layer.

## Current implemented capability

```text
engine                 DuckDB
storage                monthly Parquet
interval               1m
session policy         all_observed
price basis            raw
availability clocks    event_time / available_at
available_at           source bar-start timestamp + 1 minute
session_type           observed_unclassified
```

`REGULAR`, `EXTENDED`, split-adjusted/total-return-adjusted reads and higher intervals are deliberate capability gaps until US-D2 binds them to calendar/action/resampling evidence.

The full-corpus store and test fixture use the same `DuckDBParquetMinuteStore`; there is no fixture-specific query engine.

## Why real source rows are not committed

The admitted historical corpus remains scoped to `local_non_redistributed_research`, and source usage/redistribution rights remain unresolved. Do **not** commit a subset of the real OHLCV rows merely to make CI convenient.

The repository instead contains:

```text
tests/fixtures/us_minute/synthetic_ohlcv.csv
```

This is fully synthetic, follows the same raw schema and contains synthetic exact/conflicting duplicates plus invalid OHLC/volume rows. CI converts it to monthly Parquet with DuckDB and runs the actual Data Plane against those Parquet files.

For local L3 integration, use the real-sample exporter. Its default output is under `/data`, which is ignored by Git.

## Local real-data development sample

Windows / Conda:

```powershell
(finagent) PS D:\PythonWorkspace\FinAgent> python scripts\export_us_minute_dev_sample.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --asset MSFT `
  --asset NVDA `
  --asset AMD `
  --asset INTC `
  --start 2026-03-23T00:00:00+00:00 `
  --end 2026-04-01T00:00:00+00:00 `
  --output-dir data\dev_samples\us_minute_seed
```

The exporter:

- verifies the exact accepted revision and inventory identity;
- applies the accepted whole-conflict-group quarantine and row cleaning;
- caps one export at 32 assets and 31 days;
- preserves the original raw monthly schema and filenames;
- writes a local `sample_manifest.json` with an explicit `do_not_commit_or_redistribute` limitation.

The exported rows are a developer sample only. They are not a ResearchUniverse, Alpha dataset or redistribution artifact.

## Full local-corpus smoke

A bounded query against the full 87GB corpus uses the same code:

```powershell
(finagent) PS D:\PythonWorkspace\FinAgent> python scripts\smoke_us_d1_minute_store.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --asset MSFT `
  --asset NVDA `
  --asset AMD `
  --asset INTC `
  --start 2026-03-23T13:31:00+00:00 `
  --end 2026-03-27T20:01:00+00:00 `
  --output reports\us_d1\seed_week.parquet
```

The query interval is `[start, end)`. Under the default `available_at` policy, a raw bar timestamped `13:30` becomes observable at `13:31`; the Data Plane therefore pushes an event-time window shifted back by one minute into the monthly Parquet scan.

The query plan reports selected partition months/bytes and the materializer reports actual row count and output size. The store never constructs a multi-year dense NumPy/pandas panel.

## Predicate and cleaning boundary

For a bounded asset/time query, ticker/time predicates are inserted into the monthly `base` scan **before** duplicate classification. This still retains all variants of every requested `(ticker,timestamp)` key, so exact duplicate collapse and whole-key conflicting duplicate quarantine remain valid while avoiding a full-month all-ticker duplicate aggregation.

After monthly reads are unioned, the Data Plane repeats exact/conflicting duplicate protection across partition boundaries before projecting canonical rows.

## Development ordering

US-I0 remains the current stage until the full 20–30-name EngineeringUniverse is frozen. The accepted four-name seed mapping is sufficient to develop and validate the US-D1 foundation in parallel. The complete EngineeringUniverse remains a gate before broader data certification/baseline research; seed-only development does not create a market-wide or survivorship-unbiased claim.
