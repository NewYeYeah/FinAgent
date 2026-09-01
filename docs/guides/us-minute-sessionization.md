# U.S. minute sessionization

US-D2.1 adds a calendar-aware layer above the raw US-D1 minute store. The raw `DuckDBParquetMinuteStore` remains authoritative for admitted `1m + RAW + ALL_OBSERVED` rows; session semantics are added by `CalendarSessionizedMinuteStore` and are bound to the accepted XNYS calendar evidence.

Accepted research calendar:

```text
calendar_id  trading-calendar-03a9c29f566d6634aedbbbdc
market       XNYS
timezone     America/New_York
coverage     1992-01-02 .. 2026-03-31
```

## Session classification

Classification always uses `event_time`, never `available_at`:

```text
calendar date absent
→ outside_calendar

calendar date present and open_at <= event_time < close_at
→ regular

calendar date present but event_time outside the regular interval
→ outside_regular
```

The regular interval is open-inclusive and close-exclusive. A normal XNYS session therefore has minute offsets `0..389`; the accepted post-Thanksgiving half-day has `0..209`.

Sessionized rows add:

```text
session_type
session_id
session_open
session_close
minute_offset
is_regular_session
is_half_day
```

`data_version` changes when the raw data version, calendar identity or sessionization spec changes. `SessionizationEvidence` binds the base plan, sessionized plan, calendar and both data versions.

## Capability boundary

The sessionized adapter currently supports:

```text
interval             1m
price basis          raw
session policies     all_observed, regular
availability clocks  event_time, available_at
```

`EXTENDED` remains fail-closed. The accepted `exchange_calendars` schedule contains authoritative regular-session open/close times but does not materialize explicit pre-market/post-market boundaries. FinAgent therefore does not invent 04:00/20:00 extended-session authority in this stage.

Adjusted research prices, 5m/15m/30m resampling and typed labels remain later US-D2 increments.

## Golden regression coverage

The committed synthetic sessionization fixture exercises:

- 2025-11-28 half-day close at 18:00 UTC;
- 2026-03-06 pre-DST regular session at 14:30–21:00 UTC;
- 2026-03-09 post-DST regular session at 13:30–20:00 UTC;
- exact open/close boundary behavior;
- weekend `outside_calendar` rows;
- fail-closed `EXTENDED` queries;
- calendar JSON identity recomputation/tamper rejection.

The fixture is fully synthetic and contains no source OHLCV rows.
