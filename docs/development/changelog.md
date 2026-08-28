# Changelog

This file summarizes meaningful development milestones. Commit and pull-request history remains the detailed audit trail.

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

## 2026-08-28 — Visualization V0 semantic contract

- added canonical `EvidenceRef`, `EvidenceBundle`, factor, fold, portfolio, execution and lineage contracts;
- added fail-closed A2/A2.5, A2.6 and A4 semantic adapters;
- made authoritative, derived and diagnostic evidence explicit;
- added acyclic lineage validation over immutable evidence identities;
- added canonical `AgentRunProjection` from read-only Agent audit SQLite;
- added the first `FinWidgetSpec` catalog defined by product questions and evidence authority;
- froze the no-hidden-reasoning and no-UI-mutation architecture boundary.

## 2026-08-28 — A4 execution-aware portfolio validation

- added a feature-only A-share inference adapter that reads no forward-label rows and keeps the 2025+ reserve untouched;
- added exact-session close marks for end-of-day account valuation without stale-session fallback;
- added a panel-native frozen-factor AlphaModel that preserves A2.6 weights/directions and calibrates on each fold training range only;
- connected historical OAS risk, mean-variance targets and A3 target-to-executable-order rules;
- added synchronized gross and net ledgers to separate explicit fee/slippage drag from T+1, lot, suspension, limit and cash constraints;
- added NAV, return, Sharpe, drawdown, turnover, implementation-shortfall, order-reason and ex-post participation evidence;
- added fold consistency, HAC, circular block bootstrap and a preregistered internal economic gate;
- added immutable A4 specifications, an explicit no-robust-factor path, deterministic JSONL execution ledgers and exact replay;
- kept A4 internal-only, reserve-untouched and promotion-ineligible.

## 2026-08-28 — A3 A-share execution semantics

- added an exact-session local daily execution adapter that never falls back to stale earlier quotes;
- added explicit tradable, suspended, missing, invalid-price and price-limit-unavailable states;
- added side-specific buy-at-limit-up and sell-at-limit-down rejection using vendor limits;
- added target → desired order → executable order compilation with deterministic identities and reason codes;
- added board-aware buy lots, STAR minimum quantity and odd-lot sell handling;
- added immutable T+1 total/sellable/unsettled inventory accounting;
- separated broker commission, minimum commission, sell-side stamp duty, transfer fee and optional exchange/regulatory fees;
- added deterministic exact-open fills, fee-aware cash scaling, local historical smoke, Windows/Ubuntu tests and an A3 guide;
- kept A3 outside factor reserve, promotion, PAPER, realtime and live-capital claims.

## 2026-08-28 — A2.6 robust ResearchProgram

- added immutable A-share ResearchProgram specifications and SQLite identity storage;
- added annual expanding walk-forward folds with training-frozen factor direction;
- added pooled internal-OOS RankIC/ICIR, fold minima, HAC, block bootstrap and Holm/BH diagnostics;
- added preregistered hard candidate gates and a valid `NO_ROBUST_FACTOR_FOUND` result;
- added deterministic robust factor-family selection and Agent feedback v3;
- integrated existing program budget/lifecycle controls and exact replay;
- kept the 2025+ reserve untouched and the result promotion-ineligible before A3/A4.

## 2026-08-27 — Read-only research visualization

- added a Streamlit/Plotly Research UI for A2/A2.5 reports;
- added development-versus-validation, rolling/subperiod RankIC, quantile, correlation, ensemble and universe-policy views;
- added Agent discovery-round, JSONL span, LLM usage, repair/error and Phoenix navigation views;
- added read-only generated-feature SQLite inspection for accepted Python source and validation metadata;
- enforced report-denominator alignment before rendering and kept reserve/promotion governance visible;
- kept every UI page read-only: no LLM calls, reruns, prompt edits, model promotion or research-state mutation;
- added a dedicated visualization dependency extra, launcher, tests, guide and CI workflow.

## 2026-08-27 — A2.5 research correctness and stability

- added split-independent liquidity warm-up to remove artificial zero-eligible split starts;
- separated workflow completion from the factor research verdict;
- changed validation comparisons to development-frozen direction and signed deltas;
- added rolling/yearly RankIC stability, HAC inference, deterministic block bootstrap and family-wise Holm/BH adjustments;
- kept the A-share ensemble ineligible for promotion until execution semantics are certified.

## 2026-08-27 — Agent generation robustness and observability

- hardened DeepSeek/OpenAI-compatible calls with termination telemetry and bounded provider retries;
- aligned the generated-feature prompt with the actual restricted Python sandbox ABI;
- added bounded JSON/AST/sandbox candidate self-repair and bounded replacement;
- added scoped SQLite checkpoints so accepted logical candidate slots survive process restart without another LLM call;
- preserved hidden-reasoning privacy while recording reasoning-token counts, latency and finish status;
- added vendor-neutral JSONL/OTLP Agent traces and a lightweight Phoenix visualization path without coupling FinAgent to an Agent framework.

## 2026-08-27 — A2 bounded A-share factor research

- added a fixed pre-development candidate-universe selector for bounded 100–200 stock studies;
- added a PIT research-universe policy for listing age, ST state, price and rolling liquidity;
- added panel-native generated-feature materialization to avoid per-asset/session DuckDB queries;
- added deterministic baseline and multi-round Agent Factor Quant discovery modes;
- froze ensemble weights and factor directions on development evidence only;
- added independent factor-level validation, untouched reserve records and exact replay;
- kept A-share execution, promotion, holdout, PAPER and realtime outside the A2 acceptance claim.

## 2026-08-27 — A-share suspension/session semantics

- verified five zero-open/high/low daily anomalies as real suspension/no-trade placeholders rather than corrupted market prices;
- classified the strict vendor pattern `open=high=low=0, close=pre_close>0, vol=amount=0` as non-tradable while keeping all other invalid OHLC fail-closed;
- excluded suspension placeholders from `PriceBar` construction without modifying the frozen vendor source;
- changed A-share forward-return labels to a common panel-session clock so one-session labels cannot silently stretch across suspensions;
- kept legacy vendor identifiers quarantined rather than mapping them to modern securities.

## 2026-08-27 — A-share dataset freeze and supplemental reference layer

- added content-addressed/metadata frozen manifests for local A-share vendor data;
- added independently versioned supplemental delisting/ST/suspension files and source registry;
- kept supplemental status data separate from immutable vendor Parquet;
- added a historical-only local A-share system smoke through the canonical `ResearchDataset` interface;
- documented Yahoo Finance as a secondary/reference option rather than replacing Alpaca SIP.

## 2026-08-27 — Documentation consolidation

- replaced phase/version document sprawl with `guides/`, `testing/`, `architecture/` and `development/`;
- condensed active decisions, roadmap, changelog and risk register;
- rewrote README for the current A-share historical-research-first baseline.

## 2026-08-27 — Local A-share data track

- added DuckDB-backed local A-share Parquet data layer;
- normalized daily and minute unit semantics;
- separated raw execution prices from adjustment-aware research returns;
- certified the observed 241-row 1-minute convention;
- added candidate security-master semantics and explicit survivorship limitations;
- added data certification CLI and Windows CI.

## 2026-08-27 — Agent × Factor Quant research core

- added development-only factor diagnostics and cumulative Agent feedback;
- added IC/RankIC, IC decay, quantile portfolio, turnover and redundancy diagnostics;
- added deterministic multi-factor ensemble selection;
- validated ensemble as a real AlphaModel against the full single-factor denominator.

## 2026-08-26 — Research governance hardening

- added immutable research program/family lifecycle;
- filtered Agent-visible evidence scopes;
- added atomic scoped result writes;
- added preregistered sealed-holdout contracts and one-shot evaluator;
- connected deterministic research promotion to model registry;
- added explicit human-approved `VALIDATED → PAPER` handoff.

## Earlier baseline

- canonical PIT `DataAdapter → ResearchDataset` interfaces;
- deterministic alpha, GARCH/OAS/PCA risk and portfolio optimizers;
- event-driven historical execution and transaction costs;
- bounded Agent tooling, LLM provider adapters and generated-feature sandbox;
- paper/shadow broker, reconciliation, approval and kill-switch primitives;
- provider-neutral real-market ingestion and deterministic replay/cross-provider evidence.

## Documentation policy

Stage-specific PHASE/DEVLOG/release notes were removed from the active `docs/` tree in favor of this condensed changelog, the current roadmap and architecture decision summary. Historical documents remain recoverable through Git history.
