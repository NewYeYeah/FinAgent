# FinAgent Current Development Plan

Planning revision: **4.1**  
Stable path: `docs/development/current-plan.md`  
Stage authority: `docs/status.toml`  
Scope: **Historical v1.0 closure → U.S. minute research → Agent incremental-value validation → CFD historical execution → provider-neutral realtime → MT5 demo/PAPER → separately governed live-capital acceptance**

This document answers **why the next work exists, what it changes, its dependencies and its exit gate**. It does not duplicate PR-level implementation history, the test command catalog or release notes.

---

## 1. Planning authority and stage map

There is one active plan and one current-stage authority. Planning revisions update this file in place; Git history preserves previous revisions.

```text
DOC-0  Documentation authority reset
  ↓
H0     A-share Historical v1.0 final release closure
  ↓
ENG-0  Reproducible development baseline
  ↓
US-S0 U.S. historical source authority
  ↓
US-C0 Intraday provider-neutral contracts
  ├─────────────→ MT5-P0 read-only broker capability probe
  ↓                         ↓
US-I0 ResearchInstrument ↔ BrokerInstrument mapping
  ↓
US-D1 DuckDB/Parquet minute Data Plane
  ├─────────────→ MT5-D0 read-only broker market reference
  ↓
US-D2 session-aware resampling / typed labels / corporate actions
  ↓
US-D3 U.S. minute certification
  ↓
US-B0 deterministic non-Agent baselines
  ↓
US-A0 Agent incremental-value experiment
  ↓
US-R1 robust intraday research + Alpha Gate
  ↓
       robust Alpha?
      /             \
    NO               YES
    ↓                 ↓
research iteration  US-X0 CFD historical execution semantics
                      ↓
                    US-X1 execution-aware historical portfolio gate
                      ↓
                    RT-R0 realtime event contracts
                      ↓
                    RT-R1 ReplayGateway
                      ↓
                    RT-R2 state projection
                      ↓
                    MT5-M1 market gateway + source reconciliation
                      ↓
                    MT5-E1 demo/PAPER execution
                      ↓
                    MT5-O1 reconciliation / recovery / safety
                      ↓
                    RT-R3 Live Workbench acceptance
                      ↓
                    MT5-L0 separate live-capital gate
```

The exact active stage is never inferred from this diagram; read `docs/status.toml`.

---

## 2. Frozen strategic constraints

### 2.1 Historical A-share becomes a release, not a permanent constraint on `main`
After H0, the accepted Historical v1.0 product is preserved through release identity/tag/evidence. Future U.S./MT5 changes to normal runtime/Workbench files must not be treated as illegal drift from the historical release.

### 2.2 U.S. source review precedes local research admission
A convenient large dataset is not accepted by title or mutable URL alone. FinAgent binds an immutable source/revision and records public provenance, usage-rights and semantic limitations. For the project's current **local, non-redistributed engineering-research** scope, a public source that remains `REFERENCE_ONLY` may receive a separate exact-snapshot local research admission after inventory, schema/time and sampled data-quality certification under an identity-bound cleaning policy. A `REJECTED` source can never be admitted. Publication/redistribution authority remains separate from local research admission.

### 2.3 `ResearchDataset` stays bounded
Do not make dense NumPy research panels responsible for tens of billions of potential sparse minute cells. Introduce a lazy/out-of-core query layer below them.

### 2.4 DuckDB is the first Data Plane engine
Use partitioned Parquet + DuckDB predicate/column pushdown. Arrow is an interchange boundary; Polars is deferred until a demonstrated requirement avoids a three-engine semantic/test matrix.

### 2.5 First U.S. signal clock is 15 minutes
Source/execution clock is 1m; canonical research signal is 15m, with 5m/30m robustness checks. This reduces microstructure noise, compute and turnover while retaining intraday behavior.

### 2.6 First strategy is same-session / intraday-flat
No overnight position is required for the first Alpha Gate. Research prices still handle cross-day corporate actions correctly, but account-level overnight swap/financing is not a prerequisite for proving intraday edge.

### 2.7 MT5 read-only measurement moves early; order authority stays late
Instrument availability, symbol specifications, spread/history depth and broker constraints are cheap to measure and necessary for universe design. `order_send`/external mutation remains forbidden until the historical Alpha and execution gates pass.

### 2.8 Engineering and statistical universes are distinct
The present broker intersection is an integration universe. Formal broader Alpha claims require an explicit PIT/survivorship policy.

### 2.9 Agent value must be falsifiable
The Agent is compared with manual and programmatic search under identical data, candidate budgets, validation gates and costs. Architecture investment alone is not evidence of incremental research value.

### 2.10 Agent Value Gate and Alpha Gate are different
A manual strategy may pass Alpha while the Agent adds no value; the trading system can continue while Agent scope contracts. Conversely, an Agent can outperform search baselines while all candidates still fail the deployment Alpha Gate.

### 2.11 Historical simulator is not the broker interface
Keep deterministic synchronous historical execution separate from asynchronous broker lifecycle ports/events.

### 2.12 Live Workbench is last
Do not build live dashboards before the canonical event/state/reconciliation semantics they would display are accepted.

### 2.13 Three-source realtime development model; delayed feeds are a first-class degraded mode
FinAgent development uses three complementary market-data roles rather than treating one temporary broker feed as the universal development source:

```text
DEV-REPLAY   certified/local U.S. historical database -> paced canonical BarEvent stream
             purpose: algorithm, feature, portfolio and stateful streaming development

DEV-LIVE     FX (EURUSD / GBPUSD / USDJPY) -> real connected MT5 QuoteEvent stream
             purpose: transport, clock, polling, reconnect, freshness and runtime integration

FINAL-FREEZE target-broker U.S. CFD -> broker-specific current/delayed source + execution evidence
             purpose: final symbol/contract/feed/execution/reconciliation freeze
```

The observed MetaQuotes-Demo delayed U.S. equity feed remains a required **degraded/delayed-feed compatibility profile**, not a discarded anomaly. FinAgent must preserve and test structural delay behavior because a future target broker may expose only polling or delayed market-data APIs.

A source capability is therefore classified explicitly rather than inferred from ticker shape:

```text
CURRENT
DELAYED
REPLAY
UNKNOWN
```

Rules:
- algorithms consume provider-neutral canonical events/state, never MT5/DuckDB objects directly;
- `event_time` remains source/market time and `received_at` remains delivery time; replay may pace delivery but must not rewrite market chronology;
- delay/freshness is data, not a hidden adapter assumption: measured/declared source delay propagates into health/state and strategy admissibility;
- a delayed source may pass transport/interface compatibility while failing a strategy freshness budget; this is an intentional terminal, not a reason to relabel the quote as current;
- 1m OHLCV may generate truthful `BarEvent` replay only; it must not synthesize authoritative bid/ask/tick/order-book history that the source never contained;
- FX validates only asset/feed-invariant runtime behavior. It does not become U.S. research or CFD microstructure evidence;
- the current Lane B delayed U.S. evidence chain remains governed by its frozen policies/Issue until an explicit later governance change; normal implementation work must not be blocked on collecting it;
- final target-broker U.S. CFD acceptance rebinds broker/server/account/symbol/contract/source identities. If that broker is delayed-only, the previously tested degraded mode is used and current-market strategy authority remains unavailable unless another admitted current source exists.

This is a source-substitution architecture, not a market-substitution claim.

---

# 3. DOC-0 — Documentation Authority Reset

## Goal
Reduce active documentation to current truth + compact historical summaries and make authority machine-checkable.

## Deliverables
- `docs/status.toml` as the only stage authority;
- stable `docs/development/current-plan.md`;
- consolidated architecture/testing/guides;
- aggregate changelog and active risk register;
- release snapshot(s) for frozen products;
- removal of versioned current plans, roadmaps and stage changelogs from the active tree;
- `scripts/check_docs.py`, governance regression and CI;
- PR template documentation-impact declaration.

## Exit Gate
- exactly one active plan;
- no forbidden versioned plan/roadmap/stage-changelog file remains under active `docs/development`;
- docs checker passes;
- README has no independent current-stage value;
- existing detailed history remains recoverable in Git/PRs.

---

# 4. H0 — A-share Historical v1.0 Release Closure

## Goal
Finish the already frozen A-share Historical v1.0 product and detach future `main` development from its post-freeze drift denominator.

## Required work
1. close the remaining V4-4 stable-render unit-test race without modifying financial runtime semantics;
2. run the complete frontend unit/type/build/E2E gates;
3. run real HW-1.0-RS against exact A-C5/A-C3 local evidence;
4. require `contract_valid=true`, browser `passed`, `accepted=true`, reserve non-consumption;
5. record final smoke identity, release SHA, freeze identity and reviewed no-alpha interpretation;
6. create a historical release tag (recommended `finagent-ashare-historical-v1.0`);
7. finalize `docs/releases/ashare-historical-v1.md` and update `docs/status.toml` to the next stage.

## Interpretation boundary
Historical v1.0 may validly terminate at `NO_ROBUST_FACTOR_FAMILY`. That proves the platform can preserve evidence and say “no robust Alpha”; it does not create a strategy, portfolio result, PAPER readiness or live-capital claim.

## Non-goals
No new A-share factor family, new Workbench analytics, reserve consumption, PAPER, realtime or broker authority.

## Exit Gate
```text
A-C5 frozen = true
HW-1.0-RS accepted = true
production reserve consumed = false
release snapshot finalized
tag/release identity recorded
status.current_stage advanced
```

---

# 5. ENG-0 — Reproducible Development Baseline

## Goal
Make the environment identity sufficiently reproducible before a large new U.S./MT5 line increases the dependency graph.

## Python
- introduce one resolved lock strategy (`uv.lock`, `conda-lock`, or hash-pinned generated requirements; choose one, not several authorities);
- keep `pyproject.toml` as dependency intent, lock as resolution;
- CI verifies lock consistency and `pip check`.

## Node
- document Node 22 as the current frontend developer/CI baseline until an explicit upgrade gate is run;
- keep `package-lock.json` authoritative for frontend resolution;
- do not change install-script policy merely to silence warnings without an explicit dependency review.

## Exit Gate
Fresh Ubuntu core/research and Windows frontend/MT5-prep environments can be reproduced from repository files without ad-hoc version guessing.

---

# 6. US-S0 — U.S. Historical Source Authority and Local Research Admission

## Goal
Bind the exact U.S. minute source and prove that the downloaded immutable snapshot is fit for an explicitly limited local research scope before provider-neutral query/calendar/label code is built on top of it.

US-S0 distinguishes two independent facts:

```text
public source/publication authority
                ↓
exact local snapshot certification
                ↓
local research admission
```

The public layer records what is actually known about origin, redistribution/usage rights and published semantics. The local layer decides whether one exact snapshot may be used for `local_non_redistributed_research` under explicit limitations and a deterministic cleaning policy.

## Contracts

Source/publication authority:

```text
DatasetSourceCandidate
DatasetRevision
DatasetFileDescriptor
DatasetProvenanceRecord
DatasetUsageRightsRecord
DatasetAuthorityDecision
DatasetAuthorityBundle
```

Local snapshot/admission:

```text
HuggingFaceSnapshotLayout
LocalMinuteInventory
MinuteDataCleaningPolicy
MinuteSampleQuality
LocalMinuteResearchCertification
LocalMinuteResearchAdmission
```

## Required review and certification

**Public/source evidence**
- exact repository/provider and immutable revision;
- upstream/origin statement and verification status;
- license/usage-rights status without inventing redistribution permission;
- published schema/partitioning/time semantics;
- raw/adjusted and corporate-action behavior where supportable;
- ticker/lifecycle limitations explicitly recorded.

**Exact local snapshot**
- `refs/main` / immutable snapshot revision match;
- complete monthly file inventory and expected coverage;
- schema and timezone-aware timestamp validation;
- observed ticker/time coverage on representative partitions;
- regular versus extended-hours diagnostics measured from data rather than assumed from README;
- duplicate `(ticker,timestamp)` classification into exact versus conflicting duplicates;
- identity/OHLC/volume sanity checks;
- bounded deterministic cleaning policy whose thresholds/actions are part of certification identity.

Do not assume coverage, row count, corporate-action correctness or redistribution rights from a dataset title/readme alone. Conversely, do not reject a multi-decade local research corpus merely because it contains extremely sparse deterministic defects that can be quarantined under a frozen policy.

## Public authority states

```text
ACCEPTED_FOR_RESEARCH
REFERENCE_ONLY
REJECTED
```

Interpretation:

- `REJECTED` can never receive local research admission.
- `ACCEPTED_FOR_RESEARCH` still requires local snapshot/data-quality certification before the local corpus is consumed.
- `REFERENCE_ONLY` may receive a separate `local_non_redistributed_research` admission when the exact snapshot passes local certification; all unresolved public-source blockers remain attached as limitations.
- Local admission does **not** grant redistribution/publication rights and does not convert the public authority state to `ACCEPTED_FOR_RESEARCH`.

## Cleaning policy boundary

For the bound `mito0o852/OHLCV-1m` snapshot, sparse deterministic defects may be handled only through the identity-bound `MinuteDataCleaningPolicy`:

```text
invalid OHLC within frozen rate      → quarantine/drop
exact duplicate full rows within rate → deterministic collapse
conflicting duplicate keys           → fail closed
invalid ticker/timestamp              → fail closed
negative/null volume                  → fail closed
outside-session observations          → diagnostic unless later calendar evidence proves invalid
```

Changing thresholds or actions changes `policy_id` and therefore certification identity. Thresholds must not be loosened ad hoc to force acceptance.

## Exit Gate

```text
immutable source/revision bound
public provenance/usage limitations recorded
local inventory covers expected 1992-01..2026-03 with no missing month
schema/time contract passes
representative partition quality passes the frozen cleaning policy
conflicting duplicate keys = 0 in certification samples
LocalMinuteResearchAdmission exists for local_non_redistributed_research
source + revision + inventory + certification + cleaning-policy identities are preserved
publication/redistribution limitations remain explicit
```

Only after this gate passes does `docs/status.toml` advance to US-C0. US-S0 does not itself claim survivorship-free market-wide Alpha validity; that remains constrained by lifecycle/PIT evidence in later research stages.

---

# 7. US-C0 — Intraday Core Contracts

## Goal
Freeze time, query, calendar, label and action semantics before minute storage/research code proliferates.

## Modules
Prefer small domain modules over extending `market_bars.py` indefinitely:

```text
src/finagent/domain/market_bars.py        # existing bar primitives
src/finagent/domain/trading_calendar.py   # new
src/finagent/domain/labels.py             # new
src/finagent/domain/corporate_actions.py  # new
src/finagent/data/query.py                # new
src/finagent/data/capabilities.py         # new adapter capability layer
```

## Contracts

### TradingCalendarEvidence
```text
calendar_id
market_id
source/revision
session_date
open_at
close_at
pre_open_at?
post_close_at?
is_half_day
```
The exact materialized schedule is hashed/versioned even when generated by a third-party calendar library.

### LabelSpec
```text
metric
horizon
horizon_unit
allow_cross_session
price_basis
availability_policy
```
For example, “60 trading minutes, same-session simple return” is a different identity from “4 bars” or “next day”.

### CorporateActionEvent
Start with split/dividend/cash-event types needed to state research-price semantics. Do not claim complete event accounting when the source cannot support it.

### MarketDataQuery
```text
assets
start/end
interval
fields
session_policy
adjustment_policy
availability_policy
```
Returns a bounded/lazy `MarketDataView`; it does not return a full multi-year dense NumPy panel.

### AdapterCapabilities
Record only functionality actually implemented/tested in FinAgent. Provider/API capability remains separate.

## Tests
- timezone-aware invariant;
- DST transition weeks;
- holiday and half-day schedules;
- no cross-session label when forbidden;
- action-adjustment fixtures;
- query bound and field validation;
- provider-capability ≠ adapter-capability regression.

## Exit Gate
All later minute adapters/resamplers/research code consume these contracts instead of inventing provider-specific time/horizon semantics.

---

# 8. MT5-P0 — Read-only Broker Capability Probe

## Goal
Measure the actual connected broker/terminal surface early without order authority.

## Platform
Official MT5 Python integration is a Windows-native adapter. Core/research/replay stay cross-platform; real capability evidence is collected locally on Windows against the selected demo/real-data terminal session.

## Package
```text
src/finagent/brokers/mt5/
  capabilities.py
  symbols.py
  probe.py
```

The package must remain import-safe when `MetaTrader5` is unavailable; optional dependency/platform errors are explicit.

## Evidence
```text
MT5TerminalCapability
MT5SymbolSpec
MT5HistoryCapability
MT5CapabilityProbeReport
```

Collect, without mutation:
- terminal/broker/server/build/version;
- symbol inventory and visibility;
- trade/contract/tick/digits fields;
- volume min/max/step;
- margin/swap properties;
- supported order/fill/trade modes;
- broker sessions where exposed;
- earliest/latest/count of available M1/tick history;
- representative spread snapshots.

## Safety rules
Forbidden in this stage: `order_send`, position mutation, account-setting mutation, live-capital command registration or generic browser execution authority.

## Exit Gate
The project knows what the actual broker can trade and measure before freezing the engineering universe.

---

# 9. US-I0 — Research/Broker Instrument Mapping

## Goal
Make the listed research asset and broker CFD explicitly different identities with an evidence-bound mapping.

## Contracts
```text
ResearchInstrument
BrokerInstrument
InstrumentMapping
InstrumentMappingEvidence
EngineeringUniverse
```

`BrokerInstrument` includes broker symbol plus contract/point/tick/volume/margin/swap/session semantics from MT5-P0. Mapping includes validity/version and source evidence.

Do not strip broker prefixes/suffixes ad hoc inside strategy code.

## EngineeringUniverse
Initial integration target: roughly 20–30 liquid names selected from certified history ∩ measured MT5 availability ∩ acceptable current spread/liquidity.

This is **not** a survivorship-unbiased ResearchUniverse and cannot support a market-wide historical claim by itself.

## Exit Gate
Every engineering asset used downstream has both research and broker identities or is rejected with an explicit mapping reason.

---

# 10. US-D1 — Out-of-core Minute Data Plane

## Goal
Query very large minute history without full-dataset pandas/NumPy materialization.

## Package
```text
src/finagent/data/minute_store/
  manifest.py
  parquet_store.py
  query.py
  materialize.py
```

## Engine
First implementation uses partitioned Parquet + DuckDB. Use Arrow only as an interchange/record-batch boundary when useful; do not add Polars as a second execution engine without a demonstrated requirement.

## Canonical normalized row
At minimum:
```text
research_asset_id
session_date
event_time
available_at
interval
open/high/low/close
volume
session_type
source_id
source_revision
data_version
```

## Bounds
Every query requires bounded assets and time range, validates requested fields, uses predicate/column pushdown and exposes estimated/actual row counts. Browser/API limits remain separate from internal aggregate scans.

`ResearchDataset` is materialized only for the bounded window/universe needed by a computation.

## Exit Gate
Representative multi-month/multi-asset scans demonstrate bounded memory behavior and exact deterministic results/replay identities.

---

# 11. MT5-D0 — Read-only Broker Market Reference

## Goal
Collect broker-side M1/tick/spread samples for reconciliation and later CFD cost calibration without making MT5 the historical research authority.

Persist:
```text
broker symbol
UTC timestamp
bid/ask or broker bar
spread
volume fields available
source terminal/server identity
retrieved_at
```

Cross-source disagreement remains evidence; it is never silently normalized away.

---

# 12. US-D2 — Session-aware Resampling, Labels and Corporate Actions

## Goal
Produce deterministic higher-timeframe research bars and labels from certified 1m data under explicit market/calendar/action semantics.

## Resampling
Canonical derived bars:
```text
1m → 5m / 15m / 30m
```
60m may be added only after the session-boundary rule is explicitly frozen because the 390-minute regular session does not partition into identical 60-minute bars.

Rules include:
- group only inside a materialized session segment;
- deterministic OHLCV aggregation;
- no spanning lunch/closed/overnight gaps;
- explicit partial-bar policy;
- derived-series identity binds source series + resampling spec + calendar identity.

## Initial research clock
```text
source/execution: 1m
canonical signal: 15m
robustness: 5m and 30m
first labels: same-session trading-minute horizons
```

## Corporate actions
Maintain a research-price policy and raw/executable price authority separately. If source action semantics cannot be certified, fail or narrow the research claim rather than infer a transformation.

## Exit Gate
Golden fixtures across normal days, DST weeks, half-days, gaps and split/dividend examples reproduce exactly.

---

# 13. US-D3 — U.S. Minute Data Certification

## Goal
Create the data gate that must pass before robust Agent or Alpha research.

## Checks
**Identity:** source/revision/file/partition/row identities.  
**Time:** UTC conversion, NY session membership, DST, holidays, half-days, monotonic availability, duplicates/out-of-order.  
**Market:** OHLC invariants, gaps/no-trade behavior, volume semantics, extended-hour classification.  
**Actions:** split/dividend consistency with the frozen policy.  
**Lifecycle:** symbol mapping and survivorship/PIT limitations stated explicitly.  
**Reconciliation:** sampled comparison with independent/broker references produces a report, not silent replacement.

## Development/source boundary
US-D3 research certification and normal implementation progress are separated from the temporary availability of one current U.S. broker API:

- certified local U.S. history may be emitted through a paced database replay source to validate the exact streaming path used by algorithms;
- FX may validate connected source-invariant MT5 plumbing, but cannot itself satisfy U.S. research/reconciliation authority;
- the existing delayed U.S. Lane B path remains a governed structural-delay/degraded-feed evidence chain and is not weakened or silently replaced;
- no delayed source is promoted to current market-data authority merely because the algorithm interface works;
- final U.S. CFD broker/source semantics remain a later broker-specific freeze.

The current formal US-D3 evidence requirements remain whatever `docs/status.toml`, the frozen policies and their active issue/evidence chain require; this planning clarification changes the development dependency model, not accepted evidence retroactively.

## Outcomes
```text
CERTIFIED_FOR_ENGINEERING_RESEARCH
CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS
REJECTED
```
A broad ResearchUniverse requires stronger lifecycle/PIT evidence than the EngineeringUniverse.

---

# 14. US-B0 — Deterministic Intraday Baselines

## Goal
Establish non-Agent research baselines before evaluating Agent value.

## Initial feature families
Keep the first library small, interpretable and implementable from certified OHLCV, for example:
- short-horizon reversal / momentum;
- intraday volatility/range;
- volume surprise / relative volume;
- close-location / gap/session-position features;
- simple cross-sectional normalization and lagged combinations.

No feature may depend on information after `available_at` or silently use future session totals.

## Split protocol
Freeze a pilot walk-forward design before observing final results. The engineering universe is for pipeline/Agent comparison; broader market claims require a PIT ResearchUniverse.

## Output
Baseline candidate denominator, feature artifacts, Factor Quant evidence and cost-free/diagnostic performance sufficient to define the later controlled experiment.

---

# 15. US-A0 — Agent Incremental-Value Experiment

## Goal
Answer “why does this project need an Agent?” with controlled evidence.

## Evidence additions
```text
CandidateGenerationEvent
CandidateGenerationRun
SearchArmResult
AgentValueExperiment
```

Record generation metadata needed for product/research analysis without hidden chain-of-thought:
```text
run/round/candidate/parent IDs
generator_type
model/provider identity where applicable
prompt-template identity
proposal/validation status
repair/replacement counts
generated_at
LLM calls/tokens/latency/cost metadata
```

## Arms
```text
MANUAL       fixed human-designed candidates
PROGRAMMATIC deterministic/randomized bounded search
AGENT        LLM Agent proposal/repair workflow
```
All arms use the same certified data, universe, primitive vocabulary, candidate budget, robust gates and transaction-cost assumptions where applicable.

## Initial budgets
Pilot: 16 candidate slots per arm.  
Formal experiment: 32 slots per arm; programmatic search ≥3 seeds; Agent ≥3 independent runs. Revisions require a preregistered experiment update before results are inspected.

## Compare
- valid-candidate rate;
- invalid/repair/duplicate rate;
- novelty and redundancy;
- OOS RankIC / worst-fold evidence;
- robust accepted-factor count;
- quality versus trial count;
- trials to first accepted factor;
- LLM calls/tokens/cost;
- regime/fold transfer.

## Agent Value Gate
A practical first gate requires evidence of incremental research efficiency/quality, not merely different outputs. If the Agent does not improve accepted quality, discovery efficiency or meaningful novelty under the fixed budget, no new Agent complexity becomes P0; the Agent remains an optional hypothesis interface.

---

# 16. US-R1 — Robust Intraday Research and Deployment Alpha Gate

## Goal
Run the formal robust program on certified minute data with intraday-aware inference and a terminal that can stop downstream deployment.

## Statistical requirements
- purged/embargoed walk-forward where label overlap requires it;
- HAC lag sufficient for overlapping horizons/autocorrelation;
- session/block bootstrap rather than IID minute bootstrap;
- Holm/BH multiplicity over the frozen candidate denominator;
- frequency-aware turnover and annualized presentation metrics;
- statistical inference sample size is not replaced by a naive `sqrt(252 × bars/day)` display factor.

## Valid terminals
```text
ROBUST_FACTOR_FAMILY
NO_ROBUST_FACTOR_FAMILY
SYSTEM_FAILURE
```

## Deployment Alpha Gate
Only `ROBUST_FACTOR_FAMILY` with preregistered OOS/fold/stability/economic criteria permits strategy-specific CFD execution/Live-product work. `NO_ROBUST_FACTOR_FAMILY` is a valid research-platform result but stops the deployment branch; data/replay/reference infrastructure may continue independently.

---

# 17. US-X0 — CFD Historical Execution Semantics

## Goal
Translate robust research signals into broker-compatible historical execution without importing A-share T+1/lot/limit defaults.

## Domain
```text
CFDInstrumentSpec
CFDAccountSpec
CFDOrderIntent
CFDOrderCompiler
CFDSpreadModel
CFDSlippageModel
CFDMarginModel
CFDSwapModel        # may remain unavailable while strategy is intraday-flat
```

The cost model binds measured/assumed spread, volume step, contract size and broker semantics to a versioned execution specification. Historical simulation remains deterministic and separate from MT5 order APIs.

## Exit Gate
Target → quantity → cost → fill → account/NAV conservation is exact and broker-spec-compatible for the EngineeringUniverse.

---

# 18. US-X1 — Execution-aware Historical Portfolio Acceptance

## Goal
Determine whether the robust signal survives realistic CFD friction and portfolio constraints before realtime/broker order integration.

Required evidence:
- gross/net NAV and returns;
- spread/slippage/fees where applicable;
- turnover/participation diagnostics;
- realized vs target weights;
- constraint/rejection attribution;
- margin/cash utilization;
- exact replay/reconciliation of ledger to portfolio aggregates.

## Exit Gate
A preregistered historical economic gate passes. Failure returns to research/execution assumptions; it does not proceed to broker mutation merely because statistical Alpha existed.

---

# 19. RT-R0 — Provider-neutral Realtime Event Contract

## Goal
Freeze replayable event semantics before a real broker gateway owns state transitions.

Recommended package: `src/finagent/realtime/`.

Envelope:
```text
event_id
source
source_event_id?
event_time
received_at
sequence?
schema_version
```

Events:
```text
QuoteEvent
BarEvent
MarketStatusEvent
AccountStatusEvent
OrderEvent
TradeEvent
OrderErrorEvent
ConnectionEvent
```

Duplicate, late and out-of-order behavior is part of the contract.

---

# 20. RT-R1 — ReplayGateway

## Goal
Test state machines and failure semantics without a broker.

Required scenarios:
```text
normal quote/bar flow
stale market data
disconnect / reconnect
duplicate events
out-of-order events
order reject
partial fills
cancel / expire
restart from persisted event/state checkpoint
```

Replay fixtures are authoritative for contract tests, not evidence of broker readiness.

## Streaming-source development extension
The next implementation increment turns replay from a pre-built event tuple into the same subscription surface used by live sources:

```text
RealtimeMarketDataSource / MarketEventSource
FeedTimingProfile
DatabaseReplaySource        # DuckDB/Parquet -> paced BarEvent
MT5RealtimeSource           # FX during development; U.S. CFD at final freeze
AlgorithmSubscription
AlgorithmRunner
```

Required replay modes:

```text
1x realtime pace
accelerated pace (for example 60x)
as-fast-as-possible deterministic regression
step/debug mode
explicit delayed delivery profile
```

The database source preserves historical `event_time` and assigns delivery/`received_at` according to the replay clock/profile. The same algorithm runner must be able to consume database replay, FX live and target-CFD live/delayed streams without provider-specific strategy branches.

Delay is tested structurally through a `FeedTimingProfile`/equivalent contract. A strategy declares or derives a maximum admissible freshness/decision budget; a source whose effective delay exceeds that budget is rejected/degraded even if connectivity is healthy.

---

# 21. RT-R2 — Projection / State Store

## Goal
Build canonical state from append-only events.

Projections:
```text
MarketState
StrategyState
PortfolioState
ExecutionState
AccountState
SystemHealthState
```

State transitions are idempotent/replayable and retain source event identities. Browser code consumes projections, not event-reduction business logic.

---

# 22. MT5-M1 — Read-only Market Gateway and Source Reconciliation

## Goal
Normalize official MT5 historical/realtime bar/tick data into realtime contracts, classify the observed feed timing capability, and persist differences from the historical research source.

Do not select “the better source” silently. Reconciliation records timestamp/session/OHLC/volume/instrument differences and classifies expected CFD-vs-equity differences separately from data-quality failures.

Final source admission records whether the bound target source is `CURRENT`, `DELAYED` or `UNKNOWN` under a frozen timing/freshness policy. A delayed-only target may prove adapter/runtime compatibility but does not create current-market authority. Strategy activation must compare the measured source delay/freshness against the strategy decision budget and fail closed when the source is too old.

Development should first prove the identical canonical interface with FX live and database replay; target U.S. CFD is reserved for the smallest broker/source-specific freeze surface.

---

# 23. MT5-E1 — Demo/PAPER Execution

## Ports
```text
OrderCommandPort
BrokerEventSource
BrokerQueryPort
```

Identities include `client_order_id`, broker order/ticket ID, deal/fill ID and event IDs.

Required behavior:
- idempotent submit/retry policy;
- broker acknowledgement and reject handling;
- partial fills;
- cancel/expire lifecycle;
- append-only command/event audit;
- demo/PAPER only.

A successful demo order is not a live-capital acceptance.

---

# 24. MT5-O1 — Reconciliation, Recovery and Safety

Required capabilities:
- internal vs broker orders/deals/positions/account reconciliation;
- restart/recovery from durable state;
- stale-data gate;
- exposure/notional/daily-loss guardrails;
- kill switch and incident ledger;
- explicit unknown/drift state when reconciliation cannot be proven.

This stage must fail closed; “broker responded” is not equivalent to state consistency.

---

# 25. RT-R3 — Live Workbench Acceptance

Only now activate live Market/Strategy/Portfolio/Execution/System Health panels.

The browser displays canonical projections, including freshness, broker/reconciliation drift, order lifecycle and system health. It never calls MT5 directly and never recomputes broker/account truth.

Acceptance is demo/PAPER product acceptance only.

---

# 26. MT5-L0 — Separate Live-capital Acceptance

This is an intentionally separate human-governed milestone. It requires a new explicit acceptance plan covering broker/account identity, capital/risk ceilings, operational responsibility, recovery, kill-switch procedure, monitoring/incident policy and jurisdiction/account-specific constraints.

No previous research, historical, replay, demo/PAPER or Workbench gate implicitly authorizes live capital.

---

# 27. Cross-stage quality policy

## Strict typing for new lines
All new provenance/calendar/minute/CFD/realtime/MT5 code starts under strict focused mypy. Do not extend legacy typing exemptions into new modules.

## No new fat modules
Separate domain contracts, calculations, application orchestration, storage, projections and provider adapters. New 30–60 KB mixed-responsibility files are considered an architectural regression.

## Evidence first
Financial/statistical facts become Workbench features only after an authoritative/derived evidence contract exists. Missing benchmark/risk/capacity facts remain unavailable.

## No hidden fallback
Unsupported provider capability, missing corporate-action semantics, incomplete mapping, stale broker state or reconciliation mismatch produces an explicit terminal/limitation; no silent provider/rule substitution.

## Reproducibility
A meaningful result binds Git/code identity, data source/revision, configuration/protocol and dependency environment sufficiently to reproduce the calculation path.

---

# 28. Recommended PR sequence

```text
DOC-0  docs authority + consolidation + docs CI
H0     final Historical v1.0 test/smoke/tag/release closure
ENG-0  dependency/runtime reproducibility
US-S0  source/publication authority + exact local snapshot certification/admission
US-C0  calendar/LabelSpec/actions/query/adapter-capability contracts
MT5-P0 Windows read-only capability probe
US-I0  instrument mapping + EngineeringUniverse
US-D1  DuckDB/Parquet minute store
MT5-D0 read-only broker market reference
US-D2  resampling/labels/actions
US-D3  minute certification gate
US-B0  deterministic baselines
US-A0  Agent controlled experiment evidence
US-R1  robust intraday Alpha Gate
US-X0/X1 only if Alpha passes
RT-R0/R1/R2 + streaming-source harness (database replay / FX live / delayed profile)
MT5-M1/E1/O1
RT-R3
MT5-L0 separate live-capital plan
```

Do not combine source certification, Agent research and broker-order mutation in one PR. Each gate must be inspectable and independently reversible before irreversible/external authority appears.

---

# 29. Explicitly deferred

- new A-share-only analytics/features except correctness/security fixes;
- A-share reserve consumption solely to improve a historical release badge;
- full A-share minute research stack before the U.S. pivot;
- QMT callback/order implementation without a real SDK/account acceptance environment;
- generic live-capital commands;
- benchmark/style/industry/capacity/risk contribution without authoritative evidence;
- overnight CFD strategy semantics until intraday Alpha survives costs;
- multiple Data Plane engines without a demonstrated need.

---

# 30. v4.1 definition of success

v4.1 is successful if the project can make and preserve the following evidence-based decisions:

1. **Data:** the exact U.S. historical source and local snapshot are trustworthy enough for the stated research claim, with public-source and cleaning limitations preserved explicitly, or the source/snapshot is rejected.
2. **Agent:** controlled evidence shows whether the Agent improves research quality/efficiency over non-Agent baselines.
3. **Alpha:** robust intraday Alpha either passes or stops strategy deployment honestly.
4. **Execution:** passing Alpha survives broker-compatible historical CFD friction before broker mutation.
5. **Operations:** realtime/demo/PAPER state is replayable, reconciled and recoverable before a Live Workbench is accepted.
6. **Authority:** live capital remains separately human-governed.
