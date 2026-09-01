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

## What this increment does not yet claim

This foundation does not run formal US-B0 statistics, choose a winning factor, define transaction-cost authority, create a portfolio result or advance the project stage. After US-D3 certification passes, the next US-B0 increment should materialize these eight candidates on the certified 15m EngineeringUniverse, bind the full candidate denominator to the certification/universe IDs, and produce deterministic baseline evaluation evidence for the later MANUAL/PROGRAMMATIC/AGENT controlled experiment.
