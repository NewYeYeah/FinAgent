# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs propose hypotheses and bounded feature code; deterministic components own data chronology, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

## Current scope

The current baseline supports:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- bounded Agent-generated features with validation, restricted execution, repair and checkpointing;
- factor IC/RankIC/decay/quantile/turnover and stability/inference diagnostics;
- A2.6 immutable A-share ResearchPrograms with expanding walk-forward, robust gates, explicit no-alpha outcomes and exact replay;
- A3 exact-session A-share execution semantics including T+1, board quantity rules, suspension/price limits and asymmetric fees;
- A4 execution-aware internal portfolio validation with frozen-factor Alpha, risk, optimizer targets, gross/net ledgers and replay;
- A5 eligibility sealing, one-shot evaluation, crash-safe `CONSUMED`, terminal/ledger persistence and replay/audit;
- V4-0 authoritative `StrategyDecisionSeriesEvidence`: immutable signal/alpha → target → A3 order/fill → realized weight → gross/net PnL/cost rows persisted as manifest JSON + Parquet;
- V4-1 `FactorSeriesEvidence`: immutable primary/decay IC, quantile/long-short return, turnover and coverage period rows plus explicitly derived rolling IC/NAV persisted as manifest JSON + Parquet;
- V4-2 Strategy Decision Explorer: verified bounded V4-0 GET APIs plus an interactive Strategy Workbench for close/reference/fill price, alpha, target/realized weight, order/fill constraints and gross/net cost evidence;
- V4-3 Factor Tear Sheet: verified bounded V4-1 GET APIs plus an interactive Factors Workbench for IC/decay, quantile/long-short, turnover/coverage, frozen inference/multiplicity and factor-correlation evidence;
- V4-4 Portfolio / Execution Interactive Pack: authoritative A4 NAV/performance plus verified V4-0 asset/order/weight/cost/PnL rows, with server-side derived drawdown, rolling/monthly performance, cost and constraint attribution;
- Alpaca SIP US reference ingestion and local A-share Parquet research;
- V2/A5 evidence review and the accepted V3 Workbench foundation: Agent indexing, governed local Control, typed deep links, sanitized product SSE and cross-plane acceptance;
- an explicit two-plane Workbench architecture: GET-only Evidence + local governed Control;
- legacy Streamlit/Plotly and optional Phoenix diagnostics retained.

The market priority remains **A-share historical research first**. A-share live capital/realtime acceptance remains deferred until frozen research, execution-aware validation, reserve governance and repeated PAPER gates are complete.

The V3 Workbench Foundation is complete through **V3-5 acceptance**, and V4 linked analytics is complete through **V4-4 Portfolio / Execution Interactive Pack**. The current development milestone is **V4-5 — Linked Analytics Acceptance**, which validates authority declarations, bounded read behavior and cross-module `WorkbenchContext` interactions across the delivered Strategy, Factors, Portfolio and Execution surfaces.

## Quick start

Python 3.11+ is required.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional dependencies:

```bash
python -m pip install -e ".[llm]"           # DeepSeek / SiliconFlow / OpenAI transport
python -m pip install -e ".[us-market]"     # Alpaca
python -m pip install -e ".[cn-free]"       # AKShare
python -m pip install -e ".[a-share]"       # Tushare
python -m pip install -e ".[local-parquet]" # local A-share Parquet / DuckDB
python -m pip install -e ".[observability]" # OTLP Agent trace exporter
python -m pip install -e ".[visualization]" # legacy Streamlit / Plotly inspector
python -m pip install -e ".[workspace]"     # FastAPI / Uvicorn Workbench APIs
```

## A-share research-to-execution flow

```text
Frozen local Parquet
        ↓
A2.6 robust ResearchProgram
        ↓
Frozen factor family / explicit no-alpha result
        ↓
A3 target-to-executable-order semantics
        ↓
A4 internal gross/net portfolio validation
        ↓
Visualization V2 + human review
        ↓
A5 eligibility / one-shot reserve governance
        ↓
Independent human-authorized production reserve operation
        ↓
RESERVE_PASS → A6 Strategy Freeze / PAPER
RESERVE_FAIL → no promotion; same reserve never reused for modified-strategy validation
```

A completed A4 report remains `promotion_eligible=false`. No production 2025+ reserve is consumed by development or CI.

## V4-0 StrategyDecisionSeriesEvidence

V4-0 adds a separate deterministic evidence layer over immutable A2.6/A4 artifacts. It does **not** modify the existing A4 report or JSONL execution-ledger schema and does not rerun risk, optimizer or execution.

The authoritative path is materialized per `(fold_id, session_date, asset)`:

```text
formation alpha score / rank
        ↓
portfolio target
        ↓
A3 desired quantity
        ↓
A3 executable quantity / constraint reasons
        ↓
fill quantity / reference price / execution price
        ↓
close realized weight
        ↓
gross PnL / fees / slippage / net PnL
```

The missing formation-time alpha vector is reconstructed by replaying only the exact frozen A4 AlphaModel. Every fold must rebuild to the same A4 `alpha_model_id`; prediction uses formation features/PIT eligibility only, and no forward label rows are requested. The combined score is recovered from the verified train-only calibration and ranked deterministically.

Asset PnL follows the A4 wealth identity and is reconciled on every source session:

```text
asset_pnl
= current_close_market_value
- previous_close_market_value
- signed_executed_notional
- actual_fees

sum(asset gross_pnl) == A4 gross NAV change
sum(asset net_pnl)   == A4 net NAV change
```

Slippage is already embedded in net execution price and is also retained as explanatory cost evidence; it is not subtracted twice.

Materialize from an existing A4 validation:

```bash
python scripts/materialize_strategy_decision_series.py \
  configs/research/ashare_portfolio_validation.local.toml \
  --a4-report reports/ashare_a4.json \
  --ledger reports/ashare_a4_ledger.jsonl
```

Default outputs are siblings of the A4 report:

```text
<report-stem>.strategy-decisions.json
<report-stem>.strategy-decisions.parquet
```

The manifest binds A4/A2.6/data/factor/AlphaModel/ledger/row identities plus physical SHA-256 values. `StrategyDecisionSeriesProjection` verifies those bindings and exposes bounded read-only asset/fold/date queries with at most 5,000 rows per request. V4-2 consumes this verified projection directly rather than reconstructing the decision path from A4 summary reports.

## V4-1 FactorSeriesEvidence

V4-1 adds a separate deterministic evidence layer over the frozen A2.6 ResearchProgram. It does **not** rewrite the A2.6 report, does not select factor direction from the test period and does not access the production reserve.

Long-form evidence is persisted for every frozen candidate and internal walk-forward test fold:

```text
factor / fold / session
        ↓
raw Pearson IC / RankIC by primary + decay horizon
        ↓ frozen train_direction
oriented Pearson IC / RankIC
        ↓
Q1–Qn primary-label return
long-short return
one-way turnover
coverage
        ↓
rolling IC + cumulative Q/NAV transforms
```

Raw/oriented IC, return, turnover and coverage rows are authoritative. Rolling IC and cumulative quantile/long-short NAV are persisted deterministic transforms and remain explicitly `authority=derived`.

Before any V4-1 file is written, the rematerialized rows must reproduce the frozen A2.6 report for every candidate/fold, including RankIC/ICIR, raw/oriented long-short Sharpe, coverage, quantile monotonicity, turnover and period counts. Candidate-level pooled/fold metrics, direction consistency and horizon-sign consistency are also reconciled. Any disagreement fails closed.

Materialize from an existing A2.6 report:

```bash
python scripts/materialize_factor_series.py \
  configs/local_ashare_robust_research.toml \
  --a2p6-report reports/ashare_a2p6.json \
  --rolling-window 20
```

Default outputs are siblings of the A2.6 report:

```text
<report-stem>.factor-series.json
<report-stem>.factor-series.parquet
```

`FactorSeriesProjection` verifies source-report/manifest/Parquet identity and supports bounded filters over factor, fold, date, series kind, metric, label horizon and quantile with at most 5,000 rows per request. The delivered V4-3 Factor Tear Sheet consumes this evidence rather than recreating missing IC/quantile/turnover history from A2.6 summary reports.

## V4-2 Strategy Decision Explorer

V4-2 activates the **Strategy** module in the V3 Workbench and exposes verified V4-0 series through GET-only Evidence Plane endpoints:

```text
GET /api/v4/strategy-series
GET /api/v4/strategy-series/by-portfolio/{portfolio_validation_id}
GET /api/v4/strategy-series/{series_id}
GET /api/v4/strategy-series/{series_id}/dimensions
GET /api/v4/strategy-series/{series_id}/decisions
```

A series is visible only after its V4-0 source A4 report, execution ledger and Parquet pass existing identity/SHA/schema/row verification. Decision queries accept only asset/fold/date/offset filters and remain bounded to `limit <= 5000`; the browser never supplies host paths or executable inputs.

The Strategy page uses the existing `WorkbenchContext` keys `portfolio_validation_id`, `asset_id`, `date_range`, `session_date` and `fold_id`, and renders authoritative per-session V4-0 facts:

- close/reference/fill price timeline with buy/sell fill markers;
- pre-trade / target / realized weights;
- combined frozen AlphaModel score, rank, expected return and uncertainty;
- desired / executable / filled quantities and A3 constraint codes;
- gross/net asset PnL, fees and slippage;
- frozen factor/program/selection/AlphaModel identity context.

Two non-fabrication boundaries are explicit. First, V4-0 does not persist authoritative open/high/low values, so V4-2 reports `ohlc_available=false` and renders a **close-price execution timeline**, not synthetic candlesticks. Second, V4-0 does not persist per-asset factor-component contributions, so the page shows combined alpha plus frozen factor identities and does not reverse engineer contribution values in React.

Equivalent deterministic V4-0 rematerializations are de-duplicated by semantic series identity even when output filenames differ; genuine semantic conflicts fail closed. If optional DuckDB/local-Parquet support is absent, Strategy series become unavailable with explicit warnings while unrelated V3/V2 Workspace surfaces continue to start.

## V4-3 Factor Tear Sheet

V4-3 activates the **Factors** module at `/factors` and exposes verified V4-1 series through GET-only Evidence Plane endpoints. It combines V4-1 period rows with the frozen A2.6 statistical summaries that produced those rows; it does not create a second factor-statistics implementation in React.

The Factor Tear Sheet renders:

- authoritative primary/decay RankIC and Pearson IC period evidence;
- persisted derived rolling IC;
- persisted derived Q1–Qn and long-short NAV over authoritative period returns;
- authoritative one-way turnover and coverage;
- server-derived fold/year IC means with explicit `derived_presentation` authority;
- frozen A2.6 HAC statistics, block-bootstrap p-value/95% CI, Holm adjusted p-value and BH q-value;
- frozen gate result/reason codes and selected-component state;
- frozen factor correlation values with server-derived hierarchical ordering;
- frozen candidate identity, hypothesis, generator ID and lookback provenance.

The page uses URL-backed `WorkbenchContext` keys `program_id`, `factor_id`, `fold_id` and `date_range`. V4-3 also makes a deliberate chronology boundary explicit: A2.6 freezes candidate denominator identity/provenance/order but not Agent generation timestamps or discovery rounds. Therefore `agent_chronology_available=false`, and the denominator order is never presented as an Agent evolution timeline.

Rows remain bounded to `limit <= 5000`, all `/api/v4/factor-series*` surfaces are GET-only, and no V4-3 route adds reserve, promotion, PAPER, broker/live, shell/Python or other Control authority.

## V4-4 Portfolio / Execution Interactive Pack

V4-4 activates the canonical **Portfolio** and **Execution** Workbench modules by linking two existing authorities rather than creating a new calculation engine: A4 owns portfolio-level NAV/period returns/frozen performance metrics, while verified V4-0 `StrategyDecisionSeriesEvidence` owns asset/order/weight/quantity/price/cost/PnL/constraint rows.

The Evidence Plane exposes GET-only `/api/v4/portfolio-execution*` catalog, detail, portfolio-series, analytics and decision routes. Browser row requests remain bounded to `limit <= 5000`; server-side aggregation over larger verified V4-0 evidence iterates the existing bounded projection in pages so transport limits never silently truncate the resulting presentation aggregate.

The Portfolio surface renders authoritative A4 gross/net NAV and frozen aggregate metrics together with explicitly `derived_presentation` drawdown, rolling performance, monthly returns and filtered fee/slippage totals. The Execution surface renders authoritative V4-0 target/realized weights and bounded decision rows with `client_order_id`, desired/executable/filled quantity, prices, costs, PnL and `constraint_codes`, plus derived order-funnel and constraint-count views.

`WorkbenchContext` now includes durable `order_id -> ?order=` in addition to portfolio, asset, session, date-range and fold identity. Portfolio ↔ Execution navigation and reload preserve these identities. A selected session constrains both authoritative Execution rows and the corresponding server-side derived execution aggregates; account-level Portfolio NAV is never spuriously filtered by asset/order identity.

V4-4 explicitly reports benchmark return/NAV evidence as unavailable rather than inventing benchmark-relative metrics. React remains presentation-only and does not recompute NAV, return, drawdown, rolling/monthly statistics, costs or constraint aggregates.

## FinAgent Workbench V3.5+

The accepted Workbench keeps two independent authority planes and combines deterministic context, typed navigation, notification streaming and V4 linked analytics without merging authority:

```text
Evidence Plane  127.0.0.1:8765
  GET-only / read-only projections
  V3-3 typed refs + bounded Artifact Inspector
  V3-4 Agent / CommandRun SSE notifications
  V4-2 Strategy Decision Explorer projections
  V4-3 Factor Tear Sheet projections
  V4-4 Portfolio / Execution linked projections

Control Plane   127.0.0.1:8766
  explicit local opt-in
  typed application_service_ready L0/L1 commands only
  durable CommandIntent → CommandRun → CommandResult audit
```

The Evidence Plane never acquires a command mutation route. Starting Control is a separate user action. SSE is notification-only: complete Agent and CommandRun details still come from their canonical audit/durable records.

V3-5 verifies the foundation as a whole: complete API route inventories, Evidence GET-only behavior, exact bounded Control authority, rejected L2/L3/A5-like commands, durable cross-plane command identity, context restoration through browser history/reload, sanitized SSE reconnect/disconnect/terminal behavior and Ubuntu/Windows/frontend regression. V4-2/V4-3/V4-4 add only GET analytical projections on top of that accepted authority boundary.

### Build the frontend

```bash
python -m pip install -e ".[workspace,local-parquet]"
cd workspace
npm ci
npm run build
cd ..
```

### Start the Evidence Plane

```bash
python scripts/run_workspace.py \
  --reports reports \
  --configs configs \
  --agent-audit .finagent/agent_audit.sqlite \
  --command-store .finagent/workbench/commands.sqlite \
  --open-browser
```

Open `http://127.0.0.1:8765`.

The command-store path may be configured before the Control process creates the SQLite file. Evidence readers use SQLite read-only mode; once the store appears, CommandRun deep links/SSE become available without restarting Workspace. V4 Strategy/Factor/Portfolio/Execution analysis additionally requires the `local-parquet` extra to open verified columnar evidence; if it is absent, unrelated Workspace surfaces remain available with explicit analytical warnings.

### Explicitly start the local Control Plane

```bash
python scripts/run_workbench_control.py \
  --configs configs \
  --reports reports
```

Defaults:

```text
Control URL   http://127.0.0.1:8766
Command DB    .finagent/workbench/commands.sqlite
Export dir    .finagent/workbench/exports
```

The Control launcher refuses non-loopback hosts. When it is absent, the Workbench Commands button stays disabled and there is no fallback execution path.

### Current command readiness

Executable through the generic V3 Control Plane:

```text
config.validate              L0  application_service_ready
data.certify_local_ashare    L0  application_service_ready
review.export_bundle         L0  application_service_ready
```

Visible but deliberately non-executable:

```text
research.run_development     L1  adapter_required
research.run_a2p6            L1  adapter_required
portfolio.run_a4             L1  adapter_required
```

A2/A2.6/A4 remain `adapter_required` because their current scripts still own substantial orchestration. V3/V4 do **not** use `subprocess`, arbitrary shell or browser-supplied Python to make them appear ready. Their readiness can change only in a reviewed change that extracts the real typed application service.

### Durable command and SSE semantics

`SQLiteCommandStore` persists intent/run/result/event state before and during execution. Request IDs are idempotency keys; conflicting reuse fails closed. On process restart, incomplete `planned`/`running` work becomes explicit terminal `failed` and is never automatically retried.

The Command Palette binds only typed inputs:

- exact `command_id`;
- approved ConfigSnapshot when required;
- allowlisted `WorkbenchContext`;
- explicit confirmation where required.

V3-4 replaces the former 600 ms active-CommandRun lifecycle polling with Evidence Plane SSE. A normalized SSE snapshot only signals state change; the browser then refreshes the complete Control record. If SSE is unavailable, there is no hidden timed-poll fallback; the Run Inspector exposes an explicit manual refresh.

SSE deliberately excludes prompts/hidden reasoning, raw provider callbacks, raw OTLP/Phoenix spans, CommandRun parameters/outputs/artifact paths/free-form messages and host filesystem paths.

The browser cannot submit generic executable arguments, output filesystem paths, shell commands or Python code. Review-bundle report/output paths are injected server-side.

Generic Control authority explicitly excludes:

```text
production reserve
strategy promotion
PAPER mutation
broker order
live capital
arbitrary shell
arbitrary Python
```

## Current Workbench capabilities

- rebuildable derived Evidence Catalog and protocol comparison;
- A2.6 lifecycle, Gate matrix, statistical forest and fold evidence;
- A4 gross/net NAV, economic evidence and execution realization;
- A5 eligibility/consumption/terminal/ledger/audit inspection;
- Agent Project → Thread → Run navigation and verified artifact links;
- typed URL-backed `WorkbenchContext` across research/portfolio/Agent/Strategy/Factor selections;
- V3-3 `WorkbenchReference` navigation across Agent / Factor / ResearchProgram / A4 / A5 / Config / CommandRun identities;
- bounded, verified source-report/generated-feature Artifact Inspector;
- public Config Registry with secret-file exclusion and recursive credential redaction;
- read-only Command Catalog with real readiness metadata;
- separate local Command Palette and persisted Run Inspector;
- V3-4 normalized Agent + CommandRun SSE with deterministic event IDs and explicit no-hidden-reasoning boundary;
- V3-5 cross-plane, authority, context-history, SSE lifecycle and browser-mode acceptance coverage;
- V4-0 verified bounded StrategyDecisionSeries evidence;
- V4-1 verified bounded FactorSeries evidence;
- V4-2 linked Strategy Decision Explorer with explicit close-only/no-browser-recompute semantics;
- V4-3 linked Factor Tear Sheet with frozen A2.6 inference/multiplicity/correlation summaries and explicit derived-presentation labels;
- V4-4 linked Portfolio / Execution analytics with authoritative A4/V4-0 sources, server-side presentation derivatives, durable order/session context and explicit benchmark-unavailable semantics;
- context-preserving navigation and typed server-state cache/de-duplication boundary.

Configuration editing remains read-only. Protocol changes must become new governed identities/forks rather than rewriting historical evidence.

## Core boundary

```text
Provider / local data
        ↓
DataAdapter → ResearchDataset
        ↓
Agent hypothesis / generated feature
        ↓
Factor Quant / robust ResearchProgram
        ↓
Frozen multi-factor AlphaModel
        ↓
RiskModel → Portfolio Optimizer
        ↓
Market-specific execution rules
        ↓
Internal validation / reserve governance
        ↓
Human-approved paper/shadow operations
```

The Agent never owns positions, fills, risk limits, validation thresholds or broker state. The Evidence Plane never owns prompts, numerical evidence or lifecycle transitions. The generic Control Plane owns only allowlisted application-service invocation and its command audit; it does not become trading authority.

## Research / governance invariants

1. Features use only information available at `asof`.
2. Forward labels never define formation eligibility.
3. Failed/weak trials remain in the search denominator.
4. Frozen families replay without silent mutation.
5. Provider changes create new evidence identities; fallback is never silent.
6. Research and executable prices remain separate where required.
7. A software test pass or Control success is not evidence of persistent alpha/live readiness.
8. Viewing validation evidence cannot make the same window clean for a modified program.
9. A4 cannot consume reserve, alter A2.6 factor direction/weight or bypass A3 rules.
10. Portfolio/execution evidence must reproduce through exact identities.
11. Presentation derivatives never replace authoritative evidence.
12. Durable reserve `CONSUMED` is irreversible.
13. Protocol edits create new identities/forks rather than rewriting prior evidence.
14. Generic Workbench commands never receive reserve/promotion/PAPER/broker/live authority.
15. Workbench config projection never exposes credential values.
16. `application_service_ready` must match a real registered in-process service binding.
17. Command restart recovery never silently retries incomplete execution.
18. Workbench deep links resolve verified canonical identities and fail closed on ambiguity.
19. SSE is a sanitized notification projection, never an alternate evidence/control authority.
20. Product streams never expose hidden reasoning, raw provider/OTLP/Phoenix payloads or host paths.
21. V3 foundation acceptance does not imply alpha persistence, reserve authorization, promotion or live readiness.
22. V4 authoritative series bind immutable core identities and reconcile to source evidence before presentation code may consume them.
23. V4-0 materialization never rewrites A4 evidence or grants reserve, promotion, PAPER, broker or live authority.
24. V4-1 materialization never rewrites A2.6 evidence, never selects direction from test data and never relabels rolling/NAV transforms as authoritative raw factor evidence.
25. V4-2 never fabricates missing OHLC or per-factor contribution evidence and never turns a read-only linked analytics surface into trading/control authority.
26. V4-3 never reconstructs frozen factor inference/multiplicity evidence in React and never presents candidate denominator order as an Agent generation chronology.
27. V4-4 never reconstructs authoritative A4/V4-0 portfolio or execution facts in React and never infers benchmark/exposure evidence that core has not persisted.

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Market data and local A-share datasets](docs/guides/data-sources.md)
- [Agent research workflow](docs/guides/agent-research.md)
- [A-share execution semantics](docs/guides/ashare-execution.md)
- [A-share portfolio validation](docs/guides/ashare-portfolio-validation.md)
- [FinAgent Workspace / Workbench](docs/guides/workspace.md)
- [A-share reserve governance](docs/guides/ashare-reserve.md)
- [Testing and acceptance](docs/testing/testing.md)
- [Architecture overview](docs/architecture/overview.md)
- [Workbench architecture v3.1](docs/architecture/workbench-v3.md)
- [Roadmap](docs/development/roadmap.md)
- [V3-4 changelog](docs/development/changelog-v3-4.md)
- [V3-5 acceptance](docs/development/changelog-v3-5.md)
- [V4-0 StrategyDecisionSeries contract](docs/development/changelog-v4-0.md)
- [V4-1 FactorSeries contract](docs/development/changelog-v4-1.md)
- [V4-2 Strategy Decision Explorer](docs/development/changelog-v4-2.md)
- [V4-2 read API contract](docs/development/v4-2-api-contract.md)
- [V4-3 Factor Tear Sheet](docs/development/changelog-v4-3.md)
- [V4-4 Portfolio / Execution Interactive Pack](docs/development/changelog-v4-4.md)
- [V4-4 read API contract](docs/development/v4-4-api-contract.md)
- [Changelog](docs/development/changelog.md)

## Data note

The local A-share database is treated as immutable vendor raw data. FinAgent normalizes units and time semantics but does not automatically trust undocumented vendor factors or claim survivorship-free coverage when delisting/list-status history is incomplete. Supplemental historical reference data remains separate from raw vendor data.

## License and data rights

FinAgent code and third-party market data have separate licensing/usage constraints. Users are responsible for complying with provider terms and entitlements. Do not commit API keys or paid/raw datasets to the repository.
