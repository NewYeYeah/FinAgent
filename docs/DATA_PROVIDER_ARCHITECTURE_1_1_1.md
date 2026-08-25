# FinAgent 1.1.1 Data Provider Architecture — US-first validation

Date: 2026-08-26

## Goal

This maintenance milestone completes the planned provider-neutral data interfaces while moving development and validation emphasis to the US market, where open/research-grade data access is materially easier to audit.

The strategic rule is:

```text
US market = primary development / validation market
A-share   = supported provider surface, narrower certification scope
```

The change does not remove A-share support. It prevents A-share data limitations from blocking the Agent/quant research pipeline.

## Provider roles

| Provider | Market role | Default FinAgent role |
| --- | --- | --- |
| Alpaca | US historical + realtime/paper feed | US primary |
| AKShare | CN/US community aggregation | free development + cross-check |
| HiThink Financial-API | official A-share daily/snapshot API | CN daily primary candidate |
| Tushare 15k baseline | CN low-frequency/reference/fundamental data | optional reference only |

Tushare is intentionally retained for compatibility and cross-provider evidence, but its 15,000-point capability declaration does **not** claim separately paid realtime, minute or US-market entitlements.

## New contracts

### `ProviderCapabilities`

Every provider declares machine-readable capabilities instead of relying on provider-name conditionals:

```text
markets
historical_daily
historical_minute
realtime_snapshot
realtime_stream
fundamentals
macro
corporate_actions
pit_universe
delisted_history
alternative_data
```

Capabilities are conservative claims. A provider that can return A-share daily bars does not automatically satisfy survivorship-bias-free individual-equity research.

### `ResearchDataRequirement`

A research study can declare data requirements before pulling or evaluating data:

```python
ResearchDataRequirement(
    market=MarketRegion.A_SHARE,
    frequency=DataFrequency.DAILY,
    require_pit_universe=True,
    require_delisted_history=True,
)
```

For the current public HiThink surface this requirement fails closed because PIT broad-universe/delisted-history coverage is not certified.

### `ProviderSymbolMap`

Canonical instrument identity remains separate from provider encodings. Example:

```text
FinAgent canonical: SPY
AKShare provider:   105.SPY
```

The provider symbol is evidence/query metadata; it never becomes `AssetId.symbol`.

### `ProviderDiffReport`

Already-normalized datasets can be compared without silently reconciling disagreements:

```text
calendar/missing rows
close absolute error
close relative error
volume relative error
```

A disagreement remains evidence. FinAgent does not automatically choose whichever provider makes a study pass.

## Provider adapters

### Alpaca

Existing US adapter remains the primary US-market path. Its declaration includes daily/minute historical data and realtime feed capabilities, subject to account/feed entitlements.

### AKShare

New `AKShareMarketDataIngestor` supports daily research ingestion for:

```text
A-share equity
A-share ETF
US equity / ETF
```

The adapter is explicitly best-effort and intended for free development, smoke studies and cross-provider comparison. US provider symbols are configured through `ProviderSymbolMap`; strict mode is recommended to prevent guessing provider-specific codes.

Example config:

```text
configs/markets/us_etf_akshare_smoke.toml
```

Install:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,cn-free]'
```

Pull:

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_akshare_smoke.toml \
  --show-capabilities
```

### HiThink Financial-API

New `HiThinkMarketDataIngestor` uses the official REST daily historical endpoint:

```text
GET /api/a-share/prices/historical
adjust=none
interval=1d
```

Credential:

```bash
export HITHINK_FINANCE_API_KEY='...'
```

Example:

```bash
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/a_share_hithink_smoke.toml \
  --show-capabilities
```

The capability declaration intentionally records current public limitations:

```text
no minute/tick/Level-2 claim
no US-market claim
no survivorship-bias-free delisted-history claim
```

This is suitable for fixed-universe A-share/ETF smoke studies and provider QA, not yet broad historical individual-equity certification.

### Tushare

Existing adapter remains operational. In the default architecture it is reclassified as an optional A-share reference/fundamental source under the user's 15,000-point-only constraint.

The declared baseline explicitly excludes separately paid:

```text
realtime data
historical minute data
US-market data
```

No new US Tushare adapter is planned under this budget model.

## US-first validation plan

The next research-development cycle should use US ETFs first:

```text
SPY / QQQ / IWM / DIA
```

Recommended evidence stack:

```text
Alpaca  -> primary normalized dataset
AKShare -> free cross-provider dataset
           |
           v
ProviderDiffReport
           |
           v
nested historical study
           |
           v
Agent-market research pipeline (next milestone)
```

The goal is to validate orchestration, PIT, factor generation, multiplicity control, alpha/risk integration and report reproducibility without making A-share market semantics the gating dependency.

## Cross-provider CLI

After two providers have produced normalized `bars.csv` files:

```bash
./scripts/finagent.sh python scripts/compare_market_providers.py \
  data/market/us_etf_alpaca/bars.csv \
  data/market/us_etf_akshare_smoke/bars.csv \
  --left-provider alpaca \
  --right-provider akshare \
  --output reports/provider_diff_us_etf.json
```

The output is evidence only. It never rewrites either source dataset.

## A-share deferred functional work

Data interfaces are landed now, but the following A-share research semantics remain targeted follow-up work:

```text
survivorship-bias-free PIT individual-equity universe
delisting terminal returns
suspension/resumption semantics
T+1 sellability
100-share lots
price limits
stamp duty / asymmetric fees
research-price vs execution-price corporate-action ledger
```

Until these are complete, broad A-share individual-stock studies must fail their `ResearchDataRequirement` or remain explicitly non-certified exploratory studies.

## Stable invariants

1. Provider-specific symbols never replace canonical `AssetId` identity.
2. Provider capabilities are explicit and conservative.
3. Unsupported research requirements fail before the study is treated as certified evidence.
4. Provider fallback is never silent.
5. Provider disagreement is stored/reported, not auto-reconciled.
6. Raw prices remain the execution-price input for the current historical-study contract.
7. US development remains Alpaca-primary; AKShare is free secondary evidence.
8. A-share development is supported by HiThink + AKShare, with Tushare optional reference coverage.
