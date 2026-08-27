# A-share Supplemental Reference Data

This directory contains small, independently versioned historical reference files used to supplement the local vendor Parquet dataset.

Rules:

1. Never edit vendor Parquet files to insert these records.
2. Every row must cite a registered `source_id`, exact `source_url`, and `observed_at` timestamp.
3. The current dataset declares `coverage = "partial"`; absence of a record never means a stock was definitely normal/listed/tradable.
4. Prefer exchange/regulatory sources. Secondary sources may be used only when clearly identified.
5. Corrections are made by changing these small files, which changes `AshareSupplementalDataStore.data_version` and therefore research evidence identity.
6. Do not use supplemental data to claim survivorship-free certification until an explicit completeness audit exists.

Files:

- `sources.toml` — source registry and global coverage statement.
- `delistings.csv` — known delisting effective dates.
- `st_periods.csv` — known ST/risk-warning periods.
- `suspensions.csv` — known suspension periods.

The repository intentionally starts with schemas/source registrations rather than pretending a handful of collected rows is complete history.
