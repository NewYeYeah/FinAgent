# Development history that still matters

This is **not** a chronological changelog. It preserves only completed work and negative results that constrain or materially inform the active roadmap. Exact implementation details remain in Git and pull-request history.

R4 Controller milestone: the existing bounded R3 runtime now executes offline research loops over the deterministic R4 core, including current-time FactorGraph proposals evaluated retrospectively without backdating. Complete trial/audit history and the thin Console make explicit actions, results, budgets and authority inspectable. This established engineering capability before the matched campaign and did not itself imply AdaptiveStrategy/Alpha/PAPER/live acceptance.

R4 campaign engineering milestone: matched resource/tool/failure/terminal rules and immutable freeze verification ran through a full synthetic campaign using the existing runtime, ledger, audit and deterministic evaluator. Real 2025 source lineage and train-prefix MarketState admission were bound without factor/portfolio PnL evaluation. At that engineering milestone, the first real non-research provider probe failed verification; no accepted real campaign freeze or financial campaign existed. The blocked freeze preserves the design and failed admission lineage.

## R4 accepted provider admission and v3 freeze

The 2026-09-07 offline admission/freeze milestone completed independent review with `EVIDENCE_ACCEPTED`; its [repository-safe evidence record](../../configs/research/r4_matched_v3_accepted/README.md) was recorded on 2026-09-08. A separately authorized real non-research `deepseek-v4-pro` probe passed the exact typed R4 action, created verified ProviderAdmission, and allowed an ACCEPTED `r4-matched-v3` freeze on executable main `edf7c1942b3acf97926390e45bd46c8ac9aacbee`. Exact freeze verification passed twice and all 34/34 recorded invariants passed.

- ProviderAdmission: `r4-provider-admission-b78a63f33352d5a01bf2a4ca`; SHA256 `a785e02fcb52f546c1e4cf8a7a08a33e90644323d2cba8722937b99f599e6098`.
- Successful probe request SHA256: `88cfa12ac119059ae8b2295d92714160e61c40fa6c7b07c4af5faecc418f2a4c`; probe contract `r4-provider-probe-contract-fe25be88367262b64ee310ec`.
- Reused ResearchAdmission: `r4-research-admission-61df92c1caacb80e369f538f`.
- CampaignFreeze: `r4-campaign-freeze-1d12fade12cb269d2b4da416`; SHA256 `c7ae0d5151f818b3dc190c223cf1663a5d547c1b4ef0c5771553dc50741e41c3`.
- Protocol: `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3`.

History remains cumulative: the 2026-09-06 failure had insufficient receipt evidence; the earlier 2026-09-07 attempt verified transport/model/usage but failed strict action; only the separately authorized later attempt after hardening passed exact action admission. Old failure artifacts and hashes remain unchanged. No result-dependent retry, fallback or threshold weakening is implied by the later success.

B-005 was resolved at the admission evidence-recording boundary. The full original freeze remains local immutable authority because it embeds local input-binding paths; only its exact ID/hash and sanitized attestation are public. That development phase recorded existing evidence without any new real probe, admission, freeze or campaign.

## R4 accepted matched v3 campaign result

A later, separately authorized Offline Testing Phase executed the reviewed `r4-matched-v3` freeze exactly once. Independent campaign-result review returned `R4_RESULT_ACCEPTED`; the repository-safe [result record](../../configs/research/r4_matched_v3_result/README.md) records the accepted identity without reconstructing the immutable local `campaign_result.json`.

- Execution main: `276846f5d83abe9753614e90a24613e176859f61`.
- CampaignResult: `r4-campaign-result-d32ec253d62eb4f9349896b0`; SHA256 `5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`.
- Campaign review bundle SHA256: `5e387790ec9b6d3198a2439c02900c1817d742de1b123c854f2ca31d4328c69d`.
- Run invocation count: 1; automatic retry: no; rerun: no; provider fallback: no.
- Completed runs: deterministic, selection-01, selection-02, selection-03, discovery-01, discovery-02, discovery-03.
- Verified provider calls: 100; charged tokens: 327556; ledger cost: 437643 microusd.
- Artifact integrity: 44/44 bound artifact digests PASS, with zero missing/mismatch.
- AgentValue: `INCONCLUSIVE`; successful Agent runs: 0; median portfolio-evaluation saving: 3; deterministic oracle: null.
- Deterministic host terminal: `NO_ADAPTIVE_CANDIDATE`; `candidate_id = null`; no development-candidate artifact or AdaptiveStrategy exists.

The economic limitation is essential to the interpretation. The deterministic search structurally covered 4 factor sets x 5 allocators = 20 strategy keys, but **0/20** had complete economic evidence under the required three-fold rule. Every deterministic strategy had `evaluable_folds = 0/3`, with unavailable-session counts from 39 to 64, and all 30 Primary candidate rows were incomplete. Thus no deterministic economic oracle could be constructed. The accepted terminal is coverage/completeness-driven; it is not evidence that all strategies lost money, not proof of negative economic performance, and not proof that the Agent was ineffective.

The result is also not `SYSTEM_FAILURE`. Deterministic evaluations completed as `PORTFOLIO_EVALUATED`, all required Primary runs completed, and discovery-03 ended the admitted terminal `SLOT_ATTEMPTS_EXHAUSTED`. Candidate completeness and campaign infrastructure failure remain separate host gates.

The campaign also retained negative operational evidence: 62 rejected Agent action attempts overall. Discovery-03 used 48 provider calls, retained 44 rejected actions and ended `SLOT_ATTEMPTS_EXHAUSTED`; 43 of those rejections were `candidate_not_proposed_in_run`. ProviderAdmission remained valid, so this is retained as an autonomous tool-use reliability limitation rather than reclassified as admission failure.

B-006 is resolved by the accepted matched-campaign terminal. That does not establish Alpha success. The result remains development-only with no independent confirmation, Alpha/PAPER/Live authority or R5 eligibility. R5 does not start because no AdaptiveStrategy candidate exists. A future research attempt must be a new versioned R4 cycle rather than a result-driven rerun; WORKBENCH-2 remains allowed by the current roadmap.

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

The MarketState + FactorLibrary slice adds a causal, reproducible scikit-learn GMM and a durable registry over real FactorGraphs. Existing R2 Parquet/calendar fixtures execute fit → project → materialize → global/state metrics → persisted query, with negative/failure outcomes and unavailable data retained. R3 runtime, graph engine, economic accounting and the deterministic R2 regime remain reusable. This was an engineering milestone validated on controlled synthetic OHLCV, not a new real-market research campaign or confirmed Alpha.

## R4 deterministic allocation baselines

The second R4 slice adds session-released factor-performance history, canonical same-bar normalization and five deterministic allocators with a causal multi-fold portfolio evaluator. Each fold fits a fresh GMM on its declared TRAIN prefix, accumulates subsequent causal state/performance pairs, and fits positive Ridge only on matured TRAIN examples. Complete FactorWeightSeries and economic evidence are persisted using existing R3 accounting and FactorLibrary storage. Controlled Parquet fixtures verify future-mutation isolation, replay and the CLI. This established executable baselines, not Alpha/PAPER/live authority.

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
