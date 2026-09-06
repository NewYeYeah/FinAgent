# PAPER-TRADING — target-broker vertical integration

## Goal

Run one R5-confirmed `AdaptiveStrategySpec` end to end against an MT5 demo/PAPER environment with canonical realtime state, durable order/account reconciliation, safety controls and a Workbench that displays the same state used by the controller.

This stage integrates existing realtime/operations modules. It does not recreate them as separate RT-R0/R1/R2 projects.

## Preconditions

- R5 result for the target `AdaptiveStrategySpec` is `CONFIRMED`;
- the broker/server/account class for PAPER is explicitly selected;
- strategy freshness/decision budget and cost assumptions are frozen for the PAPER trial;
- broker symbol mappings are revalidated for the selected environment.

## Existing code to reuse

`src/finagent/realtime/` already provides canonical events, replay/database sources, streaming transforms, MT5 source and projection logic.

`src/finagent/operations/` already provides approval, PAPER controller/strategy helpers, reconciliation, safety and durable stores.

`src/finagent/brokers/` owns broker-specific adapters.

The first task is an implementation audit and interface consolidation, not a new event architecture.

## Data scope

Historical Tick/LOB data is not required.

The PAPER strategy may use:

```text
M1/bounded bar observations
current quote/bid/ask where broker exposes them
observed spread
bar/quote freshness
canonical account/order/trade state
```

Do not invent order-flow/LOB features from OHLCV.

## Deliverables

### 1. Broker/source admission

Freeze for the PAPER environment:

```text
terminal/package/build
broker/server/account class
symbol mapping
trade/contract specifications
source timing class
quote/bar availability
session semantics
spread/volume field meaning where relevant
```

Entitlement/capability is environment-specific and must be re-probed rather than inherited forever from the earlier engineering baseline.

### 2. One canonical streaming path

The confirmed strategy must run through the same algorithm/state path for:

```text
DatabaseReplaySource
MT5 connected development source
MT5 target PAPER source
```

Provider switching happens outside strategy logic.

Preserve `event_time`, `received_at`, sequence/source identity and explicit stale/delayed state.

### 3. Strategy → order vertical slice

Connect:

```text
canonical market state
→ streaming features / MarketState
→ frozen factor allocation
→ target position/order intent
→ safety/approval
→ MT5 command
→ broker acknowledgement/events
→ projection
```

Order idempotency and client/broker/deal identity mapping are mandatory.

### 4. Reconciliation/recovery

Continuously reconcile:

```text
internal orders ↔ broker orders
internal fills ↔ broker deals
internal positions ↔ broker positions
internal account state ↔ broker account state
```

On restart, rebuild/recover from durable internal state plus broker truth. Unknown drift is an explicit degraded/blocked state, not silently overwritten.

### 5. Safety

At minimum:

- stale-data/freshness gate;
- symbol/market-session gate;
- per-order and total notional/exposure limits;
- daily loss/drawdown boundary for the trial;
- duplicate-order prevention;
- unknown-reconciliation block;
- kill switch;
- incident ledger.

Agent cannot raise these limits during PAPER.

### 6. PAPER Workbench

Develop UI with the same backend slice, not as a standalone later project.

Required panels:

#### Market
- current M1/price view;
- spread and freshness;
- market/state probability;
- signal timestamp.

#### Strategy
- active factors;
- factor weights;
- current allocator/Agent-frozen decision context;
- target exposure/positions.

#### Portfolio
- NAV/cash/equity;
- positions/exposure;
- realized/unrealized PnL;
- historical vs PAPER comparison where semantically valid.

#### Execution
- order lifecycle;
- desired/accepted/filled/rejected quantities;
- fill price/slippage/cost;
- expected vs broker state.

#### System Health
- connection/source freshness;
- reconciliation status;
- pending/unknown orders;
- safety gates/kill switch;
- incident timeline.

The browser consumes canonical projections and never calls MetaTrader5 directly.

### 7. Visual implementation

Reuse existing Workbench shell, context, ECharts, React Flow and TanStack Table.

Introduce TradingView Lightweight Charts for financial price/volume/order/fill interaction if it improves the Market/Execution surface. Do not replace ECharts for statistical/research charts.

### 8. Soak/acceptance

A single successful demo order is insufficient.

Exercise at least:

```text
normal session
no-signal/cash behavior
stale/delayed source
connection loss/reconnect
restart during active state
order reject
cancel/expire when supported
partial fill where the environment can produce or fixture it
duplicate/replayed broker events
internal/broker drift
kill switch
end-of-session flattening
```

Where the real demo environment cannot reliably create a failure mode, deterministic replay/fixture may prove the state machine but cannot replace real broker evidence for the behaviors that require broker mutation.

## Non-goals

- live capital;
- Agent-controlled safety limits;
- HFT/LOB execution optimization;
- high-availability production architecture before the single-node PAPER flow works;
- QMT integration unless it becomes a concrete target environment.

## Suggested PR slices

Natural vertical slices:

1. audit/consolidate existing realtime + PAPER interfaces and admit target demo environment;
2. confirmed strategy → MT5 PAPER order lifecycle + minimal Market/Strategy/Execution UI;
3. reconciliation/recovery/safety + Portfolio/System Health UI;
4. soak/operational acceptance fixes if required.

Do not recreate separate stages for event contract, replay, projection and UI when those modules already exist.

## Exit gate

PAPER is accepted only when:

```text
one confirmed strategy runs through the canonical realtime path
real target demo/PAPER orders are identity-bound and reconciled
restart/recovery is demonstrated
stale/unknown/reconciliation failures block safely
kill switch and incident evidence work
Workbench reflects canonical market/strategy/portfolio/execution/health state
multi-session soak shows no unexplained state drift
no live-capital authority is enabled
```
