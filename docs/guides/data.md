# Data guide

## Authority levels

FinAgent distinguishes:

```text
provider/API capability
FinAgent adapter capability
source provenance/usage authority
normalized data quality
research certification
```

These are not interchangeable.

## Existing sources

The repository contains local A-share Parquet support and provider adapters such as Alpaca/AKShare/HiThink/Tushare. Their exact capability and historical interpretation are provider/config-specific; never silently fall back from one provider to another.

Local A-share source behavior is historical-release context after H0. New P0 data development targets certified U.S. minute history.

## U.S. minute workflow

```text
DatasetSourceCandidate
  ↓ US-S0
DatasetAuthorityDecision
  ↓
partitioned immutable source data
  ↓ US-C0/US-D1
MarketDataQuery / DuckDB bounded scan
  ↓
MarketDataView
  ↓
bounded materialization
  ↓
ResearchDataset
```

US-S0 must decide exact revision, provenance, usage rights, timestamp/adjustment/action/lifecycle semantics before a source is authoritative.

### Source-authority review

Source authority is represented by `finagent.data.provenance`. A review binds:

```text
DatasetSourceCandidate
DatasetRevision
DatasetProvenanceRecord
DatasetUsageRightsRecord
DatasetAuthorityDecision
DatasetAuthorityBundle
```

`DatasetAuthorityBundle.require_research_authority()` is the fail-closed boundary for downstream authoritative research. `REFERENCE_ONLY` and `REJECTED` candidates cannot cross it.

Review a repository candidate without downloading the bulk corpus:

```bash
uv run --frozen python scripts/review_us_source_authority.py \
  configs/us_source_authority/mito0o852_ohlcv_1m.toml \
  --output reports/us_source_authority/mito0o852_ohlcv_1m.json
```

The initial `mito0o852/OHLCV-1m` review is deliberately `REFERENCE_ONLY`. Its immutable Hugging Face revision and published schema/time convention are recorded, but research authority remains blocked while upstream-origin verification, usage rights, session coverage, price-adjustment, corporate-action and symbol-lifecycle semantics are unresolved. Do not treat the dataset title, size or README origin statement as a research license or data-quality certification.

Adding another candidate means adding a new authority config/evidence review; it does not modify this candidate's immutable revision or silently replace its decision.

## Time semantics

All authoritative timestamps are timezone-aware. `event_time` is the represented market event; `available_at` is the PIT observation clock. U.S. sessions use materialized/versioned trading-calendar evidence including DST/holidays/half-days.

## Research and execution prices

Research price basis and executable/raw market prices are separate policies. Corporate actions are explicit evidence/transform semantics rather than an implicit assumption hidden in a vendor field.

## Large-data rule

Do not load the full minute corpus into pandas or a dense `ResearchDataset`. Query bounded assets/time/columns with DuckDB and materialize only the computation slice.

## Broker reference data

MT5 broker M1/tick/spread samples are reconciliation/cost/reference evidence unless a later stage explicitly grants them historical research authority. Equity-source and CFD-source differences remain visible.
