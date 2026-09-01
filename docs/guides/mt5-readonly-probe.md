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

An inventory-only report is deliberately insufficient to close MT5-P0 because it contains no targeted M1/tick capability or representative spread evidence.

## Pass 2 — acceptance-bound capability evidence

After selecting exact visible/tradable broker symbols from pass 1, use `--p0-representative-symbol`. Every representative receives symbol-spec, M1-history and spread measurement. Historical tick retrieval is intentionally treated as a **capability-level** probe because it can be expensive and may be unavailable even when M1 history exists.

By default only the first representative becomes the tick capability probe symbol. Override this with repeatable `--p0-tick-symbol` only when a second independent tick-history measurement is justified.

Do **not** assume the listed exchange's theoretical UTC session when choosing a tick interval. The default P0 path first reads the broker's returned M1 history and then derives a 60-minute tick window from the tail of that observed M1 history:

```powershell
python scripts\probe_mt5_readonly.py `
  --expected-package-version 5.0.6147 `
  --p0-representative-symbol MSFT `
  --p0-representative-symbol NVDA `
  --p0-representative-symbol AMD `
  --p0-representative-symbol INTC `
  --bar-start 2026-08-24T00:00:00+00:00 `
  --bar-end 2026-09-01T00:00:00+00:00 `
  --output reports\mt5\mt5_p0_capability_probe.json
```

The command also writes, by default:

```text
reports/mt5/mt5_p0_capability_probe_assessment.json
```

For explicit diagnostics, `--tick-start` and `--tick-end` remain available and replace the automatic window. The history evidence records:

```text
requested_tick_start / requested_tick_end
tick_window_basis = explicit | derived_from_m1_tail
tick_window_m1_bar_count
tick_count / tick_first_at / tick_last_at
```

A zero tick count is interpretable only when the requested tick interval contains observed M1 activity for that same broker symbol. A zero count in a window with no M1 bars does **not** prove that the broker lacks historical ticks.

`copy_rates_range` and `copy_ticks_range` evidence means exactly what the connected terminal returned for the requested UTC interval. It is not silently promoted to the authoritative U.S. historical research source or to broker-global history beyond the requested window.

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
bid/ask spread sample is structurally valid
```

For the selected tick capability probe symbol, the policy additionally requires that a tick request was actually made and that its interval overlaps observed M1 bars. The broker is **not required to return non-zero historical ticks**. When an M1-anchored `copy_ticks_range` call returns an empty array, P0 records:

```text
history:<SYMBOL>:tick_history_unavailable_in_observed_m1_window
```

as a broker capability limitation. This is measured absence, not successful tick support and not a reason to invent tick data.

A structurally valid spread whose broker tick timestamp is already stale before the probe begins is also retained as a limitation (`spread:<SYMBOL>:stale_at_probe_start`) rather than silently treated as a fresh market quote. Later US-I0/MT5-D0 universe design must use the measured spread/session evidence appropriate to its own gate.

`terminal.trade_allowed=false` does **not** invalidate the read-only P0 measurement; it is preserved as `terminal:automated_trading_not_allowed` and becomes a downstream Demo/PAPER limitation. A later execution stage must independently prove trading permission before any order authority exists.

The acceptance result has deterministic `policy_id` and `assessment_id`. MT5-P0 closes only from an accepted real assessment, not from manual inspection of an inventory JSON.

## MT5-P0 closure evidence

A real accepted assessment establishes the connected terminal/broker measurement needed to freeze the engineering integration universe. Broker symbols then become `BrokerInstrument` candidates. They are not equivalent to listed-equity `ResearchInstrument` identities until US-I0 creates explicit evidence-bound mappings.
