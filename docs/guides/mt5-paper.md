# MT5 / replay / PAPER development guide

This guide replaces the older per-stage MT5/realtime operator notes. It describes the source roles and boundaries that remain relevant to the active PAPER roadmap.

## 1. Current reality

FinAgent already contains:

- MT5 read-only/realtime adapter code;
- canonical realtime event types;
- database replay/source interfaces;
- streaming feature/resampling/research components;
- idempotent realtime projections;
- PAPER/approval/reconciliation/safety/store modules.

These modules are **not** yet one accepted target-broker PAPER system.

## 2. Development source roles

### Replay

Use local historical U.S. data for deterministic algorithm behavior, chronology, market-state/factor logic, failure fixtures and restart tests.

Replay preserves market `event_time`; delivery pacing may vary.

### Connected engineering source

A continuously available source such as FX may be used for transport/reconnect/clock/timestamp plumbing only when the behavior is genuinely market-invariant.

It cannot prove U.S. session semantics, CFD mapping, U.S. feed entitlement, PAPER fills or U.S. broker economics.

### Target MT5 demo/PAPER source

Only the selected target broker/server/account can prove final broker-specific source, contract, order/deal, reconciliation and PAPER behavior.

Re-probe capabilities when PAPER begins; prior environment evidence is not permanently universal.

## 3. Current feed/tick limitation

Historical tick data is not currently available for the active research program. That does not block minute/bar PAPER integration.

The strategy may use source-supported M1/bars and current bid/ask/quote data where the broker exposes them. Do not derive synthetic Tick/LOB history from OHLCV.

## 4. Canonical event path

Strategy/runtime code should consume canonical FinAgent events/state, not MetaTrader5 objects directly:

```text
MT5 / replay source
→ QuoteEvent / BarEvent / ConnectionEvent / ...
→ RealtimeProjector / canonical state
→ strategy/controller
→ safety/approval
→ broker command
→ OrderEvent / TradeEvent / errors
→ reconciliation
```

Provider switching belongs outside strategy logic.

## 5. Timing/freshness

Always distinguish:

```text
current progressing source
progressing but delayed source
stale/frozen source
disconnected source
```

Preserve `event_time`, `received_at`, source identity and sequence. Compare effective source freshness to the frozen strategy decision budget; fail closed/degrade when too old.

## 6. Market Watch / symbol mapping

The governed target symbol set must be visible/available in the terminal under the accepted operator policy. Do not add hidden `symbol_select()` behavior merely to force a pass if the workflow intentionally treats Market Watch state as an operator boundary.

Before PAPER, verify exact one-to-one research↔broker mapping and contract specifications for the selected server/account.

## 7. PAPER authority

A demo order is not PAPER acceptance.

PAPER requires:

- canonical strategy decision path;
- durable client/broker/deal identities;
- reject/cancel/partial/fill lifecycle handling;
- position/account reconciliation;
- restart/recovery;
- stale-data/exposure/loss gates;
- kill switch and incident evidence;
- multi-session soak;
- Workbench views sourced from canonical projections.

See [`../development/stages/paper-trading.md`](../development/stages/paper-trading.md).

## 8. Live boundary

Live capital is separately human governed after PAPER acceptance. No replay/FX/demo/PAPER state auto-promotes to live authority. See [`../development/stages/live-capital.md`](../development/stages/live-capital.md).
