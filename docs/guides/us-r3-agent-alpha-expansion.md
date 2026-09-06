# US-R3 Agent Boundary and Frontier Alpha Expansion

## Existing 1min data and execution feasibility

The admitted raw snapshot is local at `D:/Data/datasets--mito0o852--OHLCV-1m`; it contains 411 monthly partitions from January 1992 through March 2026 (87,719,544,647 bytes). Partition coverage does not imply every symbol has complete history. Project `/data` contains samples and derived panels; `data/market/us_etf_alpaca*` are separate daily ETF datasets.

Use the existing economic ledger to inspect minute-volume feasibility without regenerating candidates:

```powershell
python scripts/audit_us_r3_minute_liquidity.py `
  --root D:/Data/datasets--mito0o852--OHLCV-1m `
  --campaign reports/us_r3/economics/development_2025_activity_v5 `
  --output reports/us_r3/minute_liquidity/january_2025_v2 `
  --start 2025-01-01 --end 2025-01-31 `
  --opening-capital 100000 --participation-limit 0.01
```

Activate the `finagent` environment first. Each run is bounded to one month and at most 32 assets. It reads all frozen strategy arms at 5bp, binds source/ledger hashes before querying, uses the existing whole-conflict-group quarantine and keeps missing minutes explicit. The output request and summary are immutable; identical reruns reproduce the evidence, while changed inputs require another output directory. This is a historical ledger audit, so it consumes preserved ledger contents without requiring the current simulator to equal the old simulator snapshot.

At reference time 10:45, matching uses the raw minute starting 10:44 and available at 10:45. Participation is `abs(net shares per dollar of daily-opening NAV) * declared capital / observed minute volume`; opposite sleeve trades are already netted in the ledger. Capital is held constant at each session's opening for this diagnostic, not compounded across days. The reported capital ceiling is the most restrictive observed leg under the hypothetical participation limit, not estimated executable capacity. Zero volume gives a zero ceiling; missing references, unresolved sessions or aggregate notional mismatches invalidate the whole-period ceiling. Cash-only arms have no capacity estimate.

The January run matched 25,110 trade legs across 20 sessions/13 arms, with no missing trade-minute reference or frame-notional mismatch. At USD 100,000 and a 1% threshold, 218 legs exceeded the limit. There were 186,628 observed regular-session asset-minutes out of the fixed 195,000-slot grid. Neither missing bars nor source volume certifies PIT universe membership or total-market liquidity. Actual bid/ask, fees and market impact remain unmeasured. The diagnostic does not alter old PnL or allow the just-finished execution minute's volume to influence earlier orders.

Further exploratory research may use these OHLCV inputs with declared/stressed costs. Measured costs and independently admitted evidence remain requirements for their respective confirmation claims, rather than universal prerequisites for developing a testable mechanism.

## Purpose

The remaining R3 engineering is exposed through `scripts/run_us_r3_completion.py`: bounded real-provider research, frozen exploratory replay, and separately admitted independent confirmation. The operational protocol and limits are described under [bounded completion workflow](#bounded-completion-workflow). Consult `docs/status.toml` for the actual pilot outcome and outstanding acceptance conditions.

US-R3 develops a new research iteration after US-R2 ended with reviewed terminal `NO_ROBUST_FACTOR_FAMILY`. This guide distinguishes the v1 implementation reviewed at `d171615b2ad033be404139671566ef0f0535149f`, the revision 4.3 correctness/runtime design, the revision 4.4 minimum economic loop, revision 4.5 pending exits and revision 4.6 low-turnover experiment. Read [stage authority](../status.toml) for acceptance and [the active plan](../development/current-plan.md#us-r3--correctness-evidence-design-and-controlled-research) for development order and exit gates.

The data-blind bundle is reproducible with:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python scripts/freeze_us_r3_research_iteration.py
Remove-Item Env:PYTHONPATH
```

The preserved v1 bundle is `us-r3-research-bundle-dbfa49573ce477e71ca8d85b`, policy `us-r3-agent-boundary-21cd5b601dc578df6ecd2a2a`, and plan `us-r3-research-plan-b3793331cb19cb0544fa6857`. Freezing reads no financial data, calls no external model, accesses no MT5 surface and evaluates no financial performance. It freezes three prototype graphs and budget declarations, not the complete experiment. Running this script does not implement or freeze the proposed v2 feedback policy.

## Review findings and limits

The architecture's deterministic core, content identities, independent evaluation and valid no-alpha terminals are sound. The first three proposed formulas are conventional price/volume interactions worth testing as baselines. Their citations motivate mechanisms but do not validate these exact windows, market, horizon or costs. R2 found zero complete-gate passes; the old A0 pilot did not demonstrate enough Agent value to proceed. Neither result proves all future mechanisms or richer Agents must fail.

The review at `d171615` identified two implementation gaps. The panel correction is described under [offline feature usability](#offline-feature-usability); the separate v2 runtime addresses cumulative admission as described below. These are the original observations, not claims that the repaired paths still have these defects:

1. `_panel_transform()` receives intermediate values before the final per-asset completeness mask. In a synthetic aligned panel, A=100 and B=200 are complete, C is incomplete, and minimum breadth is three. With C=1 the output ranks for A/B are 0.5/1.0; with C=300 they are 0.0/0.5. Both are wrong under a valid-input breadth rule: only two inputs are complete, so the formation should be unavailable. Masking only C's final output cannot undo contamination of A/B. The node-level availability and downstream lag/rolling propagation need corrective tests and implementation.
2. Calling `validate_agent_factor_proposal()` repeatedly for the same run/slot returns valid each time. That is normal for a stateless validator, but it proves no persistent slot admission or cumulative budget enforcement. Model-tool isolation, strict external decoding and a run ledger remain separate work. A policy ID supplied as a string also does not independently authenticate regime classifications or their availability timestamps.

The original observations came from synthetic/read-only checks, not a financial backtest. Corrective tests now cover node availability, composition, clocks, future perturbation and session parity. Source regime-lineage authentication remains separate from checking supplied evidence IDs/timestamps. The original finding was specific to the new panel path and does not invalidate accepted legacy R2 statistics by inference.

## Implemented v1 Agent proposal boundary

The Agent may:

1. propose a bounded typed `FactorGraphSpec`;
2. propose a structured mechanism hypothesis;
3. propose falsification and invalidation criteria;
4. request deterministic graph validation.

The Agent may not submit arbitrary executable code or access labels, candidate performance, reserve/holdout evidence, positions, fills, broker state, provider tools or MT5. It cannot alter thresholds, refit direction, select candidates after results, place orders or receive live-capital authority. Persisted evidence stores structured proposals and provider/model/prompt identities, never hidden reasoning text.

Each proposal is checked against graph complexity, submitted slot/round ranges, requested capabilities, data classes, tool names, canonical candidate identity and required inputs. These are envelope checks, not proof of process isolation or cumulative quota enforcement. Valid proposals still require the run-level and numerical admission gates before financial evaluation.

## Implemented v2 capability runtime

`finagent.agents.r3_runtime.ResearchCapabilityRuntime` adds enforced capabilities without changing the v1 validator or bundle identity. The trusted host constructs a `DevelopmentScope`, `ResearchRuntimePolicy`, provider and optional evaluator; the model returns one bounded JSON action. The provider receives the complete compact action guide and bounded run-local feedback through `ResearchRequest.context_json`.

| Tool | Implemented boundary |
| --- | --- |
| `read_literature` | Reads an exact host-curated record ID; does not browse or fetch arbitrary URLs. |
| `read_development` | Reads admitted, bounded coverage/evaluation summaries within the frozen development scope; no raw data/path resolution. |
| `validate_factor` / `submit_factor` | Strictly decodes typed graphs and structured hypotheses using existing canonical numeric validation; no arbitrary Python. |
| `evaluate_development` | Evaluates a previously validated same-run graph through a trusted callback; checks returned scope/source/evaluator/candidate identity. |
| `recall` | Acknowledges bounded current-run feedback already included in the next context; no arbitrary memory writes or cross-run lookup. |

The SQLite ledger reserves before calling a provider and stores every admitted attempt, including invalid proposals, repairs and duplicates. Submitted/duplicate slots close; a replayed request returns its recorded result without another call. Invalid wire content is retained only as a digest and fixed diagnostic, not raw responses or hidden reasoning. Validated structured proposals are persisted for reproducible evaluation. Scoped v2 validation has its own identity and never labels feedback-informed proposals as v1 data-blind evidence. All admitted tool actions consume attempt and provider budgets, including reads; a slot count alone is not the complete adaptive search denominator.

Default v2 bounds are 24 slots, 72 total attempts, six attempts per slot, 24 development evaluations, 65,536 cumulative tokens and 250,000 micro-USD cumulative modeled cost; per-call ceilings are 16,384 tokens and 50,000 micro-USD. The run deadline is 900 seconds and the call timeout is 30 seconds. Every new call needs the full worst-case reservation available; exact known usage releases only its unused reservation. These are policy ceilings, not a direction to spend the quota. `feedback_enabled=False` provides a separate policy-bound no-development-feedback ablation, while retaining literature and validation.

One database binds one run's policy, scope manifest, implementation hash, provider and model. Restarts cannot reset budgets or change the binding. Concurrent callers are serialized; a pending crashed request returns `PENDING_RECONCILIATION`, and another request returns `RUN_BUSY`. Do not delete the database, rename a run to bypass quotas, or automatically resend an uncertain paid request. After the original workers have stopped, a trusted operator may use `ledger.abandon_pending()` to stop the run without refunding uncertain usage. Starting a new run requires a separately admitted budget; account-wide budget governance remains outside this per-run ledger.

### Offline operator

From the activated `finagent` Conda environment at the repository root:

```powershell
python scripts/check_us_r3_agent_runtime.py --output-root reports/us_r3/agent_runtime/offline_v2_scoped
```

This is a synthetic harness, not an API-generation command. It writes `us_r3_agent_runtime_policy_v2.json`, `us_r3_agent_runtime.sqlite` and immutable `us_r3_agent_runtime_smoke.json`. It exercises curated retrieval, coverage, graph validation, synthetic evaluation, submission, repair, duplicate retention and denied file access. The first run makes nine **simulated** provider calls and one synthetic evaluation; repeating the same command makes zero of both and preserves the report identity. Progress is flushed to stderr; the final summary is flushed to stdout. No API key or MT5 connection is used, and the fixture metric is not financial evidence. A changed implementation must use a new explicitly chosen output directory; old evidence must remain unchanged.

### Trusted-adapter limits before real generation

The runtime is an application-level JSON boundary, not an OS sandbox. Providers and evaluators are trusted Python adapters, never model-submitted code. The host must establish authentic development-only source lineage independently of the record's claimed partition. Arbitrary Python, final/outer/reserve paths, broker tools and regime gates are unavailable; regime source authentication remains a separate gate.

The provider must enforce a single transport attempt, actual total-token/output and spending ceilings, a transport timeout and exact usage. Do not plug in the generic provider unchanged: hidden retries or default zero-usage metadata can violate the run accounting contract. Quota exhaustion, unknown usage or transport uncertainty stops the run and retains the full reservation. A Python thread timeout cannot kill remote work or the adapter thread; late replies never execute tools, but the trusted transport must cancel/limit its own work. Real-provider contract tests and authentic data/evaluator admission remain prerequisites to a bounded real-model pilot. No production-provider readiness is claimed by the offline harness.

## Further capability targets

The v2 runtime supplies the narrow controlled interfaces above; the following richer research capabilities still need data, adapters or experimental evidence. They remain disabled in the preserved v1 path:

| Capability | Controlled interface | Required evidence |
| --- | --- | --- |
| Literature and mechanism retrieval | Curated source index, dated citations, explicit market/horizon applicability | Citation accuracy and comparison against a fixed known-factor library |
| Data diagnosis | Schema, coverage, missingness and availability summaries scoped to development | Tool cannot resolve final/holdout paths or data; fixture and access-denial tests |
| Experiment design | Typed requests for approved features, ablations, costs and evaluation on development splits | Persistent trial/evaluation quotas; all attempts and parent IDs retained |
| Repair and critique | Parser/type errors, deterministic failures and bounded development diagnostics | Bounded repairs; no budget reset; semantic critiques remain advisory |
| Development memory | Versioned source/split/proposal/feedback summaries | No final evaluation output enters prompts, caches, logs or recall |
| Portfolio/model proposals | Typed combination/training rules submitted to the existing core | Training-only fitting and a frozen rule evaluated as a complete model |

Development-only feedback is compatible with architecture decision D6. The search policy and budget are frozen before feedback; the realized candidates and model-selection rule are frozen before outer/final evaluation. Retain the no-feedback LLM as an ablation. Neither feedback availability nor a more complex grammar is evidence of incremental Agent value.

## Preserved v1 budgets and v2 comparison requirements

```text
MANUAL        24 candidate slots
PROGRAMMATIC  24 candidate slots × at least 3 frozen seeds
AGENT         24 candidate slots × 3 independent runs
```

V1 permits no performance feedback during generation. Duplicate/invalid slots must remain in the declared budget, but a complete generation ledger and denominator have not yet been materialized. Keep this behavior and its identities as the control.

V2 must distinguish per-run and total budgets: a single 24-slot manual arm must not be compared with the selected winner of three 24-slot Agent runs. Use fixed manual anchors as a common comparator, ordinal-matched deterministic/Agent runs, a no-feedback LLM ablation, and a separate compute/evaluation-matched comparison. Define how anchor candidates consume slots, how all arms share the experiment family, and how invalid/duplicate/repaired trials contribute to accounting before generation. Start with the smallest meaningful pilot; the old 24-slot figure is not a command to exhaust quota. More runs require a preregistered revision and uncertainty/power justification.

## Frontier catalog

The first catalog separates graph-representable hypotheses from ideas whose required data or operators do not yet exist. Here, executable means syntactically compilable in synthetic fixtures; it does not mean admitted for financial evidence.

| Strategy | Readiness | First implementation |
|---|---|---|
| Volatility-scaled cross-sectional momentum | feature usability verified; financial admission pending | recent return / local volatility, winsorized and cross-sectionally standardized |
| Volume-conditioned liquidity reversal | feature usability verified; financial admission pending | negative short return × relative volume, winsorized and ranked |
| Volume-confirmed range-location continuation | feature usability verified; financial admission pending | recent range location × relative volume, winsorized and standardized |
| Opening-window to closing-window market momentum | deferred | requires typed session anchors and market aggregation |
| Day/night decomposed momentum | deferred | requires admitted cross-session prices and overnight semantics |
| Order-flow/private-information conditioned reversal | deferred | requires trades, quotes and order-imbalance contracts |

The first three are transfer hypotheses, not claims that the cited literature has already proven the exact FinAgent formula. Relative volume is not silently labeled order imbalance, and a same-session close series is not used as an overnight proxy.

The volatility graph uses a four-endpoint return (45 minutes on a 15m clock), an eight-return local standard deviation, and a proposed 60m response. These are separate lookback and prediction horizons. A small estimated volatility can amplify noise. The volume graphs compare current activity with the latest eight bars, which is not a same-time-of-day seasonal baseline and can confound regular opening/closing activity with information. Their first ablations should test unscaled return, seasonal activity normalization, market-relative signal and the volume interaction separately. Rank/z-score are useful normalization, but a monotonic transform ordinarily leaves RankIC ordering unchanged; graph novelty alone can exaggerate economic novelty.

Session-anchor market momentum deserves higher priority because it identifies a specific formation/holding window. It needs time-series/market-timing endpoints and an explicit entry after signal availability, not a forced cross-sectional rank gate. Day/night features may predict an intraday-flat holding, but must not be enabled until historical adjustment/lifecycle semantics exist. The v1 catalog's blanket `same_session_only=true` is a scope label, not a faithful representation of the deferred day/night research requirement; correct the distinction in a new catalog version.

## Primary research basis

- Gu, Kelly and Xiu, *Empirical Asset Pricing via Machine Learning* (`10.1093/rfs/hhaa009`): motivates bounded nonlinear interactions among momentum, liquidity and volatility predictors, not unrestricted model fitting.
- Moreira and Muir, *Volatility-Managed Portfolios* (`10.1111/jofi.12513`): motivates testing volatility scaling as a transfer hypothesis; it is not treated as direct evidence for the exact intraday formula.
- Gao, Han, Li and Zhou, *Market Intraday Momentum* (`10.1016/j.jfineco.2018.06.011`) and Aït-Sahalia, Fan, Xue and Zhou, *How and When are High-Frequency Stock Returns Predictable?* (`10.3386/w30366`): motivate explicit session-anchor/seasonality candidates, which remain deferred until those operators exist.
- Bongaerts, Rösch and van Dijk, *Cross-Sectional Identification of Private Information* (`10.1093/rapstu/raaf009`): motivates separating liquidity pressure from informed price impact; it also explains why OHLCV relative volume cannot be called order imbalance.
- Barardehi, Bogousslavsky and Muravyev, *What Drives Momentum and Reversal? Evidence from Day and Night Signals* (`10.1093/rfs/hhag036`): motivates a cross-session decomposition that stays outside the current same-session authority.
- Giglio, Liao and Xiu, *Thousands of Alpha Tests* (`10.1093/rfs/hhaa111`): motivates a frozen denominator and explicit multiple-testing control for any later evaluation.

Further design references checked for this review:

- [AlphaAgent](https://arxiv.org/abs/2502.16789v2) studies originality, hypothesis/formula alignment and complexity controls. These motivate ablations; the paper does not establish FinAgent's intraday or CFD profitability.
- [AlphaForge](https://arxiv.org/abs/2406.18394v5) separates factor discovery and combination. A FinAgent extension must validate the frozen complete model rather than report post-hoc combinations of factor returns.
- [Trading Costs of Asset Pricing Anomalies](https://pages.stern.nyu.edu/~afrazzin/pdf/Trading%20Cost%20of%20Asset%20Pricing%20Anomalies%20-%20Frazzini,%20Israel%20and%20Moskowitz.pdf) finds short-term reversal particularly constrained by costs in its institutional equity sample. This supports early cost sensitivity, not direct transplantation of its cost estimates to CFDs.

## Deterministic panel semantics

The `multi_asset_panel_v1` compiled scope now produces v2 materializations with aligned event time, close availability and session IDs across assets. It evaluates shared graph nodes once per asset or panel node, enforces continuous 15m spacing within sessions, and enforces asset, bar and estimated node-value-cell bounds before allocation. The 64-bar kernel limit is not a complete process RSS bound. The usability operator explicitly streams session partitions and bounds DuckDB separately.

- rank: average percentile rank on available assets, with stable asset-ID traversal and averaged ties;
- z-score: population variance with `math.fsum`; zero dispersion is explicitly unavailable;
- winsorization: Type-7 quantiles and explicit lower/upper bounds;
- regime gate: the compiled policy ID must exactly match an aligned mask carrying explicit source identity and causal availability timestamps; source authenticity is not inferred from those strings;
- availability: every node is masked before consumption, including the complete intervening raw window for lag/endpoint-return nodes; warm-up is session-local and incomplete inputs cannot affect valid peers.

The original `single_asset_time_series_v1` path remains the default and preserves prior compiled/evidence identities.

## Offline feature usability

`scripts/check_us_r3_alpha_usability.py` verifies all three frozen prototypes against an independent direct-formula implementation. It selects only OHLCV, identity, completeness and input clocks from the existing `decay_15m_30m` slice. The slice is an input view, not a response-horizon or profitability evaluation. Byte-level source hashing binds the whole file, but forward-label values are never queried, interpreted or used by feature computation.

The operator streams 512-row fetches into one session, with a 256MiB DuckDB memory setting, one database thread, a task-owned spill directory capped at 1GiB, and pre-allocation session/asset bounds. Absent records become explicitly incomplete internal padding, not imputed observations; assets are not silently dropped to obtain rectangular data. Duplicate asset/clocks and off-grid clocks fail closed. Reports distinguish observed rows from padding.

Run the complete intended source set into a new output directory:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
$env:PYTHONPATH = (Resolve-Path src).Path
$r3Arguments = @(
    'scripts/check_us_r3_alpha_usability.py',
    '--output-root', 'reports/us_r3/usability/operator_run'
)
foreach ($r3Year in 2006..2026) {
    $r3Arguments += @(
        '--source', "data/us_r2/robustness/base/year=$r3Year/us_r2_robustness_base.parquet"
    )
}
python @r3Arguments
Remove-Item Env:PYTHONPATH
```

Progress and full error tracebacks go to flushed stderr; final JSON goes to stdout. Exit 0 means all three formulas produced usable inputs and matched the numerical reference; exit 1 means failure/non-usability; interruption returns 130. An OS hard kill cannot print a Python traceback, but previously published annual artifacts survive.

Repeat exactly the same command to resume. A frozen usability plan binds source hashes, implementation sources, candidates and minimum breadth before evaluation. Annual JSON is atomically published and verified, never replaced. Changed implementation, source set or breadth requires a new directory; old evidence is not silently reused. The final manifest is `us_r3_feature_usability.json`. Source hashing still occurs on resume; Parquet queries and feature evaluations do not.

The local 21-source run covered 5,092 sessions and 2,846,317 observed rows, with 13,013 padded missing positions and at most 650 aligned rows per session. All three candidates matched the reference at absolute/relative tolerance `1e-10`; the repeat reused all 21 annual artifacts with zero feature evaluations. This tolerance and default breadth three are engineering checks, not changes to R1/R2 statistical thresholds. The 2026 source is partial-year (61 sessions).

**This is not a backtest or Alpha acceptance.** It computes no forward-return metrics, makes no selections, calls no model/provider/MT5 interface and grants no execution authority. Full R3 completion still requires the evidence/cost protocol, enforced runtime, context mechanisms, controlled pilot and appropriate frozen financial/independent evaluation in the active plan.

## Evidence and development decisions

### Minimum economic screen operator

`scripts/run_us_r3_economic_screen.py` provides two explicit steps: freeze the local source/calendar/exposure/strategy/cost binding, then evaluate that exact protocol. It uses the active Conda environment and has no model or MT5 dependency:

```powershell
conda activate finagent
python scripts/run_us_r3_economic_screen.py freeze `
    --source "data/us_r2/robustness/base/year=2025/us_r2_robustness_base.parquet" `
    --calendar reports/us_calendar/xnys_1992_2026.json `
    --base-plan reports/us_r2/robustness/base/year_2025/us_r2_robustness_base_plan.json `
    --base-evidence reports/us_r2/robustness/base/year_2025/us_r2_robustness_base_evidence.json `
    --start 2025-01-02 --end 2025-12-31 `
    --execution-profile pending_exit_5m `
    --output reports/us_r3/economics/development_2025_pending_v3/protocol.json

python scripts/run_us_r3_economic_screen.py run `
    --protocol reports/us_r3/economics/development_2025_pending_v3/protocol.json `
    --output-root reports/us_r3/economics/development_2025_pending_v3
```

An existing protocol/output is immutable. Exact repeats reuse session artifacts and reconstruct the identical summary without querying Parquet when all sessions are complete. Code or input changes require a new explicitly chosen protocol/output path. An interrupted run keeps completed days; source hashes and report identities are checked before reuse. The operator prints flushed session progress to stderr and a JSON result to stdout. A zero exit code means the report was produced, including a valid `EXPLORATORY_INCOMPLETE_EVIDENCE` terminal; it does not mean economic acceptance.

The seven arms are the three preserved graph prototypes, same-session opening momentum with/without the contemporaneous eligible-universe mean, eligible equal-weight and cash. The opening mechanisms are operator-local experimental features, not newly admitted Agent/FactorGraph operators. They do not incorporate overnight return, a market index, a fitted beta, trailing time-of-day volume or performance-based candidate selection. Selection uses positive top-five scores with at least 20 valid inputs; rank reversal scores are centered at 0.5. All candidate/cost combinations remain in the report.

The ledger uses initial daily NAV of one, at most one-quarter daily-opening NAV per 60m sleeve, 15m decisions, one full bar of delay, long-only cash-limited baskets and net share trading. Simultaneous exits/entries in the same asset incur costs only on net external notional. The final exit is scheduled 15m before the accepted calendar close, including half-days. Notional-to-share conversion at the execution reference is an idealized research sizing assumption. Costs are 0/1/5/10 bps per gross traded notional, not per half-L1 turnover, and are scenario assumptions rather than measured CFD spreads. No leverage, borrow, taxes, intraday cash interest, tick-size/lot rounding or measured capacity is modeled.

Feature inputs and execution references have separate bounded projections. Features retain full-window completeness. The v2 execution reader uses only `source_price` and its exactly matching `source_available_at` from the raw 1m source side of the R2 join; it does not read `target_available_at`, `label_value` or `label_available`. The two DuckDB readers each use a 256MiB setting, 512-row fetches and a bounded session; they are not a measured total-process RSS limit. Full ledgers are persisted per session and removed from memory before aggregate reduction.

Missing entry prices cancel the whole proposed basket without reallocating to observed winners. Missing held marks produce an unavailable intraday equity point; they do not forward-fill a price. The default `strict_15m` profile invalidates a session immediately on a missing scheduled exit. The explicitly selected `pending_exit_5m` profile instead reads authentic source-side anchors from `frequency_5m_60m`, sells observable due legs and retains the remaining shares until their next observed reference. It pauses new baskets while any due exit is pending. It keeps the original 15m signal, entry delay, sleeve size and scheduled exits; it does not generate 5m signals. Retry stops five minutes before calendar close, including half-days. A remaining position invalidates the session even if a closing price subsequently exists. Ledgers retain pending shares, actual delayed fill clocks, costs and missing equity marks; summaries include coverage, delays and suppressed baskets.

Every calendar session remains in the denominator, including wholly missing sessions. Any unresolved day makes full-period compounded return and daily-close drawdown unavailable. Available-session means are explicitly diagnostic and can be selection-biased; different arms may have different evaluable subsets. Break-even cost is a zero-cost-path linear diagnostic only; the separate fee scenarios rerun cash accounting, so that diagnostic is not a promised executable cost limit. `EXPLORATORY_COMPLETE` means the frozen experiment produced complete session accounts; it is compatible with negative returns and does not admit Alpha or establish Agent value. The 5m profile is a separately frozen execution-policy experiment, not a silent replacement of the retained strict 15m evidence.

### Bounded daily opening experiment

For the separately frozen low-turnover comparison, add `--experiment low_turnover_opening` and retain `--execution-profile pending_exit_5m` in the freeze command; use a new output path such as `reports/us_r3/economics/development_2025_opening_v4/protocol.json`. Run with that protocol and the corresponding output root. The default experiment remains the seven-arm sleeve baseline. Changes to implementation require a fresh protocol, even when rerunning a prior experiment; local implementation snapshots preserve the code used for earlier artifacts.

The new experiment retains all seven original arms and adds `opening_60m_momentum`, `opening_60m_relative_momentum` and the matched `opening_60m_equal_weight` control. Only two new mechanism variants are searched. All three new arms decide at open-plus-60m, attempt one cash-limited full-NAV basket at open-plus-75m, retain fixed shares and exit at close-minus-15m. A missing entry cancels the whole basket for the day; later prices/signals never replenish or retry it. The existing pending-exit rules apply. Missing early feature history disables momentum; the matched equal-weight control follows the existing current-bar eligibility rule, so its active/canceled days may differ and are reported explicitly.

The protocol binds the schedules, capital rule, controls, full 0/1/5/10-bp grid and primary 5-bp diagnostic. Summaries retain active/cash-only days, basket counts and paired daily return differences against matched equal-weight, cash and the corresponding sleeve strategy. Compounded-return differences are comparisons of two accounts, not a return on a tradable spread; the schedules also differ in exposure and risk. Zero-cost arithmetic mean or a small positive linear break-even diagnostic can coexist with negative compounded return, and must not override the primary endpoint. No automatic ranking, selection or Alpha acceptance is performed.

### Causal activity context and bounded reversal experiment

`--experiment activity_reversal` retains the previous ten arms and adds one activity-conditioned relative reversal, its no-activity ablation and a trigger-matched broad equal-weight control. It requires the pending-exit profile and three explicitly bound prior-year history artifacts:

```powershell
conda activate finagent
python scripts/run_us_r3_economic_screen.py freeze `
    --source data/us_r2/robustness/base/year=2025/us_r2_robustness_base.parquet `
    --calendar reports/us_calendar/xnys_1992_2026.json `
    --base-plan reports/us_r2/robustness/base/year_2025/us_r2_robustness_base_plan.json `
    --base-evidence reports/us_r2/robustness/base/year_2025/us_r2_robustness_base_evidence.json `
    --history-source data/us_r2/robustness/base/year=2024/us_r2_robustness_base.parquet `
    --history-base-plan reports/us_r2/robustness/base/year_2024/us_r2_robustness_base_plan.json `
    --history-base-evidence reports/us_r2/robustness/base/year_2024/us_r2_robustness_base_evidence.json `
    --start 2025-01-02 --end 2025-12-31 `
    --execution-profile pending_exit_5m --experiment activity_reversal `
    --output reports/us_r3/economics/development_2025_activity_v5/protocol.json
python scripts/run_us_r3_economic_screen.py run `
    --protocol reports/us_r3/economics/development_2025_activity_v5/protocol.json `
    --output-root reports/us_r3/economics/development_2025_activity_v5
```

This bounded operator starts at the year's first session and takes exactly the preceding 20 calendar sessions from the prior-year source. History is feature-only warm-up, not 20 additional financial trials. Every session advances the history, including missing days. Same-slot volume uses a median of all 20 complete observations and a positive denominator; current-session data is added only after the day's ratios are computed. Slots are relative to calendar open, preserving DST alignment; missing afternoon slots after half-days remain unavailable rather than being borrowed from earlier full days. Partial resume reconstructs this state including already evaluated days; complete resume reads no Parquet. Input hashes are checked for history as well as the evaluation source.

The hypothesis selects positive current-bar mean-minus-asset returns when same-slot relative volume is at least 2, with at least 20 valid-history assets before the mask and at most five selected names. It is not an opening-anchor momentum rule and not order-flow data. From open-plus-60m, the first eligible signal gets one cash-limited basket after a 15m delay, held for 60m. Missing entry references cancel the day; there is no second attempt. Exit cutoffs and costs reuse the accepted exploratory ledger. The ablation removes only the volume mask while retaining history eligibility, so its first trigger time may differ. The broad equal-weight control shares the conditional signal trigger, although execution-price availability may cancel different baskets.

Full per-asset/day `activity_ratios` remain in session evidence. The existing paired-comparison report also contains the activity strategy against both controls and cash. The frozen follow-up rule requires positive full-period 5-bp compounded return and positive paired mean excess against both controls; failing any condition stops this rule. This is an exploratory triage rule, not independent statistical acceptance. History metadata binding does not authenticate upstream data or admit Agent access.

The corrected 2025 screen completed on 2026-09-06 with all 250 sessions recorded and a zero-evaluation resume. It retained an incomplete-evidence terminal: source anchors are genuinely missing and no trading arm has a complete annual account path. See the stage authority and risk register for the remaining work. The original feature-completeness pricing screen remains under `reports/us_r3/economics/development_2025_v1`, with its implementation snapshot; its available-session numbers are superseded by the explicit raw-anchor profile, not relabeled accepted results. Neither screen authenticates an independent sample or enables Agent feedback access.

The single development sequence and its exit gates are maintained in [current-plan.md](../development/current-plan.md#us-r3--correctness-evidence-design-and-controlled-research). Correctness and evidence/cost design lead, followed by enforced research tools, context features, the controlled pilot, exploratory model evaluation and independent confirmation. All research increments can run without MT5.

An alternate source for the same asset/dates is reconciliation, not fresh statistical evidence. A new ticker subset exposed to the same research process can share market shocks and selection bias. A later date range must also be uninspected by the research team/model workflow. Prospective observations after the complete model/protocol freeze provide the clearest practical separation, subject to adequate effective sessions and market regimes. No fixed short calendar period guarantees enough test power.

R2's gross return and return-per-turnover hurdles are not an explicit spread/slippage/borrow/impact model. Add broker-neutral cost scenarios and delay/participation stress during research; report net evidence and break-even costs alongside the unmodified old diagnostics. Costs based only on OHLCV remain assumptions. Conditional activity, market/sector exposure, overlapping holdings, cash periods and all tried variants belong in the new experiment protocol.

## Review scores

The following scores are the historical planning-review snapshot at `d171615`, not an automatically updated assessment after each implementation increment.

Scores below are reviewer judgments on a 0–10 scale, not calibrated probabilities of profitability. Research priority uses five equally weighted axes: plausible mechanism, relevant independent support, data/semantic fit, economic plausibility and falsifiability. The evidence/readiness scores are separate; a plausible idea can still have zero validated Alpha evidence. Uncertainty is at least about one point for priority and design scores.

| Area | Score | Interpretation |
| --- | --- | --- |
| Existing research engineering foundation | 8/10 | Strong identities, replay and frozen gates; this does not excuse the new panel defect. |
| Current Agent boundary design | 7/10 | Clear ceilings and typed proposals; permanent data blindness limits useful research. |
| Implemented R3 Agent research capability | 4/10 | Proposal validation exists; runtime tools, durable quotas, feedback isolation and generation comparison remain incomplete. |
| Demonstrated Agent incremental value | 2/10 | A0 had a negative progression decision; no richer R3 pilot exists. This is an evidence score, not a theorem about LLM ability. |
| Three v1 Alpha hypotheses, research value | 5/10 | Reasonable inexpensive baselines, limited new information and substantial cost/context uncertainty. |
| Validated deployable Alpha evidence | 0/10 | Zero R2 complete-gate passes and no independently evaluated R3 strategy. Zero records missing positive evidence, not an estimated zero chance of discovery. |
| Original 4.2 development design | 6/10 | Useful contracts, but generation preceded correctness/enforcement and the independent-sample/cost design was too late. |
| Revised 4.3 development design | 8/10 target | Better dependencies and falsifiable exits; implementation and market outcomes remain unproven. |

| Hypothesis | Five axis scores: mechanism / support / data / economics / falsifiability | Research priority | Financial-evaluation readiness |
| --- | --- | --- | --- |
| Volatility-scaled momentum | 6 / 4 / 7 / 4 / 6 | 5.4/10 | Pending numeric gate and cost/denominator freeze |
| Volume-conditioned reversal | 5 / 3 / 6 / 2 / 6 | 4.4/10 | Pending numeric gate; particularly cost-sensitive |
| Volume-confirmed range location | 5 / 3 / 7 / 3 / 6 | 4.8/10 | Pending numeric gate; distinguish interaction from baseline trend |
| Opening-to-closing market momentum | 7 / 7 / 5 / 5 / 8 | 6.4/10 | Session anchors/market timing evaluator required |
| Day/night information | 7 / 6 / 2 / 4 / 6 | 5.0/10 | Cross-session data/action semantics missing |
| Order-flow-conditioned reversal | 7 / 6 / 1 / 3 / 6 | 4.6/10 | Required trades/quotes are absent |

The practical research recommendation is to improve information/context and falsification quality before increasing formula counts. A successful system can reject every candidate; passing CI or meeting a research target never guarantees a positive Alpha result.

## Test boundary

Focused tests cover graph validity, deterministic rank/tie/z-score/winsor behavior, explicit regime masks, clock and resource failures, all three executable graphs, Agent proposal admission/rejection, equal search budgets, data-blind bundle identity and a static no-`MetaTrader5` import guard.

This work grants no Alpha, US-X0 progression, execution, order, PAPER or live-capital authority.

## Bounded completion workflow

Use the activated `finagent` environment. Freeze first, then run against the same immutable protocol:

```powershell
python scripts/run_us_r3_completion.py freeze --economic-protocol reports/us_r3/economics/completion_source_v6/protocol.json --output NEW_PREREGISTERED_RUN/protocol.json
python scripts/run_us_r3_completion.py run --protocol NEW_PREREGISTERED_RUN/protocol.json --output-root NEW_PREREGISTERED_RUN
```

The second command uses the configured DeepSeek account and consumes paid API quota on an unfinished run. A completed run verifies the protocol, source hashes, frozen membership and all twelve run identities and returns with zero model/evaluator calls. Do not replace the output directory to bypass an exhausted or uncertain ledger. Partial restart reuses deterministic request IDs and completed evidence; an uncertain in-flight request is never silently resent. Protocol changes require a new identity and must retain earlier attempts in the research history.

The completed `pilot_v1` is stopped, not an instruction to start another search. Its exact implementation is retained under `reports/us_r3/completion/pilot_v1/implementation`. Later changes (precise generator/ledger types, a variable rename and stronger prospective receipt endpoint checks) intentionally change the current code identity. `completion_source_v6` only refreshes the local source contract against current code; it has no new performance run. Reproduce the historical zero-call result with its snapshot:

```powershell
$env:PYTHONPATH = (Resolve-Path reports/us_r3/completion/pilot_v1/implementation).Path
python reports/us_r3/completion/pilot_v1/implementation/run_us_r3_completion.py run --protocol reports/us_r3/completion/pilot_v1/protocol.json --output-root reports/us_r3/completion/pilot_v1
Remove-Item Env:PYTHONPATH
```

The pilot has four methods, three runs per method, three candidate slots per run and at most three development evaluations per run. All 36 slots remain in the denominator. The manual controls repeat the three preserved deterministic prototypes; this is not three independent human researchers. Programmatic windows use fixed seeds. Blind LLM sees contracts and validation feedback, while feedback Agent also receives authorized development economics. The two LLM methods have identical slot/attempt/token/cost ceilings; feedback is the treatment. Neither sees validation/outer prices. This pilot uses the existing graph grammar; local activity/session-context capabilities are not implicitly added to Agent permissions.

Only `deepseek-v4-pro` at the official endpoint is admitted by this transport. It makes one completion request, disables reasoning output and retries, validates cache-hit/cache-miss/input/output usage, and executes inside a killable process with a 45-second total call budget. Unknown usage retains the full reservation and stops the run. Keys remain in the host worker and neither credentials nor hidden reasoning enter model context or evidence. Quota availability is checked before each completion. Runtime accounting is an upper-bound reservation, not a promise of provider invoice reconciliation.

The total external cost ceiling is USD 1.50. The tariff frozen on 2026-09-06 uses the [official peak DeepSeek prices](https://api-docs.deepseek.com/quick_start/pricing/): USD 0.044/1.32 per million cached/uncached input tokens and USD 3.96 per million output tokens. Off-peak billing can be lower. Reverify pricing before a later protocol; do not change the tariff of a started experiment.

Source/plan/evidence/calendar hashes admit the already-exposed local R2 snapshot for exploration. There is no claim of upstream reauthentication. The 2025 window is split into 82 development, 82 validation and 84 outer exploratory sessions, with one whole purged session at each boundary. The evaluator's SQL projection is restricted to the authorized dates; forward labels are absent from the feature/execution projections. All folds remain globally exposed. Missing prices stay missing and can invalidate complete returns.

After development, each run selects the complete candidate with the highest strictly positive development net return at the frozen 5bp cost, using candidate identity to break ties; otherwise it selects cash. All twelve memberships, directions, selection logic, execution clocks and costs are frozen before validation/outer replay. Reports preserve all run returns, 0/1/5/10bp costs, two-bar-delay stress, cash/trading diagnostics, invested-weight concentration, structural/behavioral duplication, and paired equal-weight comparisons. Mechanism prose is validated as a falsification contract; that does not verify its causal explanation. Existing fixed mechanism ablations remain in the economic campaign, while the pilot adds feedback removal and matched allocation controls. Sector and capacity evidence remain explicitly unavailable.

Daily uncertainty uses fixed five-lag Bartlett HAC and five-session circular bootstrap blocks. Bonferroni accounts for 36 slots times two primary endpoints (cash and eligible equal-weight). Three runs are descriptive, not a population-level Agent superiority test. The 999 bootstrap draws cannot resolve the extreme adjusted tail reliably, so the report explicitly flags this limitation. The normal power design assumes a 5bp daily effect, 50bp daily standard deviation, AR(1)=0.2, family alpha 0.05 and power 0.8: 1,632 effective sessions, approximately 2,448 calendar sessions. These are preregistered planning assumptions, not estimated certainty or a reason to relax a failed threshold.

## Independently admitted final returns

`us_r3_confirmation.py` implements the final-return gate. It deliberately requires an externally trusted receipt hash before opening any final return file. A receipt must bind the exact frozen model/protocol IDs, return-file SHA-256, independent reviewer identity, non-exposure attestation, point-in-time universe and cost/execution admission, the exact scheduled-session list, primary 5bp policy and observation start/end timestamps. `preregistered_at_utc` must lie between model freeze and the start of observations; the calendar must contain exactly the frozen `planning_calendar_sessions`, preventing outcome-dependent shortening/extension. This implementation admits prospective observations strictly after `frozen_at_utc`; alternate historical confirmation is not supported by this command.

The receipt's hash is supplied by the trusted host/operator following independent review. Merely putting a reviewer name or a self-computed digest inside a model action does not authenticate evidence. The receipt and its trust-root delivery remain an external responsibility; this CLI is not a signing authority or an independent reviewer.

The return artifact is JSON with `model_id`, `sessions`, `equal_weight_net_returns` and `series`. The series keys must be exactly every `method-run` member in the frozen model (for example `manual-0`); each array must contain one finite net return or explicit `null` per scheduled session. Missing observations are retained and yield insufficient evidence, never silently dropped. To evaluate an independently admitted artifact:

```powershell
python scripts/run_us_r3_completion.py confirm --model reports/us_r3/completion/pilot_v1/frozen_model.json --protocol reports/us_r3/completion/pilot_v1/protocol.json --receipt PATH_TO_ADMITTED_RECEIPT --trusted-receipt-sha256 INDEPENDENTLY_SUPPLIED_SHA256 --returns PATH_TO_FINAL_RETURNS --output PATH_TO_IMMUTABLE_CONFIRMATION_REPORT
```

The gate checks chronology, membership, calendar, cost and hashes before inference. Each member ends `CONFIRMED_POSITIVE`, `CONFIRMED_NEGATIVE` or `INSUFFICIENT_INDEPENDENT_EVIDENCE`. Positive requires sufficient effective observations, positive adjusted lower means against both controls, positive compounded net return and the preregistered economic effect versus equal-weight. Independent statistical review remains required. No terminal automatically grants Alpha or broker authority. When no source is admitted, the exploratory run records the insufficient-evidence terminal without opening or inventing a final dataset.

## Follow-up audit and guided workflow

The follow-up CLI keeps the original pilot immutable:

```powershell
python scripts/run_us_r3_followup.py review --previous-root reports/us_r3/completion/pilot_v1 --output reports/us_r3/followup/review_v1.json
python scripts/run_us_r3_followup.py evidence-plan --previous-root reports/us_r3/completion/pilot_v1 --output reports/us_r3/followup/evidence_plan_v1.json
```

The review recomputes daily cost/PnL, compounding and drawdown without the production summarizer, reads SQLite in read-only mode, and verifies all slot/calendar/selection/cost/delay identities. It also checks the source snapshot manifest. This is a reproducible technical audit by the implementer; `reviewer_independent_of_author=false` and `AWAITING_EXTERNAL_ATTESTATION` remain explicit. No command fabricates a reviewer signature. The evidence plan lists unavailable quote/trade, cost, PIT-universe and independent-sample requirements; its feasibility scenarios do not change the old endpoints or permit further search.

For a newly preregistered adherence experiment, freeze before any model call:

```powershell
python scripts/run_us_r3_followup.py freeze-workflow --previous-root reports/us_r3/completion/pilot_v1 --output NEW_WORKFLOW_RUN/protocol.json
python scripts/run_us_r3_followup.py run-workflow --protocol NEW_WORKFLOW_RUN/protocol.json --output-root NEW_WORKFLOW_RUN
```

The policy permits three runs, one candidate and one evaluation per run, six attempts per run and at most USD 0.45 total API cost. Returns are diagnostic and cannot select, replace or extend runs. Only the old development dates are queried; no validation/outer/final results are read by the runner. Every run must complete validation, real development evaluation and identical submission to pass. All failed attempts remain charged and visible.

`ResearchCapabilityRuntime(..., require_evaluated_submission=True)` binds the new workflow in the SQLite run identity. Its required tool/action is visible in model context and enforced at dispatch. Direction must be positive, the evaluated candidate must be the slot's validated candidate, and submission must preserve the exact graph and hypothesis. State is reconstructed from committed slot history, not only the last six feedback messages. Existing policies are not silently upgraded. A pending or busy worker now raises a reconciliation requirement without writing a final report; stop/reconcile the original worker before attempting recovery, and never create a replacement directory to bypass uncertain usage.

The completed `workflow_v1` passed three runs in ten calls with USD 0.029027 conservative charges. One invalid attempt was retained; all three proposals reused existing baselines and remained negative at 5bp. This accepts a guided tool workflow, not novel factor discovery or autonomous Agent superiority. The exact run source is preserved; a later pending-worker guard changes the current code identity. Reproduce the completed zero-call result with:

```powershell
$env:PYTHONPATH = (Resolve-Path reports/us_r3/followup/workflow_v1/implementation).Path
python reports/us_r3/followup/workflow_v1/implementation/run_us_r3_followup.py run-workflow --protocol reports/us_r3/followup/workflow_v1/protocol.json --output-root reports/us_r3/followup/workflow_v1
Remove-Item Env:PYTHONPATH
```

The historical snapshot reproduces an already-completed run; use current source for new runs and pending-worker handling. External review, authentic historical execution costs and independently admitted data remain separate prerequisites for stronger research claims.
