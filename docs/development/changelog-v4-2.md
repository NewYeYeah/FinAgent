# V4-2 Strategy Decision Explorer

V4-2 delivers the first interactive linked-analytics surface over the immutable V4-0 `StrategyDecisionSeriesEvidence` contract. It activates the Strategy module in the V3 Workbench without changing A2.6/A4 evidence identity, reserve governance or Control authority.

## Evidence source and discovery

The Evidence Plane discovers `finagent.strategy-decision-series.manifest.v1` files under configured report roots. A candidate series is exposed only after `StrategyDecisionSeriesProjection` verifies the immutable V4-0 source bindings:

- source A4 report SHA-256 and semantic identity;
- source execution-ledger SHA-256 and canonical ledger digest;
- Parquet SHA-256, canonical columns, row count, row identity and ordering;
- A4 validation/spec, A2.6 program/selection/data/factor and fold AlphaModel identities.

Equivalent deterministic rematerializations with the same semantic `series_id` are de-duplicated even when their physical output filenames differ. A conflicting semantic identity sharing a `series_id` fails closed and is omitted from the explorer.

If optional DuckDB/local-Parquet support is unavailable, V4-2 records a catalog warning and leaves unrelated V3/V2 Workspace surfaces available instead of making Evidence Plane startup fail.

## GET-only V4 Evidence API

V4-2 adds these read-only routes:

```text
GET /api/v4/strategy-series
GET /api/v4/strategy-series/by-portfolio/{portfolio_validation_id}
GET /api/v4/strategy-series/{series_id}
GET /api/v4/strategy-series/{series_id}/dimensions
GET /api/v4/strategy-series/{series_id}/decisions
```

Decision queries accept only semantic filters:

```text
asset
start
end
fold_id
limit  (1..5000)
offset (>=0)
```

No route accepts a report path, Parquet path, host path, Python, shell, output path or calculation expression. POST/PUT/PATCH/DELETE are not added to the Evidence Plane.

## Strategy Workbench module

The Strategy panel is now an available V3 Workbench module at:

```text
/strategy
/strategy/{series_id}
```

It uses the existing URL-backed `WorkbenchContext` rather than creating page-local authoritative identity:

```text
portfolio_validation_id
asset_id
date_range
session_date
fold_id
```

Selection therefore survives context-preserving navigation, browser history and reload, and can link back to the corresponding A4 cockpit or frozen factor identities.

## Rendered analytical surfaces

All financial values below are read directly from bounded V4-0 rows:

- authoritative close/reference/fill price timeline;
- buy/sell fill markers;
- pre-trade, target and realized weights;
- frozen combined AlphaModel score, rank, expected return and uncertainty;
- desired, executable and filled quantities;
- A3 decision status and constraint codes;
- per-session gross/net asset PnL;
- fees and slippage;
- immutable data/program/selection/AlphaModel/factor identity context.

The browser does not calculate target weights, alpha, execution realization, cumulative portfolio PnL or any replacement numerical evidence.

## Deliberate non-fabrication boundaries

### No synthetic candlesticks

V4-0 persists `close_price`, `reference_price` and `fill_price`, but it does **not** persist authoritative open/high/low bars. V4-2 therefore declares:

```text
price_semantics = authoritative_close_only
ohlc_available = false
```

The main chart is an authoritative **close-price execution timeline**, not a fabricated candlestick chart. A later candlestick view requires a separately frozen OHLC evidence contract.

### No inferred per-factor contribution

V4-0 persists the combined frozen A4 alpha forecast and the selected factor identities, but not each factor's per-asset contribution at every formation timestamp. V4-2 displays the combined alpha context and component identities only. React does not reverse engineer factor contributions from weights or summary reports.

## Authority boundary

V4-2 remains Evidence-only and read-only. It adds no authority for:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

The existing generic Control Plane readiness is unchanged; A2.6 and A4 orchestration remain `adapter_required`.

## Acceptance coverage

V4-2 acceptance covers:

- verified V4-0 discovery, dimensions and bounded decisions;
- GET-only route enforcement and `limit <= 5000`;
- equivalent-rematerialization de-duplication;
- optional DuckDB degradation without Workspace failure;
- Ubuntu and Windows Workspace API execution;
- Ruff/mypy/dependency consistency;
- TypeScript typecheck, Vitest, production build and Playwright;
- Strategy WorkbenchContext asset/fold/date/portfolio persistence;
- absence of Control fallback when the local Control Plane is unavailable;
- repository Python 3.11/3.12/3.13 and Windows pytest regression;
- A2.6, V4-0, A5 reserve-governance and legacy Research UI regression.

V4-2 acceptance is an analytics/presentation acceptance. It is not evidence of persistent alpha, reserve authorization, strategy promotion or live readiness.
