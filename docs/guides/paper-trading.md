# Paper and Shadow Operations

FinAgent's operational layer is supervised. A validated research model does not obtain authority to trade by itself.

## Stages

```text
Research validation
→ VALIDATED model
→ immutable handoff request
→ HumanApproval
→ PAPER model
→ deterministic strategy plan
→ rebalance approval
→ PaperBroker
→ reconciliation / operational evidence
```

`PaperStrategyRuntime` produces a plan; it does not directly mutate broker state.

## Core invariants

- retry must not create a second trade;
- process restart must not reset financial state;
- approval request and application are separate events;
- expired/revoked approval cannot authorize execution;
- reconciliation failure moves the system toward a safe state;
- a halted kill switch survives restart;
- shadow mode creates targets/theoretical orders only.

## Current scope

The repository includes an internal deterministic `PaperBroker`. It is not an external brokerage integration and does not imply live-capital readiness.

A-share realtime/paper acceptance is currently deferred. A-share development is historical-research first until execution semantics and supplementary market-status data are mature.

## Testing

Run the operational regression suites as part of the full test command:

```bash
python -m pytest -q
```

Focused suites can be located under `tests/test_operations_*` and the paper strategy runtime tests. See `docs/testing/testing.md` for the canonical release gate.
