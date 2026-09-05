# US-R3 Agent Boundary and Frontier Alpha Expansion

## Purpose

US-R3 develops a new research iteration after US-R2 ended with reviewed terminal `NO_ROBUST_FACTOR_FAMILY`. This guide distinguishes the v1 implementation reviewed at `d171615b2ad033be404139671566ef0f0535149f` from the revision 4.3 design. Read [stage authority](../status.toml) for acceptance and [the active plan](../development/current-plan.md#us-r3--correctness-evidence-design-and-controlled-research) for development order and exit gates.

The data-blind bundle is reproducible with:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python scripts/freeze_us_r3_research_iteration.py
Remove-Item Env:PYTHONPATH
```

The preserved v1 bundle is `us-r3-research-bundle-dbfa49573ce477e71ca8d85b`, policy `us-r3-agent-boundary-21cd5b601dc578df6ecd2a2a`, and plan `us-r3-research-plan-b3793331cb19cb0544fa6857`. Freezing reads no financial data, calls no external model, accesses no MT5 surface and evaluates no financial performance. It freezes three prototype graphs and budget declarations, not the complete experiment. Running this script does not implement or freeze the proposed v2 feedback policy.

## Review findings and limits

The architecture's deterministic core, content identities, independent evaluation and valid no-alpha terminals are sound. The first three proposed formulas are conventional price/volume interactions worth testing as baselines. Their citations motivate mechanisms but do not validate these exact windows, market, horizon or costs. R2 found zero complete-gate passes; the old A0 pilot did not demonstrate enough Agent value to proceed. Neither result proves all future mechanisms or richer Agents must fail.

The review at `d171615` identified two implementation gaps. The first has since been repaired and tested as described under [offline feature usability](#offline-feature-usability); the second remains a separate runtime milestone:

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

## Proposed capability expansion

The next useful Agent is a research assistant with scoped feedback, not merely a formula writer. These capabilities are design targets and remain disabled in the v1 runtime:

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
