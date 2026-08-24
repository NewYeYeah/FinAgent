# ADR-007 — Phase 1 Numerical Data Contract

**Status:** Accepted / Frozen for Phase 1  
**Date:** 2026-08-24

## Context

Phase 0.5 intentionally kept `ResearchDataset` as a schema/artifact contract. That was sufficient to validate portfolio, risk, order and execution boundaries, but it did not specify how real numerical time-series data should move from a data source into alpha/risk models.

The Phase 1 contract must support:

- point-in-time safety;
- multi-asset time-series models;
- missing observations;
- covariance estimation;
- deterministic/reproducible datasets;
- future adapters for pandas/Qlib/Parquet/brokers without making any of those frameworks canonical.

## Decision

### 1. DataAdapter is the only vendor/file boundary

```python
class DataAdapter(Protocol):
    @property
    def data_version(self) -> str: ...

    def build_dataset(self, request: DatasetRequest) -> ResearchDataset: ...

    def feature_window(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        lookback: int,
    ) -> FeatureWindow: ...

    def market_snapshot(
        self,
        asof: datetime,
        universe: tuple[AssetId, ...],
    ) -> MarketSnapshot: ...

    def calendar(
        self,
        start: datetime,
        end: datetime,
        universe: tuple[AssetId, ...],
    ) -> tuple[datetime, ...]: ...
```

No alpha/risk/portfolio component may depend on CSV column names, SQL schemas, vendor symbols or a pandas DataFrame provided by a data source.

### 2. Numerical panel layout is fixed

`ResearchSplit` is the canonical training/evaluation matrix:

```text
feature_values.shape = (time, asset, feature)
label_values.shape   = (time, asset, label)
```

`FeatureWindow` is the canonical inference matrix:

```text
values.shape = (time, asset, feature)
```

Axis order is therefore permanently:

```text
T × N × F
```

for numerical research panels.

### 3. Arrays are immutable at module boundaries

Arrays are defensively copied to contiguous `float64` NumPy arrays and marked read-only.

Missing observations use `NaN`. Positive/negative infinity is rejected.

A model may create internal working copies but may not mutate a `ResearchDataset` or `FeatureWindow` in place.

### 4. ResearchDataset preserves the Phase 0.5 manifest

The existing fields remain stable:

```text
artifact
universe
features
labels
splits: Mapping[str, TimeRange]
point_in_time
metadata
```

Phase 1 adds:

```text
panels: Mapping[str, ResearchSplit]
```

and:

```python
dataset.get_split("train") -> ResearchSplit
```

This preserves compatibility with experiment fingerprints and schema-only datasets while allowing a DataAdapter to materialize numerical data.

### 5. Split semantics are half-open

`TimeRange(start, end)` means:

```text
[start, end)
```

A forward label is valid only if its target observation belongs to the same split. Labels crossing a train/validation/test boundary are emitted as `NaN` rather than leaking information across splits.

### 6. `available_at` is the research clock

`PriceBar.event_time` is the market event represented by the bar.

`PriceBar.available_at` is when that observation can actually be used.

The built-in Phase 1 adapters align numerical panels on `available_at`. `feature_window(asof=...)` may use only bars satisfying:

```text
available_at <= asof
```

This is the hard point-in-time rule.

### 7. Models receive FeatureWindow, not MarketSnapshot

The Phase 0.5 prediction interface was insufficient for AR/GARCH because one current bar cannot represent historical state.

The frozen Phase 1 model interfaces are:

```python
class AlphaModel(Protocol):
    @property
    def required_features(self) -> tuple[str, ...]: ...

    @property
    def min_lookback(self) -> int: ...

    def fit(self, dataset: ResearchDataset, split: str = "train") -> ArtifactRef: ...
    def predict(self, window: FeatureWindow) -> AlphaForecast: ...
```

and the equivalent `RiskModel` interface.

`MarketSnapshot` remains the execution/mark-to-market input. `FeatureWindow` is the model inference input. They are intentionally separate.

### 8. Public contracts do not use pandas

NumPy is now an intentional numerical dependency. pandas remains allowed inside future adapters/feature implementations, but a raw DataFrame is still prohibited as a cross-module public contract.

## Built-in Phase 1 feature naming

The current `InMemoryPriceDataAdapter` implements:

```text
close
volume
log_return_N
simple_return_N
squared_log_return_N
log_volume_change_N
```

and labels:

```text
forward_log_return_N
forward_simple_return_N
```

The naming scheme is an adapter capability, not a restriction on future FeatureStore/Factor adapters.

## Consequences

### Positive

- AR, ARMA, GARCH and covariance models share one deterministic numerical interface.
- Cross-sectional and time-series models can use the same panel layout.
- Missing data behavior is explicit.
- Data leakage controls are enforceable before model code runs.
- Qlib/pandas/Parquet adapters can be introduced without changing model contracts.

### Costs

- NumPy becomes a core dependency starting in Phase 1.
- Large datasets are currently materialized in memory; lazy/chunked storage is deferred.
- Asynchronous intraday feeds will require a more granular event/quote contract, but must adapt into the same `FeatureWindow` model interface.

## Change control

This contract is frozen for Phase 1. Any incompatible change to:

- tensor axis order;
- split semantics;
- `available_at` semantics;
- DataAdapter method signatures;
- AlphaModel/RiskModel fit/predict signatures;

requires a new ADR and regression tests demonstrating why the current contract is insufficient.
