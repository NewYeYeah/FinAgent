# MT5-M1 Read-Only Realtime Market Adapter

This guide defines the implementation-only MT5-M1 source adapter that maps read-only MetaTrader 5 polling observations into the canonical RT-R0 event contracts.

The project authority frontier remains US-D3. Issue #125 remains open. This adapter does not convert FX engineering evidence, MetaQuotes delayed U.S. references, or synthetic events into authoritative U.S. live-market evidence.

## Architecture

The source boundary is:

```text
MetaTrader5 read-only API
  terminal_info / account_info
  symbols_get
  symbol_info_tick
  copy_rates_range
        |
        v
MT5 broker-clock evidence
        |
        v
MT5RealtimeMarketAdapter
        |
        +--> QuoteEvent
        +--> BarEvent
        +--> ConnectionEvent
        |
        v
RealtimeProjector / ReplayGateway-compatible downstream state
```

The adapter never owns portfolio, strategy, browser, order, or broker-account truth. It only converts observations into canonical events.

## Explicit feed lanes

`MT5RealtimeAdapterPolicy.feed_lane` is mandatory and must be one of the existing explicit MT5 feed regimes:

```text
fx_continuous_engineering_fixture
metaquotes_demo_delayed_us_equity_reference
target_broker_current_us_equity_or_cfd
```

The lane is never inferred from ticker shape, contract fields, quote age, or observed delay.

A lane label is descriptive evidence context, not authority. Even the future target-broker lane still requires separate MT5-M1 acceptance before `live_market_data_authority` may become true elsewhere.

## Broker clock

The adapter requires a passing `MT5BrokerClockEvidence` bound to the exact broker server.

For tick or bar raw broker epoch `t_raw`:

```text
event_time = broker_clock.normalize_epoch_msc(t_raw)
received_at = actual FinAgent polling receipt time
```

The two clocks remain separate in every canonical event. The adapter rejects failed clock evidence and server drift.

## MT5 polling observation identity

The official MT5 Python polling interface does not expose a durable provider-native event identifier for `symbol_info_tick()` or `copy_rates_range()` observations.

Therefore MT5-M1 deliberately defines `source_event_id` as the identity of one **polling observation**, not one underlying exchange tick.

For a quote observation the identity binds:

```text
broker_server
feed_lane
kind=quote
symbol
raw broker time_msc
received_at
bid / ask / last
```

For a bar observation it additionally binds OHLC, tick volume, interval and the explicit completed-bar flag.

This resolves an important retry/reconnect ambiguity:

```text
same old MT5 tick polled at 10:00:01
!=
same old MT5 tick polled again at 10:00:02
```

They are two polling observations with the same source `event_time` but different `received_at` and source-observation identities. The RT projector can ingest both without treating the later poll as a corrupted reuse of one provider identity.

If the exact same raw observation and exact same `received_at` are reconstructed, the canonical source/event identities are deterministic.

## Quote semantics

MT5-M1 does not impose stock-only assumptions:

- `bid` and `ask` may be zero when the provider does not expose a usable current quote;
- `last` may be zero or unavailable;
- volume is not synthesized into quote bid/ask size;
- feed regime is not inferred from ticker.

This is necessary because continuous FX engineering fixtures and future broker CFDs may expose different quote fields from U.S. stock-style feeds.

## Bar semantics

`bar_event()` accepts mapping/namedtuple/attribute/numpy-index-like MT5 rows and maps:

```text
time -> broker-clock-normalized event_time
open/high/low/close -> canonical OHLC
tick_volume -> BarEvent.volume
```

`complete` is an explicit caller decision. The adapter does not silently decide whether the current M1 bar is complete.

The operator CLI is conservative: when M1 bars are requested, `--bar-end` must be at least two minutes in the past and emitted bars are marked complete. Current-bar inference is outside v1.

`real_volume` is not promoted over `tick_volume` and no stock-volume authority is inferred.

## Connection semantics

`connection_event()` consumes the existing read-only `MT5CapabilityProbeReport` and emits one canonical `ConnectionEvent` bound to the same broker server and capability probe identity.

A disconnected terminal may still emit a diagnostic connection event, but the adapter report is blocked with:

```text
terminal:not_connected
```

## Report authority

`MT5RealtimeAdapterReport` binds:

- explicit adapter policy / feed lane;
- MT5-P0 capability probe ID;
- broker-clock evidence ID;
- canonical emitted event IDs;
- blockers and generated time.

A passing report means only:

```text
implementation_ready_for_mt5_m1_acceptance = true
```

It always retains:

```text
read_only = true
symbol_select_used = false
order_send_used = false
us_market_source_authority = false
live_market_data_authority = false
broker_account_authority = false
execution_authority = false
paper_authority = false
status_authority = false
stage_exit_authority = false
live_capital_authority = false
```

## Local fake/offline validation

The implementation can be fully regression-tested without MetaTrader 5:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

pytest -q `
  tests\test_mt5_realtime_adapter.py `
  tests\test_realtime_replay_projection.py `
  tests\test_mt5_p0_feed_regime.py
```

Static checks:

```powershell
ruff check `
  src\finagent\brokers\mt5\realtime_adapter.py `
  scripts\probe_mt5_realtime_events.py `
  tests\test_mt5_realtime_adapter.py

mypy --strict `
  src\finagent\brokers\mt5\realtime_adapter.py `
  scripts\probe_mt5_realtime_events.py

python -m py_compile `
  src\finagent\brokers\mt5\realtime_adapter.py `
  scripts\probe_mt5_realtime_events.py
```

CI also performs a literal mutation-surface guard against:

```text
symbol_select(
order_send(
market_book_add(
positions_get(
```

inside the MT5-M1 adapter and operator CLI.

## Connected D1 engineering probe

For a normal Asian-daytime engineering check, use the continuous FX lane:

```powershell
python scripts\probe_mt5_realtime_events.py `
  --expected-package-version 5.0.6147 `
  --feed-lane fx_continuous_engineering_fixture `
  --clock-reference-symbol EURUSD `
  --clock-reference-symbol GBPUSD `
  --clock-reference-symbol USDJPY `
  --symbol EURUSD `
  --symbol GBPUSD `
  --symbol USDJPY `
  --capability-output reports\mt5\mt5_realtime_capability_probe.json `
  --clock-output reports\mt5\mt5_realtime_broker_clock.json `
  --output reports\mt5\mt5_realtime_adapter_report.json
```

This tests:

- official MT5 package loading;
- initialize/shutdown;
- terminal/account/server identity;
- read-only symbol inventory;
- broker-clock normalization;
- real polling observations -> canonical QuoteEvent;
- canonical ConnectionEvent;
- adapter identity and report assembly.

It does **not** test U.S. live source acceptance.

## Optional completed M1 window

A past completed M1 window can be added without requiring a current U.S. session:

```powershell
python scripts\probe_mt5_realtime_events.py `
  --feed-lane fx_continuous_engineering_fixture `
  --bar-symbol EURUSD `
  --bar-start 2026-09-03T00:00:00+00:00 `
  --bar-end 2026-09-03T00:10:00+00:00
```

The current CLI intentionally refuses a bar end within two minutes of now, so v1 never labels a potentially active M1 bar complete by inference.

## Future U.S. MT5-M1 acceptance

When a target broker/current U.S. equity or CFD feed becomes available, the same adapter can be rerun with the explicit target-broker lane. That future acceptance must additionally bind the actual:

```text
broker/server/account
instrument mappings
current quote freshness
current/executable spread semantics
M1/tick continuity
reconnect behavior
historical/realtime reconciliation
```

Only a later reviewed acceptance artifact may promote U.S. live-market authority. No existing FX, delayed MetaQuotes, simulation, replay, or adapter implementation report can do so.

## Next implementation handoff

After this adapter is fixture validated, development can continue into MT5-E1/MT5-O1 using replay/fake broker command ports first. Real `order_send()` and PAPER broker mutation remain a separate future D3 acceptance boundary.
