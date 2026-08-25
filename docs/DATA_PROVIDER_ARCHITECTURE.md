# FinAgent Multi-Provider Data Architecture

Date: 2026-08-25

## Purpose

FinAgent no longer treats one vendor name as a proxy for research suitability. The data layer is capability-driven and records explicit provider boundaries before a study starts.

The development/testing priority is now US equities/ETFs because free and official A-share history still has important survivorship and market-microstructure gaps. A-share provider interfaces are landed now so later market-specific work does not require another ingestion redesign.

## Provider roles

| Provider | Primary role | Markets | Current FinAgent adapter | Important boundary |
| --- | --- | --- | --- | --- |
| Alpaca | primary US research provider | US | historical daily bars | vendor realtime/minute capabilities are not yet exposed by the adapter |
| AKShare | free development and cross-check provider | CN, US | historical daily bars | public upstream aggregation, no SLA; US symbols are resolved from `stock_us_spot_em` or explicit mapping |
| HiThink Financial-API | official CN research provider candidate | CN | historical daily equity/ETF bars | public service does not currently guarantee delisted-history completeness; no minute/tick feed |
| Tushare | optional reference/fundamental provider | CN | historical daily equity/ETF bars | capability model assumes 15k points and no separately paid services; no US/minute/realtime entitlement is assumed |

There is no silent provider fallback. A failed provider run fails the study unless the caller explicitly starts a new run with another provider. Provider changes produce separate manifests and data versions.

## Capability contract

The public data layer exposes:

```text
DataCapability
ProviderTier
ProviderCapabilities
ResearchDataRequirement
ProviderSymbolMap
ProviderRegistry
```

`ProviderCapabilities.available` describes provider/account capabilities known to FinAgent. `ProviderCapabilities.implemented` describes the subset currently exposed by FinAgent code. This prevents vendor marketing capability from being mistaken for an implemented research path.

Example:

```python
ResearchDataRequirement(
    market=MarketRegion.US_EQUITY,
    asset_types=frozenset({AssetType.ETF}),
    capabilities=frozenset({DataCapability.HISTORICAL_DAILY}),
)
```

The default registry currently returns Alpaca and AKShare as implemented candidates for that requirement. A realtime-stream requirement returns no implemented candidate even though Alpaca's vendor capability is recorded as available. That distinction is intentional.

## Symbol mapping

Canonical research symbols and provider symbols are separate concepts.

AKShare's US historical API uses provider codes such as `105.XYZ` or `106.XYZ`, while FinAgent research uses canonical symbols such as `SPY` and `QQQ`.

For AKShare US data, FinAgent either:

1. resolves the canonical ticker through `stock_us_spot_em()` once and caches the result; or
2. uses explicit TOML mappings under `[market.provider_symbols]`.

Explicit mappings are incorporated into the request metadata/fingerprint so a mapping change creates a different immutable data version.

## Cross-provider QA

`ProviderDiffReport` compares already-normalized datasets by canonical symbol and trading session. It reports:

```text
common rows
rows missing from either provider
close mismatches
volume mismatches
maximum absolute close error
maximum relative close error
```

Use:

```bash
./scripts/finagent.sh python scripts/compare_market_providers.py \
  data/market/us_etf_smoke/bars.csv \
  data/market/us_etf_akshare_smoke/bars.csv \
  --left-provider alpaca \
  --right-provider akshare \
  --output reports/us_provider_diff.json
```

A provider diff is evidence, not an automatic repair mechanism. FinAgent never fills missing vendor rows from another provider inside the same immutable dataset.

## Free US-first workflow

Install:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,cn-free]'
```

AKShare free US smoke data:

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_akshare_smoke.toml

./scripts/finagent.sh python scripts/run_market_backtest.py \
  configs/markets/us_etf_akshare_smoke.toml
```

For the primary US provider, keep the existing Alpaca path:

```bash
export ALPACA_API_KEY='...'
export ALPACA_SECRET_KEY='...'

./scripts/finagent.sh python -m pip install -e '.[dev,us-market]'
./scripts/finagent.sh python scripts/pull_market_data.py configs/markets/us_etf_smoke.toml
./scripts/finagent.sh python scripts/run_market_backtest.py configs/markets/us_etf_smoke.toml
```

The recommended validation order is:

```text
AKShare free smoke
        ↓
FinAgent regression/backtest behavior
        ↓
Alpaca primary historical study
        ↓
AKShare ↔ Alpaca ProviderDiffReport
        ↓
Agent-market research integration
```

## A-share interfaces landed now

### AKShare

`configs/markets/a_share_etf_smoke.toml` now uses AKShare as the free default. The adapter supports A-share equity/ETF daily bars. It remains a development/cross-check provider because upstream public websites can change without an API SLA.

### HiThink Financial-API

`HiThinkMarketDataIngestor` uses the official REST API and supports:

```text
A-share equity: /api/a-share/prices/historical
ETF:            /api/fund/market/historical
```

The adapter automatically splits requests to respect the official maximum request window (10 years for equity history and 5 years for ETF history), merges windows deterministically and rejects nonzero API error codes.

Example:

```bash
export HITHINK_FINANCE_API_KEY='...'
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/a_share_etf_hithink_smoke.toml
```

HiThink is not yet sufficient as the sole source for survivorship-bias-free historical individual-equity research because current public issue evidence reports missing delisted stocks. Wide-universe studies requiring delisted history must remain blocked until that requirement is satisfied.

### Tushare

Tushare remains installed only through:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,tushare-reference]'
```

The registry models the user's actual budget boundary: 15,000 points with no separately paid minute/realtime/US packages. It is therefore retained for low-frequency reference, fundamentals, macro and alternative-data expansion rather than as the default market-data dependency.

## Deferred A-share functional work

The interfaces above are complete enough that later A-share work should extend capabilities, not redesign provider selection. Deferred market semantics include:

```text
survivorship-bias-free PIT individual-equity universe
delisting terminal returns
suspension/tradability state
A-share T+1 sellable quantity
100-share lot rules
price limits
stamp duty and asymmetric fees
dual research-price/execution-price corporate-action accounting
minute/tick/Level-2 data from a suitable provider
```

## Next development milestone

With the provider layer stabilized, the highest-priority 1.2 milestone remains the Agent-to-real-market research orchestration:

```text
immutable market dataset
    -> ResearchProgram
    -> Agent hypothesis/feature generation
    -> PIT materialization
    -> nested validation + multiplicity control
    -> alpha calibration/ensemble
    -> risk + portfolio
    -> timed historical backtest
    -> evidence memory
```

The implementation and test emphasis should remain US-first until the A-share Level-2 market-semantics checklist is addressed.
