# US-R1 Robust Intraday Research / Deployment Alpha Gate

US-R1 is the first U.S. stage that asks whether a structural factor family is robust enough to justify downstream execution research. It is deliberately separate from US-A0 Agent Value.

## Authority boundary

- **US-A0 Agent Value Gate** asks whether Agent search adds research value versus MANUAL and PROGRAMMATIC search under the same grammar and budget.
- **US-R1 Deployment Alpha Gate** asks whether any admitted structural candidate survives dependence-aware, multiplicity-corrected intraday robustness checks.
- **US-X0/X1** asks whether accepted research alpha survives the actual MT5/CFD execution semantics and cost model.
- **Live capital/order authority** remains a later gate.

A positive US-A0 review never implies alpha. A positive US-R1 review never implies executable or live-trading authority.

`docs/status.toml` remains the sole project-stage authority. The protocol and Gate policy in this increment may be frozen before US-R1 is active, but formal R1 execution must fail closed unless `current_stage = "US-R1"` and the exact terminal A0 review/experiment/evidence graph are recorded as accepted.

## A0 → R1 candidate denominator

US-R1 does **not** select candidates by A0 RankIC, return, novelty score, or Agent arm performance.

The frozen admission rule is:

> take every `VALID_UNIQUE` structural candidate from the latest completed A0 phase, preserve first-seen experiment order, deduplicate by structural `candidate_id`, and admit the full union into the US-R1 multiplicity denominator.

Consequences:

- If PILOT terminates with `PILOT_DO_NOT_PROCEED_TO_FORMAL` or a reviewed `INCONCLUSIVE`, R1 uses the complete PILOT three-run union.
- `PILOT_PROCEED_TO_FORMAL` is not terminal and cannot start R1.
- If FORMAL is completed, R1 uses the complete FORMAL seven-run union.
- A negative Agent Value result may contract future Agent generation scope, but it does not delete Agent-origin candidates already present in the completed A0 denominator.

This prevents A0 performance from becoming an implicit pre-screen for R1 multiple testing.

## Frozen intraday research protocol

Canonical v1:

| Item | US-R1 rule |
| --- | --- |
| Market scope | accepted EngineeringUniverse only; no broad PIT/survivorship-safe market claim |
| Primary signal frequency | 15m |
| Frequency robustness | 5m and 30m |
| Primary label | same-session 60 trading-minute RAW simple return |
| Decay checks | 30m and 120m around the 60m primary |
| Session policy | XNYS regular-session / same-session only |
| Position horizon | intraday-flat |
| Purge | 60 trading minutes |
| Embargo | 60 trading minutes |
| HAC lags | 12 at 5m, 4 at 15m, 2 at 30m |
| Bootstrap unit | trading session, never individual intraday bars |
| Bootstrap | circular session blocks, 5 sessions, 2,000 samples, frozen seed |
| Multiplicity | Holm FWER + Benjamini-Hochberg FDR over the exact frozen candidate denominator |

The HAC lag choices cover one full 60-minute overlapping-label horizon at each signal frequency. Purge and embargo also cover the full primary label horizon.

Annualization is presentation-only. Intraday period counts are never treated as independent annualized sample size for inference.

## Statistical-kernel reuse from the A-share release

US-R1 intentionally reuses mature cross-market statistical primitives where the mathematics is invariant:

- `factor_stability.adjust_family_pvalues()` for Holm and BH correction;
- the same Bartlett/Newey-West long-run-variance convention used by historical A-share robust research;
- existing factor/candidate content-addressing conventions.

It does **not** copy A-share daily defaults as U.S. authority. In particular, day-level bootstrap block sizes, historical A-share thresholds, and A-share universe assumptions are not US-R1 contracts. US-R1 adds a session-level intraday bootstrap and its own frozen thresholds.

## Candidate robust evidence

For every admitted candidate, the authoritative family evidence records at least:

- primary 15m fold mean RankIC and fold RankICIR;
- worst-fold RankIC / ICIR and positive-fold ratio;
- Newey-West/HAC t-statistic and raw p-value;
- session-block-bootstrap p-value and 95% CI;
- Holm-adjusted p-value and BH q-value;
- 5m / 15m / 30m RankIC and sign consistency;
- 30m / 60m / 120m decay RankIC and sign consistency;
- long-short gross return, one-way turnover and return-per-turnover;
- feature coverage and quantile monotonicity.

A technical absence of required evidence is not a negative alpha result. It is `SYSTEM_FAILURE`.

## Canonical Alpha Gate v1

A candidate passes only when all frozen conditions are met:

- at least 3 folds;
- primary mean RankIC ≥ 0.01;
- worst-fold RankIC ≥ 0;
- mean fold RankICIR ≥ 0;
- worst-fold RankICIR ≥ -0.05;
- positive-fold ratio ≥ 2/3;
- raw HAC p ≤ 0.05;
- Holm-adjusted p ≤ 0.10;
- BH q ≤ 0.10;
- session bootstrap p ≤ 0.05 and the bootstrap lower CI is strictly positive;
- frequency sign consistency ≥ 2/3 across 5m / 15m / 30m;
- decay sign consistency ≥ 2/3 across 30m / 60m / 120m;
- minimum coverage ≥ 0.80;
- quantile monotonicity ≥ 0.25;
- mean gross long-short return ≥ 1 bp per evaluated period;
- mean one-way turnover ≤ 1.0;
- gross return-per-turnover ≥ 1 bp.

These thresholds are preregistered research/deployment-alpha criteria. They are not CFD execution-cost thresholds. Exact spread, commission, swap, slippage, quote-staleness and volume semantics remain US-X0/X1 evidence.

## Terminal semantics

Exactly three terminal families exist:

- `ROBUST_FACTOR_FAMILY`: complete evidence and at least one candidate passes the frozen Gate.
- `NO_ROBUST_FACTOR_FAMILY`: complete evidence, no technical blocker, and no candidate passes.
- `SYSTEM_FAILURE`: required evidence is technically incomplete or invalid; never relabel as no alpha.

All passing candidates are retained in the robust family. The Gate does not perform a performance-ranked top-K selection.

## Independent review

The deterministic assessment is followed by a review artifact. A reviewer may accept the machine terminal or conservatively downgrade it to `SYSTEM_FAILURE`; the reviewer may never upgrade a negative result to `ROBUST_FACTOR_FAMILY`.

A completed review has `alpha_gate_authority=true`. Positive `alpha_authority=true` and `supports_us_x0_progression=true` occur only for `ROBUST_FACTOR_FAMILY`. A reviewed `NO_ROBUST_FACTOR_FAMILY` is an authoritative negative Alpha Gate result, not evidence that alpha exists.

Even a positive review keeps:

- `status_authority=false`;
- `stage_exit_authority=false` until the exact review is accepted by `docs/status.toml`;
- `order_authority=false`;
- `live_capital_authority=false`.

## Pre-result freeze commands

These two artifacts may be frozen now because they consume no A0 result, market data, API secret or broker state:

```powershell
python scripts\freeze_us_r1_protocol.py `
  --output reports\us_r1\us_r1_research_protocol.json
```

```powershell
python scripts\freeze_us_r1_alpha_gate_policy.py `
  --output reports\us_r1\us_r1_alpha_gate_policy.json
```

Do not run formal R1 materialization until project authority actually reaches US-R1.
