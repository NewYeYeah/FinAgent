# Changelog

This file records **meaningful completed milestones**, not per-PR implementation detail. Git commits and pull requests are the detailed audit trail; frozen product interpretation belongs in `docs/releases/`.

## 2026-09-01 — MT5 read-only broker capability closure (MT5-P0)

- accepted real MetaQuotes-Demo read-only capability assessment `mt5-p0-assessment-31cbb83d554010e791698384` over probe `mt5-capability-probe-db652a528408fda2dd3a606e`, with `accepted=true` and no blockers;
- measured 12,455 broker symbols, including 11,517 currently tradable symbols, and preserved MSFT/NVDA/AMD/INTC as the first representative engineering seed without granting any order or position mutation authority;
- corrected tick-history evidence semantics so one bounded capability probe is anchored to actually observed M1 activity instead of assuming exchange-clock availability for every representative symbol;
- established that the MSFT M1-anchored 60-bar probe window returned no historical ticks and retained this as `history:MSFT:tick_history_unavailable_in_observed_m1_window`, rather than fabricating tick support or treating a measured broker limitation as an adapter failure;
- retained `terminal:automated_trading_not_allowed` as a downstream Demo/PAPER limitation while keeping MT5-P0 valid as a read-only measurement stage;
- advanced the current stage to US-I0, where research and broker identities must be mapped explicitly before the engineering universe is frozen.

## 2026-09-01 — U.S. intraday core-contract closure (US-C0)

- froze provider-neutral `TradingCalendarEvidence`, `LabelSpec`, `CorporateActionEvent`, bounded/lazy `MarketDataQuery` / `MarketDataView`, and FinAgent-only `AdapterCapabilities` before the minute Data Plane is allowed to invent source-specific semantics;
- materialized the exact XNYS research schedule with `exchange_calendars==4.13.2` for the requested 1992-01-01 → 2026-03-31 interval, yielding 8,622 sessions with coverage 1992-01-02 → 2026-03-31 and 75 half-day sessions;
- accepted calendar evidence `trading-calendar-03a9c29f566d6634aedbbbdc` and materialization report `calendar-materialization-9cf62f5d9925477884cf9a56` after coverage, 2025 Independence Day, 2025 post-Thanksgiving half-day and 2026 DST anchors all passed;
- retained the research calendar as content-addressed evidence rather than trusting a mutable library name, and kept research market-event semantics separate from account-mutating corporate-action processing;
- advanced the current development stage to read-only `MT5-P0`; no order, position, account mutation, PAPER or live-capital authority was introduced.

## 2026-09-01 — U.S. minute source/local admission closure (US-S0)

- bound `mito0o852/OHLCV-1m` to immutable revision `776328445b7ac6e7815ef3a483e9c8ded1eb6d56` while retaining public-source authority as `REFERENCE_ONLY` and the local scope as `local_non_redistributed_research`;
- inventoried the complete 1992-01 → 2026-03 local snapshot with no missing monthly partition and preserved inventory identity `us-minute-inventory-c2cbf682b456f97eb613ed65`;
- replaced zero-defect gating with identity-bound deterministic cleaning: sparse invalid OHLC rows are quarantined, exact duplicates collapse, and ambiguous duplicate `(ticker,timestamp)` groups are removed wholesale rather than assigned an arbitrary winner;
- diagnosed the 2026-03 conflict cluster as 392 ambiguous keys / 799 raw rows across 333 tickers and froze a maximum conflicting raw-row rate of `5e-5`;
- accepted real local v3 certification `us-minute-certification-8e585c22fef175a2a4ce58ed` with `post_clean_conflicting_duplicate_key_count=0` and local admission `us-minute-local-admission-f9634ce117862410d2d00135`;
- retained explicit limitations for unresolved public usage rights, publisher-declared upstream origin, session coverage, raw/split-unadjusted prices, missing embedded corporate actions and absent PIT security-master/lifecycle evidence;
- advanced the current development stage to `US-C0` without implying Alpha, portfolio, PAPER, broker-mutation or live-capital acceptance.

## 2026-09-01 — Reproducible development baseline (ENG-0)

- fixed the canonical Python developer baseline at 3.11 via `.python-version`, pinned uv 0.12.1 as the sole resolver, and committed `uv.lock` as the resolved Python environment authority while retaining `pyproject.toml` as dependency intent;
- fixed the frontend developer/CI baseline at Node 22 via `.nvmrc` and retained `workspace/package-lock.json` as the npm resolution authority;
- replaced the one-shot lock bootstrap with a permanent Ubuntu + Windows reproducibility gate covering `uv lock --check`, frozen environment sync, dependency consistency, Windows `npm ci`, frontend typecheck, unit tests and production build;
- retained Python 3.12/3.13 as compatibility coverage rather than competing environment authorities;
- kept the official MT5 SDK, broker capability evidence and all mutation authority outside ENG-0, and advanced the current development stage to `US-S0`.

## 2026-09-01 — Historical v1.0 release closure (H0)

- received and recorded a real local HW-1.0-RS acceptance with `accepted=true`, browser `passed`, `contract_valid=true` and reserve non-consumption;
- bound the accepted release summary to freeze identity `ashare-historical-v1-76ba98983c1ffc6efb4b0f9a16acd5192eb7dd6c` and smoke identity `historical-workbench-rs-7ad4e7bdfa86b3551da62c6691934933bc312c73`;
- retained the reviewed `NO_ROBUST_FACTOR_FAMILY` outcome without fabricating strategy/portfolio evidence;
- closed A-share Historical v1.0 and advanced the current development stage to `ENG-0`;
- registered `finagent-ashare-historical-v1.0` as the release tag over the pre-ENG-0 closure baseline.

## 2026-09-01 — Documentation authority reset (DOC-0)

- replaced multiple versioned current plans/roadmaps with one stable `docs/development/current-plan.md`;
- made `docs/status.toml` the only current-stage authority;
- consolidated active architecture/testing/guides around current truth rather than phase chronology;
- consolidated A-C4/A-C5/HW historical-release instructions into the A-share Historical v1.0 release record;
- removed stage-specific changelog/completion/API-contract documents from the active tree; their detailed history remains in Git/PRs;
- added documentation-governance checks, CI and PR template documentation-impact rules;
- added a repository-native onboarding/documentation skill for new humans and Agents.

## 2026-08-31 — A-share Historical v1.0 freeze and post-freeze hardening

- completed real A-share historical end-to-end acceptance and initial-requirement compliance auditing;
- froze A-share Historical v1.0 with exact Git/data/evidence/dependency identities and explicit deferred capabilities;
- accepted a reviewed `NO_ROBUST_FACTOR_FAMILY` terminal without fabricating a strategy, MarketBarSeries or portfolio result;
- added Historical Workbench 1.0 post-freeze release-smoke infrastructure over exact frozen local evidence;
- hardened Windows UTF-8 subprocess capture, protected-product dirty-worktree checks and browser failure diagnostics;
- fixed test-only Workbench acceptance regressions while keeping test files outside the frozen runnable-product denominator;
- retained production reserve non-consumption and no PAPER/broker/live-capital implication.

## 2026-08-31 — A-C1 through A-C5 historical closure

- extracted historical development/A2.6/A4 orchestration into typed L1 application workflows with durable CommandRun audit;
- introduced provider-neutral `MarketBarSeriesEvidence`, interval/timestamp/session contracts and authoritative Strategy OHLC binding;
- certified one real A-share historical chain through data → research → A2.6 → A4 → Strategy/Factor/MarketBar evidence → Workbench/review bundle;
- audited original requirements as PASS/PARTIAL/DEFERRED/N/A and closed release-blocking partials under the frozen policy;
- froze the historical product rather than consuming the independent one-shot production reserve merely to obtain a release badge.

## 2026-08-30 — V4 linked analytical evidence and Workbench

- delivered immutable StrategyDecisionSeries evidence for signal/target/order/fill/weight/PnL/cost paths;
- delivered immutable FactorSeries evidence for IC/RankIC, decay, quantile/long-short, turnover/coverage and explicit derived series;
- added Strategy Decision Explorer and Factor Tear Sheet backed by verified bounded evidence APIs;
- added linked Portfolio/Execution interactive analytics over A4 portfolio authority + V4 decision rows;
- accepted cross-module WorkbenchContext, server-side complete aggregation and `browser_recomputation=false` across Strategy/Factors/Portfolio/Execution.

## 2026-08-29 — Workbench foundation and A5 reserve governance

- evolved the read-only Workspace into a two-plane Workbench: GET-only Evidence + explicit local governed Control;
- added Agent Project → Thread → Run projections, URL-backed WorkbenchContext, typed configuration/command catalogs and L0/L1 application-service execution;
- added command audit/SSE/deep-link/replay contracts while forbidding generic shell/Python/broker authority;
- completed A5 eligibility sealing, one-shot reserve runner infrastructure, crash-safe pre-access `CONSUMED` semantics and read-only reserve evidence projections;
- kept actual production reserve execution separately human-governed.

## 2026-08-28 — Robust A-share research, execution and portfolio line

- delivered A2.6 immutable ResearchPrograms with expanding walk-forward, training-frozen direction, HAC/block-bootstrap/Holm/BH evidence and explicit no-alpha terminals;
- implemented A3 exact-session A-share execution semantics including T+1, board quantity, suspension/price-limit and fee rules;
- implemented A4 execution-aware portfolio validation with frozen-factor Alpha, risk/optimizer targets, gross/net ledgers, implementation-shortfall/cost evidence and exact replay;
- delivered read-only visualization/evidence/governance products over these immutable outputs.

## 2026-08-27 — Data correctness, Agent robustness and Factor Quant

- built DuckDB-backed local A-share Parquet ingestion with raw-execution vs adjustment-aware research-price separation;
- froze local dataset identity and independently versioned supplemental status/reference data;
- corrected suspension/common-session label semantics and split liquidity warm-up;
- added bounded Factor Quant, stability/inference/multiplicity diagnostics and deterministic ensemble validation;
- hardened LLM provider handling, generated-feature sandbox/repair/checkpointing and vendor-neutral audit/observability;
- added provider capability declarations and U.S. reference ingestion scaffolding.

## 2026-08-26 and earlier — Core baseline

- canonical PIT `DataAdapter → ResearchDataset` contracts and explicit `event_time` / `available_at` clocks;
- deterministic Alpha/Risk/Portfolio interfaces and event-driven historical execution;
- bounded Agent tools and generated-feature sandbox;
- experiment/program identity, structured evidence memory, sealed evaluation/holdout governance, model registry and human-approved operational handoff primitives;
- provider-neutral ingestion/replay/cross-provider evidence foundations.

## Documentation policy

The active documentation tree intentionally does not keep phase-by-phase DEVLOG/roadmap/current-plan copies. Update this file for meaningful completed milestones; use Git/PR history for exact implementation diffs and `docs/releases/` for frozen product records.
