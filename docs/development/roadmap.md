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
- Visualization V2 pre-reserve A4/governance cockpit, execution-ledger projection and human-review bundle export;
- legacy read-only Streamlit/Plotly inspection with Phoenix as an optional low-level Agent trace viewer;
- existing sealed-holdout, promotion, registry, PAPER/shadow and operational-control primitives.

## Current product state

The Workspace now provides the V2 pre-reserve review surface over A2/A2.5, A2.6, A4, immutable A4 JSONL execution ledgers and Agent-audit evidence. It remains strictly read-only. The next governed milestone is A5 one-shot reserve evaluation; Visualization V3/V4 remain subsequent product work.

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

### Completed — Visualization V2 A4 + governance cockpit

The pre-reserve review gate now includes:

- rebuildable SQLite Evidence Catalog and deterministic allowlisted protocol diff;
- ResearchProgram lifecycle cockpit with explicit A2.6/A3-binding/A4/A5 status;
- A2.6 Gate matrix, statistical forest evidence and fold heatmap;
- richer A4 gross/net NAV, derived rolling review series, fold and economic evidence;
- immutable A4 JSONL desired → compiled/adjusted → executable → fill projection;
- T+1, lot, suspension, limit, cash and session/data attribution;
- fill-level fee components, target-versus-realized weights and implementation shortfall;
- combined immutable A2.6 → A4 lineage plus an explicitly `derived` A3 protocol binding where no standalone A3 evidence identity exists;
- reserve/promotion authority visibility and raw evidence inspection;
- downloadable human-review bundles containing manifest, lineage, protocol diff, CSV summaries and source evidence.

Authoritative metrics continue to come from FinAgent core. Presentation-only derivatives are labelled `derived`; the UI still exposes no research, reserve, promotion or trading mutation route.

### P1 — A5 one-shot reserve protocol

**A5-1, A5-2 and A5-3 implementation are complete; no production reserve has been consumed by development or CI.** The repository now provides deterministic eligibility/review sealing, the frozen one-shot evaluation engine, an irreversible pre-access `CONSUMED` claim, durable terminal/ledger persistence, explicit crash recovery without reserve re-access, and lifecycle replay/audit.

Remaining sequence:

1. issue and independently review the production `ReserveEligibilitySeal`;
2. independently verify the A5-3 state store/audit acceptance and archive the exact code/data identities;
3. only then may a human operator execute the exact sealed reserve once through the A5-3 guarded one-shot runner;
4. **A5-4:** integrate consumption/terminal/audit evidence into the read-only Workspace;
5. never relabel the consumed reserve as development data.

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