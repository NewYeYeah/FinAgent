# Market Data and Local Datasets

FinAgent separates market-data identity, provider capability and research evidence. Provider fallback is never silent.

## 1. Current provider roles

### A-share historical research — local Parquet

The downloaded local A-share dataset is the primary historical research source. The vendor raw directory is treated as immutable input.

Expected layout:

```text
A-Share/
├─ stock_basic_data.parquet
├─ stock_daily.parquet
├─ stock_1min/
├─ stock_5min/
├─ stock_15min/
├─ stock_30min/
└─ stock_60min/
```

Current certified surfaces:

- daily bars;
- audited 1-minute convention;
- `ts_code` identity across SSE/SZSE/BSE;
- daily volume: lots → shares (`×100`);
- daily amount: thousand CNY → CNY (`×1000`);
- intraday volume/amount already treated as shares/CNY;
- raw OHLC retained for market/execution semantics;
- return features and labels use `raw close × adj_factor`.

The source is **not** certified as a complete survivorship-free security master. Missing/incomplete delisting and historical-status data remain external supplements.

Install and certify:

```bash
python -m pip install -e ".[local-parquet]"
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

Windows PowerShell:

```powershell
python -m pip install -e ".[local-parquet]"
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

Do not modify vendor Parquet files to insert hand-collected delisting/ST/suspension records. Supplemental reference data is kept in separate, versioned files so it can be audited and replaced independently.

### US historical/reference — Alpaca SIP

Alpaca SIP is the canonical US historical reference path. IEX is a single-exchange feed and is appropriate for smoke tests, not for complete historical market coverage.

```bash
python -m pip install -e ".[us-market]"
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

For historical research the market config should use `feed = "sip"`. Recent/live SIP access depends on account entitlement; old historical queries may be available under a different entitlement rule than realtime SIP.

### AKShare

AKShare is credential-free and best-effort. It is useful for development and cross-provider evidence, but upstream websites and network/proxy behavior can change without notice.

```bash
python -m pip install -e ".[cn-free]"
```

### Tushare

Tushare is an optional A-share reference/fundamental provider. API access depends on account points and product entitlement.

```toml
[market_credentials.tushare]
token = "..."
```

### HiThink

HiThink is an optional official A-share API candidate. Snapshot and historical endpoints differ by asset class. Credential validity does not imply that every symbol/endpoint is supported.

```toml
[market_credentials.hithink]
api_key = "..."
```

## 2. A-share near-term boundary

A-share work is currently **historical-research first**. Near-term development does not require realtime A-share validation or live brokerage.

Deferred until the research stack is mature:

- realtime A-share acceptance;
- live broker integration;
- complete delisting history certification;
- historical ST/suspension/price-limit event certification;
- T+1/lot/minimum-commission execution semantics;
- production-grade corporate-action and symbol-history handling.

The project may use inexpensive/free public information to maintain supplemental reference files. Such files must record source, observation date and coverage limitations and must never be presented as complete merely because they are present.

## 3. Dataset identity

Every research run should record:

```text
provider/local source
source path or manifest
frequency
market
universe
start/end
adjustment semantics
data_version/digest
supplemental-data version, if used
```

The raw local A-share dataset, supplemental reference files and generated research dataset are separate identities.

## 4. Quality rules

Primary historical data must fail closed on:

- duplicate bars;
- invalid OHLC;
- invalid/non-positive adjustment factors;
- unknown symbol identity;
- time-zone ambiguity;
- silent provider substitution;
- schema changes that break the frozen data contract.

A missing supplementary status record is not silently interpreted as “normal trading”; the research protocol must state what coverage it assumes.
