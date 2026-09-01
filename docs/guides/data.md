# Data guide

## Authority levels

FinAgent distinguishes:

```text
provider/API capability
FinAgent adapter capability
source provenance/publication authority
local research admission
normalized data quality
research certification
```

These are not interchangeable.

## U.S. minute source workflow

```text
DatasetSourceCandidate
  ↓ source review
DatasetAuthorityDecision
  ↓ exact local snapshot
LocalMinuteCertification
  ↓ local-only admission
LocalResearchAdmission
  ↓ later US-C0 / US-D1
MarketDataQuery / DuckDB bounded scan
  ↓
MarketDataView
  ↓
bounded materialization
  ↓
ResearchDataset
```

The source/publication review and the local research admission answer different questions. The former records what is publicly documented about origin, published semantics and usage rights. The latter answers whether one exact locally downloaded immutable snapshot is sufficiently identified and empirically checked for **local, non-redistributed research**.

A `REJECTED` source can never receive local admission. A `REFERENCE_ONLY` public source may receive local admission if the exact snapshot passes certification and all unresolved source issues remain explicit limitations. This does not assert redistribution rights.

## Canonical OHLCV-1m candidate

FinAgent currently binds:

```text
mito0o852/OHLCV-1m
revision 776328445b7ac6e7815ef3a483e9c8ded1eb6d56
```

The dataset card reports:

```text
schema: timestamp/open/high/low/close/volume/ticker
timestamp timezone: UTC
timestamp convention: start of minute
partitioning: data/ohlcv_YYYY-MM.parquet
coverage: 1992-01 through 2026-03
upstream: Finnhub, declared by the dataset publisher
```

Finnhub documents intraday stock candles as **unadjusted**, while daily candles are split-adjusted. FinAgent therefore treats this 1m source as raw/split-unadjusted intraday history. Split/dividend events are not embedded in the OHLCV rows and must be handled separately by later research semantics.

The dataset contains historical ticker observations but no point-in-time security-master/lifecycle table. This limits broad survivorship-free claims but does not prevent bounded engineering research.

Regular-versus-extended-hours coverage is measured from the local files instead of being inferred from the README.

## Source-authority review

Source authority is represented by `finagent.data.provenance` and remains bound to the exact revision:

```text
DatasetSourceCandidate
DatasetRevision
DatasetProvenanceRecord
DatasetUsageRightsRecord
DatasetAuthorityDecision
DatasetAuthorityBundle
```

Review the public source metadata with:

```bash
uv run --frozen python scripts/review_us_source_authority.py \
  configs/us_source_authority/mito0o852_ohlcv_1m.toml \
  --output reports/us_source_authority/mito0o852_ohlcv_1m.json
```

The publication layer remains `REFERENCE_ONLY` because the publisher-origin statement is not independently verified, the README declares no license, and historical session coverage is not globally specified. Price-adjustment, corporate-action and symbol-lifecycle semantics are now narrowed rather than left completely unknown.

## Local Hugging Face snapshot

Supported layout:

```text
<cache-root>/
  refs/main
  snapshots/<revision>/
    README.md
    data/
      ohlcv_YYYY-MM.parquet
```

or an exact snapshot directory containing `README.md` and `data/` directly.

For the current Windows workstation:

```text
D:\Data\datasets--mito0o852--OHLCV-1m
```

Do not move or duplicate the 80+ GB corpus into the FinAgent repository.

## Local minute certification

Run from the repository root:

```powershell
uv run --frozen --extra local-parquet python scripts\certify_us_minute_snapshot.py `
  "D:\Data\datasets--mito0o852--OHLCV-1m" `
  --sample-month 1992-01 `
  --sample-month 2000-01 `
  --sample-month 2014-06 `
  --sample-month 2020-08 `
  --sample-month 2026-03 `
  --output reports\us_minute_local_certification.json
```

Certification performs:

- exact `refs/main` / snapshot revision verification;
- inventory of every `ohlcv_YYYY-MM.parquet` file using path and size identity;
- expected 1992-01 → 2026-03 coverage and missing-month detection;
- Parquet schema and timezone-aware timestamp validation;
- full scans of selected monthly partitions for duplicate `(ticker,timestamp)` keys;
- positive/consistent OHLC and non-negative volume checks;
- sampled ticker counts and timestamp ranges;
- observed regular/extended-hours diagnostics in `America/New_York`;
- deterministic inventory and certification identities.

If certification passes, FinAgent emits a `LocalResearchAdmission` with scope:

```text
local_non_redistributed_research
```

The admission carries the public-source blockers forward as limitations instead of deleting them.

## Research and execution prices

The selected minute source is raw/split-unadjusted. Before research spans corporate-action discontinuities, later stages must either attach explicit split/action evidence and a versioned transform, or exclude/segment affected windows and narrow the claim.

Do not silently treat raw intraday OHLC as a continuous adjusted price series.

## Large-data rule

Do not load the full minute corpus into pandas or a dense `ResearchDataset`. Later Data Plane work queries bounded assets/time/columns with DuckDB and materializes only the computation slice.

## Broker reference data

MT5 broker M1/tick/spread samples are reconciliation/cost/reference evidence unless a later stage explicitly grants them historical research authority. Equity-source and CFD-source differences remain visible.
