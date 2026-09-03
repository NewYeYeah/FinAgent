# US-X0 / US-X1 Historical CFD Execution

This guide defines the current provider-neutral implementation of U.S. CFD historical execution semantics. It advances the implementation frontier only. The project authority frontier remains US-D3 until Issue #125 real U.S. evidence is accepted.

## Purpose

US-R1 asks whether a candidate family is statistically robust. US-X0/US-X1 answer a different question: if a reviewed Alpha family eventually exists, can its target weights be translated into broker-shaped CFD lots and can the historical portfolio ledger explain gross PnL, spread, slippage, commission, margin and net PnL without importing A-share cash/lot rules?

The implementation in `src/finagent/backtest/us_cfd_execution.py` is deliberately offline and deterministic. It never calls MT5 `order_send()` and has no PAPER or live authority.

## X0 contract semantics

### Instrument contract

`CFDInstrumentSpec` freezes:

- symbol;
- contract size;
- minimum / maximum / step volume;
- margin rate;
- tick size;
- profit and margin currencies;
- optional source `MT5SymbolSpec.spec_id`.

`CFDInstrumentSpec.from_mt5_symbol_spec()` reuses already observed MT5 contract fields but does not infer broker-specific execution authority. `margin_rate` remains an explicit input because the current read-only symbol evidence is not sufficient to infer a universal broker margin formula.

The v1 engine fails closed when profit or margin currency differs from the account base currency. FX conversion is not silently invented.

### Target-weight compiler

For equity `E`, reference price `P`, contract size `C` and target weight `w`:

```text
raw target lots = |w| * E / (P * C)
```

Lots are rounded **toward zero** to the frozen `volume_step`. A target below `volume_min` becomes zero instead of being promoted to a larger risk exposure. A target above `volume_max` is rejected rather than silently clipped.

The order delta is:

```text
delta lots = target lots - current lots
```

Positive deltas compile to BUY and negative deltas to SELL. The same netting logic supports opening, reducing, closing and reversing long/short positions.

### CFD ledger

The historical CFD ledger does not deduct full contract notional from cash. Instead it maintains:

- balance;
- signed lots;
- average entry price;
- realized PnL;
- unrealized PnL at the current reference mark;
- equity;
- required margin.

For signed position `q`, contract size `C`, mark `P` and average entry `A`:

```text
unrealized PnL = q * C * (P - A)
```

Required margin is:

```text
margin = |q| * C * P * margin_rate
```

The engine gates the **whole target state** before executing a step. If projected margin exceeds `projected_equity * max_margin_utilization`, that step receives an explicit blocker and no partial fill is applied.

## X1 cost semantics

`CFDExecutionCostPolicy` freezes three deterministic components:

- full bid/ask spread in basis points;
- adverse slippage in basis points;
- commission in basis points of reference notional.

Half of the full spread is applied adversely on each side:

```text
BUY fill  = reference * (1 + spread/2 + slippage)
SELL fill = reference * (1 - spread/2 - slippage)
```

where rates are converted from basis points.

The report records spread cost, slippage cost and commission separately. For an intraday-flat completed run:

```text
gross PnL before costs
= net PnL + spread cost + slippage cost + commission
```

This identity is a core regression invariant.

Swap is intentionally zero in v1 because the first U.S. strategy remains intraday-flat. Overnight CFD swap semantics require a later explicit model and must not be inferred from this implementation.

## Intraday-flat boundary

A run ending with any open CFD position fails with:

```text
intraday_flat:open_positions_at_end
```

This is an implementation boundary, not merely a diagnostic.

## Development fixture

Run the focused regression:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

pytest -q tests\test_us_cfd_historical_execution.py
```

Run the deterministic long round-trip fixture:

```powershell
python scripts\run_us_cfd_execution_fixture.py `
  --output reports\development\us_cfd_historical_execution_fixture.json
```

The fixture opens a 50% long target at reference 100 and closes at reference 101 with a 10 bps full spread, 2 bps slippage and 1 bps commission. Its gross mid-price PnL must be 500 USD; net PnL must equal gross PnL minus the separately attributed transaction costs.

Run static checks:

```powershell
ruff check `
  src\finagent\backtest\us_cfd_execution.py `
  scripts\run_us_cfd_execution_fixture.py `
  tests\test_us_cfd_historical_execution.py

mypy --strict `
  src\finagent\backtest\us_cfd_execution.py `
  scripts\run_us_cfd_execution_fixture.py

python -m py_compile `
  src\finagent\backtest\us_cfd_execution.py `
  scripts\run_us_cfd_execution_fixture.py
```

## Required regression cases

The focused suite must verify:

1. target lots round toward zero to `volume_step`;
2. below-minimum targets become zero;
3. long and short round trips have symmetric gross PnL and adverse costs;
4. gross/net/cost attribution is conserved;
5. margin rejection is atomic and creates no partial position;
6. an open final position fails the intraday-flat boundary;
7. MT5 symbol contract identity can be preserved without granting broker authority;
8. identical inputs produce the same content-addressed report;
9. every report explicitly denies broker/PAPER/stage/live-capital authority.

## Authority boundary

A passing historical CFD fixture means only that the execution implementation behaves deterministically under known synthetic inputs.

It does not mean:

- Issue #125 is resolved;
- US-D3, US-B0, US-A0 or US-R1 is authoritative;
- a real robust Alpha family exists;
- the spread model represents a live executable broker spread;
- broker margin semantics are accepted;
- PAPER or live trading is authorized.

Real US-X progression must later bind the exact reviewed `ROBUST_FACTOR_FAMILY` evidence and broker-specific execution semantics. Until then every historical CFD report keeps:

```text
broker_execution_authority = false
paper_authority = false
status_authority = false
stage_exit_authority = false
live_capital_authority = false
```
