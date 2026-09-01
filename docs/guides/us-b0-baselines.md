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

A period where every formed asset has `target_crosses_session` is recognised as the expected same-session horizon boundary and is not zero-filled or charged fictitious close/reopen turnover. A partially missing realised target is fail-closed and retained as a blocker; it may not change the already-formed cross-section.

The evaluation report always retains the complete eight-candidate denominator. Missing or invalid candidates cannot disappear merely because they have weak or unavailable evidence.

## Bounded DuckDB materialization

`materialize_us_b0_baselines.py` connects the accepted data-plane evidence to the evaluator without introducing a second statistical implementation. It:

1. requires `docs/status.toml` to have actually advanced to `US-B0` with the US-D3 exit gate accepted;
2. loads the blocker-free US-D3 certification and final v2 EngineeringUniverse and binds their identities into `USBaselineRunSpec`;
3. queries only the final 20–30 research symbols through the admitted Parquet/DuckDB store;
4. materializes canonical complete/incomplete 15m regular-session RAW bars and the exact same-session 60-trading-minute RAW label plan;
5. joins the label source to the feature clock using `label.source_available_at = bar.available_at`;
6. checks that the label source close equals the completed 15m bar close before any feature observation is admitted;
7. computes the frozen eight features through `evaluate_us_baseline_feature()` rather than duplicating formulas in SQL;
8. writes local row-level input/observation artifacts under ignored `data/` paths and content-addressed aggregate reports under ignored `reports/` paths;
9. evaluates the complete denominator through the existing certification-bound evaluator.

The runner deliberately caps one bounded joined window at 100,000 rows. If a preregistered research split is larger, materialize its folds separately rather than lifting this guard merely to obtain a pass.

### Why the label join uses `available_at`

A completed 15m bar stamped at bucket start is available only at bucket end. The authoritative D2 60m label is sourced from a 1m close whose `source_available_at` is the same bucket-end formation clock. Therefore the correct identity-preserving anchor is:

```text
15m bar.available_at == label.source_available_at
15m bar.close        == label.source_price
```

Joining `bar.event_time` to `label.source_event_time` would shift the label source away from the close actually used by the completed feature bar and is rejected by construction.

## Operator command

Do not run the formal materializer while `docs/status.toml` still reports US-D3 as pending. First record the reviewed real US-D3/US-I0/MT5-D0 evidence IDs in project-stage authority and advance the current stage to US-B0.

The materializer intentionally has **no implicit research window**. `--start` and `--end` must come from the pilot split protocol frozen before results are inspected.

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

python scripts\materialize_us_b0_baselines.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --start <PREREGISTERED_FOLD_START_UTC> `
  --end <PREREGISTERED_FOLD_END_UTC> `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --certification reports\us_d3\us_minute_research_certification.json `
  --engineering-universe reports\us_instruments\us_i0_final_engineering_universe.json `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\us_b0 `
  --input-output data\us_b0\us_b0_baseline_inputs.parquet `
  --observation-output data\us_b0\us_b0_baseline_observations.jsonl `
  --evaluation-output reports\us_b0\us_b0_baseline_evaluation.json `
  --report-output reports\us_b0\us_b0_baseline_materialization.json
```

For an intentionally repeated local run, remove the previous artifacts or pass `--overwrite` explicitly. The overwrite flag changes file handling only; it does not relax any evidence, identity, coverage or evaluation gate.

Required technical result:

```text
passed = true
blockers = []
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

A candidate with weak or negative RankIC is **not** repaired, dropped or redefined. Statistical weakness is a result. Evidence incompleteness, partial realised-label loss or insufficient evaluation/IC periods remains a blocker.

## Authority boundary and next gate

A passing materialization report is still only cost-free pilot diagnostic evidence:

```text
stage_exit_authority        = false
factor_selection_authority  = false
alpha_authority             = false
```

The EngineeringUniverse is an integration universe, not a survivorship-unbiased market-wide research universe. Current spread evidence is not historical transaction-cost authority. No candidate winner may be promoted from this materializer alone.

Before interpreting final US-B0 results, freeze the pilot walk-forward split protocol required by `docs/development/current-plan.md`. Then materialize/evaluate every prescribed fold under the same denominator and certification identities. Only the resulting split-bound evidence can be considered for the US-B0 stage-exit decision and for defining the controlled MANUAL denominator used by US-A0.
