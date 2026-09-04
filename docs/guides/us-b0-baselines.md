# US-B0 deterministic intraday baselines

US-B0 establishes the non-Agent denominator that later Agent-value experiments must beat under the same certified data, universe and validation gates. The code path is certification-bound and does not create Alpha, factor-selection, transaction-cost or deployment authority.

## Frozen v1 protocol

```text
signal clock              15m
robustness clocks          5m / 30m
label                      us_same_session_60m_simple_return_raw
label horizon              60 trading minutes
formation clock            available_at
price basis                RAW
feature history            same session only
resampled-bar requirement  complete bars only
candidate generator        MANUAL / deterministic
```

No feature may use a future session total, next-session observation, adjusted-price transform that is not certified, or broker/reference price as a silent replacement for the research source.

## Initial manual denominator

The v1 denominator contains exactly eight interpretable candidates:

```text
manual_reversal_1bar
manual_reversal_2bar
manual_momentum_4bar
manual_momentum_8bar
manual_range_mean_4bar
manual_return_volatility_4bar
manual_volume_surprise_8bar
manual_close_location_1bar
```

The denominator and every feature specification are content-addressed. Changing a window, formula, hypothesis, input field or protocol identity changes the corresponding ID rather than silently mutating an existing candidate.

## Availability semantics

`evaluate_us_baseline_feature()` consumes only ordered, already-completed resampled bars. The resulting feature observation inherits:

```text
event_time   = current completed signal bar event_time
available_at = current completed signal bar available_at
```

If the required window is unavailable, the result remains explicit rather than repaired:

```text
insufficient_history
cross_session_window
incomplete_bar
zero_reference_volume
```

There is no nearest-bar repair, cross-session carry or use of future label availability in feature formation.

## Deterministic evaluation evidence

`USBaselineRunSpec` binds formal evaluation to all of:

```text
accepted US-D3 certification report id
accepted certification outcome
final EngineeringUniverse id
frozen manual denominator id
15m signal clock
same-session 60-trading-minute RAW label
```

The evaluation core groups already-formed feature observations by formation `available_at`. Cross-sectional rank weights are formed from eligible finite feature values **before** realised label availability is considered. Realised labels are used only ex post for diagnostics.

For each candidate the evidence records:

```text
observation / eligible / valid-feature cells
feature coverage
realised evaluation periods
RankIC periods and mean RankIC
cost-free rank-neutral gross return
one-way turnover / gross traded weight
expected same-session label-boundary periods
explicit blockers
```

A period where every formed asset has `target_crosses_session` is recognised as the expected same-session horizon boundary and is not zero-filled or charged fictitious close/reopen turnover. The evaluator remains fail-closed on a partially missing realised target by default. The reviewed 2026-09-04 B0 run uses the narrower complete-case amendment described below: when any already-formed asset lacks its realised label, the **entire formation cross-section** is omitted from every candidate. The implementation never deletes only the missing asset, changes the formed weights, or fills a price.

The evaluation report always retains the complete eight-candidate denominator. Missing or invalid candidates cannot disappear merely because they have weak or unavailable evidence.

## Bounded DuckDB materialization

`materialize_us_b0_baselines.py` connects the accepted data-plane evidence to the evaluator without introducing a second statistical implementation. It:

1. requires `docs/status.toml` to have actually advanced to `US-B0` with the US-D3 exit gate accepted;
2. requires the exact canonical preregistered pilot walk-forward artifact and one of its frozen fold ordinals;
3. loads the blocker-free US-D3 certification and current final EngineeringUniverse and binds their identities into `USBaselineRunSpec`;
4. derives the query start/end from the frozen fold rather than accepting operator-supplied dates;
5. queries only the final 20–30 research symbols through the admitted Parquet/DuckDB store;
6. materializes canonical complete/incomplete 15m regular-session RAW bars and the exact same-session 60-trading-minute RAW label plan;
7. joins the label source to the feature clock using `label.source_available_at = bar.available_at`;
8. checks that the label source close equals the completed 15m bar close before any feature observation is admitted;
9. computes the frozen eight features through `evaluate_us_baseline_feature()` rather than duplicating formulas in SQL;
10. writes local row-level input/observation artifacts and content-addressed evaluation/materialization reports;
11. emits a content-addressed fold-run manifest binding the frozen `USBaselineFoldExecutionSpec` to the materialization, input-plan, observation and evaluation identities.

The runner deliberately caps one frozen fold at 100,000 joined rows. The cap may not be lifted and the split may not be changed merely to obtain a pass.

### Why the label join uses `available_at`

A completed 15m bar stamped at bucket start is available only at bucket end. The authoritative D2 60m label is sourced from a 1m close whose `source_available_at` is the same bucket-end formation clock. Therefore the correct identity-preserving anchor is:

```text
15m bar.available_at == label.source_available_at
15m bar.close        == label.source_price
```

Joining `bar.event_time` to `label.source_event_time` would shift the label source away from the close actually used by the completed feature bar and is rejected by construction.

## Frozen pilot walk-forward

The formal pilot split is frozen before real baseline result inspection:

```text
Fold 1 evaluation  [2026-02-17, 2026-03-02)
Fold 2 evaluation  [2026-03-02, 2026-03-16)
Fold 3 evaluation  [2026-03-16, 2026-03-30)
```

The full train/validation/evaluation boundaries live in `USBaselineWalkForwardProtocol`. Because all v1 feature histories are same-session only and every evaluation boundary is a UTC day boundary before the relevant XNYS session, no previous-session warm-up bar is imported across the evaluation boundary.

Freeze the protocol artifact before formal execution:

```powershell
python scripts\freeze_us_b0_pilot_walkforward.py `
  --output reports\us_b0\us_b0_pilot_walkforward_protocol.json
```

The formal materializer validates the entire JSON document against the canonical preregistration. Matching only the schema or editing a date while retaining the filename is insufficient.

## Formal fold commands

Do not run the formal materializer while `docs/status.toml` still reports US-D3 as pending. First complete the active-session US-I0/MT5-D0/US-D3 task, record the reviewed real evidence IDs and advance stage authority to US-B0.

Run each frozen fold separately. There is deliberately no `--start` or `--end` override:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

python scripts\materialize_us_b0_baselines.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --fold-ordinal 1 `
  --protocol reports\us_b0\us_b0_pilot_walkforward_protocol.json `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --certification reports\us_d3\us_minute_research_certification.json `
  --engineering-universe reports\us_instruments\us_i0_final_engineering_universe.json `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB
```

Repeat with `--fold-ordinal 2` and `--fold-ordinal 3`.

Default artifacts are isolated per fold:

```text
data/us_b0/folds/fold_01/us_b0_baseline_inputs.parquet
data/us_b0/folds/fold_01/us_b0_baseline_observations.jsonl
reports/us_b0/folds/fold_01/us_b0_baseline_evaluation.json
reports/us_b0/folds/fold_01/us_b0_baseline_materialization.json
reports/us_b0/folds/fold_01/us_b0_fold_run_manifest.json
```

`fold_02` and `fold_03` use the same filenames under their own directories. Explicit output overrides remain available for local filesystem layout only; they do not change the frozen fold or any evidence gate.

For an intentionally repeated local run, remove previous artifacts or pass `--overwrite` explicitly. The overwrite flag changes file handling only.

Each passing fold should show:

```text
passed = true
blockers = []
protocol_id = us-baseline-walk-forward-...
fold_execution_spec_id = us-baseline-fold-execution-...
fold_manifest_id = us-baseline-fold-run-...
engineering_asset_count in 20..30
input_materialization_id = minute-materialization-...
observation_artifact_id = us-baseline-observations-...
evaluation_report_id = us-baseline-evaluation-...
```

Additionally inspect:

```text
diagnostics.missing_assets = []
diagnostics.assets_without_complete_bar = []
diagnostics.label_anchor_missing_count = 0
diagnostics.close_anchor_mismatch_count = 0
candidate_count = 8
```

A candidate with weak or negative RankIC is **not** repaired, dropped or redefined. Statistical weakness is a result. Evidence incompleteness or insufficient evaluation/IC periods remains a blocker. Partial realised-label loss is fail-closed under the default policy; an explicitly identified amended RunSpec may instead omit the whole affected formation cross-section and must report the omission count in every candidate's evidence.

## Split-bound aggregate and evidence graph

After all three fold reports pass, assemble them without loading row-level data or recomputing fold statistics:

```powershell
python scripts\assemble_us_b0_walkforward_evidence.py `
  --protocol reports\us_b0\us_b0_pilot_walkforward_protocol.json `
  --fold-report-root reports\us_b0\folds `
  --aggregate-output reports\us_b0\us_b0_walkforward_aggregate.json `
  --graph-output reports\us_b0\us_b0_walkforward_evidence_graph.json
```

Assembly re-hashes:

```text
USBaselineRunSpec
USBaselineCandidateEvidence
USBaselineEvaluationReport
USBaselineInputPlan identity payload
USBaselineObservationArtifact identity payload
USBaselineMaterializationReport identity payload
```

It also reconstructs each expected fold execution spec from the exact frozen protocol and shared run-spec identity. A persisted fold manifest must exactly equal the manifest reconstructed from the fold's materialization/evaluation evidence.

The aggregate preserves all eight MANUAL candidates and records mean/worst-fold RankIC, cost-free gross diagnostic return, turnover and coverage. It does not select a winner. Negative RankIC or return remains a valid result; missing/invalid fold evidence is a blocker.

The resulting evidence graph records:

```text
protocol id
shared run-spec id
MANUAL denominator id
3 fold execution-spec ids
3 fold manifest ids
3 materialization report ids
3 evaluation report ids
aggregate report id
aggregate candidate / valid-candidate counts
blockers
```

`ready_for_us_a0_candidate=true` means only that the full split-bound MANUAL baseline evidence is structurally complete and all frozen denominator candidates have valid fold evidence. It is a technical input to the later US-B0 stage-exit review, not project-stage authority.

## Authority boundary and next gate

A passing fold, aggregate or evidence graph still has:

```text
status_authority            = false
stage_exit_authority        = false
factor_selection_authority  = false
alpha_authority             = false
```

The EngineeringUniverse is an integration universe, not a survivorship-unbiased market-wide research universe. Current spread evidence is not historical transaction-cost authority. No candidate winner may be promoted from US-B0 cost-free diagnostics alone.

Only after the complete split-bound evidence is reviewed may `docs/status.toml` be advanced according to the stage-exit process and the resulting fixed MANUAL baseline be used to define the controlled US-A0 MANUAL / PROGRAMMATIC / AGENT experiment. The evidence graph itself never edits or supersedes project-stage authority.

## 2026-09-04 formal closeout and complete-case amendment

The first strict real B0 v1 execution was fully assembled and preserved as failed-closed evidence:

```text
fold 1                         passed, 8/8 candidates
fold 2                         passed, 8/8 candidates
fold 3                         failed closed, 0/8 valid candidates
aggregate report               us-baseline-walk-forward-aggregate-34a65ec2e885711892c4519c
evidence graph                 us-baseline-walk-forward-evidence-28472b6d52036f543f575245
ready_for_us_a0_candidate      false
closeout decision              BLOCKED_SOURCE_DATA_QUALITY
```

The single underlying defect is an absent EEM research-source 1m row at
`2026-03-17T18:59:00Z`. It makes the forward target partially missing for the
cross-section formed at `2026-03-18T02:00:00+08:00`; the same structural blocker is
therefore retained for all eight frozen candidates.

A read-only `MetaQuotes-Demo` diagnostic found 31 EEM M1 bars over the inclusive
`2026-03-17T18:45:00Z` through `19:15:00Z` window. This confirms that an independent
community reference has coverage near the gap, but it is not the certified research
source and does not repair, overwrite or supplement the B0 input.

The active community development feed was separately checked over all 40 selected
symbols. All 40 satisfy the frozen delayed-reference policy, with observed quote delay
between `900.161197` and `914.379197` seconds and median delay error
`1.026197` seconds. That evidence has simulation-reference authority only; it has no
live-market, executable-spread, order, stage-exit or Alpha authority.

No higher-quality same-source snapshot is available. With explicit project authorization
to make a documented data-quality concession, B0 therefore adopted one bounded change:

```text
policy                       omit_entire_formation_cross_section
scope                        evaluation only; source files and universe unchanged
affected event               one fold-3 formation period
affected candidates          all eight, identically
price fill                   none
asset-specific deletion      none
future-aware reweighting     none
fold/threshold/formula change none
```

This changes the original principle that *every* partial realised label must block the
run. The principle was too strict for an isolated ex-post label hole when source repair
is unavailable: it discarded all three folds and every candidate even though the missing
event can be removed symmetrically after the weights are formed. Whole-cross-section
omission preserves equal information and equal sample support across all candidates and
does not allow the missing asset's future outcome to alter weights. It is materially less
biased than deleting EEM from the universe, zero-filling its return, renormalizing the
remaining assets, or borrowing an independently sourced community/MT5 bar. Those
alternatives remain prohibited. The strict behavior remains the API default; only the
content-addressed amended RunSpec opts into this policy.

All three folds were rerun under that new RunSpec, not relabelled in place. The strict
evidence above remains immutable and traceable. The accepted amended result is:

```text
run spec                     us-baseline-run-spec-4ac2ae1d8cb95c01c8a99a11
fold 1                       passed, 8/8 candidates
fold 2                       passed, 8/8 candidates
fold 3                       passed, 8/8 candidates; 1 whole-period omission each
aggregate report             us-baseline-walk-forward-aggregate-88131e0eb8b205a78a559525
evidence graph               us-baseline-walk-forward-evidence-1a541f4bf39b1abca833898b
ready_for_us_a0_candidate    true
closeout decision            ACCEPTED_WITH_COMPLETE_CASE_AMENDMENT
```

The fold boundaries, 25-asset EngineeringUniverse, eight denominator candidates,
coverage/period thresholds, certified research source and walk-forward protocol identity
are unchanged. The community feed remains a delayed diagnostic reference and contributes
no values to B0. Project-stage authority was separately advanced in `docs/status.toml`;
the evidence graph itself still has no authority to perform that transition.
