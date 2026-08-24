# ADR-008 — Phase 2 Walk-Forward Validation and Dual Execution Clock

- Status: Accepted
- Date: 2026-08-24

## Context

Phase 1 deliberately used one train/test split and an idealised close-on-close execution convention. That was sufficient to validate the numerical kernel, but it is not a strong research protocol for repeated model selection and it does not represent the information/execution distinction required for realistic trading simulation.

Two independent leakage channels must be closed before an Agent is allowed to orchestrate experiments:

1. **validation leakage** — overlapping forward labels or insufficient separation between training and out-of-sample windows;
2. **execution leakage** — using a bar close/high/low to fill an order at a time when those fields were not yet observable.

## Decision

### 1. Purged chronological walk-forward

FinAgent adds `PurgedWalkForwardSplitter` with `WalkForwardConfig`.

The splitter operates on the `DataAdapter.calendar(...)` and produces chronological `WalkForwardFold` objects. Each fold has a contiguous train range and a later contiguous test range.

For the strictly forward-only Phase 2 protocol:

```text
train | purge | embargo | test
```

`purge_bars` is the mandatory exclusion driven by label horizon. For canonical labels such as `forward_log_return_5`, the minimum purge is five bars. `embargo_bars` is an additional conservative pre-test exclusion zone.

This differs from symmetric purged CV, where training blocks may exist on both sides of a test block. FinAgent Phase 2 does **not** train on future observations, therefore its embargo is represented as an additional chronological gap before the test block.

The splitter supports rolling and expanding training windows.

### 2. Phase 1 DataAdapter remains frozen

The Phase 1 research interface is not broken. `DataAdapter` remains:

```text
build_dataset
feature_window
market_snapshot
calendar
```

Field-level execution data is introduced through a separate additive protocol:

```text
ExecutionDataAdapter
    execution_calendar(...)
    execution_snapshot(...)
```

This prevents execution semantics from contaminating the research-data contract.

### 3. Field-level execution snapshot

`PriceBar.available_at` continues to represent when the full research bar is observable.

Phase 2 adds:

```text
ExecutionQuote
ExecutionSnapshot
```

An `ExecutionQuote` exposes only one executable price. It cannot reveal the rest of the OHLC bar.

For the built-in bar adapter:

```text
open  -> available at PriceBar.event_time
close -> available at PriceBar.available_at
```

High/low are intentionally not supported as execution fields because the current bar schema does not define an intrabar timestamp at which either field became known.

### 4. Dual-clock backtest

`TimedEventDrivenBacktestEngine` uses two distinct times:

```text
information_at
execution_at
```

The engine enforces:

```text
execution_at > information_at
```

The default is one executable-event lag with `price_field="open"`, i.e. the next executable open.

Signals, forecasts, portfolio optimization and risk approval are generated using information available at `information_at`. Approved orders are then filled against an `ExecutionSnapshot` at the later execution time.

## Consequences

Positive:

- same-instant signal/fill leakage is structurally impossible in the timed engine;
- forward-label purge is explicit and auditable;
- Phase 1 model/data interfaces remain backward compatible;
- later broker/quote adapters have a dedicated execution boundary;
- an Agent can request a walk-forward experiment without deciding split indices or executable prices itself.

Trade-offs:

- Phase 2 still uses bar-level execution, not order-book queue simulation;
- open-price liquidity uses the bar volume as an approximation;
- the strict forward embargo definition is intentionally simpler than symmetric combinatorial purged CV;
- calendars are currently adapter-provided rather than exchange-holiday aware.

## Rejected alternatives

### Reuse MarketSnapshot for next-open execution

Rejected because a `MarketSnapshot` exposes a complete `PriceBar`; creating it at the open would reveal close/high/low before they are observable.

### Add execution methods directly to DataAdapter

Rejected because Phase 1 froze that interface. Execution is a separate concern and receives a separate protocol.

### Let the Agent choose train/test rows directly

Rejected. Split construction is deterministic policy code and must be reproducible without an LLM.
