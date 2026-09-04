# US-R3 Agent Boundary and Frontier Alpha Expansion

## Purpose

US-R3 starts a new preregistered research iteration after US-R2 ended with reviewed terminal `NO_ROBUST_FACTOR_FAMILY`. It extends what the research platform can express and what an Agent may propose; it does not revise the R2 result or grant trading authority.

The data-blind bundle is reproducible with:

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
python scripts/freeze_us_r3_research_iteration.py
Remove-Item Env:PYTHONPATH
```

The canonical bundle is `us-r3-research-bundle-dbfa49573ce477e71ca8d85b`, policy `us-r3-agent-boundary-21cd5b601dc578df6ecd2a2a`, and plan `us-r3-research-plan-b3793331cb19cb0544fa6857`. Freezing reads no financial data, calls no external model, accesses no MT5 surface and evaluates no financial performance.

## Agent capability boundary

The Agent may:

1. propose a bounded typed `FactorGraphSpec`;
2. propose a structured mechanism hypothesis;
3. propose falsification and invalidation criteria;
4. request deterministic graph validation.

The Agent may not submit arbitrary executable code or access labels, candidate performance, reserve/holdout evidence, positions, fills, broker state, provider tools or MT5. It cannot alter thresholds, refit direction, select candidates after results, place orders or receive live-capital authority. Persisted evidence stores structured proposals and provider/model/prompt identities, never hidden reasoning text.

Every proposal is fail-closed against graph complexity, slot and round budgets, requested capabilities, data classes, tool names, canonical candidate identity and required inputs. Valid proposals still have no Alpha meaning until the frozen denominator is evaluated by the deterministic core.

## Search-arm preregistration

```text
MANUAL        24 candidate slots
PROGRAMMATIC  24 candidate slots × at least 3 frozen seeds
AGENT         24 candidate slots × 3 independent runs
```

No arm receives performance feedback during generation. Duplicate/invalid slots remain part of the declared budget. The union denominator is frozen before any financial metric is read. Candidate filtering, direction refit and threshold relaxation are forbidden.

## Frontier catalog

The first catalog separates executable hypotheses from attractive ideas whose required data or operators do not yet exist.

| Strategy | Readiness | First implementation |
|---|---|---|
| Volatility-scaled cross-sectional momentum | executable OHLCV panel | recent return / local volatility, winsorized and cross-sectionally standardized |
| Volume-conditioned liquidity reversal | executable OHLCV panel | negative short return × relative volume, winsorized and ranked |
| Volume-confirmed range-location continuation | executable OHLCV panel | recent range location × relative volume, winsorized and standardized |
| Opening-window to closing-window market momentum | deferred | requires typed session anchors and market aggregation |
| Day/night decomposed momentum | deferred | requires admitted cross-session prices and overnight semantics |
| Order-flow/private-information conditioned reversal | deferred | requires trades, quotes and order-imbalance contracts |

The first three are transfer hypotheses, not claims that the cited literature has already proven the exact FinAgent formula. Relative volume is not silently labeled order imbalance, and a same-session close series is not used as an overnight proxy.

## Primary research basis

- Gu, Kelly and Xiu, *Empirical Asset Pricing via Machine Learning* (`10.1093/rfs/hhaa009`): motivates bounded nonlinear interactions among momentum, liquidity and volatility predictors, not unrestricted model fitting.
- Moreira and Muir, *Volatility-Managed Portfolios* (`10.1111/jofi.12513`): motivates testing volatility scaling as a transfer hypothesis; it is not treated as direct evidence for the exact intraday formula.
- Gao, Han, Li and Zhou, *Market Intraday Momentum* (`10.1016/j.jfineco.2018.06.011`) and Aït-Sahalia, Fan, Xue and Zhou, *How and When are High-Frequency Stock Returns Predictable?* (`10.3386/w30366`): motivate explicit session-anchor/seasonality candidates, which remain deferred until those operators exist.
- Bongaerts, Rösch and van Dijk, *Cross-Sectional Identification of Private Information* (`10.1093/rapstu/raaf009`): motivates separating liquidity pressure from informed price impact; it also explains why OHLCV relative volume cannot be called order imbalance.
- Barardehi, Bogousslavsky and Muravyev, *What Drives Momentum and Reversal? Evidence from Day and Night Signals* (`10.1093/rfs/hhag036`): motivates a cross-session decomposition that stays outside the current same-session authority.
- Giglio, Liao and Xiu, *Thousands of Alpha Tests* (`10.1093/rfs/hhaa111`): motivates a frozen denominator and explicit multiple-testing control for any later evaluation.

## Deterministic panel semantics

`multi_asset_panel_v1` requires aligned event time, availability time and session IDs across assets. It evaluates shared graph nodes once per asset or panel node and enforces asset, bar and estimated node-value-cell bounds before allocation. The default 64-bar limit intentionally requires same-session/short partition calls instead of accumulating a multi-year dense panel in Windows memory.

- rank: average percentile rank on available assets, with stable asset-ID traversal and averaged ties;
- z-score: population variance with `math.fsum`; zero dispersion is explicitly unavailable;
- winsorization: Type-7 quantiles and explicit lower/upper bounds;
- regime gate: the compiled policy ID must exactly match an aligned supplied mask;
- availability: insufficient history, cross-session windows, incomplete bars, insufficient breadth, zero dispersion, regime exclusion and numeric failure remain typed outcomes.

The original `single_asset_time_series_v1` path remains the default and preserves prior compiled/evidence identities.

## Development sequence

1. **US-R3-0 — contracts and numeric semantics.** Review this bundle, panel executor, tests and CI.
2. **US-R3-1 — data-blind generation pilot.** Connect a model adapter only to the proposal envelope; record token/cost/latency metadata and stop cleanly if quota is unavailable.
3. **US-R3-2 — denominator freeze.** Validate all fixed MANUAL / PROGRAMMATIC / AGENT slots and freeze invalid/duplicate accounting before results.
4. **US-R3-3 — exploratory replay.** Reuse R2 data only to debug mechanics and compare hypotheses. These results cannot grant Alpha because the corpus has already been inspected.
5. **US-R3-4 — independent evidence.** Evaluate the untouched denominator on new post-R2 observations or another independently sealed, admissible corpus under a separately reviewed gate.

MT5 is absent from every US-R3-0 through US-R3-4 research requirement. Broker integration stays downstream of a later reviewed `ROBUST_FACTOR_FAMILY` terminal.

## Test boundary

Focused tests cover graph validity, deterministic rank/tie/z-score/winsor behavior, explicit regime masks, clock and resource failures, all three executable graphs, Agent proposal admission/rejection, equal search budgets, data-blind bundle identity and a static no-`MetaTrader5` import guard.

This work grants no Alpha, US-X0 progression, execution, order, PAPER or live-capital authority.
