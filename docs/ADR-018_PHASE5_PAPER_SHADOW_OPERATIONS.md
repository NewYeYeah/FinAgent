# ADR-018 — Phase 5 Paper/Shadow Operations and Reconciliation

Date: 2026-08-25

Status: Accepted

## Context

Phase 4 produced deterministic portfolio targets, constraints, stress tests and rebalance decisions. Phase 4.5 added a low-permission Supervisor that may inspect health and create non-mutating requests, but financial state still had no durable operational application layer.

The next risk boundary is operational rather than statistical: duplicate orders, partial fills, process restarts, stale sessions, reconciliation drift, corporate actions, uncontrolled loss and accidental conversion of an Agent request into a trade.

## Decision

Introduce a deterministic paper/shadow operations package:

```text
Supervisor request
      |
human approval
      |
OperationalApprovalService
      |
registered rebalance authorization
      |
TradingSafetyController
      |
PaperBroker
      |
partial fills / account state
      |
PortfolioReconciler
      |
kill switch / operational events
```

The Agent remains outside this path.

## Paper broker

`PaperBroker` is a persistent broker adapter over `ExecutionSnapshot`.

Properties:

- `client_order_id` is the idempotency key;
- reuse of the same ID with different immutable order fields is rejected;
- orders have explicit `NEW -> PARTIALLY_FILLED -> FILLED` lifecycle, plus `REJECTED/CANCELLED`;
- participation caps may produce fills across multiple snapshots;
- `(client_order_id, execution timestamp)` creates a deterministic fill key;
- fill/order/account changes are persisted atomically;
- account snapshots allow restart recovery;
- market orders outside an optional `TradingSessionCalendar` are rejected;
- Phase 5 paper accounting remains single-base-currency; implicit FX conversion is forbidden.

## Human approval boundary

Phase 4.5 request tools return `mutation_performed=false`.

`OperationalApprovalService` is outside the Agent runtime and accepts the exact request payload plus an explicit `HumanApproval`.

It may apply:

```text
operating_policy
rebalance authorization
human_review acknowledgement
```

For operating policy requests, only a pre-registered `OperatingPolicyRegistry` identity may be activated. For rebalance requests, the corresponding immutable `PortfolioHealthSnapshot` must still report `rebalance_required=True`.

A paper trading controller accepts a rebalance only when the exact stored approval ID matches the health snapshot ID.

## Safety and kill switch

`TradingSafetyController` provides deterministic pre-trade checks:

```text
kill-switch state
per-order notional
batch notional
session loss fraction
critical reconciliation issue count
```

The kill switch is durable. A process restart does not silently re-arm trading. Reset requires an explicit actor.

## Reconciliation

`PortfolioReconciler` compares deterministic ledger state and paper-broker state:

```text
cash
positions
marks
NAV
```

Cash/position mismatches are critical. Mark/NAV-only mismatches are warnings. `ApprovedPaperTradingController.reconcile()` trips the durable kill switch when critical issues exist.

## Corporate actions

Phase 5 introduces deterministic split and cash-dividend processing.

Split:

```text
quantity' = quantity * ratio
mark'     = mark / ratio
```

preserving marked NAV before transaction costs.

Cash dividend:

```text
cash' = cash + quantity * dividend_per_share
```

Corporate-action IDs are idempotent and persisted.

This is intentionally not a complete security-master implementation. Mergers, symbol changes, rights issues, withholding tax and full adjustment history remain later work.

## Shadow and cost diagnostics

`ShadowPortfolioMonitor` compares a production-reference target and a shadow target without applying the shadow target.

Metrics:

```text
max absolute weight difference
active turnover distance
cosine similarity
```

`ExecutionCostCalibrator` summarizes realized paper fills into notional-weighted slippage, commission and participation observations. These diagnostics may inform later deterministic calibration, but the Supervisor does not directly rewrite execution parameters.

## Consequences

Positive:

- paper state survives restart;
- duplicate submissions do not duplicate financial state;
- partial fills have an explicit lifecycle;
- Agent request and operational application are separated by human approval;
- reconciliation can halt paper operation deterministically;
- corporate-action and session semantics become testable;
- shadow models can be evaluated without weight authority.

Trade-offs:

- Phase 5 is paper/shadow only; no live broker credential path is added;
- account state remains single base currency;
- session calendars are configuration-based rather than exchange-master feeds;
- impact remains a deterministic approximation rather than full microstructure simulation;
- corporate-action coverage is intentionally narrow.
