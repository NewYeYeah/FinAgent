# R4-AGENT-ADAPTIVE — Agent-driven adaptive factor research

## Goal

Test whether an Agent adds measurable value by **choosing research directions, managing factor lifecycle and constructing adaptive factor allocations** under causal minute-OHLCV information.

R4 is a development/exploration program. It may use adaptive feedback, but its results are not independent confirmation.

Implemented and completed for the first frozen cycle: causal MarketState/FactorLibrary, five deterministic allocator baselines, session walk-forward evidence, bounded Agent Research Controller, thin Research Console, matched-campaign protocol/runner, guarded real campaign execution operator, accepted real ProviderAdmission and independently reviewed `r4-matched-v3` freeze. The separately authorized matched campaign was subsequently executed exactly once and independently reviewed as `R4_RESULT_ACCEPTED`. B-005 and B-006 are resolved. The frozen R4 terminal is `NO_ADAPTIVE_CANDIDATE`; Agent value is `INCONCLUSIVE`; no AdaptiveStrategy exists. The R4 exit gate is satisfied for this cycle, with development-only authority unchanged.

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

The first probabilistic model uses `sklearn.mixture.GaussianMixture` with train-only feature fitting, explicit state probabilities/availability and reproducible model identity. All historical signals and transformations retain causal session/clock semantics.

### 2. FactorLibrary

The research registry remains the durable FactorGraph lifecycle/evidence surface. It retains identity, hypothesis/source, lifecycle state, global/state-conditioned development metrics, turnover/coverage/decay, economic diagnostics, correlation/similarity and provenance. It is a bounded interpretable library, not unbounded formula generation.

### 3. Non-Agent allocator baselines

The frozen deterministic comparisons are:

```text
EqualWeight
RollingICWeight
RollingNetReturnWeight
RegimeConditionalWeight
RidgeMetaAllocator
```

They share frozen factor-pool, execution and cost semantics and provide the non-Agent comparison authority for the matched campaign.

### 4. Agent Research Controller

The Controller extends the existing R3 capability runtime. Its typed actions cover admitted inspection, factor lifecycle, factor-set/allocator proposals, deterministic evaluations/comparisons, budget decisions and final recommendation. It cannot alter frozen thresholds, erase failed trials, access R5 sealed evidence, own broker/account truth or grant safety/live authority.

### 5. Thin Research Console

The R4 console exposes the objective, Agent action stream, experiment cards, MarketState, factor set/allocator, remaining budget and explicit Agent decisions. It is not a financial-calculation authority and is not the full Workbench 2.0 redesign.

### 6. Controlled comparison

The first real matched comparison is complete. It retained strategy outcomes and research resources under the frozen protocol, including LLM calls/tokens/cost, portfolio evaluations and failed/rejected actions. The repository-safe result evidence is recorded at [`../../../configs/research/r4_matched_v3_result/README.md`](../../../configs/research/r4_matched_v3_result/README.md).

## Leakage and adaptive-overfit rules

R4 may adapt to the development set. Therefore:

- every adaptive choice is part of the algorithm being developed;
- fit market-state models only inside allowed history;
- use nested/walk-forward structure where allocator fitting and factor selection would otherwise see evaluation outcomes;
- keep overlapping labels/holdings purged or embargoed where required;
- retain every Agent/Optuna/manual trial in the effective development search record;
- never describe R4 p-values as independent confirmation of an adaptively tuned final strategy.

## Non-goals

- Tick/LOB/order-flow research;
- alternative/news/text data in the first adaptive program;
- live online parameter learning from broker observations;
- full Workbench 2.0 redesign;
- broker mutation/PAPER;
- independent Alpha certification.

## Accepted matched-campaign terminal

The accepted result binds:

- execution main `276846f5d83abe9753614e90a24613e176859f61`;
- frozen executable main `edf7c1942b3acf97926390e45bd46c8ac9aacbee`;
- ResearchAdmission `r4-research-admission-61df92c1caacb80e369f538f`;
- ProviderAdmission `r4-provider-admission-b78a63f33352d5a01bf2a4ca`;
- CampaignFreeze `r4-campaign-freeze-1d12fade12cb269d2b4da416`, SHA256 `c7ae0d5151f818b3dc190c223cf1663a5d547c1b4ef0c5771553dc50741e41c3`;
- Protocol `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3`;
- CampaignResult `r4-campaign-result-d32ec253d62eb4f9349896b0`, SHA256 `5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`.

Exactly one real campaign invocation completed. There was no automatic retry, rerun or provider fallback. The completed run order was:

```text
deterministic
selection-01
selection-02
selection-03
discovery-01
discovery-02
discovery-03
```

All required Primary runs completed and the artifact digest audit was 44/44 PASS. The deterministic host assessment is:

```text
AgentValue = INCONCLUSIVE
basis = research_efficiency_under_exhaustive_oracle
successful_agent_runs = 0
median_portfolio_evaluation_saving = 3
deterministic_portfolio_evaluations = 4
deterministic_oracle = null
candidate_decision = NO_ADAPTIVE_CANDIDATE
candidate_id = null
decision_authority = deterministic_host
```

The Primary run assessments are fixed as follows:

| Run | completion_status | portfolio evaluations | saving | oracle_noninferior | efficiency_success |
| --- | --- | ---: | ---: | --- | --- |
| selection-01 | `COMPLETE_NO_CANDIDATE` | 0 | 4 | false | false |
| selection-02 | `COMPLETE_NO_CANDIDATE` | 1 | 3 | false | false |
| selection-03 | `COMPLETE_NO_CANDIDATE` | 1 | 3 | false | false |

Median saving of 3 is not positive Agent-value evidence because the frozen economic-completeness gate produced no complete deterministic oracle.

### Economic completeness limit

The deterministic search **structurally** covered all four frozen factor sets and all five allocators, so 20/20 deterministic strategy keys were present. Economic completeness is different: 0/20 deterministic strategies had complete required three-fold evidence. Every deterministic strategy had `evaluable_folds = 0/3`; unavailable sessions ranged from 39 to 64. Across 30 total Primary candidate rows, none was complete under the frozen Candidate completeness rule.

Therefore `deterministic_evidence_complete = false` and `deterministic_oracle = null`. The accepted terminal is a **coverage/completeness-driven `NO_ADAPTIVE_CANDIDATE`**, not a negative-return-driven terminal. It must not be summarized as “all tested strategies lost money,” “economic performance proved negative,” or “Agent was proven ineffective.” The precise finding is that complete fold-level economic evidence was unavailable for every Primary strategy, so the frozen Candidate Gate found no viable candidate and Agent-value assessment remained `INCONCLUSIVE`.

### Why the result is not SYSTEM_FAILURE

Candidate completeness and campaign system failure are separate host gates. All deterministic evaluations completed as `PORTFOLIO_EVALUATED` and all required Primary runs completed. Discovery-03 ended `SLOT_ATTEMPTS_EXHAUSTED`, which is an admitted campaign-run terminal rather than an infrastructure system failure. The deterministic host therefore validly emitted `NO_ADAPTIVE_CANDIDATE` rather than `SYSTEM_FAILURE`.

### Resource and reliability observations

Accepted aggregate provider accounting is 100 verified calls, 317104 input tokens, 10452 output tokens, 327556 charged tokens and 437643 microusd ledger cost. This is ledger/provider accounting, not a reconciled provider invoice. Total portfolio evaluations were six: four deterministic and one each in selection-02 and selection-03.

The campaign retained 62 rejected Agent action attempts. Discovery-03 used 48 provider calls, ended `SLOT_ATTEMPTS_EXHAUSTED`, and retained 44 rejected actions, 43 of them `candidate_not_proposed_in_run`. ProviderAdmission still proved entry into the typed R4 interface; these observations instead establish a material autonomous tool-use reliability limitation. The contract is not weakened to hide that evidence. The limitation is tracked separately in the backlog.

## Authority and routing

The accepted CampaignResult remains `development_only = true` with `independent_confirmation = false`, `alpha_authority = false`, `paper_authority = false`, `live_authority = false` and `r5_eligible = false`.

No development-candidate artifact exists and no AdaptiveStrategy was accepted. Accordingly:

```text
R4 terminal = NO_ADAPTIVE_CANDIDATE
R5 = NOT STARTED
Alpha = NOT CONFIRMED
PAPER = NO
Live = NO
```

The current roadmap already permits WORKBENCH-2 productization after stable R4 semantics and permits a future **new versioned R4 cycle** after `NO_ADAPTIVE_CANDIDATE`. This accepted campaign must not be rerun because of its result, and this result record does not choose automatically between those future roadmap branches. R5 remains conditional on a future R4 AdaptiveStrategy candidate.

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

For this cycle, every exit condition above is satisfied through the accepted explicit `NO_ADAPTIVE_CANDIDATE` terminal. This does not create a candidate or grant any higher authority.
