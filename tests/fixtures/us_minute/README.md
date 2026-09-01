# Synthetic U.S. minute fixture

This fixture is **fully synthetic** and is safe to commit to the public repository. It is not copied, sampled, transformed or reconstructed from the admitted `mito0o852/OHLCV-1m` corpus or from Finnhub.

The CSV intentionally mirrors the bound raw source schema:

```text
timestamp, open, high, low, close, volume, ticker
```

It contains four seed symbols (`MSFT`, `NVDA`, `AMD`, `INTC`) across March and April 2026 and includes deterministic defects used to verify the frozen admission cleaning semantics:

- one exact duplicate full row (`MSFT`, 2026-03-09 13:40 UTC) that must collapse;
- one conflicting duplicate key (`NVDA`, 2026-03-09 13:45 UTC) whose whole key group must be quarantined;
- one invalid OHLC row (`AMD`, 2026-03-09 13:50 UTC) that must be removed;
- one negative-volume row (`INTC`, 2026-03-09 13:55 UTC) that must be removed.

US-D1 tests convert this small committed CSV to monthly Parquet files with DuckDB before exercising the same `DuckDBParquetMinuteStore` used for local/full-corpus queries. There is no separate fixture-only query implementation.

Real local development samples must be exported under ignored `/data` or `/reports` paths and must not be pushed while the underlying dataset usage/redistribution rights remain unresolved.
