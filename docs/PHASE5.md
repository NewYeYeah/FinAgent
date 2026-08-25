# Phase 5 — Paper Trading, Shadow Operation and Reconciliation

## Goal

Verify that a statistically governed research result and deterministic portfolio target can pass through an operational lifecycle without giving the Agent financial-state authority.

## Delivered

```text
TradingSessionCalendar

PaperOrder / BrokerOrderStatus
PaperBrokerConfig
PaperBroker
SQLitePaperBrokerStore

HumanApproval
OperationalApprovalService
OperationalApplication

TradingSafetyLimits
TradingSafetyController
durable kill switch

PortfolioReconciler
ReconciliationReport
ApprovedPaperTradingController

CorporateAction / CorporateActionProcessor

ShadowPortfolioMonitor
ExecutionCostCalibrator
```

## End-to-end paper path

```text
PortfolioHealthSnapshot
        |
Supervisor request
        |  mutation_performed=false
        v
HumanApproval
        |
OperationalApprovalService
        |
registered rebalance approval
        |
TradingSafetyController
        |
PaperBroker.submit()
        |
PaperBroker.process(ExecutionSnapshot)
        |
partial fills / account snapshots
        |
PortfolioReconciler
        |
OK --------------------------> continue paper/shadow
 |
critical
 |
kill switch HALTED
```

## Idempotency and recovery

`client_order_id` is the stable order identity. Reusing the same ID for a different request is an error. Replaying the same submission returns the existing paper order.

Each paper fill has a deterministic fill key:

```text
client_order_id + execution timestamp
```

The SQLite store commits fill, order state and account state in one transaction. Reprocessing the same snapshot therefore does not apply the same fill twice.

All paper account state is reconstructed from SQLite after process restart.

## Partial fills

Available quantity is bounded by:

```text
execution_quote.volume * max_participation_rate
```

A market order can therefore progress:

```text
NEW
 -> PARTIALLY_FILLED
 -> PARTIALLY_FILLED
 -> FILLED
```

across distinct execution snapshots.

## Safety

Pre-trade decisions are deterministic and inspect:

```text
durable kill switch
per-order notional
batch notional
session drawdown
reconciliation state
```

The Agent cannot reset the kill switch.

## Reconciliation

The paper account is compared against an independently maintained deterministic ledger. Critical cash or position differences halt paper operation.

Marks and NAV differences are recorded separately so valuation-feed problems are distinguishable from position/cash state corruption.

## Session and corporate-action semantics

`TradingSessionCalendar` handles local timezone, open/close times, weekdays and configured holidays.

Paper orders may be rejected outside the configured session.

Supported corporate actions in this phase:

```text
split
cash dividend
```

Both are idempotent by `action_id`.

## Shadow evaluation

A shadow `PortfolioTarget` is never automatically applied. It is compared to the selected reference target through deterministic distance metrics.

Paper fills can also be summarized into realized execution-cost observations for later calibration.

## Explicit limitations

Phase 5 does not claim:

```text
live broker connectivity
multi-currency cash/FX ledgers
exchange-native calendars
full security master
merger/rights/tax corporate actions
level-2 order-book simulation
production market-impact estimation
live capital readiness
```

The project remains paper/shadow-first.
