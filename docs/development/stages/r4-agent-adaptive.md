# R4-AGENT-ADAPTIVE — Agent-driven adaptive factor research

## Goal

Test whether an Agent adds measurable value by **choosing research directions, managing factor lifecycle and constructing adaptive factor allocations** under causal minute-OHLCV information.

R4 is a development/exploration program. It may use adaptive feedback, but its results are not independent confirmation.

Implemented: causal MarketState/FactorLibrary, five deterministic allocator baselines, session walk-forward evidence, bounded Agent Research Controller and a thin Research Console. Controller acceptance uses only scripted/offline providers and real deterministic fixture calculations. A real matched-budget campaign, accepted AdaptiveStrategy and the R4 terminal remain pending; B-005 provider/evaluator admission stays open.

The current Controller admits frozen quality lookback/minimum 20/5 and Ridge alpha 1. It always runs all five comparators with common execution/cost semantics. MarketState changes factor weights only; exposure timing is a later separate ablation. Default `PREDECLARED_STATIC` rejects post-TRAIN definitions; explicit `ADAPTIVE_RETROSPECTIVE` permits proposals created now and frozen before retrospective development evaluation. No proposal dates are backfilled. Agent feedback remains exposed development evidence even when the numerical evaluator uses train-only models and causal fold evaluation.

## Research question

Primary question:

> Does an Agent-controlled research/allocation loop improve a fixed data universe and factor research budget relative to strong non-Agent baselines after costs, estimation error and regime instability?

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

## Exit gate

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
