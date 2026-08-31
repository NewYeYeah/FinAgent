# A-C2 MarketBarSeriesEvidence + Frequency Contract

Status: **Implementation complete / unified acceptance pending**  
Stage: **A-C2 — MarketBarSeriesEvidence + Frequency Contract**  
Planning authority: [`current-development-plan-v4.0.md`](current-development-plan-v4.0.md)  
Next stage after acceptance: **A-C3 — Real A-share Historical E2E Acceptance**

## Purpose

A-C2 closes the authoritative market-price visualization gap that remained after V4-5. V4-0 deliberately persists close/reference/fill prices but does not contain OHLC. A-C2 therefore introduces an independent, immutable market-bar evidence authority rather than reconstructing candles from StrategyDecisionSeries rows.

The resulting authority split is:

```text
StrategyDecisionSeriesEvidence V4-0
  → signal / alpha / target / order / fill / constraint / PnL authority

MarketBarSeriesEvidence A-C2
  → raw OHLCV / interval / timestamp / session authority

Workbench Strategy
  → presentation-only overlay of both verified evidence sources
```

React never constructs OHLC from close marks and never upgrades a missing MarketBarSeries into synthetic candles.

## Step 1 — Frequency, session and evidence contracts

A-C2 adds generic contracts in:

```text
src/finagent/domain/market_bars.py
```

### BarInterval

Frozen canonical intervals:

```text
1m / 5m / 15m / 30m / 60m / 1d
```

The contract is provider-neutral and is intended to be reused by the later U.S. M1 / MT5 path.

### BarTimestampConvention

```text
bar_start
bar_end
session_open
```

`event_time` describes the bar timestamp convention. `available_at` remains an independent PIT clock and may not precede `event_time`.

### MarketSessionSpec / SessionSegment

Session structure is explicit rather than inferred from gaps in a time series.

The A-share A-C2 session specification is:

```text
Asia/Shanghai
09:30–11:30 regular morning
13:00–15:00 regular afternoon
```

This preserves the lunch break as market-session semantics rather than treating it as missing data.

### LabelHorizonPolicy

A-C2 freezes the vocabulary required before minute research:

```text
BAR_COUNT
TRADING_MINUTES
SAME_SESSION
TRADING_DAYS
```

A same-session horizon cannot enable cross-session labels. The contract exists now so later U.S. intraday research does not silently treat a bar count as an overnight-capable trading-time horizon.

### MarketBarRow

Each authoritative bar persists:

```text
asset
session_date
event_time
available_at
interval
open / high / low / close / volume
session_id
session_type
source
data_version
```

Validation rejects:

- timezone-naive timestamps;
- `available_at < event_time`;
- non-positive OHLC;
- invalid high/low envelopes;
- negative/non-finite volume;
- missing source/session/data identities.

## MarketBarSeriesEvidence

Implemented in:

```text
src/finagent/data/market_bar_series.py
```

Schemas:

```text
finagent.market-bar-row.v1
finagent.market-bar-series.manifest.v1
finagent.market-bar-series.query.v1
```

The immutable manifest binds:

```text
series_id
linked_strategy_series_id
portfolio_validation_id
source_identity
data_version
interval
timestamp_convention
session_spec
label_horizon_policy
rows_digest
data_file / data_sha256
row / asset / session counts
date range
```

`series_id` is content-addressed from the complete evidence identity and row digest. The verified projection checks Parquet SHA-256, canonical columns, row count, contiguous sequence, unique row identity, asset/session counts, interval and data version before exposing a row.

Browser queries remain bounded:

```text
1 <= limit <= 5000
```

Filters are server-side:

```text
asset / start / end / offset
```

## Strategy binding

`StrategyDecisionExplorerProjection` now discovers MarketBarSeries manifests in a second verification pass.

A bar series may bind to a strategy only when all three identities agree:

```text
linked_strategy_series_id
portfolio_validation_id
data_version
```

Failure behavior is deliberately fail-closed:

- unknown strategy identity → binding omitted;
- portfolio validation mismatch → binding omitted + warning;
- data-version mismatch → binding omitted + warning;
- multiple non-equivalent MarketBarSeries for one StrategyDecisionSeries → all OHLC binding for that strategy is omitted until the conflict is resolved.

Equivalent rematerializations may be deduplicated without creating a second authority.

## Evidence API

A-C2 adds GET-only endpoints:

```text
GET /api/v4/strategy-series/{series_id}/market-bar-binding
GET /api/v4/strategy-series/{series_id}/market-bars
```

The Strategy catalog, dimensions and detail projections now agree on OHLC availability and authority.

When evidence exists:

```text
ohlc_available = true
ohlc_authority = MarketBarSeriesEvidence
```

When evidence is absent or fails binding:

```text
ohlc_available = false
ohlc_authority = unavailable
```

A missing bar series returns an explicit unavailable state; the server does not derive OHLC from V4-0 close marks.

## A-share source materialization

A-C2 retains the frozen Phase-1 `DataAdapter` interface. The local A-share research adapter exposes a narrow read-only `bar_history()` boundary for evidence materialization instead of requiring downstream code to depend on `_query_records` implementation details.

Host-side materialization is provided by:

```text
scripts/materialize_local_ashare_market_bars.py
```

The command is intentionally **not** added to the generic Workbench Control Plane.

It:

1. verifies the source StrategyDecisionSeries manifest/Parquet;
2. derives the exact strategy asset and date scope;
3. reads certified raw A-share bars through the adapter boundary;
4. compares the adapter's real `data_version` to the strategy's frozen `data_version`;
5. refuses the binding when the versions differ;
6. materializes sibling MarketBarSeries manifest + Parquet evidence.

A-C2 formally supports only the currently audited local frequencies through this CLI:

```text
1d   primary acceptance path
1min contract/intraday smoke path
```

It does not certify 5/15/30/60-minute vendor aggregation and does not reopen a full A-share minute research program.

## Workbench presentation

Strategy retains two explicit modes.

### Verified MarketBarSeries present

The main timeline renders:

```text
OHLC candlesticks
+ V4-0 reference marker
+ V4-0 buy fill marker
+ V4-0 sell fill marker
```

ECharts candlestick values are passed directly as:

```text
[open, close, low, high]
```

from MarketBarSeries rows. React performs only coordinate/presentation mapping.

### MarketBarSeries unavailable

The existing V4-2 close/reference/fill timeline remains intact. The UI explicitly states that no verified MarketBarSeries is bound and does not render candles.

## V4-5 acceptance compatibility

The linked-analytics acceptance contract is generalized from:

```text
OHLC must be unavailable
```

to:

```text
if OHLC available:
    authority must be MarketBarSeriesEvidence
else:
    authority must be explicitly unavailable
```

This preserves V4-5's core invariant: missing evidence is never inferred and browser recomputation remains false.

## Test strategy

Per the development-efficiency policy, Step 1 and Step 2 were implemented before opening the PR or running the unified gate.

The A-C2 blocking gate is only:

```text
Ubuntu latest
Python 3.11
Workspace focused API regression
Ruff / typed-boundary mypy / pip check
frontend TypeScript / Vitest / build / Playwright
```

The previous Windows API matrix is removed from this Workbench stage. Windows/PowerShell compatibility remains a design constraint inherited from A-C1, but Windows CI is not executed as part of A-C2 acceptance.

## Acceptance cases

A-C2 tests cover:

- PIT timestamp rejection;
- session/horizon contract validation;
- content-addressed manifest verification;
- authoritative raw OHLC query;
- exact Strategy/A4/data-version binding;
- GET-only API and 5000-row browser bound;
- data-version mismatch fail-closed behavior;
- conflicting MarketBarSeries fail-closed behavior;
- legacy Strategy close-only fallback;
- frontend authoritative candlestick mode;
- no browser OHLC reconstruction.

## Completion rule

After the unified Ubuntu/Python 3.11 and frontend gates pass, this document will be marked **Completed**, the roadmap will advance to **A-C3 Real A-share Historical E2E Acceptance**, and the PR will be merged to `main`.
