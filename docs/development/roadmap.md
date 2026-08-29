# Development Roadmap

This roadmap is intentionally short. The active detailed planning baseline is [`current-development-plan-v3.1.md`](current-development-plan-v3.1.md), with the supporting architecture in [`../architecture/workbench-v3.md`](../architecture/workbench-v3.md). The previous v3 and v2 documents remain historical design/acceptance records.

## Current baseline

Planning v3.1 anchor: `main @ 2909a65aa89f11e80c434414f7fe070d3aa72a0a`.

Completed core/product capabilities include PIT data contracts, bounded Agent-generated research, A2.6 robust ResearchPrograms, A3 exact-session execution semantics, A4 execution-aware portfolio validation, Visualization V0/V1/V2, A5-1～A5-4 reserve governance/evidence, and **Visualization V3-1 Agent Project → Thread → Run index**.

No production 2025+ reserve has been consumed by development or CI. Production reserve execution remains an independent human-authorized operation.

## Product direction

The product target is now **FinAgent Workbench**, not an Agent-only viewer:

```text
Command Center
Agent
Strategy
Factors
Portfolio
Execution
Risk
Operations
Evidence & Governance
Configuration
Live (future)
```

Two authority planes are frozen:

```text
Evidence Plane  → default / GET-only / read-only
Control Plane   → future explicit opt-in / typed governed commands
```

V3-1 remains unchanged and supplies the Agent navigation substrate.

## Current priority order

### Completed — V3-1 Agent Index Contract

- deterministic `AgentProjectProjection` / `AgentThreadProjection` / `AgentRunSummary` / `AgentArtifactRef`;
- missing Project/Thread metadata receives deterministic derived fallback identity;
- conflicting thread/project bindings fail closed;
- verified artifact refs only;
- bulk read-only Agent projection through one SQLite connection;
- GET-only `/api/v3/agent/*` navigation API.

### Current — V3-2A Workbench Shell + Context Bus

Suggested branch: `feature/v3-workbench-shell-context`.

Deliver:

- desktop-first FinAgent navigation shell;
- `WorkbenchContextProvider` with Project/Run/Program/Factor/Strategy/Asset/Date identities;
- context bar and deterministic linked-selection events;
- `PanelRegistry`, Inspector slot, chart-workspace slot, Config drawer slot and Command palette slot;
- V3-1 Agent navigation/activity inside the new shell;
- TanStack Query (or equivalent) server-state foundation;
- **no write API yet**.

### P1 — V3-2B Config Registry + Command Catalog

Freeze additive contracts:

```text
ConfigDescriptor / ConfigSnapshot / ConfigFieldSpec / ConfigDiff
CommandSpec / CommandIntent / CommandRun / CommandResult
```

Configuration fields must distinguish presentation/runtime settings from research protocol, execution protocol, operational guardrails and secret references. Protocol edits create new identity/forks rather than mutating historical evidence.

This phase remains catalog/read-only: no general execution endpoint.

### P1 — V3-2C Safe Research Control Gateway

Add a **separate, explicit opt-in Control Plane** for allowlisted L0/L1 commands only, such as config validation, data certification, development research, A2.6, A4 and review-bundle export.

The Control Plane must call registered application services and persist `CommandRun` audit evidence. It must not expose arbitrary shell/Python execution, L2 operational mutations, production reserve, broker or live-capital authority.

### P1 — V3-3 Evidence / Artifact / Config Deep Link

- Agent ↔ Factor ↔ ResearchProgram ↔ A4 ↔ A5 navigation;
- Run ↔ ConfigSnapshot/ConfigDiff;
- CommandRun ↔ produced evidence;
- generated-feature/source artifact inspector;
- Phoenix remains low-level diagnostic only.

### P1 — V3-4 Agent + CommandRun SSE

Stable product projections only:

```text
AgentActiveRunProjection / CommandRunProjection
→ SSE
→ Workbench
```

No raw OTLP/provider callbacks or hidden reasoning stream.

### P1 — V3-5 Workbench Foundation Acceptance

- context/deep-link identity tests;
- Evidence Plane still GET-only;
- L0/L1 Control Plane authority/adversarial tests;
- no L2/L3 generic execution path;
- Windows/Ubuntu, ruff/mypy, TypeScript/Vitest/build/Playwright and repository-wide pytest.

## P1 — V4 Linked Quant Analytics

### V4-0 StrategyDecisionSeriesEvidence

Persist authoritative signal → target → order → fill → position → PnL/cost series, preferably as JSON manifest + Parquet data.

### V4-1 FactorSeriesEvidence

Persist missing authoritative IC/decay/quantile/long-short/turnover/coverage series.

### V4-2 Strategy Decision Explorer

Interactive price/candlestick + signal/order/fill markers + factor contribution + target/realized weights + gross-to-net PnL/cost explanation.

### V4-3 Factor Tear Sheet

- IC / rolling IC / decay;
- fold/year heatmap;
- Q1–Q5 / long-short;
- turnover / coverage;
- HAC/bootstrap forest;
- Holm/BH matrix;
- factor correlation cluster;
- Agent discovery evolution.

### V4-4 Portfolio / Execution Interactive Pack

Use existing V2 evidence plus new benchmark/series evidence for linked NAV/drawdown/rolling metrics/monthly returns/order lifecycle/constraint attribution/cost waterfall/target-realized views.

### V4-5 Linked Analytics Acceptance

Every chart must declare evidence requirements and authority class, and all asset/date/order interactions must flow through `WorkbenchContext`.

## Open-source implementation choices

- **Apache ECharts** remains the main analytical chart engine; add a shared context-aware wrapper.
- **React Flow** remains the lineage/DAG renderer.
- **TanStack Table** remains the structured-table foundation.
- **TanStack Query** is introduced in V3-2A for server state.
- **RJSF or equivalent JSON-Schema forms** may be introduced in V3-2B after typed config descriptors exist.
- **TradingView Lightweight Charts** is introduced in V4-2 for candlestick/volume/order-marker views only.
- **FINOS Perspective** is deferred until A6/QMT profiling demonstrates a need for large/streaming tables.
- Alphalens/QuantStats are visual/regression references only, not alternate authoritative calculation paths.

## OPS — Production Reserve Execution

Still not a feature PR or CI task. The reviewed A5 one-shot checklist and irreversible `CONSUMED` semantics remain unchanged.

```text
RESERVE_PASS → A6 may begin
RESERVE_FAIL → no promotion; same reserve never reused for modified-strategy validation
```

## P1 — A6 Strategy Freeze / Promotion / Internal PAPER

Conditional on `RESERVE_PASS`:

```text
A6-1 FinalStrategySpec
A6-2 registry/promotion + human approval
A6-3 internal PAPER
A6-4 reconciliation/recovery/kill switch/incident ledger
A6-5 operational acceptance
```

Only during A6 may Workbench integrate L2 governed operations, and those controls must call the existing approval/PAPER/safety/reconciliation services instead of reimplementing them.

## P1 — Data hardening before sustained PAPER / advanced risk charts

- CorporateActionEvent / CashEvent accounting;
- benchmark return/NAV evidence;
- preregistered lagged-liquidity participation/capacity model;
- later industry/style exposure evidence.

## P1.5 — V5 Risk / Attribution / Signed Audit

Only render risk evidence formally produced by core: covariance/correlation, concentration, realized exposure, drawdown attribution, later risk contribution/style/industry/stress evidence, and signed immutable audit packages.

## P2 — QMT R0-R4 / Live Workbench

Keep realtime event semantics independent from `ResearchDataset`:

```text
R0 Event Contract
R1 QMT Gateway
R2 Projection / State Store
R3 Live Workbench
R4 External PAPER reconciliation
```

R3 should register Market/Strategy/Portfolio/Execution/System Health panels into the V3 shell rather than introduce a second frontend architecture.

## Parallel / performance rule

Continue CPU/RAM-aware automatic worker budgeting for independent deterministic backend work. Large visualization series should use columnar storage and bounded date/asset APIs; worker count, caching or rendering downsampling must never alter evidence identity or authoritative aggregates.

## Development rule

```text
core/data correctness
→ immutable evidence
→ projection contract
→ WorkbenchContext / product semantics
→ interactive presentation
→ typed governed commands only after authority is explicit
→ human-governed one-shot evidence
→ promotion/PAPER after explicit gates
→ realtime only after internal operational semantics stabilize
```
