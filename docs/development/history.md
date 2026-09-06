# Development history that still matters

This is **not** a chronological changelog. It preserves only completed work and negative results that constrain or materially inform the active roadmap. Exact implementation details remain in Git and pull-request history.

## 1. A-share historical line

The A-share historical product line was accepted as `finagent-ashare-historical-v1.0` on 2026-09-01.

Durable facts:

- historical research, portfolio/execution evidence and a React/FastAPI Workbench were integrated;
- Workbench automated browser acceptance passed;
- the release ended with `NO_ROBUST_FACTOR_FAMILY` rather than a promoted strategy;
- production reserve was not consumed;
- Strategy, Factor, Portfolio and Execution analytical surfaces, Evidence/Control separation and linked context are reusable product assets;
- the historical browser smoke is **not** a fresh human usability study for the new U.S./Agent roadmap.

Frozen interpretation: [`../releases/ashare-historical-v1.md`](../releases/ashare-historical-v1.md).

The A-share line should not be reopened for feature accumulation except correctness/security fixes or compatibility needed by a reused component.

## 2. U.S. minute data and broker engineering baseline

The project moved to U.S. minute research because minute-scale speculative research and later MT5 execution were the primary target.

Accepted baseline that remains relevant:

- research source: `mito0o852/OHLCV-1m`;
- immutable source revision: `776328445b7ac6e7815ef3a483e9c8ded1eb6d56`;
- local non-redistributed research admission under bounded cleaning/quarantine;
- XNYS calendar/session contracts and minute resampling/label infrastructure;
- present-symbol 25-name EngineeringUniverse with target-broker mappings;
- target broker/server evidence observed as `TradeMaxGlobal-Live` for the accepted mapping/reconciliation path;
- listed equity history and broker CFD identity are intentionally distinct;
- the universe is survivorship conditioned because a PIT security master is absent.

Current 25-name EngineeringUniverse:

```text
AAPL AMD AMZN AVGO COIN EEM GLD GOOG GOOGL INTC
IWM JPM META MSFT MSTR MU NFLX NVDA ORCL PLTR SNDK
TSLA TSM XLE XOM
```

Publication/redistribution rights for the historical source remain limited because the dataset does not publish a complete upstream license/redistribution chain.

## 3. US-B0 / US-A0 / US-R1

The first U.S. research cycle established deterministic baselines, a controlled Agent-generation experiment and a formal robustness gate.

Durable conclusions:

- deterministic manual baselines were implemented;
- the first Agent experiment demonstrated structural novelty but did not establish repeatable quality superiority over non-Agent baselines;
- the complete R1 denominator was evaluated without result-dependent filtering;
- R1 ended `NO_ROBUST_FACTOR_FAMILY`;
- Agent novelty alone is not sufficient evidence of Agent value.

The original live-data-to-R1 cycle was closed in PR #157. Exact old thresholds and evidence IDs are available in that PR/Git history and are intentionally not duplicated into the active planning tree.

## 4. US-A1 FactorGraph

A typed declarative FactorGraph was added so Agent proposals could become structured, validated research artifacts instead of arbitrary code.

Capabilities that remain strategic:

- OHLCV inputs and bounded rolling/return/arithmetic transforms;
- cross-sectional transforms;
- complexity/lookback validation;
- deterministic canonical identity;
- shared-DAG common-subexpression execution;
- numerical compatibility with the predecessor factor family.

These capabilities should be extended only when an R4 research need cannot be expressed by the current graph. They should not be replaced by unrestricted model-generated Python.

## 5. US-R2 multi-regime research

R2 tested whether the original 37-candidate family became robust when evaluated over a longer multi-regime program.

The baseline regime was a deterministic four-state IWM classifier:

```text
UP_LOW_VOL
UP_HIGH_VOL
DOWN_LOW_VOL
DOWN_HIGH_VOL
```

with lagged state and training-fitted volatility threshold.

R2 added substantial data/materialization/inference infrastructure and evaluated 37 candidates over five folds and four regimes, including pooled inference and frequency/decay robustness.

Durable conclusion:

```text
NO_ROBUST_FACTOR_FAMILY
```

Architectural lesson: the R2 decomposition into many infrastructure-only increments was correct but too expensive for exploratory research. R4 therefore keeps the statistical lessons but uses larger vertical research slices.

## 6. US-R3 Agent expansion

R3 PR #174 expanded two capabilities and landed on main in merge `e3f9121` on 2026-09-06:

1. minute-panel FactorGraph usability and a small set of executable OHLCV alpha prototypes;
2. a v2 controlled Agent runtime with typed actions, development feedback and a transactional SQLite budget/trial ledger.

R3 additionally implemented economic evaluation and several controlled pilot/follow-up paths.

Financial facts that shape the next roadmap:

- all valid candidates in the complete 2025 development economic pilot lost money under the primary 5 bps assumption;
- the run-selection policy selected cash in all 12 completion runs;
- a later guided workflow demonstrated successful tool/evaluation/submission flow but reused known prototypes and did not establish autonomous research superiority or profitability;
- real/independent Alpha is not established;
- exposed historical periods cannot become independent confirmation data by renaming folds or changing provider labels.

R3-CLOSE passed: 216 focused local tests, 25-file strict typing/lint, documentation governance and all 55 GitHub workflows passed before PR #174 merged. Closeout repaired obsolete status-v1 assertions/CI guards and an undeclared DuckDB timezone-conversion dependency without changing the research result. The reusable runtime/evaluator remains available to R4; `WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA` is preserved. The next research question is adaptive research/allocation, not another unconstrained formula sweep.

## R4 first executable research objects

The MarketState + FactorLibrary slice adds a causal, reproducible scikit-learn GMM
and a durable registry over real FactorGraphs. Existing R2 Parquet/calendar
fixtures now execute fit → project → materialize → global/state metrics → persisted
query, with negative/failure outcomes and unavailable data retained. R3 runtime,
graph engine, economic accounting and the deterministic R2 regime remain reusable.
This is an engineering milestone validated on controlled synthetic OHLCV, not a
new real-market research campaign, confirmed Alpha, or an R4 stage exit. GMM's
incremental information and adaptive allocation remain unestablished.

## 7. Existing Workbench capability

The current Workbench is not a blank slate. It already includes:

- React 19 + Vite;
- ECharts analytical views;
- React Flow lineage views;
- TanStack Table;
- URL-backed WorkbenchContext;
- Project → Thread → Run Agent index;
- normalized SSE updates;
- GET-only Evidence Plane and separately enabled typed local Control Plane;
- Strategy Decision Explorer;
- Factor Tear Sheet with IC/rolling IC, decay, fold/year heatmap, bootstrap/multiplicity and correlation views;
- Portfolio/Execution analytical surfaces.

The main product gap is not chart quantity. The Agent surface is still primarily an **audit/review browser** rather than the primary interactive research workspace. Workbench 2.0 addresses this without replacing the existing shell or analytical components.

## 8. Existing realtime and PAPER substrate

Provider-neutral realtime and operations code already exists and must be reused:

```text
src/finagent/realtime/
  canonical events
  replay/database sources
  streaming transforms
  MT5 source
  projections

src/finagent/operations/
  approval
  paper / paper_strategy
  reconciliation
  safety
  durable stores
```

The canonical realtime event vocabulary already covers quote, bar, market status, account, order, trade, order error and connection events. Projection code already handles duplicates, ordering diagnostics, stale/future timing, account/order/trade state and portfolio lots.

This is **engineering capability**, not accepted end-to-end MT5 PAPER evidence. The active plan therefore integrates and validates these modules instead of recreating RT-R0/R1/R2 as new stages.

## 9. Lessons encoded into planning revision 5.0

1. A permanent single factor is not the primary research target; a FactorLibrary plus adaptive allocation is more appropriate.
2. Agent value should be measured across discovery, selection, allocation, adaptation and research efficiency.
3. Agent should control development research decisions, while deterministic gates and final evidence remain outside Agent discretion.
4. Exploration and confirmation require different evidence intensity.
5. Existing Workbench/realtime/PAPER code should be integrated, not rebuilt.
6. Realtime UI belongs to real PAPER state, not a standalone mock dashboard.
7. No-alpha is always an acceptable terminal.
