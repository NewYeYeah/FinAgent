# Development Roadmap

This roadmap is the canonical current implementation status. [`current-development-plan-v3.1.md`](current-development-plan-v3.1.md) is the frozen architectural planning baseline that established the V3 staging, with supporting architecture in [`../architecture/workbench-v3.md`](../architecture/workbench-v3.md). Previous v3/v2 documents remain historical design and acceptance records.

## Current baseline

The implementation baseline has now completed the **Visualization V3 Workbench Foundation through V3-5 acceptance** and the first four V4 linked-analytics stages: **V4-0 StrategyDecisionSeriesEvidence**, **V4-1 FactorSeriesEvidence**, **V4-2 Strategy Decision Explorer** and **V4-3 Factor Tear Sheet**, on top of PIT data contracts, bounded Agent research, A2.6 robust ResearchPrograms, A3 execution semantics, A4 execution-aware portfolio validation, Visualization V0/V1/V2 and A5-1～A5-4 reserve governance/evidence.

The accepted V3 foundation includes Agent indexing, the governed Workbench/Control substrate, typed deep links and sanitized product SSE. V4-0 adds immutable authoritative per-asset strategy-decision series without changing A4 report/ledger identity. V4-1 adds immutable factor-period IC/quantile/long-short/turnover/coverage evidence while keeping the frozen A2.6 report unchanged and explicitly labeling rolling IC/NAV transforms as derived. V4-2 activates the linked Strategy Workbench over verified V4-0 rows with bounded GET-only APIs and explicit no-fabrication boundaries for missing OHLC and per-factor contribution evidence. V4-3 activates the Factors Workbench over verified V4-1 period rows plus frozen A2.6 inference/multiplicity/correlation summaries, while keeping fold/year aggregation and cluster ordering explicitly presentation-derived and refusing to invent an Agent generation chronology. Detailed records are in [`changelog-v3-5.md`](changelog-v3-5.md), [`changelog-v4-0.md`](changelog-v4-0.md), [`changelog-v4-1.md`](changelog-v4-1.md), [`changelog-v4-2.md`](changelog-v4-2.md) and [`changelog-v4-3.md`](changelog-v4-3.md).

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
- V3-4 replaces the initial active-CommandRun lifecycle polling with Evidence Plane SSE while retaining the full durable Control record as the detail authority;
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

### Completed — V3-4 Agent + CommandRun SSE

- added normalized `AgentActiveRunProjection` and `CommandRunStreamProjection` contracts over canonical Agent audit and durable CommandRun state;
- SSE event IDs are deterministic digests of normalized product projections; unchanged state retains one event identity and reconnect can suppress it with `Last-Event-ID`;
- Agent Workbench uses SSE as a change signal and refreshes the canonical V3 Agent run projection rather than treating the transport as a second evidence authority;
- Command Palette no longer performs 600 ms active-CommandRun lifecycle polling; SSE change notifications trigger explicit full Control API record refresh;
- if SSE is unavailable, there is no hidden timed-poll fallback and the user retains an explicit `Refresh run` action;
- streams exclude prompt/provider payloads, token/reasoning data, raw OTLP/Phoenix spans, CommandRun parameters/outputs/artifact paths/free-form messages and host filesystem paths;
- heartbeat comments keep idle HTTP connections alive without fabricating product events;
- blocking audit/SQLite reads run outside the async event loop;
- Workspace retains the configured read-only command-store path even before the Control Plane creates the SQLite file, allowing SSE to become available without an Evidence Plane restart;
- all V3-4 stream endpoints remain GET-only and add no Control Plane authority.

### Completed — V3-5 Workbench Foundation Acceptance

- added a single cross-plane backend acceptance gate covering complete route inventories, Evidence GET-only enforcement and the exact bounded Control POST surface;
- verified that reserve, promotion, PAPER, broker, live, shell and Python command identities fail closed and persist only rejected audit records;
- verified a real durable `config.validate` CommandRun is observed through the separate Evidence Plane with the same ConfigSnapshot/WorkbenchContext identity and no Evidence-side SQLite mutation;
- covered SSE `Last-Event-ID` suppression, disconnect, disappearing sources, sanitized terminal payloads and native EventSource terminal shutdown;
- covered context-preserving module navigation plus browser back/forward/reload restoration;
- covered Evidence-only and both-plane browser modes with no fallback execution path and no L2/L3/A5 controls;
- retained Ubuntu/Windows Workspace API, repository Python 3.11/3.12/3.13 and Windows pytest, ruff/mypy, TypeScript/Vitest/build/Playwright, A2.6 and legacy Research UI gates;
- recorded the final acceptance matrix in [`changelog-v3-5.md`](changelog-v3-5.md).

## Current — V4 Linked Quant Analytics

### Completed — V4-0 StrategyDecisionSeriesEvidence

- added immutable per-asset `StrategyDecisionRow` evidence for the full historical path `signal → target → desired order → executable order → fill → realized close weight → gross/net PnL/cost`;
- kept the existing A4 report and JSONL execution-ledger contracts unchanged; V4-0 materializes a separate evidence layer and verifies the source A4 ledger against its frozen `ledger_digest`;
- replays only the exact frozen A4 AlphaModel at the original formation timestamp, rebuilding train-only calibration per fold and requiring the rebuilt artifact digest to equal the A4 `alpha_model_id`;
- reconstructs deterministic weighted/directed alpha score and rank without requesting forward labels at prediction time, and leaves historical cash/model-error fallback sessions without invented alpha evidence;
- reconciles asset-level gross/net wealth contributions to the authoritative A4 gross/net NAV change for every source session;
- writes `finagent.strategy-decision-series.manifest.v1` plus ZSTD Parquet long-form data with deterministic row ordering and content-addressed row/series identity;
- binds the manifest to A4 validation/spec, A2.6 program/spec/source-report/selection, selected factor digests, fold alpha-model IDs, data version, execution-ledger digest, row digest and physical source/data SHA-256 values;
- added a fail-closed `StrategyDecisionSeriesProjection` with verified immutable source bindings and bounded asset/fold/date queries (`limit <= 5000`);
- added a dedicated `v4-series` Ruff/mypy/dependency + Ubuntu/Windows focused gate and end-to-end acceptance through the existing synthetic A4 workflow;
- recorded the evidence/alpha/PnL/storage contract in [`changelog-v4-0.md`](changelog-v4-0.md).

### Completed — V4-1 FactorSeriesEvidence

- added immutable long-form `FactorSeriesRow` evidence over the complete frozen A2.6 candidate denominator and internal walk-forward test folds;
- persisted primary/decay-horizon raw and train-direction-oriented Pearson IC/RankIC, primary-label quantile returns, oriented long-short returns, one-way turnover and factor coverage as authoritative period evidence;
- persisted rolling IC and cumulative quantile/long-short NAV as explicit deterministic `derived` rows instead of relabeling them as raw evidence;
- rebuilt candidate universe, universe-policy identity, generated-feature artifact identity and FactorQuant settings from the frozen A2.6 report rather than mutable current research settings;
- reused the frozen training-only `train_direction` for each factor/fold; test data never chooses or flips factor sign;
- added mandatory reconciliation back to frozen A2.6 fold and candidate diagnostics before any manifest/Parquet write, including RankIC/ICIR, long-short Sharpe, coverage, monotonicity, turnover, direction and horizon-sign checks;
- writes `finagent.factor-series.manifest.v1` plus ZSTD Parquet with deterministic long-form ordering and content-addressed row/series identity;
- binds the manifest to A2.6 program/spec/walk-forward/gate/selection/plan/data/universe-policy/candidate-denominator identities, frozen quant settings, row digest, source-report content digest and physical source/data SHA-256 values;
- added fail-closed `FactorSeriesProjection` verification and bounded factor/fold/date/kind/metric/horizon/quantile queries (`limit <= 5000`);
- added dedicated `v4-factor-series` Ruff/mypy/import/dependency + Ubuntu/Windows focused acceptance while retaining the existing A2.6 and repository-wide gates;
- recorded the evidence/reconciliation/storage contract in [`changelog-v4-1.md`](changelog-v4-1.md).

### Completed — V4-2 Strategy Decision Explorer

- added a verified `StrategyDecisionExplorerProjection` that discovers V4-0 manifests under configured report roots and exposes a series only after the existing A4 report/ledger/Parquet identity, SHA, schema and row checks pass;
- added GET-only `/api/v4/strategy-series*` catalog, portfolio lookup, detail, dimensions and bounded decision routes; browser requests contain semantic filters only and retain `limit <= 5000`;
- activated the Strategy module in the V3 Workbench and bound `portfolio_validation_id`, `asset_id`, `date_range`, `session_date` and `fold_id` through the existing URL-backed `WorkbenchContext`;
- rendered the authoritative close/reference/fill execution timeline, buy/sell fill markers, pre-trade/target/realized weights, combined frozen AlphaModel context, A3 quantities/constraint codes and per-session gross/net PnL/fees/slippage directly from V4-0 rows;
- kept React presentation-only: no target, alpha, execution, cumulative portfolio PnL or replacement financial evidence is recalculated in the browser;
- explicitly reports `ohlc_available=false`: V4-0 has no authoritative open/high/low evidence, so V4-2 does not fabricate candlesticks from close marks;
- explicitly avoids per-factor contribution inference because V4-0 persists combined alpha plus factor identities, not per-asset component contributions;
- de-duplicates semantically equivalent deterministic rematerializations even if their physical output filenames differ, while conflicting `series_id` semantics fail closed;
- missing optional DuckDB/local-Parquet support degrades V4-2 to an explicit catalog warning rather than breaking unrelated Workspace surfaces;
- added Ubuntu/Windows Workspace API, Ruff/mypy, TypeScript/Vitest/build/Playwright and repository/A2.6/A5/V4/legacy-UI regression coverage;
- recorded the delivered contract in [`changelog-v4-2.md`](changelog-v4-2.md) and [`v4-2-api-contract.md`](v4-2-api-contract.md).

### Completed — V4-3 Factor Tear Sheet

- added verified `FactorTearSheetProjection` discovery over immutable V4-1 `FactorSeriesEvidence`; each package is exposed only after the existing source-report, manifest, Parquet, sequence, row-id and rows-digest checks pass;
- added GET-only `/api/v4/factor-series*` catalog, program lookup, detail, dimensions, summary, correlations, heatmap, provenance and bounded row routes;
- retained the V4-1 row authority classes and hard query bound `limit <= 5000`, with semantic filters only and no host-path/executable browser input;
- activated `/factors` and `/factors/{series_id}` in the Workbench and linked `program_id`, `factor_id`, `fold_id` and `date_range` through `WorkbenchContext`;
- rendered authoritative IC/RankIC, turnover and coverage together with persisted derived rolling IC and quantile/long-short NAV without recomputing those statistics in React;
- sourced pooled/fold metrics, HAC, block-bootstrap CI/p-value, Holm/BH adjustments, gate state, selected-component state and factor correlations directly from the frozen A2.6 report;
- labeled fold/year IC means and hierarchical factor-correlation ordering as deterministic `derived_presentation` projections rather than raw evidence;
- exposed frozen candidate identity/hypothesis/generator/lookback provenance while explicitly reporting `agent_chronology_available=false`; A2.6 candidate denominator order is not presented as a generation timeline;
- retained Ubuntu Workspace API, Ruff/mypy, TypeScript/Vitest/build/Playwright, repository Python, A2.6 and legacy Research UI regression gates, while preserving the existing Windows CI path for asynchronous/manual acceptance;
- recorded the authority, API, non-fabrication and Windows acceptance contract in [`changelog-v4-3.md`](changelog-v4-3.md).

### Current — V4-4 Portfolio / Execution Interactive Pack

Use existing V2 evidence plus V4-0 strategy-decision evidence and any newly required immutable benchmark/portfolio series for:

- linked NAV / drawdown / rolling performance;
- monthly return matrix;
- target vs realized portfolio state;
- order lifecycle and A3 constraint attribution;
- explicit fee/slippage/cost waterfall;
- asset/date/order/session interactions through `WorkbenchContext`;
- clear authoritative/derived/diagnostic labels on every analytical surface.

V4-4 must not reconstruct authoritative portfolio/execution facts in React and must not infer benchmark, exposure or cost evidence that the core has not formally persisted.

### P1 — V4-5 Linked Analytics Acceptance

Every chart must declare evidence requirements and authority class, and all asset/date/order interactions must flow through `WorkbenchContext`.

## Open-source implementation choices

- **Apache ECharts** remains the main analytical chart engine and powers the delivered V4-2 Strategy and V4-3 Factor analytical views.
- **React Flow** remains the lineage/DAG renderer.
- **TanStack Table** remains the structured-table foundation.
- the current typed query-provider abstraction remains the server-state boundary; TanStack Query can replace the internal implementation later without changing consumers.
- editable JSON-Schema forms remain deferred until explicit Config fork/mutation authority exists.
- **TradingView Lightweight Charts** remains deferred until a separately frozen authoritative OHLC evidence contract exists; V4-2 deliberately does not synthesize candlesticks from close data.
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
→ foundation acceptance
→ authoritative linked-series evidence
→ linked analytical charts
→ human-governed one-shot evidence
→ promotion/PAPER after explicit gates
→ realtime only after internal operational semantics stabilize
```
