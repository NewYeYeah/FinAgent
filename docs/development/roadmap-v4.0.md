# FinAgent Roadmap v4.0 — A-share Closure → U.S. M1 / MT5

Status: **preliminary frozen roadmap index**  
Planning baseline: `main @ 31ce20f7a6f78aee221e3649c5f6d2bb6e2fea0a`  
Implementation status: **A-C0 / V4-5 complete; A-C1 complete; A-C2 complete; A-C3 current**  
Detailed planning authority: [`current-development-plan-v4.0.md`](current-development-plan-v4.0.md)

This short roadmap is the execution index for the v4.0 planning baseline. Existing `roadmap.md`, `current-development-plan-v3.1.md` and completed V0–V4/A2.6–A5 documents remain valid historical/contract records. Where post-V4-5 priority ordering differs, **v4.0 governs new development after this planning baseline is accepted**.

## Current

### Completed — A-C0 / V4-5 Linked Analytics Acceptance

- accepted Strategy / Factors / Portfolio / Execution as one linked analytical product;
- added a machine-readable acceptance-only contract with exact evidence, authority and unavailable-evidence declarations;
- froze `browser_recomputation=false` across all four analytical surfaces;
- accepted `program/factor/portfolio/asset/order/range/session/fold` WorkbenchContext round-trip through module navigation, browser history and reload;
- retained browser `limit <= 5000` and explicitly tested full server-side aggregation across a 5,001-row execution evidence set;
- retained Evidence GET-only and the V3 Control L0/L1 authority ceiling;
- advanced the Workbench capability to `finagent-workbench-api-v4.5`;
- recorded the implementation in [`changelog-v4-5.md`](changelog-v4-5.md).

### Completed — A-C1 Historical Workbench Operational Closure

Delivered typed L1 application-service entry points for the historical pipeline with durable CommandRun audit:

```text
research.run_development
research.run_a2p6
portfolio.run_a4
```

Accepted composition:

```text
Workbench / CLI / future Agent adapter
                ↓
        typed Application Service
                ↓
      immutable historical evidence
                ↓
          durable CommandRun audit
```

Completion properties:

- extracted A2/A2.5, A2.6 and A4 orchestration from fat scripts into reusable in-process application workflows;
- retained the three scripts as thin compatibility wrappers over the same workflow functions;
- added a dedicated Historical Control Plane composition over the frozen V3 command vocabulary;
- kept the three newly operational commands at L1 with explicit confirmation required;
- preserved `SQLiteCommandStore` lifecycle/audit and evidence identities;
- kept production reserve, promotion, PAPER, broker, live-capital, arbitrary shell and arbitrary Python authority forbidden;
- added a PowerShell launcher that uses native Python/`py -3.11` argument forwarding without Bash dependency;
- accepted on Ubuntu/Python 3.11 with 55 focused backend tests + `py_compile`, Ruff/focused mypy/`pip check`, TypeScript, 34 Vitest tests, production build and 11 Playwright tests;
- recorded the implementation in [`changelog-a-c1.md`](changelog-a-c1.md).

### Completed — A-C2 MarketBarSeriesEvidence + Frequency Contract

Delivered provider-neutral market-bar authority and authoritative Strategy candlesticks without changing V4-0 strategy/execution authority.

Frozen contract surface:

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

Accepted authority composition:

```text
StrategyDecisionSeriesEvidence V4-0
  → signal / target / order / fill / constraint / PnL

MarketBarSeriesEvidence A-C2
  → OHLCV / interval / timestamp / session

Strategy Workbench
  → read-only presentation overlay
```

Completion properties:

- added content-addressed MarketBarSeries manifest + Parquet evidence with SHA/count/identity verification;
- retained bounded browser queries with `limit <= 5000`;
- froze A-share session semantics including the 11:30–13:00 lunch break;
- froze bar-count/trading-minute/same-session/trading-day label-horizon vocabulary for later minute research;
- bound MarketBarSeries to Strategy only when strategy-series, portfolio-validation and data-version identities match exactly;
- fail-closed on identity mismatch or conflicting MarketBarSeries;
- added GET-only market-bar binding/row endpoints;
- added host-side certified A-share 1d materialization and 1min contract-smoke path without adding Control authority;
- rendered authoritative candlesticks + V4-0 reference/fill overlays when evidence is present;
- retained the V4-2 close-only path with explicit unavailable state when MarketBarSeries is absent;
- generalized V4-5 acceptance so OHLC may exist only when its authority is explicitly `MarketBarSeriesEvidence`;
- removed the Windows Workspace API matrix from this development line; Ubuntu/Python 3.11 is the blocking Python environment;
- accepted with 60 focused backend tests + `py_compile`, Ruff/mypy/`pip check`, TypeScript, Vitest 35/35, production build and Playwright 11/11;
- recorded the implementation in [`changelog-a-c2.md`](changelog-a-c2.md).

### Current — A-C3 Real A-share Historical E2E Acceptance

Run one real frozen A-share historical chain through the complete accepted architecture and verify that every Workbench surface resolves to the same immutable identities.

Required chain:

```text
local dataset certification
→ development research
→ A2.6 robust research
→ A4 execution-aware validation
→ StrategyDecisionSeries
→ FactorSeries
→ MarketBarSeries
→ Historical Workbench
→ review bundle
```

Required acceptance focus:

- real frozen dataset / program / selection / A4 / V4 evidence identities are recorded;
- Workbench values match authoritative evidence rather than browser recomputation;
- Strategy displays authoritative OHLC when the matching MarketBarSeries exists;
- Factor / Portfolio / Execution retain their frozen authority boundaries;
- linked Context survives navigation/history/reload;
- review bundle resolves the same evidence identities;
- missing benchmark/exposure/capacity/risk-contribution evidence stays explicitly unavailable;
- production reserve remains untouched;
- a small 1min A-share sample may be used only for intraday contract smoke, not a full minute research rerun.

## A-share historical closure

### A-C4 — Initial Requirement Compliance Audit

Classify every original requirement as:

```text
PASS / PARTIAL / DEFERRED / N/A
```

Each classification must reference implementation and test/evidence.

### A-C5 — A-share Historical v1.0 Freeze

Record the accepted Git/evidence identities, acceptance matrix and deferred capabilities. Production reserve remains untouched unless separately authorized for an A-share operational strategy.

## U.S. minute Data Plane

### US-D0 — Dataset Provenance

Resolve the exact revision, inventory, hashes, schema, license, origin and semantics of:

`https://huggingface.co/datasets/vessel888/OHLCV-1m/tree/main`

Do not assume coverage/size/adjustment semantics before certification.

### US-D1 — Intraday / Session / Corporate Actions

Freeze:

```text
BarInterval
SessionCalendar / SessionSegment
BarTimestampConvention
LabelHorizonPolicy
CorporateActionEvent
CashEvent
```

### US-D2 — Out-of-core M1 Data Adapter

Use partitioned Parquet + DuckDB/Arrow-style bounded scans instead of full-dataset pandas/NumPy materialization.

### US-D3 — Deterministic Resampling

Canonical derived bars:

```text
1m → 5m → 15m → 30m → 60m
```

First research target should normally use 5m/15m signals with 1m execution simulation rather than one-minute HFT turnover.

### US-D4 — U.S. Minute Data Certification

Certify timezone/DST/session/gaps/OHLC/corporate actions/symbol mapping/survivorship/source identity before robust research.

## U.S. historical research

### US-R0 — Pilot Universe

Start with ~20–50 liquid instruments, preferably within:

```text
certified HF history ∩ MT5 CFD availability ∩ acceptable liquidity/spread
```

### US-R1 — Intraday Agent / A2.6 Research

All U.S. factors re-enter the candidate denominator and robust gates. A-share PASS results are not U.S. evidence.

### US-R2 — Execution-aware U.S. Historical Portfolio

Introduce broker-compatible spread/contract/volume/margin/swap semantics without reusing A-share T+1/price-limit rules as defaults.

### US-R3 — U.S. Historical Workbench Acceptance

Reuse the existing Workbench architecture for intraday evidence without provider-specific frontend forks.

## Provider-neutral realtime substrate

### RT-R0 — Realtime Event Contract

Freeze replayable `QuoteEvent`, `BarEvent`, `MarketStatusEvent`, `AccountStatusEvent`, `OrderEvent`, `TradeEvent`, `OrderErrorEvent`, `ConnectionEvent`.

### RT-R1 — ReplayGateway

Develop and test normal/stale/disconnect/duplicate/out-of-order/partial/reject scenarios before broker order integration.

### RT-R2 — Projection / State Store

Canonical Market / Strategy / Portfolio / Execution / Account / SystemHealth state over append-only event evidence.

### RT-R3 — Live Workbench Substrate

Register Market / Strategy / Portfolio / Execution / System Health panels into the existing shell. Browser consumes projections, never MT5/QMT directly.

## MT5 broker path

### MT5-0 — Capability Probe

Read-only measurement of broker symbols, actual M1/tick depth, volume constraints, spread, contract size, margin/swap and execution modes.

Five years of M1 is a measured capability, **not a frozen assumption**. MT5 official Python documentation states bar availability depends on terminal/chart history and the `Max. bars in chart` setting.

### MT5-1 — Market Data Gateway

Read-only historical/realtime bar/tick normalization into RT contracts.

### MT5-2 — HF ↔ MT5 Reconciliation

Persist timestamp/OHLC/session/volume/corporate-action/CFD-vs-equity differences rather than silently selecting one source.

### MT5-3 — Demo/PAPER Execution

Broker-specific CFD execution semantics, idempotent order identity, partial/reject handling and append-only audit. Demo/PAPER only.

### MT5-4 — Operational Reconciliation / Safety

Positions, account, orders, fills, restart/recovery, stale-data gate, risk limits, kill switch and incident ledger.

### MT5-5 — Live Workbench Acceptance

Accept broker freshness, exposure, order lifecycle, reconciliation drift and system health in demo/PAPER mode.

### MT5-6 — Live-capital Acceptance

Separate human-governed milestone. Never implied by successful demo/PAPER tests.

## Future QMT

QMT is deferred as a broker adapter, not abandoned:

```text
RT Event Contract
       ├─ MT5Gateway
       └─ QMTGateway   # when a real interface is available
```

Reuse realtime/event/state/Workbench/reconciliation infrastructure; retain A-share-specific execution semantics separately.

## Explicitly deferred

- A5 production reserve execution solely for historical closure;
- A6 A-share promotion/PAPER unless A-share operational deployment resumes;
- benchmark/style/industry/capacity/risk-contribution charts without authoritative evidence;
- generic live-capital commands;
- a complete A-share minute research stack before the U.S. pivot;
- unverified QMT callback/order implementation.

## Immediate order

```text
A-C3
→ A-C4
→ A-C5
→ US-D0
→ US-D1 / US-D2
→ US-D3 / US-D4
→ US-R0 / US-R1
→ RT-R0 / RT-R1
→ MT5-0
→ US-R2 / US-R3 + MT5-1 / MT5-2
→ MT5-3 / MT5-4 / MT5-5
→ separate MT5-6 live-capital gate
```
