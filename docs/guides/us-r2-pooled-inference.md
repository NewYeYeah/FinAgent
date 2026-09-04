# US-R2-2b pooled inference

US-R2-2b consumes the reviewed US-R2-2a primary-period metric caches and adds the preregistered pooled statistical inference layer. It does **not** reopen raw minute data, annual base Parquet, candidate-cache NPZs, or candidate feature materialization.

## Frozen inputs

The implementation is bound to the reviewed real US-R2-2a identities:

- evaluation policy: `us-r2-statistical-evaluation-policy-385ae550f8a69dc0bcbcd9b2`
- primary statistics plan: `us-r2-primary-statistics-plan-d52413a72d50cd2bf0b0b1a4`
- direction evidence: `us-r2-primary-direction-set-baf85b7070311daad95e7ada`
- primary statistics report: `us-r2-primary-statistics-39329ed645222038a8e29fef`
- candidate denominator: the accepted 37-candidate US-R1 denominator

The primary report must remain passed, blocker-free, and contain the exact `37 candidates × 5 folds × 4 regimes = 740` cells. Every admitted cell must retain the frozen minimum period/session floors and the fold-01 TRAIN direction.

## Runtime model

The operator reads exactly the 21 annual primary-period metric caches for 2006 through 2026:

```text
21 annual primary-metric NPZs
        |
        v
chronological OOS period series
        |
        +--> candidate 1
        +--> candidate 2
        ...
        +--> candidate 37
```

The annual NPZs are loaded once and shared across all candidates. The intended data-access count is therefore **21 NPZ loads**, not `21 × 37` candidate-specific loads.

The pooled period series is always ordered by formation time. Regime labels are retained for denominator checks, but rows are **never regrouped by regime before HAC or bootstrap inference**. Grouping by regime would change the time dependence structure and is prohibited.

## Inference semantics

RankIC inference reuses the accepted US-R1 implementation directly:

- direction-normalized OOS RankIC period series;
- Newey-West/HAC mean test with the inherited 15-minute lag count (`4`);
- session-block bootstrap with `2000` samples, `5`-session circular blocks, and frozen seed `20260902`;
- two-sided raw HAC p-values;
- Holm family-wise adjustment and Benjamini-Hochberg q-values across the **complete 37-candidate denominator**;
- no candidate prefilter before multiplicity correction.

The long-short return series receives the same HAC and session-block bootstrap mechanics as a diagnostic. Long-short diagnostic p-values are not used for multiplicity correction and have no gate authority in US-R2-2b.

## Evidence floors

Because each of the 20 frozen fold-regime cells already requires at least 20 periods and 20 sessions, pooled inference fails closed unless each candidate retains at least:

```text
20 cells × 20 periods  = 400 periods
20 cells × 20 sessions = 400 distinct sessions
5 folds × 20 periods   = 100 periods per regime
```

No threshold may be weakened in response to the observed inference result.

## Operator

From the repository root:

```powershell
python scripts/evaluate_us_r2_pooled_inference.py `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --candidate-denominator reports/us_r1/us_r1_candidate_denominator.json `
  --primary-data-root data/us_r2/primary `
  --primary-report-root reports/us_r2/primary `
  --output reports/us_r2/primary/us_r2_pooled_inference_report.json
```

A structurally complete run should report:

```text
candidate_count = 37
primary_metric_npz_scan_count = 21
annual_metric_year_count = 21
multiplicity_denominator_count = 37
rank_ic_hac_evaluated = true
rank_ic_session_block_bootstrap_evaluated = true
long_short_hac_diagnostic_evaluated = true
long_short_session_block_bootstrap_diagnostic_evaluated = true
holm_evaluated = true
bh_evaluated = true
frequency_robustness_evaluated = false
decay_robustness_evaluated = false
candidate_selection_applied = false
alpha_gate_evaluated = false
raw_minute_source_access = false
annual_base_parquet_access = false
candidate_cache_npz_access = false
candidate_feature_recomputation = false
terminal_authority = false
passed = true
```

`passed=true` at this stage means the pooled inference evidence is structurally complete and reproducible. It does **not** mean that any candidate has statistically significant evidence, passes the final US-R2 Alpha Gate, or has Alpha/execution/order/PAPER/live-capital authority.

## Deferred work

US-R2-2b deliberately does not execute:

- 5-minute or 30-minute frequency robustness;
- 30-minute or 120-minute decay robustness;
- final candidate selection;
- final Alpha Gate evaluation;
- project status advancement.

Those remain later evidence increments under issue #158.
