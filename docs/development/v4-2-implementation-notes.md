# V4-2 Strategy Decision Explorer — implementation notes

This note records the implementation boundary while V4-2 is under acceptance. The canonical roadmap remains authoritative for milestone status.

## Evidence source

V4-2 consumes only verified `finagent.strategy-decision-series.manifest.v1` / Parquet evidence produced by V4-0. The browser does not read host paths or A4 JSONL directly and does not reconstruct the strategy decision chain from A4 summary reports.

The Evidence Plane discovers V4-0 manifests under configured report roots and opens each candidate through `StrategyDecisionSeriesProjection`. A series is visible only after the source A4 report, execution ledger and Parquet bindings pass their existing SHA/identity/schema checks. Equivalent duplicate manifests are de-duplicated; conflicting identities fail closed.

## Product surface

The Strategy module is activated in the V3 Workbench registry and uses the existing URL-backed `WorkbenchContext` for:

- `portfolio_validation_id`;
- `asset_id`;
- `date_range`;
- `session_date`;
- `fold_id`.

The explorer renders server-projected V4-0 rows for:

- authoritative close/reference/fill price timeline with buy/sell fill markers;
- pre-trade / target / realized weights;
- combined frozen AlphaModel score, rank, expected return and uncertainty;
- desired / executable / filled quantity and A3 constraint codes;
- per-session gross/net asset PnL, fees and slippage;
- frozen selected-factor identities and immutable A2.6/A4 lineage context.

## Deliberate non-fabrication boundaries

### No synthetic candlesticks

V4-0 persists `close_price`, `reference_price` and `fill_price`, but it does not persist authoritative open/high/low bars. V4-2 therefore labels its main chart as a close-price execution timeline and reports `ohlc_available=false`. A candlestick surface requires a separately frozen OHLC evidence contract; the browser must not manufacture OHLC from close marks.

### No inferred per-factor contribution

V4-0 persists the combined frozen A4 alpha score/forecast and selected factor identities, but not each factor's per-asset contribution at each formation timestamp. V4-2 renders combined alpha context plus component identities only. Per-factor contribution cannot be reverse engineered in React and must be added as core evidence before any future contribution chart claims authority.

### No browser financial recomputation

The browser does not calculate cumulative PnL, portfolio NAV, target weights, execution realization or alpha. It renders the per-session values supplied by the verified bounded V4-0 projection. Presentation-only chart layout is not evidence.

## API

GET-only Evidence Plane endpoints:

```text
GET /api/v4/strategy-series
GET /api/v4/strategy-series/by-portfolio/{portfolio_validation_id}
GET /api/v4/strategy-series/{series_id}
GET /api/v4/strategy-series/{series_id}/dimensions
GET /api/v4/strategy-series/{series_id}/decisions
```

Decision queries retain the V4-0 bound `1 <= limit <= 5000` and support asset/fold/date/offset filters. No POST/PUT/PATCH/DELETE V4-2 route exists.

## Authority

V4-2 is a read-only linked analytics surface. It adds no reserve, strategy-promotion, PAPER, broker, live-capital, arbitrary shell or arbitrary Python authority, and it does not make A2.6/A4 generic commands executable.
