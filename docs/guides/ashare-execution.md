# A-share Execution Semantics

A3 converts a previously approved long-only A-share `PortfolioTarget` into explicit desired orders, executable orders, fills and T+1 inventory changes. It does not perform factor discovery, consume the 2025+ reserve, promote a strategy, start PAPER or connect to a broker.

## 1. Scope

```text
PortfolioTarget
      ↓
Exact daily execution state
      ↓
Desired quantity delta
      ↓
AshareOrderCompiler
      ↓
Executable orders + reason-coded adjustments/rejections
      ↓
AshareSimulatedExchange
      ↓
Fee-resolved fills
      ↓
AshareInventoryLedger
      ↓
T+1 account state
```

The generic `OrderPlanner`, exchange and ledger remain market-neutral. A3 is isolated so A-share rules cannot silently alter US/reference-market behavior.

## 2. Data semantics

`LocalAshareDailyExecutionAdapter` reads the exact requested row from `stock_daily.parquet`.

It never falls back to the most recent earlier tradable bar. An exact session becomes one of:

- `tradable`;
- `suspended` for the audited zero-OHLC/zero-flow vendor placeholder;
- `no_session_data`;
- `invalid_price`;
- `limits_unavailable`.

Execution uses raw next-session `open`. Marks use the exact open when available, otherwise the explicit previous/last close carried by a suspension row. Historical `up_limit` and `down_limit` fields are the primary price-limit source; the engine does not hard-code one percentage across boards, ST regimes or rule changes.

## 3. Tradeability

The compiler and exchange both enforce side-specific rules:

| State | Buy | Sell |
|---|---|---|
| suspended / missing / invalid | blocked | blocked |
| open at upper limit | blocked | allowed |
| open at lower limit | allowed | blocked |
| price limits unavailable | blocked by default | blocked by default |

This is a conservative daily-bar model. It does not claim order-book queue priority or intraday liquidity at a limit price.

## 4. T+1 inventory

Each position stores:

```text
total_quantity
sellable_quantity
unsettled_quantity
```

A buy fill on session `T` increases `total_quantity` and `unsettled_quantity`, but not `sellable_quantity`. When the ledger rolls to a later session, unsettled shares become sellable. A same-session sell request is clipped to the current sellable inventory and carries `T1_SELLABLE_QUANTITY_CLIPPED`.

## 5. Quantity rules

A3 models integer shares and board-specific order sizing:

- SSE/SZSE main board, ChiNext and BSE buys: 100-share lots;
- STAR buys: at least 200 shares, then integer-share increments;
- regular-board sells: 100-share lots plus the existing under-100 odd-lot remainder, which must remain unsplit;
- STAR sells: at least 200 shares unless the full remaining balance is below 200.

Every lot adjustment is explicit in `reason_codes`. The compiler never silently rounds a target and presents the result as the original desired order.

## 6. Costs

`AshareFeeSchedule` separates:

```text
broker commission
minimum broker commission
sell-side stamp duty
transfer fee
exchange handling fee
regulatory fee
```

Broker commission is account-specific. Exchange/regulatory pass-through defaults to `false` because many retail schedules quote an all-in commission. Runtime configuration owns all rates.

The example defaults include current reference values for historical testing:

- sell-side stamp duty: `0.0005`;
- transfer fee: `0.00001`;
- SSE/SZSE handling reference: `0.0000341`;
- BSE handling reference: `0.000125`.

Do not treat the example broker commission as a universal tariff. Update the configuration when the broker, date or applicable rules differ.

## 7. Smoke test

### Windows PowerShell

```powershell
Copy-Item `
  configs\execution\ashare_execution_smoke.example.toml `
  configs\execution\ashare_execution_smoke.local.toml
```

Edit the local file so both selected dates are normal trading sessions for every symbol, then run:

```powershell
python scripts\run_ashare_execution_smoke.py `
  configs\execution\ashare_execution_smoke.local.toml `
  --verify-content
```

### Ubuntu

```bash
cp configs/execution/ashare_execution_smoke.example.toml \
  configs/execution/ashare_execution_smoke.local.toml

python scripts/run_ashare_execution_smoke.py \
  configs/execution/ashare_execution_smoke.local.toml \
  --verify-content
```

The report is written to:

```text
reports/ashare_execution_smoke_a3.json
```

Expected checks:

```text
buy_orders_executed
buy_inventory_unsettled
same_session_sell_blocked_by_t1
next_session_sell_executed
positions_closed
buy_stamp_duty_zero
sell_stamp_duty_positive
cash_non_negative
integer_execution_quantities
```

## 8. Automated tests

```bash
python -m pytest -q tests/test_ashare_execution_a3.py
```

The focused tests cover:

- board detection;
- main-board/ChiNext/BSE and STAR lot behavior;
- odd-lot disposal;
- exact-session suspension and missing-row handling;
- side-specific limit-up/limit-down blocking;
- T+1 settlement;
- proportional cash scaling;
- deterministic order identity;
- buy/sell fee asymmetry;
- synthetic Parquet CLI acceptance.

The normal project matrix still runs on Ubuntu Python 3.11/3.12/3.13 and Windows Python 3.11.

## 9. Interpretation boundary

A3 certifies execution-rule plumbing, not strategy economics. The smoke result cannot be interpreted as Alpha, Sharpe, capacity or promotion evidence.

A4 is the next gate:

```text
Frozen robust factor family
      ↓
Alpha / risk / optimizer
      ↓
A3 target-to-executable-order path
      ↓
Execution-aware portfolio returns
      ↓
Gross/net attribution and economic validation
```

The 2025+ reserve remains untouched until the research and execution-aware validation protocol are frozen.
