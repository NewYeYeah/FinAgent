# Market Data and Local Datasets

FinAgent separates vendor/provider data, supplemental reference data and derived research evidence. Provider fallback is never silent.

## 1. Current provider roles

| Source | Role | Current position |
|---|---|---|
| Local A-share Parquet | Primary A-share historical research | daily + audited 1-minute adapter |
| Alpaca SIP | Primary US historical/reference | canonical US regression path |
| AKShare | Secondary cross-provider / smoke | best-effort upstream availability |
| Tushare | Optional A-share reference | entitlement-dependent |
| HiThink | Optional A-share reference/snapshot | asset-specific endpoints |
| Yahoo Finance / yfinance | Optional manual/secondary reference | no canonical adapter in current milestone |

## 2. Local A-share vendor data

Expected immutable vendor layout:

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

Current certified semantics:

- `ts_code` is authoritative identity;
- daily `vol`: lots → shares (`×100`);
- daily `amount`: thousand CNY → CNY (`×1000`);
- intraday `vol/amount`: shares/CNY;
- raw OHLC is retained for market/execution representation;
- return features/labels use `raw close × adj_factor`;
- 1-minute timestamps are bar-end; the 09:30 opening-auction observation is excluded from continuous-minute research by default.

The vendor basic file does not currently prove complete historical delisting/list-status coverage. `LocalAshareSecurityMaster` therefore remains candidate-only.

## 3. Certify and freeze the local A-share dataset

Install:

```bash
python -m pip install -e ".[local-parquet]"
```

Certify a representative 1-minute day:

```bash
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

Windows PowerShell:

```powershell
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

Freeze the **daily research source** before formal research:

```bash
python scripts/freeze_local_ashare_data.py \
  --root /data/A-Share \
  --frequency 1d \
  --output data/manifests/local_ashare_daily.json
```

```powershell
python scripts/freeze_local_ashare_data.py `
  --root D:\Data\A-Share `
  --frequency 1d `
  --output data\manifests\local_ashare_daily.json
```

Default freeze computes SHA-256 for the selected files. This is intentionally a one-time operation; a multi-GB daily file may take time to hash. Use `--fast` only for local diagnostics when a metadata-only freeze is acceptable.

Do not freeze every minute directory merely because it exists. Create frequency-specific manifests when that frequency is actually certified and used.

## 4. Supplemental A-share reference data

Missing historical delisting/ST/suspension data is not written back into vendor Parquet. It is stored under:

```text
reference_data/a_share/
├─ sources.toml
├─ delistings.csv
├─ st_periods.csv
└─ suspensions.csv
```

Every row contains an exact source URL and observation timestamp. The current registry explicitly declares `coverage = "partial"`.

Official exchange source families registered initially:

- Shanghai Stock Exchange suspended/delisted-company reference page;
- Shenzhen Stock Exchange company listing/termination notices;
- Beijing Stock Exchange official disclosure/termination announcements.

A row may improve a known instrument's historical status, but it does not prove that all missing instruments/events have been found. `SupplementedAshareSecurityMaster.survivorship_certified` therefore remains `False`.

This design lets inexpensive/free internet research improve coverage incrementally without mutating the large vendor database or changing unrelated price history.

## 5. Run the local A-share historical research smoke

Copy and edit:

```text
configs/research/local_ashare_research_smoke.example.toml
```

Then run:

```bash
python scripts/run_local_ashare_research_smoke.py \
  configs/research/local_ashare_research_smoke.example.toml
```

Windows PowerShell:

```powershell
python scripts/run_local_ashare_research_smoke.py `
  configs\research\local_ashare_research_smoke.example.toml
```

This test verifies the actual common data path:

```text
frozen vendor Parquet
→ supplemental reference store
→ security master
→ LocalAshareParquetDataAdapter
→ DatasetRequest
→ ResearchDataset / ResearchSplit
→ eligibility mask
→ lagged features / forward labels
→ deterministic cross-sectional RankIC smoke diagnostic
```

It intentionally does **not** invoke A-share execution, realtime APIs, sealed holdout or live/paper brokerage. RankIC from this script is a system diagnostic, not promotion evidence.

Use `--verify-content` when a release/research run should re-hash the frozen files instead of performing the normal fast verification.

## 6. Alpaca US reference data

For historical US research use Alpaca **SIP**, not IEX. IEX is a single-exchange feed and can contain calendar/volume gaps relative to consolidated US trading.

```bash
python -m pip install -e ".[us-market]"
python scripts/pull_market_data.py configs/markets/us_etf_agent_data_alpaca.toml
python scripts/validate_market_data.py data/market/us_etf_alpaca
```

The market config used for canonical historical research should set:

```toml
feed = "sip"
```

Recent/realtime SIP entitlements and historical SIP access are separate account concerns; FinAgent does not silently fall back to IEX.

## 7. AKShare, Tushare and HiThink

### AKShare

Credential-free; useful for development/cross-provider evidence. Upstream public websites and local proxy behavior can fail independently of FinAgent.

```bash
python -m pip install -e ".[cn-free]"
```

### Tushare

Optional A-share reference/fundamental provider. Access depends on account points/product entitlement.

```toml
[market_credentials.tushare]
token = "..."
```

### HiThink

Optional official A-share provider. Credential validity does not imply every asset-class endpoint is interchangeable. Equity and fund/ETF historical APIs must be treated separately.

```toml
[market_credentials.hithink]
api_key = "..."
```

## 8. Yahoo Finance decision

Yahoo Finance is useful as an inexpensive secondary sanity-check source, but it does **not** replace Alpaca SIP as FinAgent's canonical US provider.

Reasons:

1. Yahoo's official downloadable historical CSV is a user-facing Finance feature and may require Yahoo Finance Gold; some instruments cannot be downloaded because of licensing restrictions.
2. The commonly used Python library `yfinance` is an unofficial, community-maintained client and explicitly states that it is not affiliated/endorsed by Yahoo and that Yahoo API/data use is intended for personal use.
3. Adjustment/repair behavior must be controlled explicitly before two data sources are compared; otherwise adjusted Yahoo prices can be mistaken for raw executable prices.
4. Alpaca provides a clearer market-feed identity (SIP/IEX), stock data API, and a natural path to later paper/realtime brokerage testing.

Therefore the current milestone does **not** add a Yahoo provider adapter. If added later, it should be an explicit `yahoo` secondary provider with raw-price mode (`auto_adjust=False` or equivalent), separate corporate actions, provider-specific data versioning and no silent reconciliation into Alpaca data.

## 9. Current A-share operational boundary

A-share work is historical-research first. Near-term milestones do not require:

- realtime A-share acceptance;
- external A-share broker integration;
- complete paid delisting/security-master products;
- production 1-minute execution simulation.

The project should first validate local daily cross-sectional research, improve inexpensive supplemental status data where practical, and implement A-share execution semantics before paying for realtime infrastructure.
