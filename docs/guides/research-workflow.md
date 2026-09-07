# Research workflow

This guide describes how to work with the active research architecture without duplicating stage-specific implementation history.

## 1. Start from stage intent

Read:

1. [`../status.toml`](../status.toml);
2. [`../development/current-plan.md`](../development/current-plan.md);
3. the current stage plan.

For current R3/R4 work, inspect existing `src/finagent/research/us_a1_*`, `src/finagent/research/us_r3_*` and `src/finagent/agents/r3_*` code/tests before proposing another research runtime.

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

The Agent chooses development research actions. Deterministic code computes metrics and enforces the admitted scope/budget.

## 3. Factor representation

Use typed FactorGraph for ordinary formula factors.

Do not replace it with arbitrary model-generated Python merely to gain expressiveness. If a mechanism cannot be represented, first decide whether it is actually:

- a new factor operator;
- a MarketState feature;
- an allocation/exposure rule;
- a portfolio/execution mechanism.

Only the first category necessarily belongs in FactorGraph.

## 4. Development feedback

Development feedback is allowed in R4 but must be treated as adaptive exposure.

Keep:

- exact trial identity;
- failed/invalid/repaired/duplicate attempts;
- evaluator calls;
- model/provider identity;
- tokens/cost/time budget;
- explicit Agent decision after each result.

Do not discard poor trials because they are inconvenient for Agent-value accounting.

## 5. MarketState

The first adaptive MarketState is implemented with train-only StandardScaler and
[scikit-learn GaussianMixture](https://scikit-learn.org/stable/modules/generated/sklearn.mixture.GaussianMixture.html).
The existing R2 four-state IWM rule remains available as the deterministic comparator.

Install `uv sync --frozen --extra dev --extra adaptive-research`. Run
`python scripts/run_r4_research_slice.py run --help` for the full command. Supply
existing local R2 base Parquet, calendar, plan and passed evidence paths, source
ID/revision, an explicit comma-separated universe, and aware `--fit-start`,
`--fit-end`, `--evaluation-start`, `--evaluation-end` timestamps. Each window must
include complete calendar sessions, fit must finish before evaluation, and both
windows must fit the single annual source artifact. Default proxy is IWM; the
universe must contain it. Default breadth/top-count is 20/5; small synthetic
fixtures must declare their smaller breadth/count explicitly.

The CLI registers three existing R3 prototypes with their prior no-confirmed-Alpha
terminal in provenance, performs no candidate search, and leaves them TESTING.
`--output` receives `request.json`, `market_state_model.json`, `result.json` and
`factor_library.sqlite`; unsuccessful fitting preserves `failure.json` and the
original request. Use a new output directory for a changed request, input or
implementation. Repeating identical inputs reproduces the result and does not
duplicate registry evaluations (it currently recomputes the bounded slice).

Inspect without mutation:

```bash
python scripts/run_r4_research_slice.py inspect --library <output>/factor_library.sqlite
python scripts/run_r4_research_slice.py inspect --library <output>/factor_library.sqlite --factor <candidate-id>
```

`--factor` inspection also supports an aware `--as-of` cutoff. Result files contain
global and soft-state-weighted coverage, signal-target turnover, 15m/60m RankIC
decay and rank similarity. Economic diagnostics separately apply each fixed argmax
state as an entry gate under the full 0/1/5/10 bps grid, with delayed entries and
ungated exits. These scenarios are hypothetical costs, not measured broker fills.
Missing entire sessions invalidate economic NAV rather than disappearing or
becoming a successful cash day. Missing labels reduce the reported observation
weight without changing formation coverage. These are development diagnostics,
not evidence that MarketState adds value or that Alpha/PAPER/live is accepted.

## 6. Factor allocation

Five deterministic baselines now share one frozen pool and execution policy:

| Allocator | Frozen rule | Fallback |
| --- | --- | --- |
| EqualWeight | `1 / factor_count`; ignores performance history | none |
| RollingICWeight | positive part of mean completed-session RankIC | equal weights |
| RollingNetReturnWeight | positive part of mean standalone session return at 5bp | equal weights |
| RegimeConditionalWeight | historical decision IC weighted by then-available state probabilities; normalize each state's positive qualities, then mix with current soft probabilities | equal component weights; current state unavailable means equal weights |
| RidgeMetaAllocator | [sklearn Ridge](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.Ridge.html), positive coefficients, alpha 1, train-only StandardScaler; lagged mean IC/net-bps predict next-session standalone net-bps | equal weights on missing fit/features or all nonpositive predictions |

Rolling features use the last **20 completed sessions**, requiring **5 valid
sessions** per quality; Ridge requires **8 pooled mature training examples**.
These are fixed baseline settings, not tuned to the reported results. Ridge
coefficients remain frozen within evaluation; its lagged quality inputs update
after each session. Conditional IC requires five supported historical sessions
and retains probabilities at the exact historical decision, not a retrospective
label. No whole-window FactorLibrary aggregate metric enters an allocator.

Run `python scripts/run_r4_walkforward.py --help`. Use the same source/calendar/
base-plan/base-evidence, source ID/revision and explicit universe as the first
slice, plus `--library <existing-factor-library.sqlite>`, `--folds <folds.json>` and
`--output <new-directory>`. The library is read-only input; all registered factors
are used unless `--factor-ids` freezes an explicit subset. Rejected/retired factors
fail the request. Defaults remain IWM and breadth/top-count 20/5; controlled small
fixtures must explicitly supply their proxy and smaller breadth/count.

The fold file is a JSON array of 2–12 chronological folds, with nonoverlapping
evaluation windows. Use aware timestamps and complete sessions in the bound year:

```json
[
  {
    "name": "fold-1",
    "train": {"start": "2025-01-02T00:00:00+00:00", "end": "2025-02-03T00:00:00+00:00"},
    "state_fit_end": "2025-01-13T00:00:00+00:00",
    "evaluation": {"start": "2025-02-03T00:00:00+00:00", "end": "2025-02-10T00:00:00+00:00"}
  },
  {
    "name": "fold-2",
    "train": {"start": "2025-01-02T00:00:00+00:00", "end": "2025-02-10T00:00:00+00:00"},
    "state_fit_end": "2025-01-20T00:00:00+00:00",
    "evaluation": {"start": "2025-02-10T00:00:00+00:00", "end": "2025-02-17T00:00:00+00:00"}
  }
]
```

Adapt dates to the admitted calendar before running. Each fold refits GMM using
only its declared TRAIN prefix. Subsequent TRAIN sessions initialize genuinely
causal state/performance history; prefix decisions have unavailable states. Ridge
uses mature TRAIN labels and features formed from earlier completed sessions.
All labels and holdings finish within their session; releases occur at close,
and the next session's allocator input cutoff cannot exceed its open. This
prevents label overlap across the TRAIN/evaluation boundary without dropping
extra sessions for a nominal embargo.

Normalization ranks every factor on the same current common-support intersection.
All arms then use identical full top-K basket budgets, one-bar delay, four-bar
holding, rolling sleeves and 0/1/5/10bp costs. A fixed score offset preserves
ranking even when combined scores are negative or tied; state probabilities
change factor weights only. Missing common support remains explicit and shared.

Outputs remain `request.json`, `result.json`, `failure.json` on failure, and
`factor_library.sqlite`. The request binds folds, definitions, configurations,
source files, code and dependencies before evaluation reads. The result retains
fold-local models, session performance releases, all five FactorWeightSeries,
targets, history cutoff/identity, fallbacks and state probabilities, plus each
fold/arm/cost's economic and weight metrics. A failed later fold retains already
completed fold evidence. Identical replay is idempotent; changed requests require
a new output directory.

Session release `decision_time` identifies the first covered formation; nested
decision records preserve each IC's actual decision/outcome clocks and then-known
state. The standalone 5bp session return is stored once. State-conditional strategy
metrics describe NAV changes using the state known at each interval's beginning;
they are not separate investable state strategies. Overall mean/worst fold return
is unavailable if any fold's NAV is unresolved, and fold averages are not stitched
NAV. These are development comparisons, without Alpha/PAPER/live authority or
evidence yet of GMM/allocator profitability. The bounded R4 Controller reuses this core through explicit research-time admission.

## 7. Exploration versus confirmation

R4 result:

```text
candidate strategy or NO_ADAPTIVE_CANDIDATE
development evidence only
```

R5 result:

```text
CONFIRMED / REJECTED / INSUFFICIENT_INDEPENDENT_EVIDENCE
```

Never describe an adaptively optimized R4 development result as independent Alpha evidence.

## 8. Research Console

During R4, expose only what is needed to understand/control the loop:

- objective;
- Agent actions/tool calls;
- experiment result cards;
- current MarketState;
- selected factor set/allocator;
- remaining budget;
- explicit next decision.

The full Workbench 2.0 productization is a later stage.

The implemented Controller uses the existing `ResearchCapabilityRuntime`, provider and ResearchLedger. It can inspect admitted state/factors/literature/all trial outcomes, validate and propose FactorGraphs, select 2..20 nonterminal canonical factors, choose one of the five frozen allocator configurations, request deterministic evaluations/comparisons, record lifecycle decisions and finalize a development recommendation. It cannot change costs, holding/delay, quality lookback (20/5), Ridge alpha (1), budgets or final authority. Portfolio requests always run all five comparator arms. Proposed graphs must encode their own positive hypothesis direction; use the existing `NEGATE` operator for an inverse signal, with no allocator sign flip.

Default `PREDECLARED_STATIC` admission still rejects definitions created after first TRAIN. The Controller explicitly selects `ADAPTIVE_RETROSPECTIVE` with an immutable proposal envelope/request. `proposal_id`, `factor_definition_digest`, `proposed_at`, run/actor/scope and `visible_history_id` identify the actual research decision; `proposal_context_id` names that same exact bounded explicit-context digest. `visible_experiment_ids` and the history cutoff cannot include a later result. Successful factor development evaluation admits TESTING, never automatic ACTIVE.

Market clocks describe historical causal information. Research proposal clocks describe when the definition really existed. The ledger publishes a result only after evaluation completes (`completed_at`), so it can affect subsequent Agent actions only. Replay reuses committed requests and identical experiment specifications without another evaluation charge. Failed/negative/duplicate attempts remain visible. Unknown pending execution or an audit mismatch stops the run for reconciliation.

Retrospective artifacts bind `evaluation_mode = adaptive_development_retrospective`, `historically_predeclared = false`, `adaptive_search_exposed = true`, `development_only = true` and false independent/Alpha/PAPER/live flags. Internal walk-forward partitions are called **fold evaluation**; the whole Agent search remains exposed development evidence. `DEVELOPMENT_CANDIDATE_PROPOSED` and `NO_CANDIDATE_RECOMMENDED` are Controller recommendations, not the R4 stage terminal. A frozen matched-budget comparison and later independent confirmation remain required.

## Campaign admission and operator freeze

`scripts/r4_campaign.py` provides explicit `probe`, `admit-source`, `freeze`, `verify` and `record-blocker` commands. There is intentionally no real campaign `run` CLI in this engineering slice. Normal Workbench startup does not discover keys, select another provider or acquire campaign authority. The explicit profile is `r4_deepseek_v4_pro`; its existing StrictDeepSeek transport uses thinking disabled, temperature 0.7, strict JSON and one attempt. This does not change the shared generic-provider default.

The non-research probe has already been attempted once and failed verification. Do not repeat it as part of this PR. Its immutable failure lacks an accepted identity/usage receipt. B-005 remains OPEN; obtaining a new probe requires a separate operator decision. No credential/quota/model/cost success is inferred. Public tariff accounting uses a conservative peak upper bound, not an invoice claim; see [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/).

The real source admission was created with:

```powershell
.venv/Scripts/python.exe scripts/r4_campaign.py admit-source --source-config configs/research/r4_development_2025.json --output reports/r4_campaign_admission/development_2025_v1
```

This binds the existing annual R2 artifact, calendar, plan/evidence, explicit universe and actual-time seed registrations. It fits only the TRAIN-prefix state model; it does not run factor/portfolio economics. Do not overwrite that directory. Its immutable manifest is also embedded in the historical [v2 blocked design](../../configs/research/r4_matched_v2_blocked/campaign_freeze.json).

The corrected protocol version is code-owned by `src/finagent/research/r4_campaign_protocol.py`: normal accepted freeze generation uses `r4-matched-v3`, while a newly recorded provider-blocked design uses `r4-matched-v3-blocked-provider`. The operator CLI does not expose protocol-version selection; ordinary commands inherit those canonical versions automatically. Test-only variants such as `r4-matched-v3-test` are restricted to fixture generation and are not valid real freezes.

After a separately authorized successful admission, use a fresh output directory and explicit admission files:

```powershell
python scripts/r4_campaign.py freeze --research-admission RESEARCH_ADMISSION_DIRECTORY --provider-admission ACCEPTED_PROVIDER_JSON --output NEW_CAMPAIGN_DIRECTORY
python scripts/r4_campaign.py verify --research-admission RESEARCH_ADMISSION_DIRECTORY --provider-admission ACCEPTED_PROVIDER_JSON --output NEW_CAMPAIGN_DIRECTORY --accepted-freeze-id EXACT_ACCEPTED_ID
```

If the already-recorded failed provider lineage must be retained again under the corrected design, `record-blocker` likewise needs no version flag:

```powershell
python scripts/r4_campaign.py record-blocker --research-admission RESEARCH_ADMISSION_DIRECTORY --probe-directory FAILED_PROBE_DIRECTORY --output NEW_BLOCKED_DIRECTORY
```

The historical v1/v2 blocked directories and their old `minimum_mean_fold_improvement = 0.002` semantics are immutable evidence. Their labels (`r4-matched-v1[-blocked-provider]` and `r4-matched-v2[-blocked-provider]`) are superseded and cannot label a newly generated corrected artifact. The historical v2 blocked ID cannot satisfy `verify` or `run_campaign`; a future real campaign requires a newly generated accepted v3 freeze after provider admission. Any later semantic change must advance the code-owned protocol version rather than reusing a historical label. No local OHLCV or secrets belong in Git.
