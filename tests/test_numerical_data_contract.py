from datetime import timedelta

import numpy as np
import pytest

from finagent.domain.experiments import ArtifactRef, ArtifactType
from finagent.domain.research import FeatureWindow, ResearchDataset, ResearchSplit, TimeRange


def test_research_split_freezes_arrays(now, assets):
    features = np.zeros((3, 2, 1))
    labels = np.zeros((3, 2, 1))
    split = ResearchSplit(
        timestamps=(now, now + timedelta(days=1), now + timedelta(days=2)),
        assets=assets,
        feature_names=("r",),
        label_names=("y",),
        feature_values=features,
        label_values=labels,
    )
    features[0, 0, 0] = 99.0
    assert split.feature_values[0, 0, 0] == 0.0
    with pytest.raises(ValueError):
        split.feature_values[0, 0, 0] = 1.0


def test_feature_window_rejects_future_timestamp(now, assets):
    with pytest.raises(ValueError, match="later than asof"):
        FeatureWindow(
            asof=now,
            timestamps=(now + timedelta(seconds=1),),
            assets=assets,
            feature_names=("r",),
            values=np.zeros((1, 2, 1)),
            data_version="v1",
        )


def test_research_dataset_materialized_panel_must_match_schema(now, assets):
    artifact = ArtifactRef("d", ArtifactType.DATASET, "1", "a" * 64)
    split_range = TimeRange(now, now + timedelta(days=3))
    panel = ResearchSplit(
        timestamps=(now, now + timedelta(days=1)),
        assets=assets,
        feature_names=("x",),
        label_names=("y",),
        feature_values=np.zeros((2, 2, 1)),
        label_values=np.zeros((2, 2, 1)),
    )
    dataset = ResearchDataset(
        artifact=artifact,
        universe=assets,
        features=("x",),
        labels=("y",),
        splits={"train": split_range},
        panels={"train": panel},
    )
    assert dataset.is_materialized
    assert dataset.get_split("train") is panel
