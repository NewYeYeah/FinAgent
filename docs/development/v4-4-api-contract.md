# V4-4 Portfolio / Execution API Contract

## Authority model

V4-4 is a read-only linked projection. It does not create a new source of portfolio or execution truth.

| Surface | Source | Authority |
| --- | --- | --- |
| Portfolio NAV / period returns / frozen metrics | A4 portfolio validation report | authoritative |
| Asset/order/weight/quantity/price/cost/PnL/constraint rows | V4-0 StrategyDecisionSeriesEvidence | authoritative |
| Drawdown / rolling view / monthly matrix | verified A4 points | derived_presentation |
| Filtered fee/slippage totals | verified V4-0 rows | derived_presentation |
| Order funnel | verified V4-0 quantities | derived_presentation |
| Constraint counts | verified V4-0 constraint codes | derived_presentation |
| Benchmark | not persisted | unavailable_not_inferred |

React may render, zoom, select and align returned rows. It may not generate replacement financial facts or statistical evidence.

## Catalog

`GET /api/v4/portfolio-execution`

Returns only A4 validations for which a verified V4-0 StrategyDecisionSeries can be bound to the same `portfolio_validation_id` and the authoritative A4 portfolio cockpit resolves.

## Detail

`GET /api/v4/portfolio-execution/{portfolio_validation_id}`

Contains:

- identity binding to the V4-0 series;
- authoritative A4 aggregate metrics;
- authoritative A4 economic/fold/ledger metadata;
- explicit presentation authority declarations;
- benchmark availability and order-identity semantics.

## Portfolio series

`GET /api/v4/portfolio-execution/{portfolio_validation_id}/series`

Optional filters:

```text
start
aend  (named `end` in HTTP)
fold_id
limit <= 5000
offset >= 0
```

Response rows are direct authoritative A4 points:

```text
session_date
fold_id
net_nav
gross_nav
net_return
gross_return
authority = authoritative_a4_point
```

## Analytics

`GET /api/v4/portfolio-execution/{portfolio_validation_id}/analytics`

Optional filters:

```text
asset
order_id
start
end
fold_id
window = 2..252
```

Response sections:

- `drawdown`
- `rolling`
- `monthly_returns`
- `filtered_costs`
- `order_funnel`
- `constraint_attribution`
- `benchmark`

Every computed section declares `authority=derived_presentation` and `source_authority`.

## Decisions

`GET /api/v4/portfolio-execution/{portfolio_validation_id}/decisions`

Optional filters:

```text
asset
order_id
session_date
start
end
fold_id
limit <= 5000
offset >= 0
```

`session_date` is mutually exclusive with `start/end`. The returned decision rows retain V4-0 authority.

`order_id` maps exactly to V4-0 `client_order_id`; it is not derived from asset/date ordering or browser state.

## Bounded aggregation rule

The browser never requests an unbounded V4-0 table. When a server-side derived aggregate requires more than 5000 verified V4-0 rows, the V4-4 projection iterates through the existing bounded StrategyDecisionSeries projection in 5000-row pages until the authoritative result set is exhausted.

This pagination affects transport only and must not alter evidence identity or aggregation semantics.

## Mutation boundary

All V4-4 endpoints are GET-only. POST/PUT/PATCH/DELETE are not added to the Evidence Plane.

Production reserve, strategy promotion, PAPER execution, broker orders and live capital remain outside V4-4 authority.
