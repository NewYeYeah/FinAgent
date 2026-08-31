# Operations guide

## Authority ladder

```text
historical research
→ Alpha acceptance
→ execution-aware historical portfolio acceptance
→ realtime replay/state acceptance
→ broker read-only acceptance
→ demo/PAPER execution
→ reconciliation/recovery/safety
→ Live Workbench demo/PAPER acceptance
→ separately governed live-capital acceptance
```

No stage inherits authority automatically from the previous one.

## Historical A-share

A5 reserve infrastructure is retained, but the Historical v1.0 closure does not consume production reserve merely to obtain a PASS/FAIL badge. Historical release details live in [`../releases/ashare-historical-v1.md`](../releases/ashare-historical-v1.md).

## MT5

Official MT5 integration is treated as a Windows-native optional broker adapter. Early MT5 stages are read-only and measure terminal/server/symbol/history/spread/contract constraints. Demo/PAPER order authority is introduced only after robust Alpha and historical CFD execution gates.

## Broker lifecycle

Operational execution uses asynchronous command/event/query semantics rather than the synchronous historical `ExecutionVenue` interface. Durable client/broker order/deal/event identities support idempotency, partial fills and reconciliation.

## Recovery and safety

Before Live Workbench/PAPER acceptance, FinAgent must prove restart recovery, internal-vs-broker reconciliation, stale-data gating, exposure/loss limits, kill switch and incident evidence. Unknown reconciliation state fails closed.

## Live capital

Live capital requires a new explicit acceptance plan and human decision. Demo/PAPER success is not authorization.
