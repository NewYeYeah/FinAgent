# FinAgent 1.2.6 — Local A-share Parquet Data Layer

## 1. Scope

This increment promotes the downloaded local A-share database to a first-class
historical research source without treating vendor claims as certified semantics.
It adds:

```text
LocalAshareDatasetLayout
LocalAshareSecurityMaster
LocalAshareParquetDataAdapter
LocalAshareDatasetInspector
scripts/certify_local_ashare_data.py
```

The first certified numerical surfaces are:

```text
daily
1-minute (audited bar-end convention)
```

The 5/15/30/60-minute directories are recognized by the layout but remain fail-closed
until a sample from each frequency confirms timestamp boundaries.

## 2. Source sample findings

### 2.1 Basic sample

The supplied CSV sample contains:

```text
ts_code, symbol, name, area, industry, fullname, enname, market,
exchange, curr_type, list_status, list_date, delist_date, is_hs,
act_name, act_ent_type
```

`ts_code` is authoritative. CSV conversion changed values such as `000007` into the
integer `7`, so `symbol` must not be used to construct identity. FinAgent derives:

```text
000001.SZ -> equity:SZSE:000001:CNY
601015.SH -> equity:SSE:601015:CNY
920978.BJ -> equity:BSE:920978:CNY
```

The full basic Parquet inspected earlier contains incomplete `list_status` and
`delist_date`, plus `1970-01-01` list-date placeholders. The implementation therefore
provides a **candidate listing-date universe**, not a survivorship-free universe.

### 2.2 Daily sample

The supplied daily sample contains 33 fields, including:

```text
raw OHLC / pre_close
vol / amount / adj_factor
up_limit / down_limit
turnover_rate / volume_ratio
PE/PB/PS/dividend metrics
share counts / market capitalisation
suspend_type / is_st / listed_days
```

The actual sample is more useful than the seller's short field list, but FinAgent does
not consume undocumented vendor factors such as precomputed momentum/quality. The
initial adapter exposes only observed columns and computes return features itself.

### 2.3 241-row 1-minute sample

The supplied `000001.SZ` sample has exactly:

```text
09:30                         1 opening-auction observation
09:31 ... 11:30             120 morning continuous bars
13:01 ... 15:00             120 afternoon continuous bars
                              -----------------------------
                              241 vendor rows
```

The only time discontinuity is `11:30 -> 13:01` (91 minutes). The dataset therefore
uses a bar-end convention:

```text
09:31 row -> event interval starts 09:30, value becomes available 09:31
13:01 row -> event interval starts 13:00, value becomes available 13:01
15:00 row -> event interval starts 14:59, value becomes available 15:00
```

The `09:30` row is a separate opening-auction observation. It is excluded from
continuous-minute research by default, leaving 240 continuous bars. It can be kept
explicitly with `include_opening_auction=True`, but is never silently interpreted as an
ordinary 09:29–09:30 continuous bar.

The sample also contains a zero-volume `14:59` placeholder. Zero volume is retained;
it is not automatically replaced or dropped.

### 2.4 Daily/minute unit reconciliation

The supplied sample reconciles almost exactly:

```text
minute OHLC       = daily OHLC
sum(minute vol)   = 34,082,720 shares
daily vol * 100   = 34,082,718 shares
absolute delta    = 2 shares

sum(minute amount)  = 327,584,256 CNY
daily amount * 1000 = 327,584,247 CNY
absolute delta      = 9 CNY
```

The tiny differences are consistent with vendor rounding. The frozen unit contract is:

```text
intraday vol     = shares
intraday amount  = CNY

daily vol       = lots (100 shares) -> canonical shares = vol * 100
daily amount    = thousand CNY      -> canonical CNY    = amount * 1000
```

Tushare-style share-count and market-cap fields are also normalized:

```text
total_share / float_share / free_share -> shares (* 10,000)
total_mv / circ_mv                     -> CNY    (* 10,000)
```

Turnover/dividend rate fields retain vendor percentage units and are labelled
`rate_unit=vendor_percent` in dataset metadata.

## 3. Price and adjustment contract

The vendor stores raw OHLC and `adj_factor`. FinAgent keeps two semantics inside the
adapter:

```text
market/execution price = raw OHLC
research return price  = raw close * adj_factor
```

Therefore:

```text
close
open/high/low
```

remain executable raw prices, while:

```text
simple_return_N
log_return_N
squared_log_return_N
forward_simple_return_N
forward_log_return_N
```

use the adjustment-aware research close. This avoids corporate-action jumps without
using a future latest-factor denominator.

## 4. Installation

Install the local Parquet extra.

### Ubuntu

```bash
python -m pip install -e ".[dev,local-parquet]"
```

### Windows PowerShell

```powershell
python -m pip install -e ".[dev,local-parquet]"
```

`duckdb` is used for out-of-core Parquet scans and predicate pushdown. FinAgent does
not convert the GB-scale daily file to CSV and does not load the whole file with
`pandas.read_parquet()`.

## 5. Configuration

Copy the example:

```text
configs/local_ashare.example.toml
```

Windows example:

```toml
[local_ashare]
root = "D:/Data/A-Share"
basic_filename = "stock_basic_data.parquet"
daily_filename = "stock_daily.parquet"
sample_frequency = "1min"
sample_symbol = "000001.SZ"
sample_date = 2009-01-05
report_path = "reports/local_ashare_certification.json"
```

## 6. Certification command

### Windows PowerShell

```powershell
python scripts/certify_local_ashare_data.py `
  configs\local_ashare.example.toml `
  --root D:\Data\A-Share `
  --sample-symbol 000001.SZ `
  --sample-date 2009-01-05
```

### Ubuntu

```bash
python scripts/certify_local_ashare_data.py \
  configs/local_ashare.example.toml \
  --root /data/A-Share \
  --sample-symbol 000001.SZ \
  --sample-date 2009-01-05
```

The report checks:

```text
basic/daily schemas
instrument and row counts
duplicate keys
OHLC validity
negative volume/amount
adj_factor validity
1970 list-date placeholders
delist/list-status coverage
241-row minute sequence
daily/minute OHLCV and amount reconciliation
```

A report may pass with warnings. In particular, incomplete delisting fields remain a
warning and prevent survivorship-free certification.

## 7. Python usage

```python
from datetime import UTC, datetime
from pathlib import Path

from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
)
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.research import DatasetRequest, TimeRange

layout = LocalAshareDatasetLayout(Path(r"D:\Data\A-Share"))
security_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
adapter = LocalAshareParquetDataAdapter(
    layout,
    frequency=AshareBarFrequency.DAILY,
    security_master=security_master,
)

universe = (
    AssetId("000001", AssetType.EQUITY, venue="SZSE", currency="CNY"),
    AssetId("601015", AssetType.EQUITY, venue="SSE", currency="CNY"),
)

dataset = adapter.build_dataset(
    DatasetRequest(
        universe=universe,
        features=(
            "simple_return_1",
            "simple_return_5",
            "log_volume_change_1",
            "turnover_rate",
            "circ_mv",
        ),
        labels=("forward_simple_return_1",),
        splits={
            "train": TimeRange(
                datetime(2018, 1, 1, tzinfo=UTC),
                datetime(2022, 1, 1, tzinfo=UTC),
            )
        },
        dataset_id="a-share-daily-v1",
    )
)
```

The adapter queries all requested daily symbols in one DuckDB scan rather than one scan
per stock. Intraday files are queried only for explicitly requested symbols.

## 8. Current eligibility semantics

When a `LocalAshareSecurityMaster` is supplied, `ResearchSplit.eligibility_mask` uses:

```text
list_date is known
and asof >= list_date
and (delist_date is missing or asof <= delist_date)
```

Because source `delist_date/list_status` coverage is incomplete, metadata records:

```text
universe_grade = candidate_only
```

This is useful for development and cross-sectional research, but reports must not call
it a survivorship-free all-A-share universe. A later certified security-master source
must replace or augment the vendor basic file.

## 9. Supported features

Direct raw/canonical fields include, when present:

```text
open/high/low/close/research_close
volume/amount/adj_factor/pre_close
up_limit/down_limit
turnover_rate/turnover_rate_f/volume_ratio
pe/pe_ttm/pb/ps/ps_ttm
dv_ratio/dv_ttm
total_share/float_share/free_share
total_mv/circ_mv
is_st/listed_days
```

Derived features and labels follow existing FinAgent names:

```text
simple_return_N
log_return_N
squared_log_return_N
log_volume_change_N
forward_simple_return_N
forward_log_return_N
```

Undocumented precomputed vendor factors are not approved by default.

## 10. Known boundaries

1. `data_version` currently uses a fast path/size/mtime fingerprint and is labelled
   `fast`; it is not represented as a content SHA. Full multi-GB hashing belongs in a
   separate certification job.
2. Daily/full-market panel materialization is still constrained by the in-memory
   `ResearchSplit` array contract. DuckDB avoids whole-file reads, but callers should
   begin with bounded universes/time ranges before a chunked panel backend is added.
3. `market_snapshot()` uses a bounded historical lookup window. It is sufficient for
   normal daily/minute studies but is not a complete suspension/delisting engine.
4. 5/15/30/60-minute data is recognized but not timestamp-certified from the supplied
   1-minute sample. It fails closed unless explicitly enabled for diagnostics.
5. ST/suspension/price-limit fields are exposed but full A-share execution rules remain
   a separate milestone.
6. The seller's “no future data” claim is not accepted as evidence. PIT safety derives
   from FinAgent timestamps, split isolation, feature code and independently certified
   source fields.

## 11. Recommended next development step

After this data layer passes local certification:

```text
Local Parquet daily adapter
        ↓
bounded A-share daily universe
        ↓
Agent Factor Quant discovery
        ↓
RankIC / quantiles / ensemble
        ↓
provider/reference comparison
```

Only after daily research is stable should FinAgent certify and introduce 60/30/15/5/1
minute frequencies and connect Tushare/HiThink realtime shadow validation.
