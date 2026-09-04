# Changelog

This file records **meaningful completed milestones**, not per-PR implementation detail. Git commits and pull requests are the detailed audit trail; frozen product interpretation belongs in `docs/releases/`.

## 2026-09-05 — US-R2 denominator-preserving multi-regime Alpha Gate closure

- completed the frozen 37-candidate denominator across five non-overlapping evaluation folds, four ex-ante IWM direction/volatility regimes and 21 annual partitions from 2006 through 2026 without candidate filtering, direction refit or new Agent candidates;
- replaced the candidate-robustness runtime's annual DuckDB temp-table/four-slice `fetchall` path with a bounded ordered scan, one-slice-at-a-time reduction and at most one live feature matrix, retaining immutable 2006–2014 evidence and resuming through 2026 under a 512MB DuckDB limit;
- added flushed year/slice/asset progress and structured failure records, then proved all 21 annual candidate-metric pairs replay with zero Parquet scans, zero feature evaluations and unchanged report `us-r2-candidate-robustness-9b8a0b575e20e31e6adc9ddf`;
- observed 16 candidates passing the per-regime frequency/decay robustness sub-gate, while no candidate passed the complete inherited R1 Alpha Gate; all numeric thresholds remained unchanged and the full 37-candidate multiplicity denominator was preserved;
- accepted independent review `us-r2-alpha-gate-review-36d4d07f8dd0b3dbf70656de` and reviewed manifest `us-r2-reviewed-evidence-b9c139214723c54e250d7ab6` with terminal `NO_ROBUST_FACTOR_FAMILY`, zero final robust candidates and no technical blockers;
- closed US-R2 without Alpha, US-X0 progression, execution, order, PAPER or live-capital authority; the current-symbol universe remains survivorship conditioned and no PIT market-Alpha claim is made.

## 2026-09-04 — US-R1 robust intraday Alpha Gate closure

- executed the complete 37-candidate R1 denominator across three purged/embargoed folds and all six frozen slices per fold, with no materialization or final technical blocker;
- replaced the initial same-bar-count frequency rule after its preserved `SYSTEM_FAILURE` showed that it changed economic lookback and made long-window 30m candidates structurally unevaluable; v2 preserves the A0 15m endpoint span via a deterministic elapsed-time conversion while retaining the candidate denominator, folds, minimum periods, thresholds and multiplicity rules;
- admitted the known same-source EEM target-minute limitation through a bounded complete-case rule that omits the entire affected formation for every candidate, never fills a price or reweights only the remaining assets, and records the omission count in slice evidence;
- fixed process-level evidence nondeterminism exposed by independent replay by canonically sorting turnover assets and using `math.fsum`; retained the non-replayable artifacts, added cross-hash-seed regression coverage and regenerated all downstream statistics from unchanged observations;
- canonicalized all R1 observation clocks to UTC after streaming/batch parity exposed equal instants serialized with host-dependent offsets; retained the prior artifacts and regenerated the complete three-fold evidence while preserving the exact numeric family/assessment identity;
- accepted review `us-r1-alpha-gate-review-eb56532850e3925100f43e43` and reviewed manifest `us-r1-reviewed-evidence-c01346b54fad55b0d181c0ed` with terminal `NO_ROBUST_FACTOR_FAMILY`, zero robust candidates and `alpha_gate_authority=true`;
- closed R1 without granting Alpha, US-X0 progression, execution, order or live-capital authority; the deployment branch stops and any continuation requires a newly preregistered research iteration.

## 2026-09-04 — Target-broker mapped candidate workflow implementation

- implemented a content-addressed, explicit one-to-one `RESEARCH=BROKER` candidate policy/report so target brokers with `.NAS`/`.NYS` suffixes can reuse the admitted historical ranking gates without inferring or stripping symbols;
- propagated mapped broker symbols through current-quote seed requirements and final EngineeringUniverse materialization while retaining the exact-match v1 candidate artifact and finalizer CLI alias for compatibility;
- hardened MT5-P0 acceptance against out-of-window history responses and added explicit accepted-universe reconciliation references for brokers whose historical retention differs by instrument;
- kept the mapped selector offline and mutation-free: Market Watch changes remain a separate add-only allowlisted operator action, and all quote, inventory and minute-reference evidence continues through the funded-account dual-lock read-only client;
- accepted target-broker P0 probe `mt5-capability-probe-17e5cc9c62b808c259294eb4`, a 58-pair explicit mapping with 55 eligible names and a 40-name quote surface, then froze 25-name EngineeringUniverse `engineering-universe-259e3975a25856bef28442ff`;
- accepted four-symbol MT5-D0 reconciliation `minute-reference-reconciliation-73e9897bcb5e43fd5ce0c53d` with 100% aligned overlap for IWM/GLD/XLE/EEM at the independently measured −180-minute historical offset;
- certified US-D3 as `CERTIFIED_FOR_ENGINEERING_RESEARCH` under report `us-minute-research-cert-485aeeac152a32caa546fbb8` and advanced stage authority to US-B0 without granting PAPER, execution or live-capital authority.

## 2026-09-03 — Replay Experiment Orchestration / Streaming-vs-Batch Research Campaign v1 implementation closure

- implemented an engineering-only `ReplayExperimentCampaign` over one bounded minute source with independent streaming (`DatabaseReplaySource -> AlgorithmRunner -> USBaselineStreamingAlgorithm`) and accepted US-D2 batch (`SessionResampledMinuteStore -> SameSessionLabelStore`) paths;
- froze exact row-count + SHA-256 parity across five input slices (5m/60m, 15m/30m, 15m/60m, 15m/120m, 30m/60m) and eleven downstream B0/A0/R1 observation/diagnostic/evaluation surfaces, for sixteen mandatory unique parity checks with no tolerance-based pass;
- discovered and corrected a previously hidden clock conflation by retaining feature/bar formation `source_event_time` separately from optional D2 raw 1m `price_event_time`; new batch-backed evidence reproduces the formal D2 source clock while old v1 bridge documents remain backward-compatible;
- hardened the content-addressed campaign report so it requires the frozen five batch slices, all sixteen unique parity surfaces and the canonical B0 denominator, while persisting `formal_us_b0_operator_invoked=false`, `us_d3_certification_consumed=false` and all research/Agent-value/Alpha/execution/stage authority flags as false;
- added `scripts/run_replay_experiment_campaign.py` for bounded real local U.S. historical campaigns against frozen source revision `776328445b7ac6e7815ef3a483e9c8ded1eb6d56`, inventory `us-minute-inventory-c2cbf682b456f97eb613ed65`, cleaning stack `us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244` and calendar `trading-calendar-03a9c29f566d6634aedbbbdc`, without invoking the formal stage-gated US-B0 operator;
- deterministic real DuckDB/Parquet fixture smoke accepted campaign `replay-experiment-campaign-ae3eadfdd7110176150e9a99` with 16/16 parity checks, row counts 120/40/40/40/20 and no blockers;
- passed 55 focused campaign/bridge/streaming/B0/A0/R1 regressions, deterministic smoke, provider/mutation and authority guards, Ruff, strict mypy, py_compile, bridge backward-compatibility checks, generic project tests and documentation governance;
- retained `docs/status.toml` unchanged at US-D3: campaign parity proves implementation equivalence only and does not certify US-D3, formally admit B0/A0/R1, prove current U.S. market data, or grant CFD/PAPER/execution/live-capital authority.

## 2026-09-03 — Streaming Feature / Strategy Integration v1 implementation closure

- implemented a provider-neutral incremental 1m -> 5m/15m/30m streaming resampler that reuses the accepted US-D2 `ResamplingSpec` semantics: session-open buckets, bucket-start event time, bucket-end availability, deterministic first/max/min/last/sum OHLCV, explicit incomplete coverage and non-divisible-session fail closed;
- proved real temporary DuckDB/Parquet streaming 15m output matches the accepted `SessionResampledMinuteStore` batch path field-by-field and carries the same resampling-spec identity rather than introducing a second realtime aggregation authority;
- implemented content-addressed `StreamingResampledBar`, `StreamingFeatureSnapshot`, `StreamingCrossSectionSnapshot` and `StreamingResearchUpdate` artifacts with engineering-only authority and source-event lineage;
- reused the existing `USBaselineBar`, `canonical_us_baseline_denominator()` and `evaluate_us_baseline_feature()` contracts so the streaming feature path shares the existing B0 candidate/formula identity instead of duplicating feature formulas;
- enforced a full-symbol cross-sectional barrier: partial symbol denominators never emit a cross-sectional snapshot or inferred ranks;
- preserved the delayed-source boundary: all 60 events in the canonical ~900-second delayed fixture remained visible to runtime projection while zero events entered the feature algorithm under the frozen 60-second source-delay / 120-second event-age engineering budget;
- deterministic smoke bound B0 denominator `us-baseline-denominator-b8bdb313856e1f7dc652bdd9`, replay run `algorithm-streaming-run-fee487ab505bebb2bab5d624`, replay semantic state `realtime-semantic-state-e2b2c83909b3bb8fd1326fb0` and delayed run `algorithm-streaming-run-f7cb9a77852566773c566ba6`;
- passed 37 focused streaming/source/US-D2/B0 regressions, deterministic smoke, provider/mutation guards, Ruff, strict mypy, py_compile, Streaming Source Harness, RT replay/projection, generic pytest and project-wide quality checks;
- retained `docs/status.toml` unchanged: this closure proves streaming engineering compatibility only and does not satisfy US-D3, B0/A0/R1 research authority, target-CFD microstructure, PAPER, execution or live-capital acceptance.

## 2026-09-03 — Streaming Source Harness v1 implementation closure

- froze provider-neutral `MarketDataSource`, `MarketDataSubscription`, `FeedTimingProfile`, replay pacing and strategy-freshness contracts so algorithms do not depend directly on DuckDB or MetaTrader5 provider objects;
- implemented bounded DuckDB batch streaming and `DatabaseReplaySource` over the admitted U.S. 1m Parquet Data Plane, preserving historical `event_time`, source `available_at`, deterministic delivery identity and truthful BarEvent-only semantics;
- implemented FAST, realtime, accelerated and explicit step replay modes without changing canonical event identity, and wrapped the existing read-only MT5 quote adapter in the same source/subscription surface for FX/live engineering use;
- implemented `AlgorithmRunner` so canonical projection/health state sees every event while strategy freshness gates decide independently whether an algorithm may act;
- retained progressing delayed feeds as a first-class `DELAYED` mode: the canonical 900-second fixture produces a 960-second 1m-bar event age and is rejected by the frozen 60-second source-delay / 120-second event-age test budget without being mislabeled frozen or disconnected;
- passed the dedicated 26-test source/realtime/MT5 regression, real temporary DuckDB/Parquet deterministic smoke, provider/mutation guards, Ruff, strict mypy, py_compile, US-D1 Data Plane, RT replay/projection and generic pytest/quality regressions;
- retained `docs/status.toml` and all U.S./broker authority boundaries unchanged: replay/FX/delayed fixtures prove engineering behavior only and do not satisfy US-D3, current U.S. market-data, CFD microstructure, PAPER, execution or live-capital acceptance.

## 2026-09-01 — U.S. minute Data Plane closure and sessionization start (US-D1 → US-D2)

- accepted real local US-D1 smoke `minute-store-smoke-ac583e1435f96a227f460f00` over four seed assets with 129,398 rows and three routed monthly partitions under the frozen 512MB / 2-thread / 4GB DuckDB execution policy;
- confirmed available-at partition routing across the year boundary, where a query beginning at 2026-01-01 correctly touched 2025-12 because the source event-time window is shifted back one minute;
- accepted deterministic replay because primary and replay Parquet materializations shared content SHA-256 `dcfb8e623a024391a67551b3c870e152909551b06fb2ed11eedc4f424dd2a744` and materialization identity `minute-materialization-209027e1a1aa93b20184ad0e`;
- closed US-D1 without introducing dense multi-year pandas/NumPy panels, redistribution of real source rows, session assumptions or adjusted-price semantics;
- started US-D2 with a calendar-aware sessionization layer over the raw store, binding regular-session classification to accepted XNYS calendar `trading-calendar-03a9c29f566d6634aedbbbdc` and keeping extended-hours authority fail-closed until explicit pre/post-market boundaries exist.

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
