# Development Roadmap

This roadmap is intentionally short. The active detailed planning baseline is [`current-development-plan-v3.1.md`](current-development-plan-v3.1.md), with the supporting architecture in [`../architecture/workbench-v3.md`](../architecture/workbench-v3.md). Previous v3/v2 documents remain historical design and acceptance records.

## Current baseline

The implementation baseline has now completed the **Visualization V3-3 typed deep-link foundation** on top of PIT data contracts, bounded Agent research, A2.6 robust ResearchPrograms, A3 execution semantics, A4 execution-aware portfolio validation, Visualization V0/V1/V2, A5-1～A5-4 reserve governance/evidence, V3-1 Agent indexing and the V3-2 governed Workbench/Control foundation.

No production 2025+ reserve has been consumed by development or CI. Production reserve execution remains an independent human-authorized operation.

## Product direction

The product target is **FinAgent Workbench**:

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

Two authority planes are implemented as separate processes:

```text
Evidence Plane  :8765  → default / GET-only / immutable evidence projection
Control Plane   :8766  → explicit local opt-in / typed governed L0/L1 commands
```

The Control Plane does not weaken or add mutation routes to the Evidence Plane. Generic control authority explicitly excludes production reserve, strategy promotion, PAPER mutation, broker orders, live capital, arbitrary shell and arbitrary Python execution.

## Current priority order

### Completed — V3-1 Agent Index Contract

- deterministic `AgentProjectProjection` / `AgentThreadProjection` / `AgentRunSummary` / `AgentArtifactRef`;
- missing Project/Thread metadata receives deterministic derived fallback identity;
- conflicting thread/project bindings fail closed;
- verified artifact refs only;
- bulk read-only Agent projection through one SQLite connection;
- GET-only `/api/v3/agent/*` navigation API.

### Completed — V3-2A Workbench Shell + Context Bus

- desktop-first registry-driven Workbench shell;
- URL-backed `WorkbenchContextProvider` for Agent/research/portfolio/strategy/reserve/asset/date/session/fold/environment identities;
- deterministic URL round-trip and context-preserving cross-module navigation;
- linked-selection events remain presentation state rather than evidence identity;
- registry-driven panels, Inspector and chart-workspace extension slots;
- shared identity-keyed typed server-state cache/de-duplication boundary;
- existing V1/V2/A5 pages remain available.

### Completed — V3-2B Config Registry + Command Catalog

- froze `ConfigDescriptor`, `ConfigSnapshot`, `ConfigFieldSpec`, `ConfigDiff`, `CommandSpec`, `CommandIntent`, `CommandRun` and `CommandResult` vocabulary;
- added read-only allowlisted TOML projection with presentation/runtime/research/execution/guardrail/secret-reference domains;
- protocol changes require new identities; operational guardrail changes require governed change;
- excluded secret-like files before parsing and recursively redacted credential-looking values;
- added deterministic ConfigSnapshot identity and ConfigDiff projection;
- added the allowlisted L0/L1 command catalog and GET-only `/api/v3/config*` / `/api/v3/commands*` surfaces.

### Completed — V3-2C-1 Application Service Convergence

- added `finagent.application` with typed `ApplicationCommandInvocation`, `ApplicationCommandExecution` and fail-closed `ApplicationServiceRegistry`;
- no arbitrary shell/Python/subprocess fallback exists;
- corrected local A-share certification to its real `[local_ashare]` config contract;
- promoted exactly `config.validate`, `data.certify_local_ashare` and `review.export_bundle` to `application_service_ready`;
- refactored certification/review-export CLIs into adapters over shared in-process services;
- Evidence startup verifies catalog readiness against real service bindings;
- A2/A2.5, A2.6 and A4 deliberately remain `adapter_required` until their fat orchestration is separately extracted.

### Completed — V3-2C-2 Durable Command Store

Implemented `SQLiteCommandStore` as the canonical command lifecycle store:

```text
CommandIntent
    ↓
CommandRun
    ↓
CommandResult
    └── ordered CommandEvent audit
```

Properties:

- transactional SQLite persistence using `BEGIN IMMEDIATE`, WAL and `synchronous=FULL`;
- idempotent request-key replay with conflicting reuse rejected;
- strict `planned → running → succeeded/rejected/failed` transition validation;
- exact command/config/context/requester identity retained;
- persisted evidence/artifact/output references without changing core evidence authority;
- process restart converts incomplete `planned/running` work to visible terminal `failed` and never automatically retries it;
- command lifecycle contracts are application-owned; `finagent.visualization` re-exports them only for compatibility;
- no executable text is persisted as an instruction.

### Completed — V3-2C-3 Explicit Local Control API

Added an independently launched **local-only** Control Plane:

```text
python scripts/run_workbench_control.py
# 127.0.0.1:8766
```

The launcher refuses non-loopback hosts. The API:

- exposes GET status/catalog/run inspection plus POST CommandRun creation;
- uses `extra=forbid` typed request models and an exact WorkbenchContext allowlist;
- resolves exact `CommandSpec` + exact `application_service_ready` service binding;
- persists intent/run before background service execution;
- applies confirmation/config-descriptor checks;
- server-binds review-export report/output paths rather than accepting browser filesystem paths;
- records unknown catalog IDs and `adapter_required` requests as rejected audit records rather than attempting execution;
- has no L2/L3, A5 reserve, promotion, PAPER, broker or live-capital path.

Current executable generic commands are intentionally only:

```text
config.validate
data.certify_local_ashare
review.export_bundle
```

`research.run_development`, `research.run_a2p6` and `portfolio.run_a4` remain visible catalog entries but **not executable** until each receives a reviewed typed application-service extraction. V3-2 completion therefore means the governed control substrate is complete, not that unfinished research orchestration has been granted remote authority.

### Completed — V3-2C-4 Command Palette / Run Inspector

- the top-bar Commands slot activates only when the separate local Control Plane is reachable;
- there is no fallback execution path when Control is unavailable;
- the Palette shows complete catalog readiness, ConfigSnapshot binding, WorkbenchContext, confirmation semantics and produced evidence types;
- `adapter_required` commands remain visible but disabled;
- CommandRun state is read from durable Control Plane persistence and polled until V3-4 replaces polling with product SSE;
- Run Inspector shows ordered lifecycle events, result, evidence IDs and artifact paths;
- configuration editing remains separate/read-only; V3-2 command execution does not imply in-place protocol editing.

### Completed — V3-3 Evidence / Artifact / Config Deep Link

- introduced a common typed `WorkbenchReference` vocabulary across Evidence, Artifact, Factor, ResearchProgram, A4, A5, AgentRun, ConfigSnapshot/ConfigDiff and CommandRun identities;
- canonical root evidence wins over duplicate external references; ambiguous non-root identities fail closed;
- Agent ↔ Factor ↔ ResearchProgram ↔ A4 navigation is verified from configured evidence rather than inferred from URL strings;
- A5 links are exposed only when the authoritative reserve lifecycle stores resolve the target;
- ConfigSnapshot ↔ ConfigDiff and ConfigSnapshot ↔ CommandRun relations are available through typed refs;
- CommandRun ↔ produced Evidence uses a read-only SQLite projection over the durable command store;
- generated-feature artifacts are metadata-only verified identities and source-report preview is bounded to configured report roots and a server-side size limit;
- browser-supplied host paths are never accepted by the Artifact Inspector;
- all V3-3 Evidence Plane endpoints remain GET-only;
- Phoenix/OTLP remains low-level diagnostic only and hidden reasoning is not persisted or projected.

### Current — V3-4 Agent + CommandRun SSE

Stable product projections only:

```text
AgentActiveRunProjection / CommandRunProjection
→ SSE
→ Workbench
```

V3-4 will stream only normalized product snapshots/events derived from canonical Agent audit and durable CommandRun state. It will not expose raw provider callbacks, raw OTLP/Phoenix spans, prompt payloads or hidden reasoning.

### P1 — V3-5 Workbench Foundation Acceptance

- context/deep-link identity tests;
- Evidence Plane remains GET-only;
- Control Plane authority/adversarial tests;
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

- **Apache ECharts** remains the main analytical chart engine.
- **React Flow** remains the lineage/DAG renderer.
- **TanStack Table** remains the structured-table foundation.
- the current typed query-provider abstraction remains the server-state boundary; TanStack Query can replace the internal implementation later without changing consumers.
- editable JSON-Schema forms remain deferred until explicit Config fork/mutation authority exists.
- **TradingView Lightweight Charts** is planned for V4-2 candlestick/volume/order-marker views.
- **FINOS Perspective** remains deferred until A6/QMT profiling proves a large/streaming-table need.
- Alphalens/QuantStats remain visual/regression references, never alternate authoritative calculation paths.

## OPS — Production Reserve Execution

Still not a feature PR or CI task. A5 one-shot semantics remain unchanged:

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

Only during A6 may Workbench integrate L2 governed operations. Those controls must call existing approval/PAPER/safety/reconciliation services rather than reimplementing authority.

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

Continue CPU/RAM-aware worker budgeting for independent deterministic backend work. Large visualization series should use columnar storage and bounded date/asset APIs; worker count, caching or rendering downsampling must never alter evidence identity or authoritative aggregates.

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
→ deep links / SSE
→ human-governed one-shot evidence
→ promotion/PAPER after explicit gates
→ realtime only after internal operational semantics stabilize
```
