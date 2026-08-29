# Changelog

This file summarizes meaningful development milestones. Commit and pull-request history remains the detailed audit trail.

## 2026-08-29 — Visualization V3-2C-1 Application Service Convergence

- added the typed `finagent.application` boundary with `ApplicationCommandInvocation`, `ApplicationCommandExecution` and an allowlisted `ApplicationServiceRegistry`;
- kept the service registry in-process and fail-closed with no arbitrary shell, subprocess or Python-text execution facility;
- corrected the local A-share certification command to use the actual `[local_ashare]` configuration contract;
- promoted only `config.validate`, `data.certify_local_ashare` and `review.export_bundle` to `application_service_ready`;
- retained development research, A2.6 and A4 as `adapter_required` until their fat CLI orchestration is actually extracted;
- refactored the local-data certification and review-bundle CLIs into thin adapters over shared application services;
- added startup verification that Command Catalog readiness exactly matches the registered service identities;
- kept the Evidence Plane GET-only with `control_plane_enabled=false` and added no command execution route.

## 2026-08-29 — Visualization V3-2B Config Registry + Command Catalog

- froze typed `ConfigDescriptor`, `ConfigSnapshot`, `ConfigFieldSpec`, `ConfigDiff`, `CommandSpec`, `CommandIntent`, `CommandRun` and `CommandResult` contracts;
- added deterministic public-TOML projections with recursive secret redaction and secret-file exclusion;
- classified presentation/runtime/research/execution/guardrail/secret-reference fields with explicit mutation policies;
- added deterministic ConfigDiff identity semantics and protocol-fork requirements;
- added the read-only L0/L1 Command Catalog and explicit forbidden L2/L3 authority surface;
- exposed additive GET-only `/api/v3/config*`, `/api/v3/commands*` and Workbench status routes;
- added Configuration Registry and Command Catalog Workbench surfaces while retaining disabled execution affordances.

## 2026-08-29 — Visualization V3-2A Workbench Shell + Context Bus

- added the desktop-first FinAgent Workbench shell with registry-driven current/future modules while preserving existing V1/V2/A5 routes;
- added a typed URL-backed `WorkbenchContext` covering Agent, research, portfolio, strategy, reserve, asset/date/session/fold and environment identities;
- kept interaction events separate from deep-link identity and preserved linked context across top-level Workbench module navigation;
- added a `PanelRegistry`, chart-workspace/Inspector slots and explicitly disabled Config drawer/Command palette extension points for V3-2B/V3-2C;
- integrated the V3-1 Project → Thread → Run APIs into the primary Agent Workbench with persisted Activity and a Run Inspector;
- linked only Workspace-verified Agent artifact refs while leaving unknown audit strings unresolved and preserving the no-hidden-reasoning boundary;
- added an identity-keyed shared typed server-state query provider with cache, in-flight de-duplication, stale handling, refetch and invalidation support;
- retained legacy `/agent/:runId` compatibility through deterministic redirect into the new Workbench context URL;
- added Workbench context, React interaction and Playwright coverage while retaining GET-only Evidence Plane authority.

## 2026-08-29 — Visualization V3-1 Agent Index Contract

- added derived `AgentProjectProjection`, `AgentThreadProjection`, `AgentRunSummary` and verified `AgentArtifactRef` contracts over canonical Agent audit SQLite;
- added deterministic Project/Thread fallback identities without mutating the audit store;
- added fail-closed thread→project identity conflict detection and strict corrupted-audit handling;
- added a bulk read-only Agent projection path so the index reuses one SQLite connection rather than reopening one handle per run;
- added verified artifact resolution against Workspace evidence/factor identities while leaving unknown audit strings unresolved;
- added GET-only `/api/v3/agent/projects`, project, thread and run detail endpoints;
- retained Phoenix/OTLP as diagnostic-only input and did not construct product grouping identity from spans;
- added V3-1 contract/API coverage and Windows/Ubuntu Workspace CI gates.

## 2026-08-29 — Workspace compatibility and automatic parallel runtime

- isolated FinAgent pytest from the optional Phoenix pytest entry point so incompatible local observability installs cannot abort test collection;
- promoted supported local-data certification, local system-smoke and A3 execution-smoke artifacts into diagnostic catalog evidence instead of unsupported-schema warnings;
- separated harmless replay deduplication into catalog notices while retaining true malformed/identity-conflict warnings;
- added an automatic CPU/RAM-aware parallel worker budget with operational caps but no research-identity coupling;
- parallelized generated-feature sandbox batches without launching resource-limited `Popen` calls from worker threads;
- parallelized deterministic Workspace report/ledger ingestion and exposed runtime plans through health diagnostics.

## 2026-08-29 — Visualization V2 pre-reserve governance cockpit

- added a rebuildable derived SQLite Evidence Catalog over immutable evidence refs;
- added deterministic allowlisted A2.6/A4 protocol snapshots and configuration diffs that exclude outcomes;
- added Project lifecycle and Governance review surfaces with prominent reserve/promotion state;
- added A2.6 Gate Matrix, bootstrap/HAC/Holm/BH statistical forest evidence and fold heatmaps;
- added richer A4 portfolio/economic review and explicitly derived rolling review series;
- added digest-matched A4 JSONL execution lifecycle, reason/cost attribution and target-versus-realized projections;
- kept A3 protocol binding `derived` because no standalone authoritative A3 certification identity is persisted;
- added GET-only raw evidence inspection and human-review ZIP export with manifest/lineage/protocol diff/CSV/source artifacts;
- retained all no-mutation, no-hidden-reasoning, reserve-isolation and promotion boundaries.

## 2026-08-28 — Visualization V1 read-only Workspace

- added a GET-only FastAPI Evidence API over the V0 semantic contract;
- added an in-memory, disposable catalog for immutable A2/A2.5, A2.6 and A4 report artifacts;
- added a React/TypeScript/Vite Workspace with TanStack Table, ECharts and React Flow;
- added Project, Research, Portfolio, Factor, Agent and Widget catalog pages;
- added A2.6 factor/Gate/fold navigation and A4 gross/net NAV, derived drawdown, execution funnel and rejection/cost views;
- labelled browser-computed drawdown as derived rather than authoritative evidence;
- added canonical Agent audit timelines from read-only SQLite without Phoenix-schema coupling;
- added a cross-platform launcher, Python API tests, frontend unit/type/build tests and Playwright browser smoke;
- retained legacy Streamlit/Phoenix diagnostic paths and added no research, reserve, promotion or trading write authority.
