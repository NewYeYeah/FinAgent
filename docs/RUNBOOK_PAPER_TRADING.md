# Paper Trading Runbook

## Start of session

1. Verify the configured `TradingSessionCalendar`.
2. Load the latest persisted paper account.
3. Confirm the kill switch is `ARMED`.
4. Record session-start NAV for deterministic loss-limit checks.
5. Build and persist the current `PortfolioHealthSnapshot`.
6. Require explicit human approval for any Supervisor rebalance or operating-policy request.

## Before an order batch

Verify:

```text
exact rebalance approval ID matches snapshot ID
RiskGate already approved upstream target
execution snapshot is current
kill switch is ARMED
per-order and batch notional limits pass
```

Never submit an Agent-authored arbitrary weight vector.

## During execution

Paper market orders may fill partially. Do not resubmit residual quantity under a new client order ID merely because an order is partially filled. Let the persisted open order continue across execution snapshots or explicitly cancel it.

Retrying the same `client_order_id` is safe only when immutable request fields are identical.

## Reconciliation

After execution, compare the paper account with the deterministic ledger.

Critical:

```text
cash mismatch
position mismatch
```

Warning:

```text
mark mismatch
NAV-only mismatch
```

Any critical issue should leave the kill switch `HALTED` until an operator identifies the cause.

## Restart recovery

After restart:

1. Re-open the same SQLite paper store.
2. Read the durable kill-switch state.
3. Load the latest account snapshot.
4. Inspect open orders.
5. Do not generate replacement order IDs for open residuals.
6. Reconcile before resuming.

## Corporate actions

Apply a corporate action exactly once using its stable `action_id`.

Current support is limited to splits and cash dividends.

## Kill-switch reset

Reset is an explicit operator action. It must not be performed by the Supervisor Agent or as a side effect of process startup.

Before reset, record:

```text
root cause
reconciliation result
operator identity
time
```

## Live-capital restriction

Phase 5 provides no live-broker credential or order path. Paper/shadow operation must remain isolated from real capital.
