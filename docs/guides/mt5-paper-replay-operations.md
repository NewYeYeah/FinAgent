# MT5-E1 / MT5-O1 replay-first engineering closure

This guide describes the implementation-only validation layer for the future MT5 demo/PAPER execution and operational safety stages.

## Authority boundary

`docs/status.toml` remains the only project-stage authority and remains at US-D3 until the real U.S. engineering-universe and reconciliation evidence gate is closed. The replay-first layer below does **not** advance project stage and does not grant broker-account, current U.S. market-data, PAPER, execution, live-capital, or stage-exit authority.

The implementation deliberately has no `MetaTrader5` module dependency and exposes no `order_send()`, `symbol_select()`, market-book subscription, position mutation, or account mutation surface.

## Implemented contracts

`src/finagent/brokers/mt5/paper_replay.py` implements the plan-level ports:

```text
OrderCommandPort
BrokerEventSource
BrokerQueryPort
```

and the following explicit evidence/state contracts:

```text
MT5PaperExecutionPolicy
MT5PaperOrderCommand
MT5PaperOrderRecord
MT5PaperIncident
MT5PaperBrokerSnapshot
MT5PaperReconciliationReport
MT5PaperReplayBroker
```

All broker lifecycle output uses the canonical RT-R0 events already accepted at the implementation layer:

```text
OrderEvent
TradeEvent
OrderErrorEvent
AccountStatusEvent
```

## Lifecycle semantics

A new accepted command produces `SUBMITTED -> ACKNOWLEDGED`. Fills produce one immutable `TradeEvent` plus an updated `OrderEvent`; multiple fills produce `PARTIALLY_FILLED` and finally `FILLED`. Broker reject, cancel and expire are explicit terminal transitions.

`client_order_id` is the idempotency key. Retrying the exact same command is a no-op. Reusing the same client identity with different command content fails closed. `broker_deal_id` has equivalent immutable identity semantics for fills.

## Safety semantics

Before a new command is acknowledged, the replay broker validates:

- kill switch is not halted;
- latest quote exists and is within the frozen stale/future-skew window;
- session equity has not breached the daily-loss limit;
- order notional is within the per-order limit;
- existing and proposed gross notional can be proven from fresh quotes and remain within the gross limit;
- short exposure is allowed by policy when the command would create it.

Failure produces a canonical `OrderErrorEvent` followed by `OrderEvent(REJECTED)`. Safety failure is not silently retried or upgraded.

## Reconciliation semantics

`reconcile_mt5_paper_projection()` compares the RT-R2 projection against an independently queried replay-broker snapshot across:

- client/broker order identities, status and filled lots;
- broker deal identity set;
- signed positions;
- account equity.

Terminal states are:

```text
CONSISTENT  exact required state is proven
DRIFT       both sides are observable but disagree
UNKNOWN     required broker/account state cannot be proven
```

`UNKNOWN` is intentionally fail-closed and must never be interpreted as consistency.

## Recovery and audit

Commands, broker events, incidents and account-equity observations are stored as an append-only in-memory journal and can be written as JSONL. `recover_from_journal()` validates command/event content identities, replays broker lifecycle state, restores deal/position/account state and resumes the sequence/order identity counters.

The deterministic regression requires the recovered broker snapshot identity and broker event identities to equal the pre-restart identities. Retrying the original command after recovery must still be a no-op.

## Deterministic engineering smoke

Run from the repository root:

```powershell
python scripts/smoke_mt5_paper_replay_operations.py
```

Optional report output:

```powershell
python scripts/smoke_mt5_paper_replay_operations.py `
  --output reports/mt5/mt5_paper_replay_smoke.json
```

The smoke covers acknowledged submission, partial/full fills, canonical projection, exact reconciliation, JSONL restart recovery, idempotent retry, stale-quote rejection and kill-switch rejection.

## What remains later

A later authoritative MT5-E1/O1 run must bind the actual target broker/server/account and implement a separately reviewed MetaTrader5 mutation adapter only after upstream robust-Alpha and broker re-admission gates permit it. That future adapter must preserve the same command/event identities, reconciliation terminal states, recovery semantics and fail-closed safety rules; a successful demo order alone is not live-capital acceptance.
