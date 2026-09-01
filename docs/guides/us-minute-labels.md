# U.S. minute label materialization

US-D2.3 materializes forward labels as immutable Data Plane evidence instead of letting each research function implement its own `shift` or nearest-time merge.

## Canonical first label

```text
name                 us_same_session_60m_simple_return_raw
metric               simple_return
horizon              60
horizon unit         trading_minutes
allow cross session  false
price basis          raw
availability policy  available_at
source interval      1m
source price         close
target match         exact same-session minute_offset + 60
```

The label is intended for the first intraday Alpha line. It does not imply that 60-minute bars exist; the horizon is sixty **trading minutes**, not four 15-minute bars and not one wall-clock hour across a closure.

## PIT clocks

For a source minute whose bar starts at `13:30`:

```text
source_event_time     13:30
source_available_at   13:31
```

A 60-trading-minute target at minute offset 60 has its own explicit event and availability clocks. The label uses the target close only when that exact target minute exists in the same calendar session.

## Denominator preservation

The materializer emits one row for every source row in the requested denominator. A source row is not silently dropped merely because its forward target cannot be constructed.

```text
exact target exists in same session
→ label_available = true
→ label_value is materialized

expected target offset reaches/passes session duration
→ label_available = false
→ unavailable_reason = target_crosses_session

expected target offset is inside the same session but exact target row is absent
→ label_available = false
→ unavailable_reason = target_minute_missing
```

`target_minute_missing` is never repaired with offset `+59`, `+61`, nearest timestamp, forward-fill or interpolation.

## Identity chain

`LabelMaterializationSpec` binds the `LabelSpec`, accepted calendar identity, 1m source interval, close-price field and exact target-matching policy.

`LabelSeriesEvidence` binds:

```text
label materialization spec
LabelSpec
calendar_id
sessionization evidence
source plan / source data version
label plan / label data version
```

Changing the horizon, price basis, availability semantics, source data, calendar or matching policy changes the evidence identity.

## Capability boundary

V1 deliberately rejects:

- cross-session labels;
- adjusted-price labels;
- bar-count horizons;
- event-time-only research labels;
- source fields other than exact raw close;
- silent removal of unavailable labels.

The source corpus is raw/split-unadjusted and corporate-action evidence is not embedded. Same-session raw labels are therefore the first authoritative scope; overnight/cross-session label claims remain fail-closed until the corporate-action boundary is accepted.

## Synthetic regression

The focused fixture uses two synthetic assets in one complete 390-minute session. One exact MSFT target minute is intentionally removed. The frozen denominator is:

```text
total source rows            779
available 60m labels         658
target_crosses_session       120
target_minute_missing          1
```

The regression also checks the exact source/target PIT clocks, return calculation, no-nearest-match behavior and Python preview conversion without the optional DuckDB/pytz bridge.

No real source OHLCV rows are committed.
