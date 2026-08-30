# V4-2 read API contract

The Strategy Decision Explorer consumes only GET-only Evidence Plane projections over verified V4-0 StrategyDecisionSeries artifacts.

```text
GET /api/v4/strategy-series
GET /api/v4/strategy-series/by-portfolio/{portfolio_validation_id}
GET /api/v4/strategy-series/{series_id}
GET /api/v4/strategy-series/{series_id}/dimensions
GET /api/v4/strategy-series/{series_id}/decisions
```

The decision endpoint accepts only bounded semantic filters:

```text
asset
start
end
fold_id
limit  (1..5000)
offset (>=0)
```

It accepts no host path, report path, Parquet path, Python, shell, calculation expression, output path or command input. Full financial facts remain owned by the immutable V4-0 row.

The presentation contract declares:

```text
price_semantics = authoritative_close_only
ohlc_available = false
browser_recomputation = false
factor_contribution_semantics = combined alpha context and frozen component identities only
```

A future candlestick chart therefore requires separate authoritative OHLC evidence rather than a browser transformation of `close_price`.
