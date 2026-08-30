# V4-5 Linked Analytics Acceptance

Status: **Completed implementation / A-C0 acceptance stage**  
Stage: **A-C0 — V4-5 Linked Analytics Acceptance**  
Planning baseline: [`current-development-plan-v4.0.md`](current-development-plan-v4.0.md)  
Next stage: **A-C1 — Historical Workbench Operational Closure**

## Purpose

V4-5 accepts the delivered V4 analytical product as one coherent read-only system. It does not add another chart family and does not introduce a new financial or statistical calculation authority.

The accepted product surfaces are:

```text
Strategy
Factors
Portfolio
Execution
```

V4-5 verifies their source evidence, authority class, unavailable-evidence policy, linked WorkbenchContext semantics, bounded API behavior and Evidence/Control authority boundary as one system.

## Delivered acceptance contract

Added:

```text
src/finagent/visualization/linked_analytics_acceptance.py
src/finagent/visualization/linked_analytics_acceptance_routes.py
```

`LinkedAnalyticsAcceptanceProjection` is an acceptance-only projection. Its authority is explicitly:

```text
acceptance_contract_only_no_financial_authority
```

It does not calculate NAV, return, alpha, factor statistics, target weights, execution quantities, PnL, cost or risk.

The Workbench capability version advances to:

```text
finagent-workbench-api-v4.5
```

The acceptance contract is exposed through:

```text
GET /api/v4/linked-analytics/status
GET /api/v3/workbench/status
```

No V4-5 mutation route exists.

## Surface evidence matrix

### Strategy

Required evidence:

```text
StrategyDecisionSeriesEvidence V4-0
```

Authoritative source rows include:

- close/reference/fill price;
- alpha score/rank and frozen AlphaModel context;
- pre-trade/target/realized weights;
- desired/executable/filled quantities;
- fees/slippage/gross/net PnL;
- decision status;
- `client_order_id`;
- `constraint_codes`.

Explicitly unavailable and not inferred:

```text
OHLC candlesticks
per-asset per-factor contribution
```

The existing close-only Strategy view therefore remains correct until A-C2 introduces separately frozen `MarketBarSeriesEvidence`.

### Factors

Required evidence:

```text
FactorSeriesEvidence V4-1
frozen A2.6 ResearchProgram summary
```

Authoritative/persisted evidence includes:

- period IC/RankIC;
- turnover;
- coverage;
- persisted rolling/NAV transforms with their original derived authority;
- A2.6 inference, multiplicity, gate and correlation summaries.

Presentation-derived only:

```text
fold/year IC means
factor-correlation cluster ordering
```

Explicitly unavailable and not inferred:

```text
Agent generation chronology
```

### Portfolio

Required evidence:

```text
authoritative A4 portfolio validation evidence
verified StrategyDecisionSeriesEvidence V4-0
```

Authoritative source evidence includes:

- gross/net NAV;
- gross/net period returns;
- frozen aggregate/fold/economic metrics;
- immutable execution-ledger identity.

Server-side presentation derivatives remain:

- drawdown;
- rolling return/volatility/Sharpe;
- calendar monthly return matrix;
- filtered cost totals.

Explicitly unavailable and not inferred:

```text
benchmark return/NAV
benchmark-relative alpha/beta/information ratio
industry/style exposure
capacity
risk contribution
```

### Execution

Required evidence:

```text
verified StrategyDecisionSeriesEvidence V4-0
A3 decision semantics persisted in V4-0 rows
```

Authoritative source evidence includes:

- target/realized weights;
- `client_order_id`;
- desired/executable/filled quantities;
- reference/fill/close prices;
- fees/slippage/gross/net PnL;
- decision status and constraint codes.

Server-side presentation derivatives remain:

- desired → executable → filled funnel;
- constraint-code counts;
- filtered fee/slippage totals.

Explicitly unavailable and not inferred:

```text
capacity/impact model
broker/live account state
```

## WorkbenchContext acceptance

V4-5 freezes the linked analytical identity set used across Strategy, Factors, Portfolio and Execution:

```text
program_id
factor_id
portfolio_validation_id
asset_id
order_id
date_range
session_date
fold_id
```

The context remains presentation state rather than evidence authority.

Acceptance now covers:

```text
Strategy → Factors → Portfolio → Execution
             ↓
       browser back/forward
             ↓
            reload
```

All linked identities must round-trip through URL query state without reinterpretation.

The browser may preserve a context identity on a surface that does not use that identity for calculation. For example, `asset_id` and `order_id` remain visible when navigating to account-level Portfolio analytics, but they do not filter or redefine authoritative A4 NAV.

## Bounded API / pagination acceptance

All browser-facing long-row endpoints retain the hard bound:

```text
limit <= 5000
```

V4-5 tests this bound jointly for:

- Strategy decision rows;
- Factor period rows;
- Portfolio series rows;
- Execution decision rows.

A separate acceptance test simulates **5,001 execution decision rows** and verifies that server-side V4-4 aggregate analytics request pages at offsets:

```text
0
5000
```

The resulting fee/slippage/funnel/constraint aggregates must include all 5,001 rows. This prevents the common failure mode where a bounded browser API silently becomes the aggregation denominator.

## Evidence / Control authority acceptance

The V4 linked analytical Evidence Plane remains limited to:

```text
GET
HEAD
OPTIONS
```

The V4-5 route inventory explicitly checks Strategy, Factors, Portfolio/Execution and linked-analytics route prefixes for mutation methods.

Control authority remains the accepted V3 ceiling:

```text
L0
L1
```

V4-5 does not add:

```text
L2 / L3 authority
reserve execution
strategy promotion
PAPER mutation
broker order submission
live-capital authority
arbitrary shell/Python execution
```

## Browser recomputation acceptance

The acceptance contract records:

```text
browser_recomputation = false
```

for every V4 analytical surface.

The browser remains a rendering/interaction client. Financial/statistical facts are either:

1. authoritative immutable core evidence;
2. an explicitly labeled persisted or server-side deterministic presentation derivative; or
3. explicitly unavailable.

There is no fourth category in which React silently reconstructs a missing research or execution fact.

## Test coverage

Backend acceptance:

```text
tests/test_linked_analytics_acceptance_v45.py
```

Covers:

- exact Workbench `v4.5` capability;
- one combined runtime acceptance over V4-1 + V4-0/A4 evidence;
- surface evidence/authority/unavailable declarations;
- V4 route inventory GET-only enforcement;
- browser row bound `limit <= 5000`;
- explicit missing OHLC/Agent chronology/benchmark semantics;
- server pagination beyond 5,000 execution rows.

Frontend context unit coverage extends:

```text
workspace/src/workbench/context.test.ts
```

with the complete V4-5 linked identity round-trip.

Browser acceptance:

```text
workspace/e2e/linked-analytics-v45.spec.ts
```

covers cross-module navigation, browser back/forward, reload, Context retention and unavailable Control Plane behavior.

The first browser run exposed only an ambiguous Playwright text locator for `Evidence Plane`; the locator was narrowed to the sidebar footer. No production product semantic was changed by that repair.

## CI integration

`.github/workflows/workspace.yml` now includes the V4-5 backend acceptance test and the new acceptance projection/routes in:

- focused Workspace API testing;
- Python compile checks;
- Ruff;
- mypy;
- existing TypeScript/Vitest/build/Playwright frontend gates.

Windows remains retained in the matrix and remains asynchronous for development reporting under the existing project policy.

## Acceptance result

V4-5 freezes the following product invariant:

```text
verified immutable evidence
        ↓
read-only bounded projections
        ↓
explicit authoritative / derived / unavailable semantics
        ↓
URL-backed linked WorkbenchContext
        ↓
presentation-only React
```

V4 linked analytics is therefore closed as a feature family. Further Workbench development now moves to **A-C1 Historical Workbench Operational Closure**, whose purpose is to extract the historical research/A2.6/A4 orchestration into bounded typed L1 application services rather than add more analytical charts.
