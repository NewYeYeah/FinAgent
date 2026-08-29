# Development Roadmap

This roadmap is intentionally short. The current detailed planning baseline is maintained in [`current-development-plan-v3.md`](current-development-plan-v3.md). The previous [`current-development-plan-v2.md`](current-development-plan-v2.md) is retained as the historical design/acceptance record for Visualization V2 and A5-1～A5-4.

## Current baseline

Current planning baseline was frozen on `main @ d5859dfc69f0b734e8d8eba32fe96bc7381e390b`.

Completed core/product capabilities:

- PIT numerical data contract, split isolation and frozen local A-share Parquet identity;
- bounded Agent-generated features, conformance repair/checkpointing and JSONL/OTLP traces;
- Factor Quant, rolling/subperiod stability, HAC/block bootstrap and Holm/BH evidence;
- A2.6 immutable ResearchProgram, expanding walk-forward, preregistered robust gates and exact replay;
- A3 exact-session A-share execution semantics including T+1, board-aware quantity rules, suspension/price limits and asymmetric fees;
- A4 reserve-safe Alpha/Risk/Optimizer portfolio validation with gross/net A3 execution ledgers and exact replay;
- Visualization V0 canonical evidence/lineage/Agent/widget contracts;
- Visualization V1 GET-only FastAPI + React/TypeScript Workspace foundation;
- Visualization V2 ResearchProgram/A4/execution/governance cockpit and human-review bundle;
- A5-1 eligibility sealing;
- A5-2 deterministic one-shot reserve runner and terminal evidence;
- A5-3 atomic pre-access `CONSUMED` claim, crash-safe terminal/ledger persistence and replay/audit;
- A5-4 read-only Workspace projection of reserve eligibility/consumption/terminal/ledger/audit evidence;
- Visualization V3-1 derived Agent Project → Thread → Run index contract over canonical read-only audit SQLite;
- legacy Streamlit/Plotly inspection and optional Phoenix low-level Agent diagnostics;
- existing registry, promotion, PAPER/shadow and operational-control primitives.

No production 2025+ reserve has been consumed by development or CI. Production reserve execution remains an independent human-authorized operation.

## Current product state

The primary Workspace now covers:

```text
ResearchProgram / Factor / Gate
        ↓
A4 Portfolio / Execution
        ↓
A5 Reserve Lifecycle
        ↓
Immutable Evidence / Lineage / Audit
```

The Agent product layer now also has a deterministic read-only Project → Thread → Run index. **Visualization V3-2 Workbench Shell is the current product milestone.** Phoenix remains diagnostic rather than a product-data contract.

## Current priority order

### Completed — Planning Baseline v3

- frozen post-A5-4 state and dependencies;
- production reserve operation separated from product development/CI;
- V3-1～V3-5 frozen as the bounded Agent Workbench sequence;
- v2 retained as historical V2/A5 design and acceptance documentation.

### P1 — Visualization V3 Agent Workbench

Bounded sequence:

1. **Completed — V3-1 Agent Index Contract**
   - `AgentProjectProjection` / `AgentThreadProjection` / `AgentRunSummary` / `AgentArtifactRef`;
   - deterministic project/thread fallback identities without canonical-store mutation;
   - explicit shared-thread → project inference where canonical metadata proves the binding;
   - conflicting thread/project identity fails closed;
   - verified artifact refs only; unresolved audit strings remain unresolved rather than becoming product evidence;
   - bulk read-only projection uses a single SQLite connection;
   - GET-only `/api/v3/agent/projects`, project detail, thread detail and run detail surfaces.
2. **Current — V3-2 Workbench Shell**
   - Projects/Threads navigation;
   - semantic activity timeline;
   - Inspector panel;
   - desktop-first Codex-like task workspace, not a chat clone;
   - persisted run review only; active streaming is deferred to V3-4.
3. **V3-3 Evidence / Artifact Deep Link**
   - Agent ↔ Factor ↔ ResearchProgram ↔ A4 ↔ A5 navigation;
   - source-code/generated-feature artifact inspector;
   - Phoenix diagnostics deep links.
4. **V3-4 Active Run SSE**
   - canonical active-run projection → SSE → browser;
   - no raw OTLP/provider callback/hidden reasoning stream in React.
5. **V3-5 Acceptance**
   - API/read-only authority tests;
   - Windows/Ubuntu;
   - ruff/mypy;
   - TypeScript/Vitest/build/Playwright;
   - repository-wide regression.

Hidden chain-of-thought remains unavailable and unpersisted. Workbench displays Action / Guardrail / Evidence / Decision / Approval / Result / Error business semantics.

### P1 — Visualization V4 Factor Tear Sheet

May start from the middle of V3, but only when required authoritative series exist.

Recommended sequence:

- V4-1 `FactorSeriesEvidence` contract for missing authoritative time series;
- fold/year IC heatmap, rolling IC and IC decay;
- HAC/bootstrap forest and Holm/BH candidate matrix;
- quantile/long-short cumulative evidence;
- turnover and coverage series;
- correlation clustering;
- Agent discovery evolution and candidate → frozen-family lineage.

The browser must not manufacture cumulative financial evidence from summary metrics.

### OPS — Production Reserve Execution

Not a development PR and never a CI side effect.

Before execution independently verify/archive:

```text
exact clean Git SHA
exact data_version
A2.6 exact replay
A4 exact replay
V2 review-bundle digest
production ReserveEligibilitySeal
A5-3 state-store locations and audit readiness
operator identity
reserve interval / terminal policy
```

Then permit one seal / one execution identity / one reserve / one terminal result.

```text
RESERVE_PASS → A6 may begin
RESERVE_FAIL → no promotion; same reserve cannot validate a modified strategy
```

A5-4 is the post-execution audit surface, not an execution console.

### P1 — A6 Strategy Freeze / Promotion / Internal PAPER

**Conditional on `RESERVE_PASS`.**

Recommended sequence:

- A6-1 immutable `FinalStrategySpec`;
- A6-2 immutable registry + deterministic promotion gate + human approval;
- A6-3 repeated internal PAPER runtime;
- A6-4 reconciliation / restart / recovery / kill switch / incident ledger;
- A6-5 operational acceptance.

PAPER acceptance focuses on operational correctness:

```text
desired order
→ broker-facing order
→ fill/reject/partial
→ fee
→ position/cash/NAV
→ reconciliation
```

Agent never owns promotion, broker or live-capital authority.

### P1 — Data hardening required before sustained PAPER

Raise these items ahead of long-running PAPER:

- corporate-action / cash-event ledger so adjusted research returns reconcile with raw-price execution/accounting;
- preregistered lagged-liquidity participation cap and impact proxy instead of ex-post-only participation diagnostics.

### P1.5 — Additional Research/Data Hardening

- improve source-bound delisting/ST/suspension history without modifying vendor Parquet;
- benchmark / industry / style diagnostics and constraints;
- certify 5/15/30/60-minute timestamp conventions, auction handling and session boundaries before intraday research;
- add chunked/out-of-core orchestration only when profiling demonstrates need.

### P1.5 — Visualization V5 Risk / Attribution / Signed Audit

Only render risk evidence formally produced by core:

- covariance/correlation and concentration;
- realized exposure;
- drawdown attribution;
- report/protocol comparison;
- signed immutable evidence packages;
- later marginal/component risk, factor exposure, stress and benchmark/industry/style attribution.

Frontend remains non-authoritative for risk math.

### P2 — QMT R0-R4 Realtime / External PAPER

Do not reuse historical `ResearchDataset` as the realtime event protocol.

- **R0** freeze `QuoteEvent`, `BarEvent`, `MarketStatusEvent`, `AccountStatusEvent`, `OrderEvent`, `TradeEvent`, `OrderErrorEvent`;
- **R1** MiniQMT callback → non-blocking async event queue → normalizer;
- **R2** latest-state projection + append-only Parquet event log + DuckDB analysis;
- **R3** WebSocket Live Workspace: Market / Strategy / Portfolio / Execution / System Health;
- **R4** external PAPER reconciliation, latency, partial/reject, disconnect/reconnect and state-drift evidence.

R0 should align with A6 internal order/fill semantics before R1. Live capital remains deferred.

## Parallel runtime rule

Continue CPU/RAM-aware automatic worker budgeting, but use profiling-first optimization.

Prefer independent deterministic work:

```text
cross-candidate evaluation
cross-fold statistics
bootstrap scenario batches
read-only evidence indexing
```

Keep governance, reserve, registry, promotion, broker/accounting mutation and shared authoritative writes serial/transactional. Worker count must not alter evidence identity.

## Development rule

```text
core functional loop
→ numerical/data correctness
→ tests/CI
→ immutable evidence
→ semantic projection
→ human-readable audit
→ freeze protocol identity
→ human-governed one-shot evidence
→ promotion/PAPER only after explicit gates
→ external realtime only after internal operational semantics stabilize
```

Every bounded PR must keep its contract narrow, include tests/docs for schema changes, and merge only after relevant mainline CI is green. Production reserve execution is explicitly outside feature PRs and CI.
