# Development Roadmap

This roadmap is intentionally short. Historical phase plans remain in Git history. The detailed frozen planning baseline is maintained in [`current-development-plan-v2.md`](current-development-plan-v2.md).

## Current baseline

Completed core capabilities:

- PIT numerical data contract, split isolation and frozen local A-share Parquet identity;
- bounded Agent-generated features, conformance repair/checkpointing and JSONL/OTLP traces;
- Factor Quant, rolling/subperiod stability, HAC/block bootstrap and Holm/BH evidence;
- A2.6 immutable ResearchProgram, expanding walk-forward, preregistered robust gates, explicit no-alpha outcome and exact replay;
- A3 exact-session tradeability, T+1 inventory, board-aware quantity rules, suspension/price-limit handling and asymmetric fees;
- A4 reserve-safe inference, train-only frozen-factor calibration, historical risk/optimizer targets, gross/net A3 execution ledgers, portfolio economic evidence and exact replay;
- Visualization V0 canonical evidence, Agent projection, Widget and lineage contracts;
- Visualization V1 GET-only FastAPI Evidence API and usable React/TypeScript Workspace;
- legacy read-only Streamlit/Plotly inspection with Phoenix as an optional low-level Agent trace viewer;
- existing sealed-holdout, promotion, registry, PAPER/shadow and operational-control primitives.

## Current product state

The Workspace can now navigate A2/A2.5, A2.6, A4 and Agent-audit evidence without coupling the browser to internal report or Phoenix span schemas. It remains strictly read-only. The next product gap is a denser A4/governance cockpit suitable for reviewing the frozen protocol before one-shot reserve use.

## Current priority order

### Completed — Visualization V0 semantic contract

- canonical `EvidenceRef` / `EvidenceBundle` contracts;
- A2/A2.6/A4 evidence adapters;
- acyclic lineage graph;
- canonical `AgentRunProjection` separate from Phoenix;
- `FinWidgetSpec` and authoritative/derived/diagnostic classes;
- fail-closed unsupported schemas and hidden-reasoning boundary.

### Completed — Visualization V1 Workspace foundation

- GET-only FastAPI `/api/v1` Evidence API;
- in-memory disposable Evidence catalog;
- React + TypeScript + Vite application;
- TanStack Table, ECharts and React Flow foundations;
- Project/Research/Portfolio/Factor/Agent/Widget pages;
- A2.6 factor/Gate/fold navigation;
- A4 gross/net NAV, derived drawdown, execution funnel and rejection/cost navigation;
- Agent audit opened read-only;
- Python API, frontend unit/build and Playwright smoke tests;
- cross-platform launcher and consolidated usage/testing documentation.

### P0.5 — Visualization V2 A4 + governance cockpit

This is the minimum visualization gate before one-shot reserve use:

- ResearchProgram lifecycle and protocol-identity comparison;
- A2.6 candidate Gate matrix and statistical forest view;
- richer A4 gross/net NAV, rolling risk and fold-boundary views;
- explicit cost-component and gross-to-net drag attribution;
- desired → compiled → executable → fill lifecycle from A4 ledger;
- T+1, lot, suspension, limit and cash adjustment attribution;
- target-versus-realized portfolio and implementation shortfall;
- A2.6 → A3 → A4 lineage and immutable configuration diff;
- reserve status prominently visible;
- immutable evidence bundle export for human review.

Authoritative metrics must continue to come from FinAgent core. Presentation-only derivatives remain labelled `derived`.

### P1 — A5 one-shot reserve protocol

Only after A2.6, A3, A4 and the minimum V2 evidence cockpit pass acceptance:

1. freeze the A2.6 ResearchProgram and factor family;
2. freeze the A4 specification and execution assumptions;
3. create an eligibility seal for the exact 2025+ interval;
4. consume the reserve once, without Agent feedback or threshold changes;
5. emit terminal pass/fail evidence and close the ResearchProgram;
6. never relabel the consumed reserve as development data.

A reserve failure is a valid terminal outcome.

### P1 — Visualization V3 Agent Workbench

- Projects/Runs navigation;
- semantic activity timeline of Action / Guardrail / Evidence / Decision / Result / Error / Approval;
- evidence inspector and source-code artifacts;
- Agent ↔ Factor ↔ ResearchProgram deep links;
- optional SSE projection for active runs;
- Phoenix deep links for low-level diagnostics;
- no hidden chain-of-thought rendering.

### P1 — Visualization V4 Factor Tear Sheet

- fold/year IC heatmaps;
- IC decay and rolling stability;
- quantile and long-short cumulative evidence once authoritative series are persisted;
- turnover and coverage series;
- HAC/bootstrap forest view;
- Holm/BH candidate matrix;
- correlation clustering;
- discovery evolution across Agent rounds.

### P1 — A6 strategy freeze, promotion and PAPER

For a reserve-passing candidate:

- create an execution-valid `FinalStrategySpec` binding Alpha/Risk/Optimizer/A3/A4/A5 identities;
- register the immutable model/strategy package;
- run deterministic promotion gates and retain the human approval boundary;
- execute repeated internal PAPER sessions;
- reconcile desired orders, broker orders, fills, fees, positions, cash and NAV;
- enforce approval, kill switch, stale-data and exposure controls;
- collect operational evidence before considering an external broker.

### P1.5 — Visualization V5 risk / attribution / evidence export

Only render risk evidence that FinAgent core formally produces:

- covariance/correlation and concentration first;
- later marginal/component risk contribution, factor exposure and stress evidence;
- report-to-report identity diff and ResearchProgram comparison;
- signed immutable evidence packages for audit/review.

### P1.5 — Research and data hardening

- add benchmark, industry and style exposure diagnostics/constraints;
- improve source-bound delisting/ST/suspension history without modifying vendor Parquet;
- add a corporate-action cash/event ledger and verify raw-price execution against adjusted research returns;
- replace ex-post participation-only capacity checks with a preregistered lagged-liquidity/impact model;
- add chunked/out-of-core orchestration when the bounded panel no longer suffices;
- certify 5/15/30/60-minute timestamp conventions before enabling intraday research.

### P2 — QMT realtime / external PAPER

Freeze the QMT event contract before implementation, but do not let realtime work block historical reserve validation:

- `QuoteEvent`, `BarEvent`, `MarketStatusEvent`;
- `AccountStatusEvent`, `OrderEvent`, `TradeEvent`, `OrderErrorEvent`;
- preserve `event_time`, `received_at`, `available_at`, provider/connection/subscription/sequence identity;
- MiniQMT callbacks write to an async event queue only;
- normalized projections feed a future WebSocket Live UI;
- external paper/shadow reconciliation before any live-capital discussion.

### Deferred

A-share live capital is not a near-term milestone. Advanced ML/RL/multi-agent extensions remain lower priority than factor stability, data correctness, execution realism, evidence navigation and operational reliability.

## Development rule

```text
core functional loop
→ numerical/data correctness
→ tests/CI
→ immutable evidence
→ semantic projection
→ human-readable audit
→ freeze protocol identity
→ consume one-shot evidence
→ promotion/PAPER only after explicit gates
```

Do not proceed past errors that invalidate chronology, data identity, adaptive-search denominator, reserve isolation, exact-session tradeability, T+1 inventory, accounting conservation, exact replay or evidence lineage.