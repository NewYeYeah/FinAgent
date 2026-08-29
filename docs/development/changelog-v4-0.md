# V4-0 StrategyDecisionSeriesEvidence

## Purpose

V4-0 is the first Linked Quant Analytics data stage. It does **not** add the Strategy Decision Explorer chart. It freezes and materializes the authoritative row-level evidence that later charts are allowed to consume.

The source-of-truth chain is:

```text
immutable A2.6 ResearchProgram
        ↓ frozen factor family
immutable A4 validation report
        ↓ exact A4 execution-ledger digest
frozen A4 AlphaModel replay at formation only
        ↓
StrategyDecisionSeriesEvidence
        ├─ manifest JSON
        └─ Parquet long-form rows
```

V4-0 deliberately does not change the existing A4 report or JSONL execution-ledger schema. A4 exact replay therefore retains its previously frozen identity.

## Row contract

Schema:

```text
finagent.strategy-decision-row.v1
```

Each row is one `(fold_id, session_date, asset)` decision/accounting observation. Deterministic ordering is:

```text
session_date → fold_id → asset
```

The Parquet sequence is the zero-based index of that order.

Core fields:

```text
fold_id
session_date
signal_asof
asset
rebalanced
cash_fallback
target_id

alpha_score
alpha_rank
alpha_expected_return
alpha_uncertainty

pre_trade_weight
target_weight
realized_weight

desired_side
desired_quantity
executable_quantity
filled_quantity
reference_price
fill_price
close_price

fees
slippage
gross_pnl
net_pnl

decision_status
client_order_id
constraint_codes
```

Nullable fields are explicit. In particular, non-rebalance rows do not fabricate alpha, pre-trade or target values. A cash/model-fallback session may likewise have no alpha evidence when A4 never produced a valid forecast.

## Alpha definition

The existing A4 JSONL ledger contains target/order/fill/account evidence but does not persist the complete formation-time cross-sectional alpha vector. V4-0 therefore replays **only** the already-frozen A4 AlphaModel.

For each A4 fold:

1. rebuild the generated-feature AlphaModel from the exact frozen A2.6 feature digests, weights and directions;
2. fit only on the same A4 training split/range using the same ridge, minimum-observation and winsorization parameters;
3. require the rebuilt model artifact digest to equal the A4 fold `alpha_model_id`;
4. request only formation features from the historical feature window and apply the same PIT universe policy;
5. replay `AlphaForecast` at the original `signal_asof`;
6. reconstruct the frozen combined alpha score from the verified train-only calibration:

```text
alpha_score = (expected_return - intercept) / non_negative_slope
```

7. assign deterministic descending score rank with asset identity as the tie break.

If the frozen calibration slope is non-positive, A4 itself used the documented cash fallback and no alpha vector is invented. A historical `MODEL_ERROR:*` target likewise remains without reconstructed alpha rather than silently changing the historical decision path.

V4-0 does not rerun risk, optimizer or execution to manufacture the series.

## PnL definition and reconciliation

Per-asset PnL is derived from authoritative A4 account states and fills using the wealth identity:

```text
asset_pnl
= current_close_market_value
- previous_close_market_value
- signed_executed_notional
- actual_fees
```

where signed executed notional is positive for buys and negative for sells.

Net execution price already embeds A3 slippage. Slippage is also persisted separately as explanatory cost evidence and is **not subtracted a second time** from `net_pnl`.

Gross rows use A4's zero-fee/zero-slippage gross execution cycle. Net rows use the actual net A3 cycle.

For every source session V4-0 enforces:

```text
sum(asset gross_pnl) == A4 gross NAV change
sum(asset net_pnl)   == A4 net NAV change
```

within a tight floating-point tolerance. A failure is a materialization error, not a display warning.

## Manifest and identity

Manifest schema:

```text
finagent.strategy-decision-series.manifest.v1
```

The manifest binds at least:

```text
series_id
portfolio_validation_id
A4 spec_id
A2.6 program result/spec identity
A2.6 source-report digest
frozen selection identity
market-data version
selected factor digests
fold alpha_model_ids
A4 execution_ledger_digest
StrategyDecision row digest
source A4 report SHA-256
source A4 ledger SHA-256
Parquet SHA-256
schema/column/count/date metadata
```

`series_id` is content-addressed from semantic evidence identity and the deterministic row digest. It does not depend on output file names or filesystem paths.

The source A4 report, source A4 ledger, V4 manifest and V4 Parquet are kept as sibling files. Manifest file names are validated as sibling names rather than accepted browser/host paths.

## Parquet representation

The long-form Parquet uses explicit typed numeric/boolean/date columns and ZSTD compression. `session_date` is a Parquet `DATE`. `signal_asof` is the canonical timezone-aware ISO-8601 string from A4; storing it as text avoids a hidden runtime dependency on `pytz` while preserving the exact timezone-qualified formation timestamp.

`constraint_codes` is stored as canonical JSON text inside Parquet and projected back to a typed array at the read boundary.

## Bounded read projection

`StrategyDecisionSeriesProjection` validates the manifest and its source files before serving rows:

- A4 report/manifest identity binding;
- A4 ledger canonical digest;
- physical SHA-256 bindings;
- exact Parquet column contract;
- row count;
- unique row IDs;
- contiguous deterministic sequence.

Queries are read-only and can filter by:

```text
asset
fold_id
start session_date
end session_date
```

with:

```text
1 <= limit <= 5000
offset >= 0
```

V4-0 intentionally stops at this core bounded projection. Browser HTTP endpoints and interactive charts belong to later V4 stages after their product semantics are frozen.

## Materialization CLI

```bash
python scripts/materialize_strategy_decision_series.py \
  configs/research/ashare_portfolio_validation.local.toml \
  --a4-report reports/ashare_a4.json \
  --ledger reports/ashare_a4_ledger.jsonl
```

Default outputs are siblings of the A4 report:

```text
<report-stem>.strategy-decisions.json
<report-stem>.strategy-decisions.parquet
```

The TOML supplies data/file locations only. Research/portfolio semantics are restored from the immutable A2.6/A4 evidence; current config values are not allowed to overwrite frozen factor weights, fold definitions or A4 alpha parameters.

`--verify-content` can request content-level verification of the frozen local A-share manifest.

## Acceptance

Dedicated acceptance is in:

```text
tests/test_strategy_decision_series_v40.py
.github/workflows/v4-series.yml
```

It covers:

- a hand-audited signal → target → desired/executable → fill → realized/PnL example;
- exact per-session PnL reconciliation;
- deterministic row/series identity;
- verified manifest + bounded Parquet projection;
- tamper rejection;
- real synthetic A4 CLI generation followed by V4 materialization;
- exact A4 `alpha_model_id` replay;
- repeated V4 materialization with identical semantic series identity;
- unchanged source A4 report/ledger bytes;
- Ubuntu/Windows focused execution plus Ruff/mypy/dependency checks;
- repository-wide Python/Windows regression gates.

## Authority boundary

V4-0 is historical evidence materialization only. It adds no:

```text
reserve access
strategy promotion
PAPER mutation
broker action
live-capital authority
realtime feed
arbitrary shell/Python
new generic Control command
```

Passing V4-0 proves a deterministic, auditable series contract. It does not prove alpha persistence or live readiness.
