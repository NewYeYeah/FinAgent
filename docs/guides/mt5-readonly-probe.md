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

Use the report to identify the broker's exact equity/CFD symbol names, including any prefix/suffix. Do not normalize or strip those names inside the MT5 adapter.

## Pass 2 — targeted history and spread evidence

After selecting one or more exact broker symbols from pass 1, rerun with explicit bounded history windows. Example shape:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --history-symbol <BROKER_SYMBOL> `
  --bar-start 2024-01-01T00:00:00+00:00 `
  --bar-end 2026-09-01T00:00:00+00:00 `
  --tick-start 2026-08-31T00:00:00+00:00 `
  --tick-end 2026-09-01T00:00:00+00:00 `
  --spread-symbol <BROKER_SYMBOL> `
  --output reports\mt5\mt5_p0_capability_probe.json
```

Repeat `--history-symbol` and `--spread-symbol` when needed. Keep tick windows small: tick history can be much larger than M1 bars.

`copy_rates_range` evidence is explicitly the data returned by the connected terminal for the requested UTC interval. It is not silently promoted to the authoritative U.S. historical research source.

## MT5-P0 closure evidence

A real local report should establish at minimum:

```text
read_only = true
mutation_authority = false
terminal.connected = true
terminal package/version/build bound
broker server/company identified without account-number persistence
symbol inventory non-empty
contract/tick/volume/margin/swap semantics captured
at least one targeted M1 history probe completed
at least one targeted bid/ask spread sample completed
```

The resulting broker symbols remain `BrokerInstrument` candidates. They are not equivalent to listed-equity `ResearchInstrument` identities until US-I0 creates explicit evidence-bound mappings.
