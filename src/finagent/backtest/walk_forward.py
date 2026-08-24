from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from finagent.domain.assets import AssetId
from finagent.domain.research import DatasetRequest, ResearchDataset, TimeRange
from finagent.ports import DataAdapter

_FORWARD = re.compile(r"^forward_(?:log_return|simple_return)_(\d+)$")


def minimum_purge_bars(labels: tuple[str, ...]) -> int:
    """Infer the minimum chronological purge from canonical forward-return labels."""
    horizons: list[int] = []
    for label in labels:
        match = _FORWARD.fullmatch(label)
        if match:
            horizons.append(int(match.group(1)))
    return max(horizons, default=0)


@dataclass(frozen=True, slots=True)
class WalkForwardConfig:
    train_size: int
    test_size: int
    step_size: int | None = None
    purge_bars: int = 0
    embargo_bars: int = 0
    expanding_train: bool = False
    enforce_label_purge: bool = True

    def __post_init__(self) -> None:
        if self.train_size <= 0 or self.test_size <= 0:
            raise ValueError("train_size and test_size must be >= 1")
        step = self.test_size if self.step_size is None else self.step_size
        if step <= 0:
            raise ValueError("step_size must be >= 1")
        if self.purge_bars < 0 or self.embargo_bars < 0:
            raise ValueError("purge_bars and embargo_bars must be >= 0")
        object.__setattr__(self, "step_size", int(step))

    @property
    def pre_test_gap(self) -> int:
        """Strict forward-only gap between training and testing observations.

        In a chronological walk-forward there are no future observations in the
        training sample.  Phase 2 therefore implements embargo as an additional
        pre-test exclusion zone rather than the symmetric CV embargo used when
        train/test blocks can appear on both sides of one another.
        """
        return self.purge_bars + self.embargo_bars


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_index: int
    train: TimeRange
    test: TimeRange
    train_observations: int
    test_observations: int
    purge_bars: int
    embargo_bars: int


class PurgedWalkForwardSplitter:
    """Generate deterministic chronological train/test folds from an adapter calendar."""

    def __init__(self, config: WalkForwardConfig) -> None:
        self.config = config

    @staticmethod
    def _exclusive_end(calendar: tuple[datetime, ...], stop: int) -> datetime:
        if stop < len(calendar):
            return calendar[stop]
        return calendar[-1] + timedelta(microseconds=1)

    def split(
        self,
        calendar: tuple[datetime, ...],
        *,
        labels: tuple[str, ...] = (),
    ) -> tuple[WalkForwardFold, ...]:
        if not calendar:
            raise ValueError("calendar cannot be empty")
        if any(right <= left for left, right in zip(calendar, calendar[1:])):
            raise ValueError("calendar must be strictly increasing")
        required_purge = minimum_purge_bars(labels)
        if self.config.enforce_label_purge and self.config.purge_bars < required_purge:
            raise ValueError(
                f"purge_bars={self.config.purge_bars} is smaller than label horizon "
                f"requirement {required_purge}"
            )

        folds: list[WalkForwardFold] = []
        gap = self.config.pre_test_gap
        test_start = self.config.train_size + gap
        fold_index = 0
        while test_start + self.config.test_size <= len(calendar):
            train_end = test_start - gap
            train_start = 0 if self.config.expanding_train else train_end - self.config.train_size
            if train_start < 0:
                break
            test_end = test_start + self.config.test_size
            folds.append(
                WalkForwardFold(
                    fold_index=fold_index,
                    train=TimeRange(calendar[train_start], calendar[train_end]),
                    test=TimeRange(
                        calendar[test_start],
                        self._exclusive_end(calendar, test_end),
                    ),
                    train_observations=train_end - train_start,
                    test_observations=self.config.test_size,
                    purge_bars=self.config.purge_bars,
                    embargo_bars=self.config.embargo_bars,
                )
            )
            fold_index += 1
            test_start += int(self.config.step_size)
        if not folds:
            raise ValueError("walk-forward configuration produces no complete folds")
        return tuple(folds)

    def build_datasets(
        self,
        adapter: DataAdapter,
        *,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        labels: tuple[str, ...],
        start: datetime,
        end: datetime,
        dataset_id_prefix: str = "walk-forward",
    ) -> tuple[tuple[WalkForwardFold, ResearchDataset], ...]:
        calendar = adapter.calendar(start, end, universe)
        folds = self.split(calendar, labels=labels)
        results: list[tuple[WalkForwardFold, ResearchDataset]] = []
        for fold in folds:
            request = DatasetRequest(
                universe=universe,
                features=features,
                labels=labels,
                splits={"train": fold.train, "test": fold.test},
                dataset_id=f"{dataset_id_prefix}-fold-{fold.fold_index:03d}",
                metadata={
                    "walk_forward_fold": str(fold.fold_index),
                    "purge_bars": str(fold.purge_bars),
                    "embargo_bars": str(fold.embargo_bars),
                },
            )
            results.append((fold, adapter.build_dataset(request)))
        return tuple(results)


@dataclass(frozen=True, slots=True)
class NestedWalkForwardConfig:
    """Outer unbiased evaluation plus inner model-selection walk-forward."""

    outer: WalkForwardConfig
    inner: WalkForwardConfig


@dataclass(frozen=True, slots=True)
class NestedWalkForwardFold:
    outer_fold: WalkForwardFold
    inner_folds: tuple[WalkForwardFold, ...]

    def __post_init__(self) -> None:
        if not self.inner_folds:
            raise ValueError("nested fold must contain at least one inner fold")
        outer_train = self.outer_fold.train
        for fold in self.inner_folds:
            if fold.train.start < outer_train.start or fold.test.end > outer_train.end:
                raise ValueError("inner folds must remain entirely inside outer training range")


@dataclass(frozen=True, slots=True)
class NestedWalkForwardDatasets:
    fold: NestedWalkForwardFold
    outer_dataset: ResearchDataset
    inner_datasets: tuple[ResearchDataset, ...]


class NestedPurgedWalkForwardSplitter:
    """Create nested chronological folds without exposing outer test observations.

    Inner folds are generated exclusively from the chronological observations inside
    each outer training range.  Hyperparameter/model selection belongs to the inner
    folds; the corresponding outer test split is reserved for one final evaluation.
    """

    def __init__(self, config: NestedWalkForwardConfig) -> None:
        self.config = config
        self.outer_splitter = PurgedWalkForwardSplitter(config.outer)
        self.inner_splitter = PurgedWalkForwardSplitter(config.inner)

    @staticmethod
    def _calendar_in_range(
        calendar: tuple[datetime, ...],
        time_range: TimeRange,
    ) -> tuple[datetime, ...]:
        return tuple(ts for ts in calendar if time_range.contains(ts))

    def split(
        self,
        calendar: tuple[datetime, ...],
        *,
        labels: tuple[str, ...] = (),
    ) -> tuple[NestedWalkForwardFold, ...]:
        outer_folds = self.outer_splitter.split(calendar, labels=labels)
        nested: list[NestedWalkForwardFold] = []
        for outer in outer_folds:
            inner_calendar = self._calendar_in_range(calendar, outer.train)
            try:
                inner_folds = self.inner_splitter.split(inner_calendar, labels=labels)
            except ValueError as exc:
                raise ValueError(
                    f"outer fold {outer.fold_index} does not contain enough observations "
                    "for the configured inner walk-forward"
                ) from exc
            nested.append(NestedWalkForwardFold(outer_fold=outer, inner_folds=inner_folds))
        return tuple(nested)

    def build_datasets(
        self,
        adapter: DataAdapter,
        *,
        universe: tuple[AssetId, ...],
        features: tuple[str, ...],
        labels: tuple[str, ...],
        start: datetime,
        end: datetime,
        dataset_id_prefix: str = "nested-walk-forward",
    ) -> tuple[NestedWalkForwardDatasets, ...]:
        calendar = adapter.calendar(start, end, universe)
        nested_folds = self.split(calendar, labels=labels)
        output: list[NestedWalkForwardDatasets] = []
        for nested in nested_folds:
            outer = nested.outer_fold
            outer_request = DatasetRequest(
                universe=universe,
                features=features,
                labels=labels,
                splits={"train": outer.train, "test": outer.test},
                dataset_id=f"{dataset_id_prefix}-outer-{outer.fold_index:03d}",
                metadata={
                    "nested_role": "outer",
                    "outer_fold": str(outer.fold_index),
                    "purge_bars": str(outer.purge_bars),
                    "embargo_bars": str(outer.embargo_bars),
                },
            )
            outer_dataset = adapter.build_dataset(outer_request)
            inner_datasets: list[ResearchDataset] = []
            for inner in nested.inner_folds:
                inner_request = DatasetRequest(
                    universe=universe,
                    features=features,
                    labels=labels,
                    splits={"train": inner.train, "validation": inner.test},
                    dataset_id=(
                        f"{dataset_id_prefix}-outer-{outer.fold_index:03d}"
                        f"-inner-{inner.fold_index:03d}"
                    ),
                    metadata={
                        "nested_role": "inner",
                        "outer_fold": str(outer.fold_index),
                        "inner_fold": str(inner.fold_index),
                        "purge_bars": str(inner.purge_bars),
                        "embargo_bars": str(inner.embargo_bars),
                    },
                )
                inner_datasets.append(adapter.build_dataset(inner_request))
            output.append(
                NestedWalkForwardDatasets(
                    fold=nested,
                    outer_dataset=outer_dataset,
                    inner_datasets=tuple(inner_datasets),
                )
            )
        return tuple(output)
