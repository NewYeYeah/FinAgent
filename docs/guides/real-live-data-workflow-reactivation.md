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
pytest -q tests/test_mt5_realtime_adapter.py tests/test_streaming_source_harness.py tests/test_streaming_feature_strategy.py
ruff check src/finagent/brokers/mt5/realtime_adapter.py src/finagent/realtime/mt5_source.py src/finagent/realtime/sources.py
mypy --strict src/finagent/brokers/mt5/realtime_adapter.py src/finagent/realtime/mt5_source.py src/finagent/realtime/sources.py
python -m py_compile src/finagent/brokers/mt5/realtime_adapter.py src/finagent/realtime/mt5_source.py src/finagent/realtime/sources.py scripts/probe_mt5_realtime_events.py
```

## D1 — connected FX engineering smoke

Run on a Windows workstation with the intended MT5 terminal already logged in and the three FX symbols available from the broker:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent

git fetch origin
git checkout rt-real-live-data-workflow-v1
git pull --ff-only

python scripts\smoke_mt5_simulation_all_day_preflight.py `
  --symbols EURUSD GBPUSD USDJPY `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_fx_live_preflight.json

python scripts\probe_mt5_realtime_events.py `
  --feed-lane FX_ENGINEERING_FIXTURE `
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

## D1 soak

After the one-shot probe passes, run `scripts/smoke_mt5_continuous_quotes.py` for the same FX fixture and preserve the generated report.

## Delayed/frozen regression

Always retain the degraded-feed tests:

- progressing + approximately 900 s delay -> `DELAYED`;
- non-progressing old value -> stale/frozen, not merely delayed;
- delayed data inside a strategy freshness budget may be admitted only if explicitly allowed;
- delayed data beyond the budget must be rejected while transport can remain healthy.

## Final U.S. CFD freeze

When the target broker becomes available, reuse the same canonical source path and replace only source configuration/symbols. Revalidate broker/server/account identity, symbol contracts, timing class, spread/session behavior and PAPER lifecycle. FX acceptance never becomes U.S. CFD authority.

## CI / workstation boundary

Repository CI can validate fake/read-only adapter semantics, source contracts, delayed/frozen classification, projector behavior, provider neutrality and mutation guards. It cannot prove connectivity to the operator's local MT5 desktop terminal. Connected FX smoke is therefore an explicit workstation evidence step.
