# US-R1 Robust Intraday Research / Deployment Alpha Gate

US-R1 is the first U.S. stage that asks whether a structural factor family is robust enough to justify downstream execution research. It is deliberately separate from US-A0 Agent Value.

## Authority boundary

- **US-A0 Agent Value Gate** asks whether Agent search adds research value versus MANUAL and PROGRAMMATIC search under the same grammar and budget.
- **US-R1 Deployment Alpha Gate** asks whether any admitted structural candidate survives dependence-aware, multiplicity-corrected intraday robustness checks.
- **US-X0/X1** asks whether accepted research alpha survives the actual MT5/CFD execution semantics and cost model.
- **Live capital/order authority** remains a later gate.

A positive US-A0 review never implies alpha. A positive US-R1 review never implies executable or live-trading authority.

`docs/status.toml` remains the sole project-stage authority. Protocol/walk-forward/Gate/formation/evaluation-policy artifacts may be frozen before US-R1 is active, but formal R1 execution must fail closed unless `current_stage = "US-R1"` and the exact terminal A0 review/experiment/evidence graph are recorded as accepted.

## A0 → R1 candidate denominator

US-R1 does **not** select candidates by A0 RankIC, return, novelty score, or Agent arm performance.

The frozen admission rule is:

> take every `VALID_UNIQUE` structural candidate from the latest completed A0 phase, preserve first-seen experiment order, deduplicate by structural `candidate_id`, and admit the full union into the US-R1 multiplicity denominator.

Consequences:

- If PILOT terminates with `PILOT_DO_NOT_PROCEED_TO_FORMAL` or a reviewed `INCONCLUSIVE`, R1 uses the complete PILOT three-run union.
- `PILOT_PROCEED_TO_FORMAL` is not terminal and cannot start R1.
- If FORMAL is completed, R1 uses the complete FORMAL seven-run union.
- A negative Agent Value result may contract future Agent generation scope, but it does not delete Agent-origin candidates already present in the completed A0 denominator.

The persisted handoff is strict: `prepare_us_r1_candidate_denominator.py` requires the A0 preregistration, ExecutionPlan, terminal experiment, terminal review, every generation-run document and the exact US-R1 stage authority. Generation runs are rehashed with the existing A0 parser and matched to the experiment's exact arm/run denominator before the structural union is formed.

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

## Purged/embargoed walk-forward materialization

US-R1 v1 reuses the already preregistered B0 calendar geometry instead of introducing a result-dependent split. Each B0 validation window becomes a completely excluded pre-evaluation gap:

```text
expanding train
     ↓
whole validation window excluded
  ├─ at least 60 trading minutes purge
  └─ at least 60 trading minutes embargo
     ↓
OOS evaluation
```

The exact three OOS evaluation windows therefore remain the B0 frozen windows. The formal runner verifies the excluded gap against the exact materialized XNYS calendar and refuses the fold if it contains fewer than 120 regular-session trading minutes. In practice the frozen validation gaps are materially larger than this minimum.

## Multi-frequency formation semantics

The A0 candidate identity remains structural. US-R1 freezes this rule before results:

> keep the same structural `window_bars` at 5m, 15m and 30m rather than re-optimizing or rescaling the window to preserve elapsed minutes.

This deliberately tests whether the same structural relation survives a sampling-frequency perturbation. The implementation reuses the existing B0/A0 `evaluate_us_baseline_feature()` function; signal frequency is separate evidence metadata and is never hidden inside a second feature engine.

All formation remains:

- regular XNYS session only;
- RAW prices;
- `available_at` PIT clock;
- same-session histories;
- complete bars only.

## Exact materialization slices

Every fold must contain exactly six content-addressed slices in this order:

1. TRAIN — 15m signal / 60m label;
2. EVALUATION — 5m signal / 60m label;
3. EVALUATION — 15m signal / 30m decay label;
4. EVALUATION — 15m signal / 60m primary label;
5. EVALUATION — 15m signal / 120m decay label;
6. EVALUATION — 30m signal / 60m label.

For each slice the runner binds:

```text
resampled query/evidence
+ same-session 1m label query/evidence
+ exact available_at join
+ bounded Parquet materialization
+ candidate observation JSONL
+ diagnostics
+ materialization-slice identity
```

The joined Python boundary is capped at 100,000 rows per slice. Missing EngineeringUniverse assets, assets without any complete bar, missing label anchors, close-anchor drift or impossible target-availability clocks are technical blockers. These are not negative Alpha results.

The candidate observation JSONL is content-addressed by SHA-256 and row count. Persisted slice evidence is re-parsed before inference so the input plan, Parquet materialization, observation artifact, diagnostics and slice IDs/counts/blockers must all agree.

## Frozen statistical evaluation policy

The period-statistics policy is a separate pre-result content-addressed contract. It fixes all choices that otherwise could become result-dependent degrees of freedom:

- **direction source:** fold-1 TRAIN 15m/60m only;
- **direction statistic:** mean cross-sectional RankIC;
- **direction rule:** `+1` for non-negative TRAIN mean RankIC, `-1` otherwise;
- **direction reuse:** the one frozen direction is applied to every OOS fold, frequency and decay horizon; OOS evidence may never flip direction;
- **minimum cross-section:** 10 assets;
- **minimum periods:** 20 TRAIN periods for direction and 20 OOS periods per fold/slice;
- **quantiles:** five stable equal-count groups sorted by feature value and asset tie-break;
- **long-short:** equal-weight top quintile minus equal-weight bottom quintile;
- **turnover:** one-way half-L1 change in the long/short weight vector, reset at each session boundary;
- **coverage:** valid feature+label cells divided by label-eligible cells for each evaluated period;
- **boundary labels:** a period is skipped only when all feature-available cells are unavailable because the target crosses the session boundary;
- **partial/non-boundary missing labels:** technical blocker, never silently dropped.

Raw period metrics remain in the original factor sign. Direction normalization is applied only by the existing family-evidence builder after TRAIN direction is frozen. This prevents fold-specific or frequency-specific sign flipping.

## Statistical-kernel reuse from the A-share release

US-R1 intentionally reuses mature cross-market statistical primitives where the mathematics is invariant:

- `factor_stability.adjust_family_pvalues()` for Holm and BH correction;
- the same Bartlett/Newey-West long-run-variance convention used by historical A-share robust research;
- existing factor/candidate content-addressing conventions.

It does **not** copy A-share daily defaults as U.S. authority. In particular, day-level bootstrap block sizes, historical A-share thresholds, and A-share universe assumptions are not US-R1 contracts. US-R1 adds a session-level intraday bootstrap and its own frozen thresholds.

## Final inference evidence chain

Once all three fold materialization manifests exist, `assemble_us_r1_alpha_evidence.py` performs no new market-data query. It replays the content-addressed observation JSONL and creates:

```text
fold-1 TRAIN 15m/60m
        ↓
DirectionEvidenceSet
        ↓
5 OOS slices × 3 folds
        ↓
period-level RankIC / quintile long-short / turnover / coverage / monotonicity
        ↓
3 FoldStatisticsReport + period-metric artifacts
        ↓
existing Newey-West/HAC + session-block bootstrap
        ↓
existing Holm/BH over exact frozen denominator
        ↓
FamilyEvidence
        ↓
existing deterministic Alpha Gate
        ↓
InferenceEvidenceGraph
```

The inference graph binds the exact three materialization manifests, direction evidence, three fold-statistics reports, three metric artifacts, family evidence and Alpha Gate assessment. It has no Alpha/stage/order/live authority by itself.

The final review runner does not trust these summaries. It reloads all three materialized fold observation artifacts and reconstructs direction, period-metric bytes, fold reports, family evidence, multiplicity corrections, Gate assessment and graph. Persisted evidence must match the replay byte-for-byte/dictionary-for-dictionary before a reviewer can sign the Gate.

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

## Independent review and canonical review contract

The deterministic assessment is followed by a review artifact. A reviewer may accept the machine terminal or conservatively downgrade it to `SYSTEM_FAILURE`; the reviewer may never upgrade a negative result to `ROBUST_FACTOR_FAMILY`.

The authoritative review implementation is `finagent.research.us_r1_review`. Formal assembly/review orchestration must use this module. An earlier review class embedded in `us_r1_gate.py` is a legacy compatibility surface and is not the stage-review authority.

A completed canonical review has `alpha_gate_authority=true`. `alpha_authority=true` and `supports_us_x0_progression=true` occur **only** for `ROBUST_FACTOR_FAMILY`. A reviewed `NO_ROBUST_FACTOR_FAMILY` is an authoritative negative Alpha Gate result with `alpha_authority=false`.

Even a positive review keeps:

- `status_authority=false`;
- `stage_exit_authority=false` until the exact review is accepted by `docs/status.toml`;
- `order_authority=false`;
- `live_capital_authority=false`.

The reviewed-evidence manifest binds the replayed inference graph, family evidence, deterministic assessment and independent review into the final R1 terminal artifact.

## Pre-result freeze commands

These artifacts may be frozen before US-R1 becomes active because they consume no A0 result, market data, API secret or broker state:

```powershell
python scripts\freeze_us_r1_protocol.py `
  --output reports\us_r1\us_r1_research_protocol.json

python scripts\freeze_us_r1_alpha_gate_policy.py `
  --output reports\us_r1\us_r1_alpha_gate_policy.json

python scripts\freeze_us_r1_walk_forward.py `
  --output reports\us_r1\us_r1_walk_forward.json

python scripts\freeze_us_r1_feature_formation_policy.py `
  --output reports\us_r1\us_r1_feature_formation_policy.json

python scripts\freeze_us_r1_statistical_evaluation_policy.py `
  --output reports\us_r1\us_r1_statistical_evaluation_policy.json
```

## Formal handoff, materialization, inference and review

Only after `docs/status.toml` actually enters US-R1 and records the exact accepted terminal A0 review/experiment/evidence graph should the candidate denominator be built:

```powershell
python scripts\prepare_us_r1_candidate_denominator.py `
  --a0-preregistration <terminal A0 preregistration JSON> `
  --a0-execution-plan <terminal A0 ExecutionPlan JSON> `
  --a0-experiment <terminal A0 experiment JSON> `
  --a0-gate-review <terminal A0 Gate review JSON> `
  --generation-run <run-1.json> `
  --generation-run <run-2.json> `
  --generation-run <...all terminal phase runs...> `
  --output reports\us_r1\us_r1_candidate_denominator.json
```

Then materialize each fold:

```powershell
python scripts\materialize_us_r1_fold.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --fold-ordinal 1 `
  --a0-gate-review <terminal A0 Gate review JSON>
```

Repeat with `--fold-ordinal 2` and `3`.

After all three fold manifests pass, assemble final inference without re-querying market data:

```powershell
python scripts\assemble_us_r1_alpha_evidence.py `
  --a0-gate-review <terminal A0 Gate review JSON>
```

Then perform independent replay-bound review:

```powershell
python scripts\review_us_r1_alpha_gate.py `
  --a0-gate-review <terminal A0 Gate review JSON> `
  --reviewer-id <reviewer> `
  --reviewed-at <timezone-aware ISO-8601> `
  --review-notes <substantive notes> `
  --attest-thresholds-unchanged `
  --attest-evidence-lineage `
  --attest-agent-value-separation `
  --attest-execution-gate-separation `
  --attest-live-capital-separation
```

All formal R1 commands remain stage-gated. Do not run denominator/materialization/inference/review until project authority actually reaches US-R1.
