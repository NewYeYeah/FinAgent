# Development Roadmap

This roadmap is intentionally short. The active detailed planning baseline is [`current-development-plan-v3.1.md`](current-development-plan-v3.1.md), with the supporting architecture in [`../architecture/workbench-v3.md`](../architecture/workbench-v3.md). The previous v3 and v2 documents remain historical design/acceptance records.

## Current baseline

Planning v3.1 anchor: `main @ 2909a65aa89f11e80c434414f7fe070d3aa72a0a`.

Completed core/product capabilities include PIT data contracts, bounded Agent-generated research, A2.6 robust ResearchPrograms, A3 exact-session execution semantics, A4 execution-aware portfolio validation, Visualization V0/V1/V2, A5-1～A5-4 reserve governance/evidence, **Visualization V3-1 Agent Project → Thread → Run index**, **Visualization V3-2A Workbench Shell + Context Bus**, and **Visualization V3-2B Config Registry + Command Catalog**.

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

V3-1 remains unchanged and supplies the Agent navigation substrate. V3-2A supplies the shared shell/context substrate. V3-2B freezes the configuration and command metadata contracts consumed by the future explicit Control Plane.

## Current priority order

### Completed — V3-1 Agent Index Contract

- deterministic `AgentProjectProjection` / `AgentThreadProjection` / `AgentRunSummary` / `AgentArtifactRef`;
- missing Project/Thread metadata receives deterministic derived fallback identity;
- conflicting thread/project bindings fail closed;
- verified artifact refs only;
- bulk read-only Agent projection through one SQLite connection;
- GET-only `/api/v3/agent/*` navigation API.

### Completed — V3-2A Workbench Shell + Context Bus

Delivered on `feature/v3-workbench-shell-context`:

- desktop-first registry-driven FinAgent navigation shell covering current and future Workbench modules;
- typed `WorkbenchContextProvider` for Project/Thread/Run, Program/Factor/Portfolio/Strategy/Reserve, Asset/Date/Session/Fold and Environment identities;
- deterministic URL round-trip and context-preserving cross-module navigation;
- declared linked-selection event vocabulary kept separate from deep-link identity;
- `PanelRegistry`, Inspector slot, chart-workspace slot plus disabled Config drawer/Command palette extension slots;
- V3-1 Agent Project → Thread → Run navigation, persisted Activity and verified-artifact Inspector inside the new shell;
- identity-keyed shared typed server-state query provider with cache, in-flight de-duplication, stale handling, refetch and invalidation boundaries;
- legacy `/agent/:runId` links deterministically redirect into the V3 Workbench context URL;
- existing V1/V2/A5 pages remain available;
- **no write API or Control Plane authority added**.

### Completed — V3-2B Config Registry + Command Catalog

Delivered on `feature/v3-config-command-catalog`:

- froze public contracts for `ConfigDescriptor`, `ConfigSnapshot`, `ConfigFieldSpec`, `ConfigDiff`, `CommandSpec`, `CommandIntent`, `CommandRun` and `CommandResult`;
- added a read-only allowlisted TOML registry over supported FinAgent public configuration sections;
- classified fields into presentation, runtime, research protocol, execution protocol, operational guardrail and secret-reference domains with explicit mutation policies;
- protocol changes are labelled `new_identity_required`; operational guardrail changes require governed change rather than historical mutation;
- excluded secret/credential-like files before parsing and redacted credential-looking fields fail-closed while retaining symbolic `secret_id`/environment references;
- added deterministic ConfigSnapshot identities and read-only ConfigDiff projection;
- added an allowlisted L0/L1 Command Catalog for config validation, local-data certification, development research, A2.6, A4 and review-bundle export;
- existing CLI-orchestration commands are explicitly `adapter_required` until application-service adapters are built; the catalog does not call shell/Python;
- exposed GET-only `/api/v3/config*`, `/api/v3/commands*` and Workbench status endpoints through the V3 Workbench composition layer;
- added Configuration Registry / Command Catalog Workbench surfaces while keeping Config drawer and Command palette execution affordances disabled;
- **`execution_enabled=false` and `control_plane_enabled=false`; no write endpoint added**.

### Current — V3-2C Safe Research Control Gateway

Add a **separate, explicit opt-in Control Plane** for allowlisted L0/L1 commands only, such as config validation, data certification, development research, A2.6, A4 and review-bundle export.

Before a catalogued CLI-orchestration command can become executable, extract or wrap it behind a typed application-service adapter. The gateway must never execute arbitrary command strings, shell or Python supplied by the browser.

The Control Plane must persist `CommandIntent`, `CommandRun` and `CommandResult` audit evidence and must enforce confirmation/authority policy from `CommandSpec`. It must not expose L2 operational mutations, production reserve, strategy promotion, PAPER mutation, broker/order or live-capital authority.

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
- Evidence Plane remains GET-only;
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
- V3-2A establishes the shared **identity-keyed query-provider contract** required by Workbench server state. The current implementation is an equivalent typed cache/de-duplication layer isolated behind that boundary; TanStack Query remains the preferred external substitution if/when dependency adoption is justified before V3 foundation acceptance.
- V3-2B intentionally uses read-only typed configuration metadata rather than introducing an editable JSON-Schema form. **RJSF or equivalent JSON-Schema forms** may be reconsidered only after V3-2C defines explicit mutation authority.
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
