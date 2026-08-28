# Development Roadmap

This roadmap is intentionally short. Historical phase plans remain in Git history.

## Current baseline

Completed core capabilities:

- PIT numerical data contract and split isolation;
- deterministic alpha/risk/portfolio interfaces;
- nested validation, multiplicity control, DSR/PBO/Reality Check;
- bounded Agent-generated features, repair/checkpoint resilience and structured research memory;
- development-only Factor Quant feedback and deterministic multi-factor selection;
- sealed holdout lifecycle, research promotion and human-approved PAPER handoff;
- provider-configured US/A-share data surfaces and frozen local A-share Parquet identity;
- A2 bounded A-share factor research and A2.5 correctness/stability diagnostics;
- A2.6 immutable ResearchProgram, annual expanding walk-forward, preregistered robust gates, feedback v3, explicit no-alpha outcome and exact replay;
- vendor-neutral Agent JSONL/OTLP tracing and read-only Streamlit/Plotly Research UI;
- A3 exact-session A-share execution states, T+1 inventory, board-aware lot compilation, side-specific limit handling, asymmetric fees and deterministic execution smoke.

## Completed priority gate — A3 execution semantics

A3 keeps the generic planner and exchange market-neutral and adds an isolated A-share target-to-executable-order layer.

The execution adapter reads the exact requested daily row and never substitutes an earlier tradable quote. Suspensions, missing rows, invalid prices and absent price limits are explicit states. Buy-at-limit-up and sell-at-limit-down are rejected conservatively from vendor `up_limit`/`down_limit` fields.

Positions separate total, sellable and unsettled quantities. Buy fills become sellable only after the ledger advances to a later session. The compiler records desired quantity, executable quantity, lot/cash/T+1 adjustments and rejection reason codes. Fees separate broker commission, minimum commission, sell-side stamp duty, transfer fee and optional exchange/regulatory pass-through.

A3 certifies execution-rule plumbing only. It does not consume the 2025+ reserve or establish portfolio Alpha, capacity, promotion, PAPER or live-trading evidence.

## Current priority order

### P1 — A4 execution-aware portfolio validation

- connect a frozen A2.6 robust factor family to `AlphaModel → RiskModel → Optimizer` without changing its research identity;
- route every rebalance through the A3 target/desired/executable-order path;
- calculate gross and net portfolio returns under T+1, lots, suspensions, price limits, asymmetric fees and slippage;
- report rejected-order, T+1-clipped, lot-rounded, limit-blocked, suspension and cost attribution;
- add capacity/participation diagnostics before treating daily-bar results as economic evidence;
- freeze the A4 protocol before any 2025+ reserve access.

### P1 — A4 correctness and performance

- preserve `F_t → target_t → next executable open` chronology;
- prevent stale-price execution and same-close fills;
- support deterministic exact replay of orders, fills, fees, inventory and NAV;
- add chunked/out-of-core orchestration if 100–200 stock portfolio studies exceed practical memory/runtime limits;
- compare the A3 path with the US reference path without mixing market-specific rules.

### P1.5 — Visualization continuation

The current UI remains read-only. Later work should be driven by A4 debugging needs:

- show desired versus executable orders and reason-code attribution;
- visualize T+1 inventory, limit/suspension blocks, fee composition and gross-to-net decay;
- compare immutable ResearchProgram and execution-protocol identities;
- keep every research modification as an explicit new ResearchProgram rather than in-place mutation.

### P2 — Research-to-operation continuation

- consume the 2025+ reserve only after A2.6, A3 and A4 protocols are frozen;
- connect reserve-passing execution-valid ensembles to promotion/model identity;
- run repeated PAPER sessions and operational reconciliation;
- add external broker paper/shadow only when historical economic validation is stable;
- improve Provider Contract v2 entitlement/runtime snapshots.

### Deferred

A-share live-capital and realtime acceptance are not near-term milestones. Expensive realtime/delisting products are not required before historical research and execution-aware validation mature.

Advanced ML/RL/multi-agent extensions remain lower priority than factor stability, data correctness and execution realism.

## Development rule

```text
core functional loop
→ P0 numerical/data correctness
→ tests/CI
→ record bounded P1 risks
→ later hardening
```

Do not proceed past errors that invalidate chronology, data identity, adaptive-search denominator, validation isolation, exact-session tradeability, T+1 inventory or execution clocks.
