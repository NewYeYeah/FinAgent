# Development Roadmap

This roadmap is intentionally short. Historical phase plans remain in Git history.

## Current baseline

Completed core capabilities:

- PIT numerical data contract, split isolation and frozen local A-share Parquet identity;
- bounded Agent-generated features, conformance repair/checkpointing and JSONL/OTLP traces;
- Factor Quant, rolling/subperiod stability, HAC/block bootstrap and Holm/BH evidence;
- A2.6 immutable ResearchProgram, expanding walk-forward, preregistered robust gates, explicit no-alpha outcome and exact replay;
- A3 exact-session tradeability, T+1 inventory, board-aware quantity rules, suspension/price-limit handling and asymmetric fees;
- A4 reserve-safe inference, train-only frozen-factor calibration, historical risk/optimizer targets, gross/net A3 execution ledgers, portfolio economic evidence and exact replay;
- read-only Streamlit/Plotly Research UI with Phoenix as an optional low-level Agent trace viewer;
- existing sealed-holdout, promotion, registry, PAPER/shadow and operational-control primitives.

## Completed priority gate — A4 execution-aware portfolio validation

A4 connects only an immutable A2.6 factor family to portfolio construction. Each internal fold fits factor calibration on the fold training range, forms targets from information available before the next open, executes through A3 and marks the account at the exact same-session close.

The test calendar and dynamic universe use a feature-only adapter that reads no future label rows. The final 2024 internal session therefore does not require the first 2025 reserve row.

A synchronized gross ledger keeps T+1, lots, suspension, price limits and cash constraints while removing fees and slippage. The net ledger applies the configured account costs. Reports separate workflow completion from economic validation and remain promotion-ineligible.

A4 freezes:

```text
A2.6 source identity
factor digests / weights / directions
walk-forward plan
A3 execution assumptions
fee schedule
portfolio/risk/optimizer settings
economic gate
execution-ledger identity
```

## Current priority order

### P0.5 — A4 unified real-data acceptance and debugging

Before reserve access, run one coordinated Windows/Ubuntu acceptance using the real frozen dataset:

- A2.6 deterministic/Agent report and exact replay;
- A3 execution smoke on normal, suspended and price-limit examples;
- A4 report and byte-identical execution-ledger replay;
- full regression/quality/build matrix;
- manual accounting checks for cash, positions, T+1, fees and NAV;
- review gross-to-net drag, order reasons, participation and cash-fallback frequency;
- record runtime/memory for the 150-stock, 2018–2024 study;
- fix only chronology, accounting, identity or implementation defects—do not tune economic gates against the internal result.

### P1 — A4.5 evidence visualization and immutable report comparison

Extend the read-only UI only where it improves real debugging:

- A4 NAV, drawdown and gross-versus-net curves;
- fee/slippage and gross-to-net attribution;
- desired/executable quantities, T+1 clipping, lot rounding, suspension/limit blocks and cash scaling;
- target versus realized weights and implementation shortfall;
- fold-level economic metrics, HAC/bootstrap evidence and capacity diagnostics;
- immutable A2.6 → A4 lineage and report-to-report configuration diff;
- downloadable read-only evidence bundles.

No UI action may rerun research, change a gate or consume reserve. Any change forks a new ResearchProgram/protocol identity.

### P1 — A5 one-shot reserve protocol

Only after A2.6, A3 and A4 pass unified acceptance:

1. freeze the A2.6 ResearchProgram and selected factor family;
2. freeze the A4 portfolio-validation specification, A3 execution rules and fee assumptions;
3. create a reserve eligibility seal for the exact 2025+ interval;
4. consume the reserve once, without Agent feedback or threshold changes;
5. emit a signed pass/fail report and close the ResearchProgram;
6. never relabel the consumed reserve as development data.

A reserve failure is a valid terminal outcome. A different hypothesis or rule set requires a new future reserve or forward PAPER evidence—not reuse of the same window.

### P1 — A6 strategy freeze, promotion and PAPER

For a reserve-passing candidate:

- create an execution-valid `FinalStrategySpec` binding Alpha/Risk/Optimizer/A3/A4 identities;
- register the immutable model/strategy package;
- run deterministic promotion gates and retain the human approval boundary;
- execute repeated internal PAPER sessions;
- reconcile desired orders, broker orders, fills, fees, positions, cash and NAV;
- enforce approval, kill switch, stale-data and exposure controls;
- collect operational evidence before considering an external broker.

### P1.5 — Research and data hardening

- add benchmark, industry and style exposure diagnostics/constraints;
- improve source-bound delisting/ST/suspension history without modifying vendor Parquet;
- add a corporate-action cash/event ledger and verify raw-price execution against adjusted research returns;
- replace ex-post participation-only capacity checks with a preregistered lagged-liquidity/impact model;
- add chunked/out-of-core orchestration when the bounded panel no longer suffices;
- certify 5/15/30/60-minute timestamp conventions before enabling intraday research;
- keep Alpaca SIP as the US reference/regression path and add providers only for a concrete evidence gap.

### P2 — External paper broker and realtime validation

- Provider Contract v2 entitlement/runtime snapshots;
- realtime calendar, symbol and corporate-action reconciliation;
- external paper/shadow adapter with idempotent order submission and reconciliation;
- latency, partial-fill, reject and disconnect incident tests;
- staged operational acceptance under supervision.

### Deferred

A-share live capital is not a near-term milestone. It remains blocked until historical reserve, repeated PAPER, reconciliation, incident recovery and human approval all pass.

Advanced ML/RL/multi-agent extensions remain lower priority than factor stability, data correctness, execution realism and operational reliability.

## Development rule

```text
core functional loop
→ P0 numerical/data correctness
→ tests/CI
→ real-data acceptance
→ freeze protocol identity
→ consume evidence once
→ promotion/PAPER only after explicit gates
```

Do not proceed past errors that invalidate chronology, data identity, adaptive-search denominator, reserve isolation, exact-session tradeability, T+1 inventory, accounting conservation or exact replay.
