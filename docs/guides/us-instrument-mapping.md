# US-I0 research/broker instrument mapping

US-I0 keeps historical research identities and broker execution identities separate. A ticker string, MT5 folder path or current broker availability is not enough to turn one identity into the other.

## Authority boundary

```text
certified local OHLCV source symbol
        ↓
ResearchInstrument

accepted MT5-P0 probe
        ↓
BrokerInstrument

ResearchInstrument + BrokerInstrument
        ↓ explicit mapping evidence + operator attestation
InstrumentMapping
        ↓ only ACCEPTED_FOR_ENGINEERING
EngineeringUniverse
```

`EngineeringUniverse` is an integration universe. It is explicitly **not** a survivorship-unbiased `ResearchUniverse` and cannot support a market-wide historical Alpha claim.

## Frozen interpretation rules

- `ResearchInstrument` keeps the immutable OHLCV source candidate/revision and the fact that no PIT security master/lifecycle evidence is currently available.
- `BrokerInstrument` keeps the exact broker symbol, server, MT5 terminal/spec identities and contract/point/tick/volume/margin/swap/order semantics measured in MT5-P0.
- MT5 `path` such as `Nasdaq\Stock\MSFT` is retained as broker metadata but is never promoted to authoritative listed-exchange identity.
- Matching ticker text is evidence, not automatic acceptance.
- Broker prefixes/suffixes are never stripped inside strategy code. A non-identical broker symbol must be stated explicitly as `RESEARCH=BROKER`.
- `ACCEPTED_FOR_ENGINEERING` requires explicit operator attestation plus a visible/tradable broker symbol and compatible quote/profit/margin currency evidence.
- This attestation means only “use this mapping for the bounded engineering integration universe”. It does not prove PIT identity, listed venue, corporate-action completeness, survivorship-free history or live-trading suitability.

## Seed mapping workflow

After MT5-P0 is accepted and `main` contains the US-I0 materializer, run from the existing Windows Conda environment:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
git checkout main
git pull --ff-only

python scripts\materialize_us_i0_engineering_universe.py `
  --mt5-probe reports\mt5\mt5_p0_capability_probe.json `
  --mapping MSFT=MSFT `
  --mapping NVDA=NVDA `
  --mapping AMD=AMD `
  --mapping INTC=INTC `
  --accept-for-engineering MSFT `
  --accept-for-engineering NVDA `
  --accept-for-engineering AMD `
  --accept-for-engineering INTC `
  --output reports\us_instruments\us_i0_engineering_universe.json
```

The `--accept-for-engineering` switches are deliberately separate from `--mapping`: declaring a pair does not silently approve it.

Expected accepted seed report:

```text
accepted = true
blockers = []
mapping_count = 4
accepted_mapping_count = 4
universe_id = engineering-universe-...
```

If a broker symbol is missing, invisible, disabled or has incompatible currency evidence, the materializer fails closed and records the exact mapping blocker. Do not rename, strip suffixes or substitute another broker symbol merely to force acceptance.

## Deterministic candidate selection

The 20–30-name expansion begins with a reproducible candidate report rather than manual cherry-picking. The selector uses the admitted cleaning stack and accepted XNYS calendar to evaluate recent regular-session activity, then intersects research symbols with the exact tradable MT5 inventory.

Default window:

```text
2026-01-01T00:00:00Z ≤ event_time < 2026-04-01T00:00:00Z
```

Default candidate gates:

```text
minimum active sessions                20
minimum active-session ratio           0.80
minimum median regular-minute coverage 0.80
minimum median session close            1.00 USD
selected spread-probe candidates       40
minimum viable candidate set           20
```

Run locally:

```powershell
python scripts\select_us_i0_universe_candidates.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --mt5-probe reports\mt5\mt5_p0_capability_probe.json `
  --calendar reports\us_calendar\xnys_1992_2026.json `
  --start 2026-01-01T00:00:00+00:00 `
  --end 2026-04-01T00:00:00+00:00 `
  --top-n 40 `
  --minimum-selected 20 `
  --memory-limit 512MB `
  --threads 2 `
  --max-temp-directory-size 4GB `
  --temp-directory data\duckdb_temp\us_i0_candidates `
  --output reports\us_instruments\us_i0_universe_candidates.json
```

The report is row-free and records:

```text
research symbol count
tradable broker symbol count
exact symbol intersection count
eligible candidate count
selected ranking and aggregate activity/coverage metrics
current spread bps when already present in the supplied probe
manual Market Watch visibility actions
```

Selection uses an explicit liquidity proxy:

```text
daily_notional_proxy = Σ(close × source volume)
```

This is a ranking diagnostic, not independently verified consolidated dollar volume. It must not be used as market-capacity authority.

Exact ticker equality is still not same-security proof. The selected 40-name report is only the input to visibility/spread measurement and mapping review. Invisible but tradable MT5 symbols remain candidates with `visibility_action_required=true`; the selector does not call `symbol_select` or mutate terminal state.

A valid first-stage output has:

```text
ready_for_spread_probe = true
blockers = []
selected_candidate_count >= 20
missing_seed_symbols = []
```

The resulting `spread_probe_symbols` should then be measured with the read-only MT5 spread surface, preferably during the broker-observed active session. Current spread is diagnostic and does not substitute for historical transaction-cost evidence.

## Expansion beyond the seed

The planning target remains roughly 20–30 liquid engineering names. Seed acceptance proves the mapping machinery, not the final universe denominator. Expansion must intersect:

```text
certified local research-history availability
∩ measured MT5 availability/tradability
∩ acceptable current spread/liquidity evidence
```

The broader expansion is generated through the deterministic candidate-selection report, followed by visibility/spread measurement and explicit mapping attestation. US-I0 closes only when every engineering asset used downstream has an accepted mapping or an explicit rejection and the final universe identity is recorded in `docs/status.toml`.
