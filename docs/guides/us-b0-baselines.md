# US-B0 deterministic intraday baseline foundation

US-B0 establishes the non-Agent denominator that later Agent-value experiments must beat under the same certified data, universe and validation gates. This foundation is intentionally implementation-only while `docs/status.toml` remains US-D3 until the real US-D3 certification report passes.

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

`USBaselineRunSpec` binds any later formal evaluation to all of:

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

The evaluation report always retains the complete eight-candidate denominator. Missing/invalid candidates cannot disappear merely because they have weak or unavailable evidence.

## Current authority boundary

The code above is a preimplementation of the next stage only. It does not make `US-B0` the active project stage and no formal baseline result may be recorded until the real US-D3 certification is accepted. The current implementation also deliberately avoids intraday annualised Sharpe, p-values or deployment claims; robust inference belongs to the later frozen research protocol rather than being copied from the historical A-share daily evaluator.

After US-D3 certification passes, the next US-B0 increment is the bounded DuckDB materializer that joins certified 15m bars, exact same-session labels and this eight-candidate evaluator for the final EngineeringUniverse.
