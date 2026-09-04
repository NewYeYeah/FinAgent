# US-R2 primary fold-regime statistics

This increment consumes the reviewed US-R2 candidate cache and regime-v2 projection. It does not read raw 1m data, annual base Parquets, or recompute candidate features.

## Reviewed inputs

The first operator run is bound to:

- candidate-cache batch `us-r2-candidate-cache-batch-7e6c9d5406cc1c444c4fd5ca`;
- candidate-cache plan `us-r2-candidate-cache-plan-6028ce9e260a383b13aba78c`;
- shared A1 batch `us-a1-compiled-factor-batch-e2f0f128d916bfaaf0dafeb0`;
- R1 denominator `us-r1-denominator-be5184ac3883b0799c00c5dc` with 37 candidates;
- regime-v2 evidence `us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b`.

The observed candidate-cache run emitted 2,896,731 formation rows from 26 annual candidate NPZs with no raw-minute source access. These IDs are operator evidence, not Alpha or listing-history authority.

## Preregistered R2 evaluation policy

`canonical_us_r2_statistical_evaluation_policy()` is frozen before primary candidate results are inspected.

Direction is selected once from `us-r2-fold-01` TRAIN (2001-2005), using the accepted R1 15m/60m mean cross-sectional RankIC. Zero ties map to +1 and the direction is then immutable across all OOS folds and regimes.

The primary robustness cell is `fold x regime`: five frozen evaluation folds times four frozen regime labels, for 20 cells per candidate. The R1 statistical and Alpha-Gate thresholds are not relaxed. Fold-based R1 primary thresholds are mapped to the 20 fold-regime cells; pooled HAC/bootstrap and 37-candidate Holm/BH multiplicity remain required by the later terminal layer. Frequency and decay robustness remain separate later evidence and are not fabricated from the 15m/60m cache.

The inherited complete-case mechanics remain exact:

- minimum cross-section = 10;
- five stable equal-count quantiles;
- top-minus-bottom equal-weight long-short return;
- one-way turnover = half L1 weight change and reset at the session boundary;
- any non-boundary missing label omits the entire formation for every candidate;
- all feature-available labels missing only because the 60m target crosses the session are boundary skips;
- coverage is valid-feature rows divided by label-eligible rows at that formation.

The minimum evidence in every candidate/fold/regime cell is 20 metric periods and 20 distinct sessions. This preserves the accepted R1 OOS floor and the reviewed regime-v2 20-session admission floor.

## Bounded runtime and storage

The operator first materializes one direction evidence file from candidate-cache years 2001-2005. Each evaluation year 2006-2026 is then scanned at most once from its annual candidate NPZ and reduced to a compact annual primary metric NPZ with matrices for RankIC, long-short return, turnover, coverage, monotonicity and an explicit status code.

Result-level statuses such as insufficient cross-section or undefined RankIC remain in the metric cache. They are not mislabeled as source-materialization failures. The final primary statistics report contains 37 x 5 x 4 = 740 candidate/fold/regime slices and preserves blockers explicitly.

A replay validates existing immutable direction/annual metric evidence and does not reopen candidate NPZs when no derivation is missing. The report is rebuilt from the much smaller primary metric caches.

## Operator

```powershell
python scripts/evaluate_us_r2_primary_statistics.py `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --candidate-denominator reports/us_r1/us_r1_candidate_denominator.json `
  --candidate-cache-plan reports/us_r2/candidates/us_r2_candidate_cache_plan.json `
  --candidate-cache-batch-evidence reports/us_r2/candidates/us_r2_candidate_cache_batch_evidence.json `
  --candidate-data-root data/us_r2/candidates `
  --candidate-report-root reports/us_r2/candidates `
  --regime-data data/us_r2/regime/us_r2_regime_projection_v2.parquet `
  --regime-evidence reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --output-data-root data/us_r2/primary `
  --output-report-root reports/us_r2/primary
```

A successful primary report is only a prerequisite for R2 inference. It does **not** evaluate pooled HAC/bootstrap, Holm/BH, 5m/30m frequency robustness, 30m/120m decay robustness, the final R2 Alpha Gate, or any execution/live-capital authority.

The current fixed EngineeringUniverse remains survivorship-conditioned and there is still no point-in-time security master. Historical current-ticker presence must not be interpreted as listing/delisting authority or a survivorship-safe market claim.
