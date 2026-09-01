# MT5-P0 read-only capability probe

MT5-P0 measures the actual connected MetaTrader 5 terminal/broker surface before any order authority exists.

## Authority boundary

```text
MetaTrader5 provider/API capability
        ↓ measured through read-only client
MT5TerminalCapability
MT5SymbolSpec
MT5HistoryCapability
MT5SpreadSample
        ↓
MT5CapabilityProbeReport
        ↓ explicit stage policy
MT5P0AcceptancePolicy
        ↓
MT5P0AcceptanceAssessment
```

This stage does **not** expose `order_send`, `order_check`, `symbol_select`, market-book subscriptions, position mutation, account-setting mutation, PAPER authority or live-capital authority.

The FinAgent read-only client deliberately exposes only:

```text
initialize / shutdown
version
terminal_info
account_info
symbols_get
symbol_info_tick
copy_rates_range
copy_ticks_range
```

The report does not persist account login/account number or local terminal/data paths.

MT5 `path` is broker grouping metadata, **not** authoritative listed-exchange identity. US-I0 must not infer NYSE/Nasdaq membership from the MT5 path and must not equate identical ticker text with an accepted research/broker mapping.

## Windows / Conda environment

Run locally in the existing Conda environment:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
git checkout main
git pull --ff-only
python -m pip install "MetaTrader5==5.0.6147"
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
```

Expected package version:

```text
5.0.6147
```

The MetaTrader 5 desktop terminal must already be installed, running and logged into the broker account whose capability surface is being measured.

## Pass 1 — inventory-only probe

First collect the actual terminal/broker and symbol inventory without guessing broker symbol names:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --output reports\mt5\mt5_p0_inventory.json
```

The console prints only a compact summary. The JSON report retains the complete returned symbol specifications.

Use the report to identify exact broker symbols that are already `visible=true` and `tradable=true`. Do not call `symbol_select` merely to force a candidate into the MT5-P0 acceptance set, and do not normalize or strip broker names inside the MT5 adapter.

An inventory-only report is deliberately insufficient to close MT5-P0 because it contains no targeted M1/tick history or representative spread evidence.

## Pass 2 — acceptance-bound history and spread evidence

After selecting exact visible/tradable broker symbols from pass 1, use `--p0-representative-symbol`. Each representative symbol is automatically included in M1 history, tick history and current spread measurement.

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --p0-representative-symbol <BROKER_SYMBOL_1> `
  --p0-representative-symbol <BROKER_SYMBOL_2> `
  --bar-start 2026-08-24T00:00:00+00:00 `
  --bar-end 2026-09-01T00:00:00+00:00 `
  --tick-start 2026-08-31T13:30:00+00:00 `
  --tick-end 2026-08-31T14:30:00+00:00 `
  --output reports\mt5\mt5_p0_capability_probe.json
```

The command also writes, by default:

```text
reports/mt5/mt5_p0_capability_probe_assessment.json
```

Keep tick windows small: tick history can be much larger than M1 bars. `copy_rates_range` and `copy_ticks_range` evidence means exactly what the connected terminal returned for the requested UTC interval. It is not silently promoted to the authoritative U.S. historical research source or to broker-global history beyond the requested window.

## MT5-P0 deterministic acceptance

For every representative symbol, the default policy requires:

```text
report.read_only = true
report.mutation_authority = false
terminal.connected = true
MetaTrader5 package version = expected exact version
broker server identified
terminal build identified
symbol exists in measured inventory
symbol.visible = true
symbol.tradable = true
M1 row count > 0
tick row count > 0
bid/ask spread sample is valid
```

`terminal.trade_allowed=false` does **not** invalidate the read-only P0 measurement; it is preserved as `terminal:automated_trading_not_allowed` and becomes a downstream Demo/PAPER limitation. A later execution stage must independently prove trading permission before any order authority exists.

The acceptance result has deterministic `policy_id` and `assessment_id`. MT5-P0 closes only from an accepted real assessment, not from manual inspection of an inventory JSON.

## MT5-P0 closure evidence

A real accepted assessment establishes the connected terminal/broker measurement needed to freeze the engineering integration universe. Broker symbols then become `BrokerInstrument` candidates. They are not equivalent to listed-equity `ResearchInstrument` identities until US-I0 creates explicit evidence-bound mappings.
