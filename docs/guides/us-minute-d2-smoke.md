# U.S. minute US-D2 transform smoke

The final US-D2 local gate exercises the accepted real OHLCV-1m snapshot through the complete narrowed transform path:

```text
admitted raw 1m
  -> XNYS sessionization
  -> regular-session 5m / 15m / 30m resampling
  -> exact same-session 60-trading-minute labels
  -> corporate-action research authority checks
```

The smoke report contains no real OHLCV price rows. Real derived Parquet materializations are written under `/data` and remain local/non-redistributed.

## Scenarios

The frozen smoke uses four accepted seed assets by default (`MSFT`, `NVDA`, `AMD`, `INTC`) and three calendar scenarios:

```text
half_day  2025-11-28 14:30–18:00 UTC  expected regular minutes: 210
pre_dst   2026-03-06 14:30–21:00 UTC  expected regular minutes: 390
post_dst  2026-03-09 13:30–20:00 UTC  expected regular minutes: 390
```

Each scenario records:

- actual regular 1m row count and expected-row coverage ratio;
- 5m/15m/30m materialization identity/content hash;
- complete/incomplete derived-bar counts and minimum source-minute coverage;
- canonical 60-trading-minute label denominator, available count, session-cross count and exact-target-missing count.

The smoke does not fail merely because an incomplete bar or exact target minute is observed; those conditions are preserved as evidence for US-D3 data certification. It fails if a required transform path produces no usable rows or an unknown label-unavailable reason appears.

Corporate-action checks require the current narrowed authority to remain stable:

```text
same-session RAW       allowed
cross-session RAW      denied
SPLIT_ADJUSTED         denied
TOTAL_RETURN_ADJUSTED  denied
```

## Windows / Conda command

After the smoke runner is merged to `main`:

```powershell
(finagent) PS D:\PythonWorkspace\FinAgent> python scripts\smoke_us_d2_transforms.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\us_d2 `
  --output-dir data\dev_samples\us_d2_smoke `
  --report-output reports\us_d2\us_d2_transform_smoke_report.json `
  --overwrite
```

The default asset set is the accepted four-name engineering seed. `--asset` may be repeated to replace it, with a smoke cap of 32 assets.

Only `reports\us_d2\us_d2_transform_smoke_report.json` should be shared for project review. Do not commit or redistribute the derived Parquet files under `/data`.

US-D2 may close only when the report has `passed=true` and `blockers=[]`. The 20–30-name EngineeringUniverse expansion remains a separate prerequisite before US-D3/broader research certification.
