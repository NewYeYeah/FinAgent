# U.S. minute resampling

US-D2.2 derives deterministic regular-session 5m / 15m / 30m bars from the calendar-sessionized 1m Data Plane. Resampling is a transform above the raw and sessionized authorities; it does not modify or replace source Parquet rows.

## Frozen canonical rules

```text
source interval        1m
target intervals       5m, 15m, 30m
session policy         regular only
price basis            raw
bucket anchor          XNYS session_open
event_time             bucket_start
available_at           bucket_end
missing-minute policy  preserve_incomplete
partial-bar policy     reject_non_divisible_session
```

The canonical research signal clock is 15m. 5m and 30m are the initial robustness clocks.

## OHLCV aggregation

Inside one `(research_asset_id, session_date, bucket_index)` group:

```text
open   = first observed open by event_time
high   = maximum high
low    = minimum low
close  = last observed close by event_time
volume = sum volume
```

Derived OHLCV values are normalized to `DOUBLE`, matching the admitted raw schema.

Every derived bar also carries:

```text
bar_index
observed_minute_count
expected_minute_count
coverage_ratio
is_complete
is_half_day
```

A missing source minute is never forward-filled or interpolated. The bucket is preserved with `is_complete=false` and an explicit coverage ratio.

## Session boundaries

Buckets are anchored to the accepted XNYS `session_open`, not midnight or arbitrary wall-clock multiples. Therefore DST changes do not move the bar index within the session.

For a normal 390-minute XNYS session:

```text
5m   -> 78 bars
15m  -> 26 bars
30m  -> 13 bars
```

For the accepted 210-minute post-Thanksgiving half-day:

```text
5m   -> 42 bars
15m  -> 14 bars
30m  -> 7 bars
```

The v1 partial-bar policy is fail-closed: if a relevant materialized session duration is not divisible by the requested target interval, the plan is rejected rather than silently creating a short terminal bucket.

## Availability semantics

For a 15m bucket beginning at 13:30 UTC:

```text
event_time    = 13:30
available_at  = 13:45
```

An `availability_policy=available_at` query therefore filters on bucket end, not bucket start. The lower 1m query window is expanded as needed so the bucket can be built without lookahead.

## Deliberate capability gaps

`60m` remains unsupported because the regular 390-minute session does not divide into equal 60-minute bars. `ALL_OBSERVED` and `EXTENDED` resampling are also unavailable: v1 derives only calendar-authoritative regular-session bars.

Split-adjusted and total-return-adjusted resampling remain unavailable until corporate-action evidence is introduced. Typed forward labels are the next US-D2 increment.

## Regression coverage

The focused synthetic regression proves:

- exact 5m/15m/30m counts for normal and half-day sessions;
- deterministic OHLCV aggregation and `available_at=bucket_end`;
- explicit incomplete coverage when a 1m row is missing;
- availability-clock filtering;
- fail-closed 60m and non-regular policies;
- fail-closed non-divisible session duration.

All fixtures are synthetic; no real source OHLCV rows are committed.
