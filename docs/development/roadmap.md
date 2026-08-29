# Development Roadmap

This roadmap is intentionally short. The active detailed planning baseline is [`current-development-plan-v3.1.md`](current-development-plan-v3.1.md), with the supporting architecture in [`../architecture/workbench-v3.md`](../architecture/workbench-v3.md). The previous v3 and v2 documents remain historical design/acceptance records.

## Current baseline

Planning v3.1 implementation anchor: `main @ 2ddad3fb279bc5c4a1379cfe1405d9f565473351` before the V3-2C incremental control work.

Completed core/product capabilities include PIT data contracts, bounded Agent-generated research, A2.6 robust ResearchPrograms, A3 exact-session execution semantics, A4 execution-aware portfolio validation, Visualization V0/V1/V2, A5-1～A5-4 reserve governance/evidence, **Visualization V3-1 Agent Project → Thread → Run index**, **V3-2A Workbench Shell + Context Bus**, **V3-2B Config Registry + Command Catalog**, and **V3-2C-1 Application Service Convergence**.

No production 2025+ reserve has been consumed by development or CI. Production reserve execution remains an independent human-authorized operation.

## Product direction

The product target is **FinAgent Workbench**, not an Agent-only viewer:

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

Two authority planes remain frozen:

```text
Evidence Plane  → default / GET-only / read-only
Control Plane   → future explicit opt-in / typed governed commands
```

The Agent navigation substrate, Workbench context substrate and typed configuration/command vocabulary are now in place. V3-2C incrementally builds the governed execution substrate without weakening the Evidence Plane.

## Current priority order

### Completed — V3-1 Agent Index Contract

- deterministic `AgentProjectProjection` / `AgentThreadProjection` / `AgentRunSummary` / `AgentArtifactRef`;
- missing Project/Thread metadata receives deterministic derived fallback identity;
- conflicting thread/project bindings fail closed;
- verified artifact refs only;
- bulk read-only Agent projection through one SQLite connection;
- GET-only `/api/v3/agent/*` navigation API.

### Completed — V3-2A Workbench Shell + Context Bus

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

- froze public contracts for `ConfigDescriptor`, `ConfigSnapshot`, `ConfigFieldSpec`, `ConfigDiff`, `CommandSpec`, `CommandIntent`, `CommandRun` and `CommandResult`;
- added a read-only allowlisted TOML registry over supported FinAgent public configuration sections;
- classified fields into presentation, runtime, research protocol, execution protocol, operational guardrail and secret-reference domains with explicit mutation policies;
- protocol changes are labelled `new_identity_required`; operational guardrail changes require governed change rather than historical mutation;
- excluded secret/credential-like files before parsing and redacted credential-looking fields fail-closed while retaining symbolic secret references;
- added deterministic ConfigSnapshot identities and read-only ConfigDiff projection;
- added an allowlisted L0/L1 Command Catalog for config validation, local-data certification, development research, A2.6, A4 and review-bundle export;
- exposed GET-only `/api/v3/config*`, `/api/v3/commands*` and Workbench status endpoints;
- added Configuration Registry / Command Catalog Workbench surfaces;
- **`execution_enabled=false` and `control_plane_enabled=false`; no write endpoint added**.

### Completed — V3-2C-1 Application Service Convergence

This increment establishes the execution seam without exposing execution:

- added `finagent.application` with typed `ApplicationCommandInvocation`, `ApplicationCommandExecution` and an allowlisted `ApplicationServiceRegistry`;
- the registry has no arbitrary shell/Python/subprocess escape hatch and unknown `command_id` values fail closed;
- corrected `data.certify_local_ashare` to bind the real `[local_ashare]` configuration contract rather than the unrelated research-smoke descriptor;
- promoted exactly three L0 commands to `application_service_ready`: `config.validate`, `data.certify_local_ashare`, and `review.export_bundle`;
- refactored `certify_local_ashare_data.py` and `export_workspace_review_bundle.py` into CLI adapters over the shared in-process services;
- Workbench startup verifies that `application_service_ready` catalog identities exactly match registered service identities;
- A2/A2.5, A2.6 and A4 remain `adapter_required` because their fat CLI orchestration has not yet been safely extracted;
- **the Evidence Plane remains GET-only and does not retain or expose the service registry for execution**.

### Current — V3-2C-2 Durable Command Store

Persist the already-frozen command contracts before any HTTP execution is enabled:

```text
CommandIntent
    ↓
CommandRun
    ↓
CommandResult
    └─ CommandEvent / audit transitions
```

Required properties:

- SQLite transactional persistence with deterministic/explicit identities;
- strict state-transition validation and idempotent replay/read semantics;
- command/config/context identity retained exactly;
- crash-visible `planned/running/failed/rejected/succeeded` states;
- produced artifact/evidence references persisted without changing core evidence authority;
- no arbitrary executable text stored as an execution instruction;
- no Control API yet required for this persistence increment.

### Next — V3-2C-3 Explicit Control API

Add a **separate, opt-in Control Plane** for only `application_service_ready` L0/L1 commands.

Recommended deployment remains:

```text
Evidence API : 8765
Control API  : 8766
```

The gateway must:

- resolve exact `CommandSpec` and exact registered application service;
- bind an approved `ConfigSnapshot` where required;
- persist `CommandIntent` / `CommandRun` before executing;
- enforce `requires_confirmation` and authority level;
- never accept arbitrary shell command, executable text or Python source from the browser;
- never expose production reserve, strategy promotion, PAPER mutation, broker order or live-capital authority.

Before `research.run_development`, `research.run_a2p6` or `portfolio.run_a4` can become executable, their orchestration must be extracted behind typed application services and their catalog readiness changed in the same reviewed change.

### Next — V3-2C-4 Command Palette / Run Inspector

Only after the Control API and durable command audit exist:

- enable the reserved Command Palette for commands actually permitted by the connected Control Plane;
- bind ConfigSnapshot and WorkbenchContext explicitly;
- show confirmation/authority/produced-evidence semantics before launch;
- project persisted CommandRun status rather than browser-local loading state;
- keep Config editing/fork workflows separate from command execution.

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
- V3-2A establishes the shared identity-keyed query-provider contract; the current implementation remains an equivalent typed cache/de-duplication layer behind that boundary.
- Editable JSON-Schema forms remain deferred until explicit Config mutation/fork authority is implemented; V3-2C control execution does not imply in-place protocol editing.
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
→ typed application services
→ durable command audit
→ explicit governed Control Plane
→ interactive presentation
→ human-governed one-shot evidence
→ promotion/PAPER after explicit gates
→ realtime only after internal operational semantics stabilize
```
