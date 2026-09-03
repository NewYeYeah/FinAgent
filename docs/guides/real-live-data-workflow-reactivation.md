# Real Live-Data Workflow Reactivation

## Purpose

This branch reactivates the connected real-time market-data workflow without changing the authoritative project stage. The connected development fixture is FX (`EURUSD`, `GBPUSD`, `USDJPY`); delayed U.S. data remains a degraded-feed fixture; target U.S. CFD remains the final source/broker freeze.

`docs/status.toml` remains authoritative and is not advanced by this workflow.

## Frozen execution path

```text
MT5 terminal (read-only)
  -> capability probe + broker-clock evidence
  -> MT5RealtimeMarketAdapter
  -> canonical ConnectionEvent / QuoteEvent / optional completed M1 BarEvent
  -> MT5RealtimeSource / MarketDataSource contract
  -> RealtimeProjector / AlgorithmRunner
  -> FeedTimingProfile + StrategyFreshnessBudget
  -> streaming feature/research pipeline when BarEvent input is available
  -> persisted engineering evidence / replay parity
```

## Source roles

- **FX live**: connected engineering validation for terminal connectivity, broker clock, polling, bid/ask, event normalization, progression, timing/freshness, reconnect and runtime behavior.
- **Delayed U.S. feed**: first-class degraded-mode validation. Progressing-but-delayed must not be confused with frozen/stale data.
- **Local U.S. replay**: algorithm/research streaming development and batch/stream parity.
- **Target U.S. CFD**: final broker/server/account/symbol/contract/feed freeze only.

No authority may inherit automatically between these roles.

## D0 — deterministic/offline

Run before any connected MT5 test:

```powershell
uv sync --frozen --extra dev
uv run --frozen pytest -q `
  tests/test_mt5_broker_clock.py `
  tests/test_mt5_continuous_quote_smoke.py `
  tests/test_mt5_p0_feed_regime.py `
  tests/test_mt5_p0_readonly_probe.py `
  tests/test_mt5_realtime_adapter.py `
  tests/test_mt5_realtime_adapter_numpy_scalars.py `
  tests/test_realtime_replay_projection.py `
  tests/test_streaming_source_harness_v1.py `
  tests/test_streaming_feature_strategy_v1.py `
  tests/test_us_i0_delayed_reference.py `
  tests/test_us_d3_simulation_admission.py

uv run --frozen ruff check `
  src/finagent/brokers/mt5/client.py `
  src/finagent/brokers/mt5/realtime_adapter.py `
  src/finagent/realtime/mt5_source.py `
  src/finagent/realtime/sources.py `
  scripts/probe_mt5_realtime_events.py `
  scripts/smoke_mt5_simulation_all_day_preflight.py `
  scripts/smoke_mt5_continuous_quotes.py

uv run --frozen mypy --strict `
  src/finagent/brokers/mt5/client.py `
  src/finagent/brokers/mt5/realtime_adapter.py `
  src/finagent/realtime/mt5_source.py `
  src/finagent/realtime/sources.py `
  scripts/probe_mt5_realtime_events.py `
  scripts/smoke_mt5_simulation_all_day_preflight.py `
  scripts/smoke_mt5_continuous_quotes.py

uv run --frozen python -m py_compile `
  src/finagent/brokers/mt5/client.py `
  src/finagent/brokers/mt5/realtime_adapter.py `
  src/finagent/realtime/mt5_source.py `
  src/finagent/realtime/sources.py `
  scripts/probe_mt5_realtime_events.py `
  scripts/smoke_mt5_simulation_all_day_preflight.py `
  scripts/smoke_mt5_continuous_quotes.py
```

The dedicated `real-live-data-workflow` CI must run this source/runtime contract surface before workstation evidence is interpreted.

## D1 — connected FX engineering smoke

Run on a Windows workstation with the intended MT5 terminal already logged in and the three FX symbols available from the broker:

When the terminal is connected to a funded account, first enable **Disable
automated trading via external Python API** in MT5 and keep terminal automated
trading disabled. Every approved connected command now fails closed unless
`terminal_info.trade_allowed=false` and `terminal_info.tradeapi_disabled=true`.
Do not bypass this guard for data collection.

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git fetch origin
git checkout rt-real-live-data-workflow-v1
git pull --ff-only

python scripts\smoke_mt5_simulation_all_day_preflight.py `
  --symbols EURUSD GBPUSD USDJPY `
  --expected-package-version 5.0.6147 `
  --expected-broker-server TradeMaxGlobal-Live `
  --output reports\mt5\mt5_fx_live_preflight.json

python scripts\probe_mt5_realtime_events.py `
  --feed-lane fx_continuous_engineering_fixture `
  --clock-reference-symbol EURUSD `
  --clock-reference-symbol GBPUSD `
  --clock-reference-symbol USDJPY `
  --symbol EURUSD `
  --symbol GBPUSD `
  --symbol USDJPY `
  --expected-package-version 5.0.6147 `
  --capability-output reports\mt5\mt5_fx_realtime_capability.json `
  --clock-output reports\mt5\mt5_fx_realtime_clock.json `
  --output reports\mt5\mt5_fx_realtime_events.json
```

Acceptance checks:

- capability probe is read-only and terminal is connected;
- broker-server identity is non-empty and stable within the run;
- broker-clock evidence passes using at least three reference symbols;
- canonical connection/quote events are emitted;
- `event_time` and `received_at` remain distinct clocks;
- FX quotes progress across repeated samples;
- no `symbol_select`, `order_send`, market-book subscription or mutation API is used;
- all U.S.-market, execution, PAPER, stage-exit and live-capital authority flags remain false.

### D1 workstation evidence — 2026-09-03 UTC

The documented commands were executed against the logged-in
`TradeMaxGlobal-Live` terminal during an active U.S. session. Package version
`5.0.6147` and terminal build `6157` were observed.

```text
capability probe          mt5-capability-probe-d2b40bb3e6144eb269e26569
realtime adapter report   mt5-realtime-adapter-5bab8c7d5d227bd8a8d0b305
continuous quote smoke    mt5-continuous-quote-smoke-f1378ce1cd519161bd464179
all-day preflight         mt5-simulation-all-day-preflight-84aa345d2fe008afcece9db5

realtime events           1 connection + 3 quotes
continuous quote pass     3 / 3
preflight pass            true
mutation calls            none
```

Five additional read-only realtime samples, spaced approximately two seconds
apart, showed advancing quote timestamps for all three FX symbols. Normalized
quote-age medians were `2.153 s` (`EURUSD`), `2.378 s` (`GBPUSD`) and `2.242 s`
(`USDJPY`); the observed maxima were `2.593 s`, `5.442 s` and `4.209 s`.

A separate 100-call local `symbol_info_tick()` diagnostic measured an
approximately `0.009 ms` median Python-to-terminal call duration. This is local
API/IPC timing, not network round-trip or exchange-feed delay. The advancing
quote timestamps and low single-digit-second quote ages support a `CURRENT`
engineering classification for this FX fixture; they do not classify the target
U.S. symbols.

This evidence closes D1 for the connected FX engineering fixture only. It does
not advance `docs/status.toml` or provide U.S., PAPER, execution or live-capital
authority.

## D1 quote soak

After the one-shot probe passes, run the frozen current-quote smoke for the same FX fixture:

```powershell
python scripts\smoke_mt5_continuous_quotes.py `
  --symbols EURUSD GBPUSD USDJPY `
  --reference-symbols EURUSD GBPUSD USDJPY `
  --minimum-symbol-count 3 `
  --maximum-quote-age-seconds 60 `
  --maximum-future-quote-skew-seconds 5 `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_fx_continuous_quote_smoke.json
```

This command is still a read-only engineering smoke. Preserve the generated report and its broker-clock identity instead of replacing it with hand-written observations.

## Delayed/frozen regression

Always retain the degraded-feed tests:

- progressing + approximately 900 s delay -> `DELAYED`;
- non-progressing old value -> stale/frozen, not merely delayed;
- delayed data inside a strategy freshness budget may be admitted only if explicitly allowed;
- delayed data beyond the budget must be rejected while transport can remain healthy.

## Target-broker U.S. timing probe

Target-broker symbols must be exposed manually in MT5 Market Watch before probing. Use
the broker's exact symbol text; this workflow does not strip suffixes or call
`symbol_select()`. On `TradeMaxGlobal-Live`, the four research seeds currently map to
`AMD.NAS`, `INTC.NAS`, `MSFT.NAS` and `NVDA.NAS` and therefore cannot reuse the old
MetaQuotes-Demo exact-symbol evidence identity.

During the active U.S. session, collect the target-broker timing evidence through the
same canonical adapter:

```powershell
python scripts\probe_mt5_realtime_events.py `
  --feed-lane target_broker_current_us_equity_or_cfd `
  --clock-reference-symbol EURUSD `
  --clock-reference-symbol GBPUSD `
  --clock-reference-symbol USDJPY `
  --symbol AMD.NAS `
  --symbol INTC.NAS `
  --symbol MSFT.NAS `
  --symbol NVDA.NAS `
  --expected-package-version 5.0.6147 `
  --capability-output reports\mt5\mt5_target_us_realtime_capability.json `
  --clock-output reports\mt5\mt5_target_us_realtime_clock.json `
  --output reports\mt5\mt5_target_us_realtime_events.json
```

Repeat the probe across multiple wall-clock samples. A changing normalized
`event_time` proves progression; `received_at - event_time` estimates quote age after
broker-clock normalization. The local `symbol_info_tick()` call duration is an API/IPC
diagnostic and must not be reported as exchange-feed delay. Classify a progressing old
quote as delayed, and a non-progressing old quote as frozen/stale.

## Final U.S. CFD freeze

When the target broker becomes available, reuse the same canonical source path and replace only source configuration/symbols. Revalidate broker/server/account identity, symbol contracts, timing class, spread/session behavior and PAPER lifecycle. FX acceptance never becomes U.S. CFD authority.

The prior MetaQuotes-Demo candidate, quote and delayed-reference artifacts remain
immutable. A target-broker freeze requires a new candidate/mapping identity and a new
timing policy bound to the observed target server; do not rewrite the old artifacts or
change their expected server merely to obtain a pass.

## CI / workstation boundary

Repository CI can validate fake/read-only adapter semantics, source contracts, delayed/frozen classification, projector behavior, provider neutrality and mutation guards. It cannot prove connectivity to the operator's local MT5 desktop terminal. Connected FX smoke is therefore an explicit workstation evidence step.
