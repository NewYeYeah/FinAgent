from __future__ import annotations

from datetime import timedelta

from finagent.backtest.walk_forward import (
    NestedPurgedWalkForwardSplitter,
    NestedWalkForwardConfig,
    WalkForwardConfig,
)

from .synthetic import make_phase1_adapter


def test_nested_walk_forward_keeps_outer_test_out_of_inner_selection() -> None:
    adapter, _, assets, start = make_phase1_adapter(n=220, seed=31)
    end = start + timedelta(days=220)
    calendar = adapter.calendar(start, end, assets)
    splitter = NestedPurgedWalkForwardSplitter(
        NestedWalkForwardConfig(
            outer=WalkForwardConfig(
                train_size=90,
                test_size=20,
                step_size=20,
                purge_bars=1,
                embargo_bars=1,
            ),
            inner=WalkForwardConfig(
                train_size=40,
                test_size=10,
                step_size=10,
                purge_bars=1,
                embargo_bars=1,
            ),
        )
    )
    folds = splitter.split(calendar, labels=("forward_log_return_1",))
    assert folds
    for nested in folds:
        outer = nested.outer_fold
        for inner in nested.inner_folds:
            assert inner.train.start >= outer.train.start
            assert inner.test.end <= outer.train.end
            assert inner.test.end <= outer.test.start


def test_nested_dataset_builder_labels_inner_holdout_as_validation() -> None:
    adapter, _, assets, start = make_phase1_adapter(n=200, seed=32)
    splitter = NestedPurgedWalkForwardSplitter(
        NestedWalkForwardConfig(
            outer=WalkForwardConfig(80, 20, 20, purge_bars=1),
            inner=WalkForwardConfig(35, 10, 10, purge_bars=1),
        )
    )
    built = splitter.build_datasets(
        adapter,
        universe=assets,
        features=("log_return_1",),
        labels=("forward_log_return_1",),
        start=start,
        end=start + timedelta(days=200),
    )
    assert built
    first = built[0]
    assert set(first.outer_dataset.splits) == {"train", "test"}
    assert first.inner_datasets
    assert all(set(dataset.splits) == {"train", "validation"} for dataset in first.inner_datasets)
    assert all(dataset.metadata["nested_role"] == "inner" for dataset in first.inner_datasets)
