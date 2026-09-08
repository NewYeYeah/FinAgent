# Research workflow

This guide describes how to work with the active research architecture without duplicating stage-specific implementation history.

## 1. Start from stage intent

Read:

1. [`../status.toml`](../status.toml);
2. [`../development/current-plan.md`](../development/current-plan.md);
3. the current stage plan.

Inspect existing research/runtime/source tests before proposing another research runtime. Reuse FactorGraph, MarketState, FactorLibrary, allocator/evaluator and the bounded Agent runtime rather than creating parallel authorities.

## 2. Research loop

The intended R4 loop is:

```text
objective
→ inspect prior evidence / literature / MarketState / FactorLibrary
→ propose hypothesis or factor-set/allocator change
→ deterministic validation/evaluation
→ explicit result
→ Agent critique/decision
→ next bounded experiment
→ freeze candidate or stop
```

The Agent chooses development research actions. Deterministic code computes metrics and enforces admitted scope, resource accounting, completeness, candidate and authority gates.

## 3. Factor representation

Use typed FactorGraph for ordinary formula factors. Do not replace it with arbitrary model-generated Python merely to gain expressiveness. If a mechanism cannot be represented, first decide whether it is a factor operator, MarketState feature, allocation/exposure rule or portfolio/execution mechanism.

## 4. Development feedback

Development feedback is allowed in R4 but is adaptive exposure. Keep exact trial identity, failed/invalid/repaired/duplicate attempts, evaluator calls, provider/model identity, tokens/cost/time budget and explicit Agent decisions. Do not discard poor trials because they are inconvenient for Agent-value accounting.

## 5. MarketState and FactorLibrary

The first adaptive MarketState uses train-only StandardScaler plus `sklearn.mixture.GaussianMixture`; the R2 four-state IWM rule remains the deterministic comparator. Market clocks, fit windows, state probabilities and availability must remain explicit and causal.

FactorLibrary is the persistent bounded registry for FactorGraphs, lifecycle, global/state-conditioned development evidence, economic diagnostics and provenance. Successful development evaluation never grants Alpha/PAPER/live authority.

## 6. Deterministic allocation

The five frozen R4 baselines are:

| Allocator | Frozen role |
| --- | --- |
| EqualWeight | equal factor weights |
| RollingICWeight | positive completed-session RankIC quality |
| RollingNetReturnWeight | positive completed-session standalone 5bp return quality |
| RegimeConditionalWeight | then-available state-conditioned historical quality |
| RidgeMetaAllocator | train-only regularized meta allocation with lagged features |

All share the same normalization, basket budget, delay, holding and 0/1/5/10bp cost scenarios. Missing whole sessions remain explicit rather than disappearing into a successful cash result. These are development comparisons, not Alpha/PAPER/live evidence.

## 7. Exploration versus confirmation

R4 result:

```text
candidate strategy or NO_ADAPTIVE_CANDIDATE
development evidence only
```

R5 result, only when an R4 candidate exists:

```text
CONFIRMED / REJECTED / INSUFFICIENT_INDEPENDENT_EVIDENCE
```

Never describe adaptively optimized R4 development evidence as independent Alpha evidence.

## 8. Research Console

During R4, expose only what is needed to understand/control the loop: objective, Agent actions/tool calls, experiment cards, MarketState, factor set/allocator, remaining budget and explicit next decision. The full Workbench 2.0 productization is separate.

The Controller uses the existing ResearchCapabilityRuntime/provider/ResearchLedger/audit boundaries. It may inspect admitted state/factors/history, propose/validate/evaluate factors, propose factor sets/allocators, request deterministic portfolio comparisons and finalize a development recommendation. It cannot change frozen costs, holding/delay, allocator hyperparameters, budgets or final authority.

Retrospective artifacts remain `development_only = true` and non-independent. `DEVELOPMENT_CANDIDATE_PROPOSED` and `NO_CANDIDATE_RECOMMENDED` are Controller recommendations; the campaign terminal is owned by the deterministic host.

## 9. Campaign admission, review, execution and result recording

The accepted R4 governance path is now complete for the first `r4-matched-v3` cycle:

```text
ProviderAdmission
→ accepted CampaignFreeze
→ independent freeze review
→ one separately authorized real matched campaign
→ independent CampaignResult review
→ canonical repository-safe result recording
```

The admission/freeze record is [`../../configs/research/r4_matched_v3_accepted/README.md`](../../configs/research/r4_matched_v3_accepted/README.md). The accepted result record is [`../../configs/research/r4_matched_v3_result/README.md`](../../configs/research/r4_matched_v3_result/README.md).

Exact accepted identities are:

- ResearchAdmission `r4-research-admission-61df92c1caacb80e369f538f`;
- ProviderAdmission `r4-provider-admission-b78a63f33352d5a01bf2a4ca`;
- CampaignFreeze `r4-campaign-freeze-1d12fade12cb269d2b4da416`;
- Protocol `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3`;
- CampaignResult `r4-campaign-result-d32ec253d62eb4f9349896b0`;
- CampaignResult SHA256 `5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`;
- accepted result review disposition `R4_RESULT_ACCEPTED`.

The real matched campaign was invoked exactly once. It completed deterministic, selection-01/02/03 and discovery-01/02/03 in that order, with no automatic retry, rerun or provider fallback. The accepted deterministic-host result is:

```text
AgentValue = INCONCLUSIVE
successful_agent_runs = 0
median_portfolio_evaluation_saving = 3
deterministic_oracle = null
candidate_decision = NO_ADAPTIVE_CANDIDATE
candidate_id = null
```

### Completeness interpretation

The frozen Primary search structurally contained 4 factor sets x 5 allocators = 20 deterministic strategies, all of which were present. Economic completeness was different: 0/20 deterministic strategies had complete three-fold evidence. Every deterministic strategy had `evaluable_folds = 0/3`; unavailable sessions ranged from 39 to 64; and all 30 Primary candidate rows were incomplete under the Candidate completeness rule.

Therefore no deterministic economic oracle could be constructed. Median evaluation saving of 3 is not positive Agent-value evidence. The accepted `NO_ADAPTIVE_CANDIDATE` is **coverage/completeness-driven**, not a claim that all strategies lost money or that economic performance was proven negative.

This is not `SYSTEM_FAILURE`. All deterministic evaluations completed as `PORTFOLIO_EVALUATED`, all required Primary runs completed, and discovery-03's `SLOT_ATTEMPTS_EXHAUSTED` is an admitted normal run terminal. System failure remains reserved for the frozen infrastructure/provider/evaluator/audit failure semantics.

### Provider/resource and reliability accounting

The accepted aggregate campaign accounting is 100 verified provider calls, 317104 input tokens, 10452 output tokens, 327556 charged tokens, 437643 microusd ledger cost and six portfolio evaluations. It is ledger/provider accounting, not a reconciled provider invoice.

All negative operational evidence is retained. There were 62 rejected Agent action attempts. Discovery-03 used 48 provider calls, retained 44 rejected actions and ended `SLOT_ATTEMPTS_EXHAUSTED`; 43 rejections were `candidate_not_proposed_in_run`. This is not a ProviderAdmission failure and must not be hidden by weakening the typed tool contract.

## 10. No result-driven rerun and no automatic R5

The first `r4-matched-v3` matched campaign is historical accepted evidence. **Do not rerun it because of its result.** Any future R4 research attempt must be a **new versioned R4 cycle** with its own preregistered semantics and evidence identities. The accepted result must not be reinterpreted under later executable code.

The accepted campaign produced no development-candidate artifact and no AdaptiveStrategy. Accordingly R5 is **not started** and `r5_eligible = false`. Alpha remains not confirmed, PAPER remains not accepted and Live remains not authorized.

The current roadmap already permits either a future versioned R4 research cycle or WORKBENCH-2 productization after stable R4 semantics. The result-recording phase does not invent or force which route is next.

## 11. Repository-safe evidence boundary

Full immutable campaign artifacts remain outside repository publication when they contain local/private execution bindings. Repository evidence records exact IDs/hashes, accepted review disposition, aggregate/run-level accounting and interpretation without reconstructing the original result bytes.

Evidence/governance development must not call the real provider, access campaign credentials/private market inputs, regenerate ProviderAdmission or CampaignFreeze, or execute `r4_campaign.py run`. GitHub CI validates repository implementation/docs/evidence packaging only; it is not a substitute campaign execution environment.
