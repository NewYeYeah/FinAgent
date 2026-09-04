# US-R2-2c2 candidate frequency/decay robustness

This increment evaluates the preregistered US-R2 robustness dimensions for the complete frozen 37-candidate denominator. It consumes only reviewed, content-addressed local evidence and remains non-terminal.

## Inputs

The operator requires:

- the frozen US-R2 protocol;
- the exact frozen 37-candidate R1 denominator;
- the complete passed 2006-2026 US-R2 exact robustness-base batch;
- the reviewed regime-v2 projection;
- the reviewed primary statistics plan, fold-01 TRAIN direction evidence, primary statistics report and 2006-2026 compact primary metric NPZs.

The robustness-base batch ID is intentionally **not hard-coded**. The local batch document is reconstructed and content-validated, and every annual Parquet/evidence/materialization identity must agree with the batch vectors. This preserves the real operator evidence boundary without inventing an ID that was not supplied in review.

## Frozen slices

Alternative data are the four exact PR #172 slices:

- frequency: `5m / 60m`;
- frequency: `30m / 60m`;
- decay: `15m / 30m`;
- decay: `15m / 120m`.

The reviewed primary `15m / 60m` RankIC is reused as the middle frequency/decay anchor. It is not recomputed from the robustness base.

## Candidate feature semantics

Candidate identities and denominator slots remain the original R1 candidates. Only the number of bars used to represent the same elapsed-time feature window changes with signal frequency, using the accepted R1 conversion exactly:

```text
1 + ceil((base_window_bars - 1) * 15 / target_interval_minutes)
```

The A1 v1 `FactorGraphSpec` contract itself remains frozen to the accepted 15m signal clock. US-R2-2c2 therefore does **not** widen that DSL to claim new 5m/30m A1 semantic candidate identities. Instead, the A1 graph is used as a time-grid-agnostic numeric/shared-DAG kernel: the outer `USR2RobustnessCandidateExecution.signal_interval` binds the actual 5m, 15m or 30m data plane, and each original R1 slot separately records its accepted effective window. The numeric output is regression-tested against the existing R1 interval-aware feature evaluator.

A1-0's original graph complexity budget was sized for the 15m grammar. The already accepted R1 elapsed-time conversion can require up to 37 bars at 5m, so only the graph-local `max_window_bars` / `max_lookback_bars` execution budget expands to the frozen effective window. Node, edge, depth, regime, candidate and statistical thresholds are unchanged.

The 30m ceil conversion can make two distinct R1 hypotheses numerically identical at that frequency—for example different original window lengths may collapse to the same effective 30m window. This must never shrink the frozen denominator. The implementation therefore compiles each unique numeric root once but keeps all 37 external R1 slots; colliding slots share the same computed root series. Evidence records both the 37-candidate denominator and the smaller unique numeric-graph count when such a collision occurs.

Per annual robustness-base partition:

```text
one Parquet scan -> temp annual relation
                   |-> 5m unique numeric DAG -----> 37 frozen R1 slots
                   |-> 15m unique numeric DAG ----> 30m label
                   |                           \---> 120m label
                   \-> 30m unique numeric DAG ----> 37 frozen R1 slots
```

Thus four robustness slices require three feature-interval evaluations. The 15m candidate feature matrix is reused for both decay horizons.

## Label and cross-section semantics

The existing same-session, RAW, exact-minute label semantics are preserved.

- `target_crosses_session` is a normal boundary-unrealized condition.
- `target_minute_missing` is a non-boundary partial label and omits the whole formation cross-section.
- `label_row_present=false` means the exact source/anchor minute itself is absent. Under the already frozen dynamic source/feature/label availability policy this is also a partial formation and therefore omits the whole formation cross-section.
- No cross-session fill, older-minute substitution, static asset exclusion or minimum-cross-section amendment is allowed.
- The frozen minimum cross-section remains 10.

## Compact annual evidence

The operator does not create another large permanent asset × candidate feature cache. For each year it materializes only compact formation × candidate RankIC/status arrays:

```text
data/us_r2/robustness/candidate/year=YYYY/us_r2_candidate_robustness_metrics.npz
reports/us_r2/robustness/candidate/year_YYYY/us_r2_candidate_robustness_metrics_evidence.json
```

Each annual evidence document binds the source robustness-base evidence/materialization IDs, content SHA-256, three feature-interval evaluations, status counts and row counts. Completed pairs are immutable and are content-validated before resumable reuse.

## Regime pooling and sign consistency

For each candidate and each frozen regime, all admitted EVAL formations across all five folds are pooled. Direction is still the reviewed fold-01 TRAIN direction; no robustness slice may refit it.

Frequency uses direction-normalized pooled mean RankIC at:

```text
5m / 60m
15m / 60m  (reviewed primary anchor)
30m / 60m
```

Decay uses:

```text
15m / 30m
15m / 60m  (reviewed primary anchor)
15m / 120m
```

The accepted R1 rule is reused exactly:

```text
sign_consistency = count(normalized_mean_rank_ic > 0) / 3
pass iff sign_consistency >= 2/3
```

Zero is not positive.

A candidate failing frequency or decay robustness is a research outcome, not a system failure. It remains present in the 37-candidate report. The report-level `passed` field means the evidence denominator is complete and computable; it does not mean all candidates are robust.

## Run

After pulling the merged implementation:

```powershell
python scripts/evaluate_us_r2_candidate_robustness.py `
  --frozen-protocol reports/us_r2/us_r2_frozen_protocol.json `
  --candidate-denominator reports/us_r1/us_r1_candidate_denominator.json `
  --robustness-base-data-root data/us_r2/robustness/base `
  --robustness-base-report-root reports/us_r2/robustness/base `
  --robustness-base-batch-evidence reports/us_r2/robustness/base/us_r2_robustness_base_batch_evidence.json `
  --regime-data data/us_r2/regime/us_r2_regime_projection_v2.parquet `
  --regime-evidence reports/us_r2/us_r2_regime_projection_evidence_v2.json `
  --primary-data-root data/us_r2/primary `
  --primary-report-root reports/us_r2/primary `
  --output-data-root data/us_r2/robustness/candidate `
  --output-report-root reports/us_r2/robustness/candidate
```

The final local report is:

```text
reports/us_r2/robustness/candidate/us_r2_candidate_robustness_report.json
```

## Authority boundary

US-R2-2c2 does not:

- filter or select candidates;
- admit new A1 candidates;
- broaden the A1 v1 DSL signal clock beyond 15m;
- recompute the reviewed primary direction;
- repeat pooled HAC/bootstrap/Holm/BH inference;
- execute the final US-R2 Alpha Gate;
- change `docs/status.toml`;
- grant stage-exit, Alpha, execution, order, PAPER or live-capital authority.

A real operator run of this increment is required before the final US-R2 gate can be implemented or evaluated.
