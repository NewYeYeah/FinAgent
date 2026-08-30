# V4-4 — Portfolio / Execution Interactive Pack

## Status

**Completed.** V4-4 is the delivered implementation milestone. The next roadmap stage is V4-5 Linked Analytics Acceptance.

The composed Workbench Evidence API now reports `finagent-workbench-api-v4.4` and exposes `portfolio_execution` capability status from the top-level `workbench_api.py` composition boundary. V4-4 routes are attached independently of the V4-3 Factor route module.

## Scope

V4-4 activates the Portfolio and Execution analytical modules over evidence that was already frozen by A4 and V4-0. It does not introduce a replacement portfolio engine, execution simulator, benchmark model, exposure model, or browser-side financial calculation authority.

## Evidence authority

### Authoritative A4 portfolio evidence

The Portfolio surface consumes the existing A4 validation report for:

- gross and net NAV;
- gross and net period returns;
- frozen aggregate and fold performance metrics;
- total fees/slippage/turnover and implementation shortfall;
- frozen A4 economic evidence;
- immutable execution-ledger identity and digest.

These values are projected without recomputation.

### Authoritative V4-0 execution evidence

The Execution surface consumes verified `StrategyDecisionSeriesEvidence` for:

- `asset` and `session_date`;
- pre-trade / target / realized weight;
- `client_order_id`;
- desired / executable / filled quantity;
- reference / fill / close price;
- fee and slippage rows;
- gross / net PnL rows;
- decision status and A3 `constraint_codes`.

`client_order_id` is retained as the order interaction identity. V4-4 does not synthesize a new order identifier.

## Derived presentation evidence

The Evidence Plane may deterministically derive the following views from verified authoritative inputs:

- drawdown: `NAV / running_peak_NAV - 1`;
- rolling compounded return, annualized volatility and Sharpe over the selected A4 period-return window;
- calendar-month return matrix using `product(1 + period_return) - 1`;
- fee/slippage waterfall as a filtered sum of authoritative V4-0 row costs;
- desired → executable → filled funnel as counts over authoritative V4-0 quantities;
- constraint attribution as counts over authoritative V4-0 `constraint_codes`.

Every such response is labeled `derived_presentation` and includes its `source_authority`. React consumes these values and does not recreate them.

## Missing evidence / no-fabrication boundary

V4-4 explicitly reports immutable benchmark return/NAV evidence as unavailable. It does not infer a benchmark series, alpha, beta, information ratio, benchmark-relative drawdown, style exposure, industry exposure, capacity, or risk contribution.

These require separately frozen core evidence before a future analytical surface may claim them.

## GET-only API

The Evidence Plane exposes:

```text
GET /api/v4/portfolio-execution/status
GET /api/v4/portfolio-execution
GET /api/v4/portfolio-execution/{portfolio_validation_id}
GET /api/v4/portfolio-execution/{portfolio_validation_id}/series
GET /api/v4/portfolio-execution/{portfolio_validation_id}/analytics
GET /api/v4/portfolio-execution/{portfolio_validation_id}/decisions
```

Browser decision and series queries retain the hard `limit <= 5000` boundary. Server-side aggregation over a larger verified V4-0 series pages through the bounded projection rather than silently truncating at the first 5000 rows.

No V4-4 mutation route exists.

## WorkbenchContext

The URL-backed context now includes a durable `order_id` key (`?order=`). Portfolio and Execution interactions use:

```text
portfolio_validation_id
asset_id
order_id
session_date
date_range
fold_id
```

Cross-module Portfolio ↔ Execution navigation and browser reload preserve these identities. Selecting `session_date` constrains both authoritative decision rows and server-side derived execution aggregations to that same session. Asset/order identity remains contextual on Portfolio navigation but does not incorrectly filter account-level A4 NAV.

## UI surfaces

### Portfolio

- frozen A4 return / Sharpe / drawdown / turnover cards;
- authoritative gross/net NAV plus labeled derived drawdown;
- rolling performance;
- monthly return matrix;
- filtered fee/slippage waterfall;
- explicit benchmark-unavailable evidence state.

### Execution

- authoritative target vs realized weight series;
- order/session/asset/fold/date selectors;
- desired/executable/filled funnel;
- A3 constraint-code attribution;
- fee/slippage waterfall;
- bounded authoritative decision-row table with `client_order_id`, quantities, costs, PnL and constraint codes.

## Acceptance

V4-4 adds focused backend tests for:

- A4 ↔ V4-0 identity binding;
- authoritative A4 point preservation;
- authoritative V4-0 order/weight/constraint rows;
- top-level Workbench `v4.4` capability/status projection;
- GET-only and bounded APIs;
- fail-closed invalid date/session combinations;
- derived-presentation authority labels.

Frontend acceptance covers:

- `WorkbenchContext` order identity round-trip;
- Portfolio / Execution panel activation;
- React no-recompute messaging;
- asset/order/session linked filtering;
- canonical `/portfolio` and `/execution` navigation;
- TypeScript, Vitest, production build and Playwright browser smoke.

The retained CI matrix covers repository/A2.6/legacy UI regressions, Ubuntu/Windows Workspace API, Ruff/mypy, TypeScript/Vitest/build and Playwright. Per development policy, Windows remains a retained CI path but is not required to block V4-4 reporting once Ubuntu API, frontend and quality are green.
