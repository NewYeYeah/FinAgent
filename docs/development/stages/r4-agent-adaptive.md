# R4-AGENT-ADAPTIVE — Agent-driven adaptive factor research

## Goal

Test whether an Agent adds measurable value by **choosing research directions, managing factor lifecycle and constructing adaptive factor allocations** under causal minute-OHLCV information.

R4 is a development/exploration program. It may use adaptive feedback, but its results are not independent confirmation.

Implemented: causal MarketState/FactorLibrary, five deterministic allocator baselines, session walk-forward evidence, bounded Agent Research Controller, a thin Research Console, the matched-campaign protocol/runner with the Primary reachability correction, a guarded real campaign execution operator, and a provider-admission probe contract aligned to the real R4 capability manifest. A real matched-budget campaign, accepted ProviderAdmission, accepted AdaptiveStrategy and the R4 terminal remain pending; B-005 provider admission stays open after transport success but strict-action failure.

The current Controller admits frozen quality lookback/minimum 20/5 and Ridge alpha 1. It always runs all five comparators with common execution/cost semantics. MarketState changes factor weights only; exposure timing is a later separate ablation. Default `PREDECLARED_STATIC` rejects post-TRAIN definitions; explicit `ADAPTIVE_RETROSPECTIVE` permits proposals created now and frozen before retrospective development evaluation. No proposal dates are backfilled. Agent feedback remains exposed development evidence even when the numerical evaluator uses train-only models and causal fold evaluation.

## Research question

Primary question:

> Does an Agent-controlled research/allocation loop improve the quality or efficiency of a fixed data universe and factor research budget relative to strong non-Agent baselines after costs, estimation error and regime instability?

Secondary questions:

- Does probabilistic market-state information improve the same factor pool?
- Does the Agent select more robust/non-redundant factor sets than deterministic search?
- Does Agent-directed experiment budgeting improve research efficiency rather than merely increase trial count?

## Deliverables

### 1. MarketState

Keep the existing R2 four-state IWM rule as the deterministic baseline.

Implement a first probabilistic model using mature library code, initially `sklearn.mixture.GaussianMixture` unless evidence justifies another model.

Causal candidate features may include:

```text
market/proxy trailing return
intraday or trailing realized volatility
cross-sectional breadth
cross-sectional dispersion
same-time-of-day relative volume
open-relative market return
```

All scalers, thresholds, PCA/components, cluster parameters and state mapping must be fit using only data available in the allowed training/development window. Realtime state uses filtering/current features; no future-sequence smoothing is permitted.

Persist/model-bind at least:

```text
MarketStateModel identity
feature definitions
fit window
state probabilities
availability time
state interpretation mapping
```

### 2. FactorLibrary

Create a research-level registry over current FactorGraphs rather than another denominator-specific cache architecture.

Each factor should expose:

```text
identity / family / hypothesis / source
status: PROPOSED | TESTING | ACTIVE | DORMANT | REJECTED | RETIRED
global development metrics
metrics by market state
turnover / coverage / decay
net economic metrics under frozen cost scenarios
correlation / behavioral similarity
Agent/manual/programmatic provenance
```

Start with a deliberately small interpretable factor pool (roughly 8–20 mechanisms/variants) plus bounded Agent proposals. Do not reopen unbounded formula generation.

### 3. Non-Agent allocator baselines

Before giving Agent allocation authority, implement strong deterministic comparisons:

```text
EqualWeight
RollingICWeight
RollingNetReturnWeight
RegimeConditionalWeight
regularized linear / ridge-style meta allocator
```

Use Optuna only when parameter search is actually required; preserve all attempted trials and freeze its search budget before looking at the final comparison.

A market-state layer may also control gross exposure/cash. Do not force a market-timing mechanism through a cross-sectional RankIC-only gate.

### 4. Agent Research Controller

Extend the existing R3 capability runtime rather than replacing it.

Target controlled actions:

```text
inspect_market_state
inspect_factor_library
inspect_factor
inspect_experiment_history
read_literature

propose_factor
validate_factor
evaluate_factor

propose_factor_set
propose_allocator
evaluate_portfolio

compare_experiments
allocate_budget
retire_hypothesis
finalize_candidate
```

Agent may decide:

- which admitted mechanism to investigate next;
- which factors to keep/retire/test together;
- which admitted allocator/bounded parameters to try;
- which ablation to request;
- how to spend the remaining development experiment budget;
- when to stop a failed hypothesis family.

Agent may **not** decide:

- final statistical/Alpha thresholds after seeing results;
- which failed trials disappear from accounting;
- access to R5 sealed evidence;
- broker/account truth;
- safety limits or live-capital authority.

### 5. Thin Research Console

R4 should expose the research loop early through a minimal extension of the existing Workbench, not a full redesign.

Minimum view:

```text
current research objective
Agent tool/action stream
experiment result cards
MarketState snapshot
current factor set / allocator
remaining budget
explicit Agent decision / next action
```

Prefer an AG-UI adapter for standardized Agent event/tool/state streaming if a bounded spike integrates cleanly with the existing runtime. Do not migrate the Agent backend to LangGraph/CrewAI/AutoGen solely for UI convenience.

### 6. Controlled comparison

At minimum compare:

```text
static equal-weight factor pool
best deterministic rolling allocator
regime-conditional deterministic allocator
Agent-controlled adaptive allocator/research loop
```

Keep factor pool/data/cost assumptions and allowed evaluation budget comparable. Report both strategy outcome and research resources:

```text
net return / Sharpe-like risk-adjusted metric / drawdown
worst state / stability
turnover and costs
factor concentration / redundancy
number of proposals/evaluations
LLM calls/tokens/cost
failed/duplicate/repaired trials
wall-clock or evaluator budget
```

## Leakage and adaptive-overfit rules

R4 may adapt to the development set. Therefore:

- every adaptive choice is part of the algorithm being developed;
- fit market-state models only inside allowed history;
- use nested/walk-forward structure where allocator fitting and factor selection would otherwise see evaluation outcomes;
- keep overlapping labels/holdings purged or embargoed where required;
- retain every Agent/Optuna/manual trial in the effective development search record;
- never describe R4 p-values as independent confirmation of an adaptively tuned final strategy.

## Open-source reuse

Priority:

```text
scikit-learn GMM          market-state baseline
Optuna                    bounded deterministic search where needed
existing FactorGraph      factor representation/execution
existing R3 runtime       Agent capability/ledger
existing evaluator        economics
ECharts/React Flow        thin console views
AG-UI                     candidate Agent/UI event protocol
```

PyPortfolioOpt may be used as a comparator where its portfolio problem matches the experiment, but it must not replace FinAgent's authoritative historical execution/cost semantics.

## Non-goals

- Tick/LOB/order-flow research;
- alternative/news/text data in the first adaptive program;
- live online parameter learning from broker observations;
- full Workbench 2.0 redesign;
- broker mutation/PAPER;
- independent Alpha certification.

## Suggested PR slices

Natural decomposition, subject to reviewability rather than a fixed count:

1. MarketState + FactorLibrary vertical slice.
2. Deterministic allocators + adaptive portfolio evaluator.
3. Agent Research Controller + thin Research Console.
4. Separately admitted and preregistered matched-budget comparison/campaign after Controller/console merge and repository-state recheck. Slice 3 does not execute a real financial campaign.

Do not split each contract/cache/statistic into its own PR.

## Campaign admission and frozen design

The engineering boundary is implemented; real execution remains blocked by provider admission. Corrected protocol generation is code-owned as `r4-matched-v3`; a newly recorded provider-blocked design uses `r4-matched-v3-blocked-provider`. The operator CLI does not choose these labels. The guarded `run` command is a thin layer over `verify_campaign()` and `run_campaign()`: it requires explicit research admission, accepted provider admission, provider config, campaign directory and the exact human-reviewed accepted freeze ID. It cannot probe, freeze, record a blocker, change protocol/research settings, retry, force, reset or use fixture/blocked authority as a real campaign. Browser/Workbench receives no campaign-run control. The v1/v2 blocked artifacts under `configs/research/r4_matched_*_blocked/` are immutable history and retain their old +0.002 Agent-value semantics. In particular, the retained historical v2 artifact has status `BLOCKED_PROVIDER_ADMISSION`, protocol ID `r4-matched-protocol-56a7f58549c2bc2d9cba2c78` and freeze ID `r4-campaign-freeze-51cdf9a05864e90ffe5310bd`; it is never accepted by the runner. Those v1/v2 labels cannot be reused for newly generated corrected artifacts. Real 2025 source admission contains no factor/portfolio evaluation results, and no corrected real v3 freeze has been generated.

Provider admission remains exact and fail-closed. The real R4 runtime exposes its typed capability contract as `capability_set = capabilities.manifest()`. The non-research provider probe now sends the same public `r4_manifest()` together with a frozen exact `PROBE_ACTION`, empty state/resources/feedback and `research_history = false`; it supplies no market data, factor evidence, PnL, research objective or campaign result. `provider_binding()` includes a deterministic `probe_contract_digest`, so changes to the R4 manifest, exact probe action or probe-context semantics change future provider-admission identity. A valid but different R4 action remains `probe_contract_mismatch`; the acceptance threshold is not weakened to “any valid action.” Strict decoder failures retain only a bounded allowlisted `strict_action_error_code`, never raw model output or exception text.

The original 2026-09-06 non-research probe failed before it retained an accepted identity/usage receipt. A later separately authorized real non-research probe on **2026-09-07** reached the transport boundary successfully: credential use/endpoint/quota succeeded, the response identified `deepseek-v4-pro`, response ID and system fingerprint were present, prompt/completion/cache usage was complete, and conservative cost accounting was retained in a verified transport receipt. It then failed in `phase = strict_action`; no `ProviderAdmission` was created. That result narrows B-005 to strict R4 action conformance for the observed attempt but does not authorize research execution. This development phase performs no additional real probe. A future real campaign still requires a separately authorized successful admission and a new accepted v3 freeze.

The execution operator is intentionally landed before any future accepted v3 freeze because `campaign_implementation()` binds tracked `src/`, `scripts/`, Workspace executable code and dependency intents, including `scripts/r4_campaign.py`. Adding or changing the operator after freeze creation would cause implementation drift and invalidate that freeze. The required future order is provider admission → source admission verification → freeze → verify → independent human review of the exact freeze ID → run. Freeze and run are not one combined action.

The corrected Primary protocol fixes the same three R3 executable frontier definitions and the FactorSet minimum size of two. The Agent-admissible factor sets are therefore exactly the full three-factor pool plus its three two-factor subsets: four sets total. Deterministic selection evaluates exactly those four sets, and every portfolio evaluation runs all five frozen allocators, yielding 20 reachable factor-set/allocator strategies. Primary factor discovery remains forbidden. Protocol construction derives this search space from the frozen IDs, FactorSet bounds and allocator catalog and requires exact equality between Agent-admissible and deterministic factor sets before it can claim `deterministic_search = exhaustive`. The deterministic Primary arm is consequently the exhaustive deterministic oracle for the frozen Primary search space; a future pool whose deterministic schedule does not cover the Agent space cannot silently reuse exhaustive-oracle semantics.

Each Agent selection run retains four factor-set proposal slots and four portfolio evaluation slots. Three independent Agent runs share the objective, starting evidence, provider configuration and budgets. Agent-value assessment uses each run's explicit final factor-set/allocator choice only as a selection; the deterministic host resolves its stable factor-set/allocator strategy key against the exhaustive oracle. Run-specific candidate IDs do not create economic superiority. Candidate viability separately ranks all completed Primary pairs. “Static equal weight” describes allocation, not historical factor existence: all campaign evidence is retrospective exposed development, and seed registrations retain the actual 2026 research clock.

Per Agent run: 48 tool calls, 1,048,576 total tokens, 2,400,000 microusd peak-tariff ceiling and 7,200 seconds. Proposal/evaluation ceilings deny that category while allowing remaining bounded inspection/finalization; hard resource ceilings or finalize stop the run. Deterministic execution uses zero LLM calls/tokens/cost. Exploratory discovery has three proposal slots, three factor-evaluation slots, four set proposals and four portfolio evaluations per independent run. It has no separately identified discovery-value claim and cannot supply the Primary oracle, Agent-value assessment or candidate.

Factor feedback is frozen to the first fold's evaluation window; portfolio feedback covers all three calendar-defined folds. Each fold uses its first 20 TRAIN sessions for scaler/GMM fit, its first 40 sessions for TRAIN, and the remaining sessions for fold evaluation. Historical performance release, train-only Ridge, normalization, exposure, 15m clock, one-bar delay, four-bar holding and 0/1/5/10bp costs are unchanged. No feedback-window adjustment is allowed after results.

Failures and duplicates remain accounted. Infrastructure retries and repairs are zero. Transport uncertainty, timeout, quota, evaluator infrastructure failure or audit inconsistency cause system failure; negative economics never justify retry. Duplicate economic requests replay the existing result and do not spend a second evaluation slot. Untyped rejection consumes a tool attempt and conservatively debits proposal categories.

Primary Agent value is `research_efficiency_under_exhaustive_oracle`, not performance superiority over an already exhaustive deterministic search. All three Primary runs must complete with authoritative campaign/ResearchLedger resource accounting. A run is an efficiency success only when its selected strategy is no worse than the deterministic oracle under the frozen economic ordering and it saves at least one portfolio evaluation relative to the four-evaluation deterministic search. Overall `SUPPORTED` requires at least two of three such successes and median portfolio-evaluation saving of at least one across the three required runs. Using all four evaluations is not an efficiency success even when the Agent selects the oracle; saving evaluations while selecting an inferior strategy is also not a success. A deliberate no-candidate is a completed negative Agent outcome. Missing required metrics or resource evidence is `INCONCLUSIVE`; provider/evaluator/audit infrastructure failure remains `INCONCLUSIVE` for Agent value and follows the existing `SYSTEM_FAILURE` campaign terminal. Performance superiority is not identifiable inside this exhausted finite Primary space.

Candidate viability remains independent and unchanged: all three folds evaluable, zero unresolved sessions, mean fold return at 5bp strictly positive, worst fold at least -0.01, and mean fold return at 10bp nonnegative. Ranking remains lexicographic: higher mean/worst 5bp economics, lower drawdown/turnover/concentration, fewer factors, less runtime Agent dependence, then canonical ID. A deterministic baseline can produce an AdaptiveStrategy candidate when Agent value is unsupported. The builder defaults Agent role to research/development only and grants no Alpha/PAPER/live or independent-confirmation authority.

## Exit gate (unchanged)

R4 exits when:

```text
MarketState and FactorLibrary are causal/reproducible
strong non-Agent allocator baselines exist
Agent can autonomously execute the admitted inspect→propose→evaluate→compare→allocate loop
all adaptive trials/resources are retained
one complete matched-budget comparison is executed
one AdaptiveStrategy candidate or an explicit NO_ADAPTIVE_CANDIDATE terminal is frozen
R4 result is explicitly development-only
```

If Agent adds no measurable value, reduce its allocation role in the frozen candidate rather than forcing an Agent-positive conclusion.
