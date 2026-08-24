from datetime import timedelta

import pytest

from finagent.backtest import PurgedWalkForwardSplitter, WalkForwardConfig
from tests.synthetic import make_phase1_adapter


def test_purged_walk_forward_generates_chronological_folds():
    adapter, dataset, assets, start = make_phase1_adapter(n=220, seed=31)
    splitter = PurgedWalkForwardSplitter(
        WalkForwardConfig(
            train_size=80,
            test_size=20,
            step_size=20,
            purge_bars=1,
            embargo_bars=2,
        )
    )
    calendar = adapter.calendar(start, start + timedelta(days=220), assets)
    folds = splitter.split(calendar, labels=dataset.labels)
    assert len(folds) == 6
    first = folds[0]
    assert first.train_observations == 80
    assert first.test_observations == 20
    assert first.train.end < first.test.start
    assert first.test.start == calendar[83]


def test_walk_forward_enforces_label_horizon_purge():
    adapter, dataset, assets, start = make_phase1_adapter(n=200, seed=32)
    splitter = PurgedWalkForwardSplitter(
        WalkForwardConfig(train_size=80, test_size=20, purge_bars=0)
    )
    calendar = adapter.calendar(start, start + timedelta(days=200), assets)
    with pytest.raises(ValueError, match="label horizon"):
        splitter.split(calendar, labels=dataset.labels)


def test_walk_forward_builds_isolated_fold_datasets():
    adapter, dataset, assets, start = make_phase1_adapter(n=200, seed=33)
    splitter = PurgedWalkForwardSplitter(
        WalkForwardConfig(
            train_size=80,
            test_size=20,
            purge_bars=1,
            embargo_bars=1,
            expanding_train=True,
        )
    )
    built = splitter.build_datasets(
        adapter,
        universe=assets,
        features=dataset.features,
        labels=dataset.labels,
        start=start,
        end=start + timedelta(days=200),
        dataset_id_prefix="wf-test",
    )
    assert built
    for fold, fold_dataset in built:
        train = fold_dataset.get_split("train")
        test = fold_dataset.get_split("test")
        assert train.timestamps[-1] < test.timestamps[0]
        assert fold_dataset.metadata["purge_bars"] == "1"
        assert fold_dataset.metadata["embargo_bars"] == "1"
        assert fold_dataset.artifact.artifact_id.startswith("wf-test-fold-")
