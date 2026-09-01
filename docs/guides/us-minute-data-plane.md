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

This fixture is fully synthetic, follows the same raw schema and contains synthetic exact/conflicting duplicates plus invalid OHLC/volume rows. CI converts it to monthly Parquet with DuckDB and runs the actual Data Plane against those Parquet files.

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

The US-D1 closure smoke intentionally intersects at least four mapped assets and two monthly partitions. It executes against the complete local snapshot inventory while keeping the actual query bounded:

```powershell
(finagent) PS D:\PythonWorkspace\FinAgent> python scripts\smoke_us_d1_minute_store.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --asset MSFT `
  --asset NVDA `
  --asset AMD `
  --asset INTC `
  --start 2026-01-01T00:00:00+00:00 `
  --end 2026-03-01T00:00:00+00:00 `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\us_d1 `
  --output data\dev_samples\us_d1_smoke\seed_jan_feb.parquet `
  --report-output reports\us_d1\us_d1_smoke_report.json
```

Default behavior materializes the same deterministic plan twice and requires identical row count, content SHA-256 and materialization identity. The portable report contains identities, counts, selected partition bytes and engine settings, but no source OHLCV rows. The two real-data Parquet outputs remain under the gitignored `/data` tree.

The execution policy freezes:

```text
DuckDB memory_limit
DuckDB thread count
preserve_insertion_order = false
temporary spill allowed/disabled
maximum temporary-directory size
```

The default `512MB` memory setting is an engine resource policy, not a claim that total process RSS can never exceed 512MB. The explicit temporary-directory ceiling prevents an out-of-core query from consuming unbounded local disk.

Use `--no-allow-temp-spill` only for a deliberate no-spill diagnostic. The script then applies `max_temp_directory_size=0B`; large queries may correctly terminate with an out-of-memory error rather than silently using disk.

The query interval is `[start, end)`. Under the default `available_at` policy, a raw bar timestamped `13:30` becomes observable at `13:31`; the Data Plane therefore pushes an event-time window shifted back by one minute into the monthly Parquet scan.

The query plan reports selected partition months/bytes and the materializer reports actual row count, output size and content SHA-256. The store never constructs a multi-year dense NumPy/pandas panel.

## Predicate and cleaning boundary

For a bounded asset/time query, ticker/time predicates are inserted into the monthly `base` scan **before** duplicate classification. This still retains all variants of every requested `(ticker,timestamp)` key, so exact duplicate collapse and whole-key conflicting duplicate quarantine remain valid while avoiding a full-month all-ticker duplicate aggregation.

After monthly reads are unioned, the Data Plane repeats exact/conflicting duplicate protection across partition boundaries before projecting canonical rows.

## Development ordering

US-I0 seed mapping is accepted for MSFT/NVDA/AMD/INTC. That seed is sufficient for US-D1 implementation and real-corpus closure smoke. Expansion to the planned 20–30-name EngineeringUniverse remains parallel work and must be completed before broader US-D3 certification and US-B0 baseline research; it does not need to block storage/query-engine development.
