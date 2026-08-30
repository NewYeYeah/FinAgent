# FinAgent Current Development Plan v4.0

Status: **preliminary frozen planning baseline**  
Date: **2026-08-30**  
Planning anchor: `main @ 31ce20f7a6f78aee221e3649c5f6d2bb6e2fea0a`  
Scope: **A-share historical closure → Historical Workbench 1.0 → US minute research → MT5 CFD PAPER/realtime**

This document freezes the next development sequence after Visualization V4-4. It preserves all completed V0–V4-4, A2.6–A5-4 and V3 authority/evidence contracts, but replaces the previous assumption that QMT must be the next realtime implementation target.

The immediate implementation stage remains **V4-5 Linked Analytics Acceptance**. After V4-5, the project first closes and certifies the A-share historical research product, then pivots to U.S. minute-level research and a provider-neutral realtime architecture whose first broker implementation is MetaTrader 5 (MT5). QMT becomes a later broker adapter when a real interface becomes available for end-to-end verification.

---

# 1. Why v4.0 exists

The project has reached a different engineering boundary from the one assumed in the earlier planning documents:

1. the A-share historical research, robust factor research, execution simulation, portfolio validation, evidence/governance and analytical Workbench are close to product closure;
2. the current QMT interface cannot be verified end-to-end in the development environment, so writing a nominal QMT gateway now would create untested execution semantics;
3. the intended next investable market is U.S. equity CFD through MT5 rather than immediate A-share external PAPER;
4. the selected U.S. research source is minute-level OHLCV, which creates new requirements around out-of-core storage, session-aware clocks, corporate actions, minute labels and broker/source reconciliation;
5. the existing Workbench should remain provider-neutral and consume evidence/projections rather than being coupled to AKShare, QMT, Hugging Face or MT5 directly.

The planning objective therefore changes from:

```text
A-share research → A6/PAPER → QMT realtime
```

to:

```text
A-share historical closure
        ↓
Historical Workbench 1.0 freeze
        ↓
US M1 data + research migration
        ↓
provider-neutral realtime contracts
        ↓
MT5 demo/PAPER gateway
        ↓
reconciliation + Live Workbench
        ↓
separate live-capital acceptance

future: QMTGateway plugs into the same realtime contracts
```

---

# 2. Frozen strategic decisions

The following decisions are frozen by this baseline unless a later planning revision explicitly changes them.

## D1 — Do not build a complete A-share intraday research line before the U.S. pivot

A-share minute data may be used for contract smoke tests, but the project will **not** duplicate the full A2.6/A3/A4 research chain at minute frequency solely to prepare for U.S. migration.

The A-share line must finish:

- Historical Workbench acceptance;
- real historical end-to-end certification;
- provider/frequency-neutral bar evidence;
- initial-requirement closure audit.

It does **not** need a separately productionized A-share M1 factor/portfolio/live stack before the U.S. pivot.

## D2 — Do not implement an untestable QMT gateway

QMT-specific callback, order, account and reconciliation code is deferred until a real SDK/account environment exists for contract verification.

Development that does not require QMT can and should proceed now:

```text
Realtime Event Contract
ReplayGateway
Realtime Projection / State Store
Live Workbench contracts
broker-neutral safety / reconciliation primitives
```

When QMT becomes available, it should be implemented as a new adapter over those contracts rather than introducing a second realtime architecture.

## D3 — Use a dual-source U.S. architecture

Historical research source candidate:

- `https://huggingface.co/datasets/vessel888/OHLCV-1m/tree/main`

Broker/execution source:

- MetaTrader 5 terminal connected to the selected CFD broker.

These sources have different authority:

```text
Hugging Face OHLCV
→ immutable historical research evidence

MT5
→ broker symbol/instrument specification
→ broker-available historical bars/ticks
→ realtime quotes
→ account/order/trade execution authority
```

MT5 data must not silently overwrite the historical research dataset. Cross-source differences are handled through explicit reconciliation evidence.

## D4 — Workbench remains source-neutral

The Workbench must consume:

```text
Evidence
Projection
WorkbenchContext
Realtime State Projection
```

It must not contain AKShare-, QMT-, Hugging Face- or MT5-specific financial logic.

Provider-specific code belongs below adapter/gateway boundaries.

## D5 — Freeze frequency-aware market evidence before serious U.S. M1 research

The project must introduce a formal `MarketBarSeriesEvidence` / interval/session contract before U.S. minute research becomes authoritative.

This closes the current V4-2 gap where OHLC is intentionally reported as unavailable and prevents the browser from reconstructing candles from unrelated evidence.

## D6 — Do not consume A-share production reserve solely to declare historical closure

A5-1–A5-4 infrastructure remains valid and the production reserve remains an independent human-governed asset.

If the A-share strategy is not being promoted to PAPER/live, historical closure does **not** require consuming the untouched reserve merely to obtain a PASS/FAIL badge.

A5 production execution and A6 promotion/PAPER resume only if a later decision makes an A-share strategy an operational target.

---

# 3. Preserved architecture and current implementation leverage

The current repository already contains the right high-level separation for the pivot.

Core protocol boundaries remain:

```text
DataAdapter
ExecutionDataAdapter
AlphaModel
RiskModel
PortfolioOptimizer
RiskGate
ExecutionVenue / TimedExecutionVenue
```

`AssetId` already carries symbol, venue, asset type and currency rather than treating a ticker as globally unique.

A-share-specific semantics are correctly isolated into specialized execution/domain implementations such as:

```text
AshareBoard
AshareTradeability
AshareAccountState
AsharePosition
T+1 sellability
price-limit rules
lot / minimum quantity rules
A-share fee and cash semantics
```

Those rules must remain A-share-specific rather than becoming defaults for U.S. CFD.

The repository also already has U.S. market scaffolding, including U.S. ETF market configurations and an Alpaca ingestion path. These are useful migration evidence that the upper architecture is not A-share-only, but the existing Alpaca implementation is daily-bar oriented and does not solve the planned M1/out-of-core problem.

---

# 4. Definition of Historical Workbench 1.0

The A-share line is considered historically closed when the following product surfaces are accepted as one system:

```text
Command Center
Agent
Strategy
Factors
Portfolio
Execution
Evidence & Governance
Configuration
```

The following are explicitly **not** required to call Historical Workbench 1.0 complete:

```text
advanced Risk attribution
Operations / broker reconciliation
Live realtime panels
benchmark-relative analytics without frozen benchmark evidence
style / industry exposure without frozen exposure evidence
capacity / impact without preregistered liquidity evidence
```

Those capabilities remain evidence-dependent later stages. The Workbench must display unavailable states rather than fabricate them.

Historical Workbench 1.0 must answer, using authoritative identities:

```text
What research program produced this result?
What factors passed or failed and why?
Why did the strategy target/trade this asset?
What quantity was desired, executable and filled?
How did gross return become net return?
Which evidence/configuration identities produced the result?
Which safe commands are available and what evidence did they produce?
```

---

# 5. A-share closure sequence — A-C0 through A-C5

## A-C0 — V4-5 Linked Analytics Acceptance

Priority: **current / blocking**

Purpose: validate V4-2/V4-3/V4-4 as one analytical product instead of adding new chart families.

Acceptance must cover:

- every Strategy/Factors/Portfolio/Execution chart/card/table declares its evidence requirement and authority class;
- React does not recalculate or silently upgrade authoritative financial/statistical facts;
- `portfolio_validation_id`, asset, order, factor, date, session and fold context survives cross-module navigation, browser history and reload;
- missing OHLC, factor contribution, benchmark and exposure evidence remains explicitly unavailable;
- bounded APIs and server-side pagination retain exact identity and full aggregate semantics;
- Evidence Plane remains GET-only;
- Control Plane remains within the accepted V3 L0/L1 ceiling;
- Ubuntu API, quality, TypeScript/Vitest/build/Playwright and repository/A2.6/legacy regression gates pass; Windows remains retained as an asynchronous compatibility path.

No new analytical family should be added inside A-C0 unless required to close an acceptance defect.

## A-C1 — Historical Workbench Operational Closure

Purpose: turn the Workbench from a high-quality evidence reviewer into a complete historical research workstation without adding broker/live authority.

Current safe executable commands are intentionally limited. A-C1 should extract reviewed typed application services for the remaining historical pipeline candidates:

```text
research.run_development
research.run_a2p6
portfolio.run_a4
```

Target flow:

```text
Workbench
  ↓
Typed L1 CommandSpec
  ↓
Application Service
  ↓
Deterministic core run
  ↓
CommandRun audit
  ↓
immutable evidence
  ↓
Evidence Plane / Workbench
```

Requirements:

- no arbitrary shell/Python execution;
- browser cannot submit host filesystem paths as executable authority;
- exact ConfigSnapshot and WorkbenchContext are stored in the command audit;
- repeated idempotency keys cannot silently launch a different protocol;
- research/A4 failures become explicit terminal CommandRun results;
- produced evidence is discoverable by the existing Evidence Plane without turning Evidence into a write API;
- no A5 reserve, promotion, PAPER or broker authority is added.

Acceptance:

- a user can certify data, run development research, run A2.6, run A4 and export a review bundle through bounded L0/L1 controls;
- every successful command has durable audit identity and evidence links;
- every disabled/unsupported command fails closed.

## A-C2 — MarketBarSeriesEvidence + Frequency Contract

Purpose: freeze provider-neutral OHLCV evidence and time semantics before U.S. M1 research.

Recommended additive contracts:

```text
BarInterval
BarTimestampConvention
MarketSessionSpec
SessionSegment
MarketBarRow
MarketBarSeriesManifest
MarketBarSeriesEvidence
LabelHorizonPolicy
```

Minimum `MarketBarRow` semantics:

```text
asset
event_time
available_at
interval
open
high
low
close
volume
session_id
session_type
source
data_version
```

Required invariants:

- timestamps are timezone-aware;
- `event_time` and `available_at` remain distinct;
- interval is part of the series identity;
- OHLC consistency is checked by core;
- duplicate asset/event-time rows fail closed;
- bar start/end convention is explicit;
- session membership is produced by core, not guessed in React;
- authoritative candles are rendered only from verified MarketBarSeries evidence.

First product integration:

```text
Strategy price/candlestick
+
signal / target / order / fill markers
```

For A-share closure, daily OHLC is sufficient to certify the evidence/UI contract. A small minute sample may be used for intraday smoke testing.

## A-C3 — Real A-share Historical End-to-End Certification

Purpose: validate the actual product path against real historical evidence rather than relying mainly on synthetic fixtures.

Required path:

```text
Frozen A-share dataset
  ↓
data certification
  ↓
development research
  ↓
A2.6 robust research
  ↓
A4 portfolio validation
  ↓
V4-0 StrategyDecisionSeries
  +
V4-1 FactorSeries
  +
MarketBarSeriesEvidence
  ↓
Historical Workbench
  ↓
review bundle
```

Required checks:

### Numerical fidelity

- Workbench values match authoritative JSON/JSONL/Parquet/SQLite evidence;
- no sign normalization or hidden clipping changes research interpretation;
- gross/net portfolio and execution costs reconcile exactly.

### Identity fidelity

- dataset version;
- ResearchProgram/spec/selection identities;
- factor-series identity;
- A4 validation/spec/ledger identity;
- StrategyDecisionSeries identity;
- MarketBarSeries identity;
- source SHA/digest where the contract defines it.

### Interaction fidelity

- asset/order/factor/fold/date/session selections propagate deterministically;
- reload/back/forward recover the same context;
- cross-module links do not infer unsupported relationships.

### Large-series fidelity

- browser row endpoints remain bounded;
- aggregates over more than one browser page are calculated server-side over the complete verified source set;
- downsampling, when introduced, is presentation-only.

### A-share minute smoke

If a convenient public minute feed is available, use only a small sample to validate:

- timezone;
- session open/close;
- midday break;
- bar interval identity;
- candlestick projection;
- 1m → higher-frequency resampling contract.

This smoke test does not create a new authoritative A-share minute research program.

## A-C4 — Initial Requirement Compliance Audit

Purpose: compare the implementation against the earliest frozen development goals and explicitly close every requirement.

The audit must use this matrix:

| Requirement | Source plan | Implementation | Test/evidence | Status | Disposition |
| --- | --- | --- | --- | --- | --- |
| requirement | document/section | code path | test/report | PASS/PARTIAL/DEFERRED/N/A | close/follow-up |

Allowed statuses:

- `PASS` — implemented and accepted;
- `PARTIAL` — implemented but missing a material acceptance condition;
- `DEFERRED` — intentionally postponed by the v4.0 strategy;
- `N/A` — no longer applicable because product direction changed.

At minimum audit:

```text
PIT DataAdapter / ResearchDataset
Agent research framework
robust Factor / A2.6
A3 A-share execution semantics
A4 execution-aware portfolio
immutable evidence / identity / replay
A5 one-shot infrastructure
Evidence/Governance
Workbench Foundation
Strategy analytics
Factor analytics
Portfolio/Execution analytics
V4 linked acceptance
historical Workbench Control execution
OHLC evidence
benchmark evidence
corporate actions
capacity / impact
advanced risk
internal PAPER
realtime gateway
QMT
```

Strategic deferral must not be mislabeled as an implementation failure.

## A-C5 — A-share Historical v1.0 Freeze

Exit artifact:

```text
FinAgent A-share Historical v1.0
```

Freeze package should include:

- accepted `main` Git SHA;
- environment/dependency lock identity where available;
- real A-share certification evidence IDs;
- A2.6/A4/V4 evidence IDs;
- Historical Workbench acceptance report;
- initial-requirement compliance matrix;
- explicit deferred-capability list;
- statement that production reserve remains untouched unless separately authorized.

After A-C5, no new A-share-only feature is P0 unless it fixes a correctness defect or is required by a later QMT adapter.

---

# 6. U.S. data architecture — historical equities versus broker CFD

The project must not treat a U.S. equity historical bar and an MT5 stock CFD quote as the same instrument simply because both contain a familiar ticker.

Recommended identity model:

```text
ResearchInstrument
  └─ U.S. listed equity identity

BrokerInstrument
  └─ broker-specific MT5 symbol
     contract size
     point/tick size
     volume min/max/step
     margin properties
     swap properties
     broker trading sessions
```

A mapping contract must bind the two explicitly:

```text
InstrumentMapping
research_asset_id
broker_provider
broker_symbol
mapping_version
valid_from / valid_to
mapping_evidence
```

A broker suffix/prefix must never be stripped ad hoc in strategy code.

---

# 7. US-D0 — Dataset provenance and exact source certification

Primary candidate source selected for development:

`https://huggingface.co/datasets/vessel888/OHLCV-1m/tree/main`

The v4.0 plan does **not** freeze an assumed row count, size, coverage end date or exact relationship to similarly named public mirrors. Those are outputs of US-D0.

US-D0 must persist a `DatasetProvenanceRecord` containing at least:

```text
repository / dataset URL
resolved revision / commit
file inventory
file hashes where feasible
schema
partition convention
coverage range
row/asset counts
license / usage metadata
upstream/origin metadata
retrieved_at
```

It must determine explicitly:

- whether the dataset is raw or adjusted;
- whether splits/dividends are reflected in prices;
- whether pre/post-market minutes are included;
- minute timestamp means interval start or end;
- halt/no-trade minutes representation;
- ticker rename/delisting behavior;
- survivorship characteristics;
- duplicate or malformed-bar policy.

No robust research begins until these semantics are sufficiently certified.

---

# 8. US-D1 — Intraday time, session and corporate-action contract

Minute research cannot reuse implicit daily assumptions.

Required contracts:

```text
BarInterval
SessionCalendar
SessionSegment
BarTimestampConvention
LabelHorizonPolicy
CorporateActionEvent
CashEvent
```

The market clock must handle at least:

```text
America/New_York trading calendar
DST transitions
regular session
optional extended hours
holidays
half-days
overnight boundary
halt / missing-minute semantics
```

The label contract must distinguish:

```text
BAR_COUNT
TRADING_MINUTES
SAME_SESSION
TRADING_DAYS
```

Example:

```text
forward_return_30m
horizon_policy = TRADING_MINUTES
same_session = true
```

This prevents an apparently intraday horizon near the close from silently becoming an overnight label.

Corporate actions become P0 for the U.S. line. The research/economic accounting contract must distinguish:

```text
adjusted research return series
vs
raw executable prices + cash/corporate-action ledger
```

No split/dividend discontinuity may be interpreted as alpha, volatility or execution PnL merely because a source lacks adjustment metadata.

---

# 9. US-D2 — Out-of-core minute Data Plane

The existing in-memory adapter remains useful for bounded fixtures and small research slices, but it must not be the full-dataset architecture for multi-billion-row minute data.

Target path:

```text
monthly/partitioned Parquet
        ↓
DuckDB / Arrow / Polars-compatible scan boundary
        ↓
predicate pushdown
asset/date/session pruning
column projection
        ↓
bounded IntradayDatasetView
        ↓
ResearchDataset / FeatureWindow materialization
```

Recommended new adapter family:

```text
ParquetIntradayDataAdapter
IntradayExecutionDataAdapter
```

Do not load the full remote dataset into pandas/NumPy memory.

Required properties:

- local immutable cache or explicitly versioned remote materialization;
- content-addressed data version;
- bounded asset/date query;
- streaming/chunked certification;
- sparse asset-minute support;
- deterministic ordering;
- no full-universe exact-timestamp intersection requirement when an asset simply has no trade in a minute;
- explicit missingness/tradability semantics;
- feature windows materialize only the requested slice.

---

# 10. US-D3 — Resampling and canonical research frequencies

M1 is the base market-data granularity, not a requirement that every strategy rebalance every minute.

Core should produce deterministic derived bar series:

```text
1m
→ 5m
→ 15m
→ 30m
→ 60m
```

Resampling must define:

- session alignment;
- first/last partial bucket handling;
- OHLC aggregation;
- volume aggregation;
- `available_at` of the derived bar;
- provenance back to source M1 identity.

Recommended first research target:

```text
market data: 1m
signal/research interval: 5m or 15m
execution simulation: 1m / later tick-aware
```

The first U.S. phase is not an HFT project. It should prioritize statistically and economically testable short-horizon alpha rather than maximize rebalance frequency.

---

# 11. US-D4 — U.S. minute data certification gate

US-D4 must produce a formal certification artifact before A2.6 is run on a production-sized U.S. universe.

Checks include:

```text
duplicate asset/timestamp
monotonic time
OHLC consistency
negative/invalid price/volume
timezone correctness
DST boundary
regular/extended-session classification
holiday/half-day handling
large unexplained gaps
corporate-action discontinuity
symbol mapping
universe survivorship
extreme return outliers
cross-file overlap/gap
source revision/hash consistency
```

Certification may be staged by sample/universe, but every research evidence identity must bind the exact certified data version it uses.

---

# 12. US-R0 through US-R3 — historical research migration

## US-R0 — Pilot universe and baseline

Start with a small, highly liquid universe rather than thousands of symbols.

Recommended first range:

```text
20–50 liquid U.S. instruments
```

Selection should prefer the intersection of:

```text
certified historical availability
∩
MT5 broker CFD availability
∩
acceptable spread/liquidity characteristics
```

This keeps data, factor, execution and broker-mapping errors diagnosable.

## US-R1 — Intraday factor/Agent research

Reuse the existing deterministic research authority and bounded Agent model, but introduce interval-aware feature families and walk-forward definitions.

Requirements:

- no direct reuse of A-share factor PASS status as U.S. evidence;
- all U.S. candidates re-enter the A2.6 denominator/gates;
- train/test split and label horizons are intraday-session aware;
- multiple-testing and robustness logic remain authoritative core calculations;
- Agent proposes, deterministic code calculates/validates.

## US-R2 — U.S. execution-aware historical portfolio

Separate the research model from CFD broker semantics.

Historical research may initially validate signal quality using listed-equity bars, but an MT5-deployable strategy must later include a broker-specific execution model covering at least:

```text
bid/ask spread
broker symbol
contract size
volume step
minimum/maximum volume
margin
swap/financing where relevant
trading session
slippage assumptions
order/fill constraints
```

The A-share A3 execution implementation must not be reused as the default U.S. compiler.

## US-R3 — U.S. Historical Workbench Acceptance

Reuse the existing Workbench shell and linked analytics.

Expected new/changed presentation concerns:

- minute timestamp density;
- authoritative candlestick source;
- sub-day context selection;
- session segmentation;
- downsampling for display only;
- U.S./broker instrument mapping in Inspector;
- no financial recomputation in React.

The goal is to prove that the same product architecture can review A-share daily evidence and U.S. intraday evidence without market-specific frontend forks.

---

# 13. Realtime architecture — replace QMT-specific staging with provider-neutral RT-R0–R3

Realtime events remain independent from `ResearchDataset`.

## RT-R0 — Event Contract

Freeze typed events such as:

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

Common fields:

```text
event_id
event_time
received_at
available_at
provider
connection_id
subscription_id
sequence
asset / broker_symbol
quality
staleness
```

The event contract must support deterministic replay.

## RT-R1 — ReplayGateway

Build before relying on a live broker.

```text
immutable historical event log
        ↓
ReplayGateway
        ↓
same event bus used by broker gateways
```

Replay must support:

- normal stream;
- delayed/stale events;
- disconnect/reconnect;
- missing bars/ticks;
- duplicate events;
- out-of-order events where the contract permits simulation;
- partial/rejected order lifecycle fixtures.

This allows realtime algorithms, state projections and Workbench behavior to be tested before live integration.

## RT-R2 — Projection / State Store

First implementation should remain simple:

```text
Latest state → process memory / optional lightweight persistence
Event log    → append-only Parquet/SQLite as appropriate
Analysis     → DuckDB
```

Do not introduce Kafka/Flink/ClickHouse without demonstrated scale requirements.

Canonical projections:

```text
MarketState
StrategyState
PortfolioState
ExecutionState
AccountState
SystemHealthState
```

## RT-R3 — Live Workbench substrate

Register live panels into the existing Workbench shell:

```text
Market
Strategy
Portfolio
Execution
System Health
```

The browser consumes realtime projections through a controlled stream surface and never connects directly to MT5/QMT.

---

# 14. MT5-0 through MT5-6 — first broker implementation

MetaTrader 5 becomes the first concrete external broker path because it can be verified in the intended U.S. CFD environment.

Official MT5 Python documentation relevant to this plan:

- historical bars: `https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py`
- symbol specification: `https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py`

The MT5 documentation states that returned historical bars are limited to history available in the terminal/chart environment and affected by the terminal `Max. bars in chart` setting. Therefore **five years of M1 must be probed, not assumed**.

## MT5-0 — Broker Capability Probe

Read-only only.

Produce `BrokerCapabilityReport` for each target symbol:

```text
broker symbol
instrument mapping
M1 earliest/latest available
M1 row count / gap diagnostics
tick-history availability
spread fields
real_volume / tick_volume availability
digits / point / tick size
contract size
volume min/max/step
margin properties
swap properties
trade/fill modes
session metadata where accessible
```

No order authority.

## MT5-1 — Market Data Gateway

Implement:

```text
MT5 historical bar reader
MT5 tick reader
MT5 realtime quote/bar normalizer
```

Convert all timestamps into the frozen realtime/event semantics. MT5 Python APIs use UTC-oriented time semantics; local workstation timezone must not leak into evidence identity.

No order authority yet.

## MT5-2 — HF ↔ MT5 Cross-Source Reconciliation

Produce explicit reconciliation evidence instead of choosing one source silently.

Compare overlapping instruments/windows for:

```text
timestamp alignment
OHLC divergence
missing bars
session differences
spread availability
volume-definition differences
corporate-action discontinuities
broker CFD versus listed-equity price differences
```

Outputs must distinguish expected structural differences from data-quality failures.

## MT5-3 — Demo/PAPER Execution Gateway

Only after MT5-0–2 pass.

New broker-specific execution contracts should include concepts such as:

```text
CFDInstrumentSpec
CFDAccountState
CFDOrderCompiler
CFDFeeModel
CFDSpreadModel
CFDMarginModel
CFDSwapModel
MT5ExecutionVenue
```

Requirements:

- demo/PAPER account only;
- idempotent client order identity;
- explicit volume-step rounding;
- stale quote rejection;
- order/result mapping into canonical OrderEvent/TradeEvent;
- partial/reject handling;
- no hidden retry that can duplicate exposure;
- append-only operational audit.

## MT5-4 — Reconciliation / Safety / Recovery

Before any external PAPER is considered accepted:

```text
internal positions ↔ broker positions
internal cash/equity ↔ broker account state
open orders ↔ broker orders
fills ↔ deal history
restart recovery
connection recovery
stale-data gate
position/exposure limits
kill switch
incident ledger
```

## MT5-5 — Live Workbench Acceptance

Workbench must display:

```text
market freshness
connection state
strategy state
target/current exposure
orders/fills/rejects
broker account/positions
reconciliation drift
latency/health
kill-switch state
```

Live presentation remains projection-based and must not become a second trading engine.

## MT5-6 — Live-capital acceptance

This is a separate human-governed operational milestone, not an automatic consequence of successful demo/PAPER tests.

It requires a new explicit acceptance document covering broker/legal/account constraints, capital/risk limits, incident handling and human authorization.

No generic Workbench command automatically enables live capital.

---

# 15. Future QMT integration

When a real QMT interface is available, add:

```text
QMTGateway
```

over the already accepted RT contracts.

Expected reuse:

```text
Realtime Event Contract
Replay semantics
Projection / State Store
Live Workbench
health/freshness
reconciliation framework
Command/audit principles
```

Expected non-reuse / separate market semantics:

```text
MT5 CFD contract/margin/swap rules
A-share T+1
A-share price limits
A-share lot rules
QMT-specific callbacks/order-status vocabulary
```

The intended future architecture is:

```text
                   RT Event Contract
                          │
          ┌───────────────┼───────────────┐
          │                               │
     MT5Gateway                      QMTGateway
          │                               │
   U.S. CFD broker                  A-share broker
```

not MT5 code translated line-by-line into QMT code.

---

# 16. Migration workload assessment

The U.S. pivot is not a rewrite of FinAgent, but the difficult work is concentrated in data and execution layers.

| Module | Expected reuse | Change scale | Main work |
| --- | ---: | --- | --- |
| Agent framework | 85–95% | S | market context / prompt inputs |
| A2.6 robustness/statistics | 80–90% | S/M | intraday folds/horizons |
| Alpha/Risk protocol interfaces | 75–90% | M | minute features/session clock |
| Asset/evidence identity | >90% | S | research↔broker mapping |
| Workbench shell/context | 85–95% | S/M | intraday timestamp context |
| Factor analytics | 80–90% | M | dense intraday series |
| Strategy analytics | 70–85% | M | authoritative candles/events |
| Portfolio analytics | 80–90% | M | intraday density |
| Data ingestion/data plane | 30–50% | L/XL | out-of-core M1/certification |
| ResearchDataset materialization | 40–60% | L | sparse minutes/session-aware slices |
| Market calendar/actions | 30–50% | L | DST/half-days/actions |
| A-share A3 execution implementation | 15–30% direct reuse | L/XL replacement | CFD execution semantics |
| A4 execution-aware evidence | 60–75% | L | intraday/broker cost semantics |
| Broker gateway | new | XL | MT5 data/order/account |
| Realtime reconciliation | new | XL | state/recovery/safety |

Planning interpretation:

- roughly **65–75% of the product/research architecture is reusable**;
- roughly **25–35% requires substantial new implementation or refactoring**;
- the new work is disproportionately concentrated in the most failure-sensitive areas: data correctness, clock semantics, broker execution and reconciliation.

Therefore migration should be staged by contracts and evidence, not by attempting a direct end-to-end MT5 trading demo first.

---

# 17. Testing and CI policy

Every new stage must have at least:

```text
unit
contract
integration
identity/replay
failure-mode tests
```

## Historical Workbench

- Python API/semantic tests;
- Evidence GET-only route inventory;
- Control authority tests;
- TypeScript/Vitest/build;
- Playwright context/back/forward/reload;
- real A-share certification acceptance;
- legacy regression.

## Intraday data

- partition/source hash tests;
- session/DST/half-day fixtures;
- sparse-minute fixtures;
- corporate-action fixtures;
- resampling identity;
- label-horizon boundary tests;
- out-of-core memory behavior tests where practical.

## Realtime / MT5

- event replay determinism;
- duplicate/out-of-order handling;
- disconnect/reconnect;
- stale data;
- partial/reject lifecycle;
- idempotent submission;
- restart recovery;
- internal/broker reconciliation;
- kill switch;
- demo/PAPER-only authority tests before live-capital acceptance.

Windows compatibility remains useful but does not need to block ordinary reporting when a stage has a known asynchronous Windows path and the core acceptance matrix is otherwise complete.

---

# 18. Recommended bounded PR sequence

The exact branch names may change, but the capability boundaries should remain small.

```text
feature/v4-linked-analytics-acceptance          # A-C0
feature/historical-workbench-l1-services        # A-C1
feature/market-bar-series-evidence              # A-C2
feature/ashare-historical-e2e-acceptance        # A-C3

docs/initial-requirement-closure-audit          # A-C4
docs/ashare-historical-v1-freeze                 # A-C5

feature/us-dataset-provenance                    # US-D0
feature/intraday-market-contracts                # US-D1
feature/parquet-intraday-data-adapter            # US-D2
feature/intraday-resampling                      # US-D3
feature/us-minute-data-certification             # US-D4

feature/us-intraday-research-pilot               # US-R0/R1 bounded slices
feature/us-execution-aware-history               # US-R2
feature/us-historical-workbench-acceptance       # US-R3

feature/realtime-event-contract                  # RT-R0
feature/realtime-replay-gateway                  # RT-R1
feature/realtime-state-projection                # RT-R2
feature/live-workbench-substrate                 # RT-R3

feature/mt5-capability-probe                     # MT5-0
feature/mt5-market-data-gateway                  # MT5-1
feature/mt5-source-reconciliation                # MT5-2
feature/mt5-demo-execution                       # MT5-3
feature/mt5-operational-reconciliation           # MT5-4
feature/mt5-live-workbench-acceptance            # MT5-5
```

Single-PR rule remains:

- one evidence contract or one bounded product capability;
- schema changes include tests/docs;
- broker/control changes include adversarial authority tests;
- chart changes name exact evidence requirements;
- no factor tuning is hidden inside product/infrastructure PRs.

---

# 19. Explicitly deferred work

The following is not deleted; it is deferred until its prerequisite/decision exists.

## A-share production path

```text
A5 production reserve execution
A6 FinalStrategySpec / promotion
A6 internal PAPER
QMT broker integration
```

Resume only if A-share operational deployment becomes a target.

## Advanced evidence

```text
benchmark return/NAV
industry/style exposure
capacity/impact model
risk contribution
stress testing
signed final production audit bundle
```

These require authoritative core evidence before Workbench visualization.

## Live capital

Neither MT5 demo success nor QMT connectivity automatically authorizes live capital. Live-capital activation remains a separately frozen human-governed milestone.

---

# 20. Stage exit gates summary

| Stage | Exit gate |
| --- | --- |
| A-C0 | V4 Strategy/Factors/Portfolio/Execution linked acceptance passes |
| A-C1 | historical research/A2.6/A4 available through bounded audited L1 services |
| A-C2 | authoritative frequency/session-aware OHLC evidence accepted |
| A-C3 | real A-share dataset → Workbench E2E passes |
| A-C4 | every initial requirement classified with evidence |
| A-C5 | A-share Historical v1.0 freeze package recorded |
| US-D0 | exact HF source revision/provenance certified |
| US-D1 | minute/session/action contracts frozen |
| US-D2 | out-of-core M1 data path accepted |
| US-D3 | deterministic M1→higher interval evidence accepted |
| US-D4 | U.S. minute dataset certification passes |
| US-R1 | U.S. candidate/robust research evidence passes its own gates |
| US-R2 | execution-aware historical evidence is broker-semantic compatible |
| US-R3 | same Workbench architecture accepts U.S. intraday evidence |
| RT-R0 | provider-neutral replayable event schema frozen |
| RT-R1 | deterministic replay/failure fixtures pass |
| RT-R2 | canonical realtime state projections accepted |
| RT-R3 | Live panels consume projections only |
| MT5-0 | actual broker capabilities measured |
| MT5-1 | read-only broker market data normalized/verified |
| MT5-2 | research↔broker source differences reconciled |
| MT5-3 | demo order lifecycle safe/idempotent |
| MT5-4 | account/order/fill reconciliation + recovery + kill switch accepted |
| MT5-5 | Live Workbench demo/PAPER acceptance passes |
| MT5-6 | separate human live-capital acceptance only |

---

# 21. Immediate next implementation order

From `main @ 31ce20f7a6f78aee221e3649c5f6d2bb6e2fea0a`, development should proceed in this order:

```text
1. V4-5 / A-C0 Linked Analytics Acceptance
2. A-C1 Historical Workbench L1 application-service closure
3. A-C2 MarketBarSeriesEvidence + frequency/session contracts
4. A-C3 real A-share historical E2E acceptance
5. A-C4 initial requirement compliance audit
6. A-C5 A-share Historical v1.0 freeze
7. US-D0 exact Hugging Face dataset provenance/certification
8. US-D1/D2 intraday contracts + out-of-core M1 data plane
9. US-D3/D4 resampling + U.S. minute certification
10. US-R0/R1 pilot research
11. RT-R0/R1 event contract + ReplayGateway
12. MT5-0 capability probe
13. US-R2/R3 and MT5-1/2 convergence
14. MT5 demo/PAPER execution and operational acceptance
```

The project must **not** skip directly from V4-4 to broker order sending. The intended sequence remains:

```text
core/data correctness
→ immutable evidence
→ projection contract
→ Workbench acceptance
→ historical product freeze
→ intraday data correctness
→ U.S. research evidence
→ replayable realtime contracts
→ read-only broker integration
→ cross-source reconciliation
→ demo/PAPER execution
→ operational safety/reconciliation
→ separate live-capital gate
```

This sequence is the preliminary frozen development baseline for subsequent FinAgent work.
