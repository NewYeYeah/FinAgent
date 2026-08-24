from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np

from finagent.agents import (
    FeatureCodeValidator,
    FeatureSpec,
    FeatureValidationReport,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.backtest import NestedPurgedWalkForwardSplitter, NestedWalkForwardConfig, WalkForwardConfig
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research import (
    GeneratedFeatureEvaluationConfig,
    GeneratedFeatureEvaluator,
    GeneratedFeatureFamilyValidationInputProvider,
    GeneratedFeatureMaterializer,
    GeneratedFeatureNestedWalkForwardStudy,
    SQLiteGeneratedFeatureResearchStore,
    evaluate_generated_feature_dataset,
)
from finagent.sandbox import FeatureSandboxResult, LocalFeatureSandbox

UTC = timezone.utc


class FastSandbox:
    def run(self, request):
        values = tuple(request.inputs[request.spec.input_fields[0]])
        return FeatureSandboxResult(values)


def _assets():
    return tuple(
        AssetId(symbol, AssetType.EQUITY, venue="TEST", currency="USD")
        for symbol in ("AAA", "BBB", "CCC")
    )


def _adapter(n=50, *, future_multiplier=1.0):
    assets = _assets()
    start = datetime(2026, 1, 1, 16, 0, tzinfo=UTC)
    histories = {}
    drifts = (0.004, 0.001, -0.002)
    for asset, drift in zip(assets, drifts):
        price = 100.0
        bars = []
        for index in range(n):
            ts = start + timedelta(days=index)
            previous = price
            ret = drift + 0.0002 * np.sin(index / 3)
            if index > 30:
                ret *= future_multiplier
            price = price * (1.0 + ret)
            bars.append(
                PriceBar(
                    event_time=ts,
                    available_at=ts,
                    open=previous,
                    high=max(previous, price) * 1.001,
                    low=min(previous, price) * 0.999,
                    close=price,
                    volume=1_000_000 + index * 1000,
                )
            )
        histories[asset] = bars
    return InMemoryPriceDataAdapter(histories, data_version=f"phase35-{future_multiplier}"), assets, start


def _artifact(field="simple_return_1", lookback=2, source=None):
    source = source or 'def compute_feature(inputs):\n    return [v for v in inputs["simple_return_1"]]\n'
    validation = FeatureCodeValidator().validate(source)
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id="generated-momentum",
            name="Generated Momentum",
            description="Use recent return as a cross-sectional signal",
            hypothesis="Recent relative strength persists one period",
            input_fields=(field,),
            lookback=lookback,
        ),
        source=source,
        validation=validation,
        generated_at=datetime(2026, 8, 25, tzinfo=UTC),
        generator_id="test-generator",
        smoke_output_digest="abc123",
    )


def _request(assets, start):
    return DatasetRequest(
        universe=assets,
        features=("simple_return_1",),
        labels=("forward_simple_return_1",),
        splits={
            "train": TimeRange(start, start + timedelta(days=25)),
            "test": TimeRange(start + timedelta(days=25), start + timedelta(days=45)),
        },
        dataset_id="phase35-generated",
    )


def test_materializer_produces_pit_generated_dataset_and_lineage():
    adapter, assets, start = _adapter()
    artifact = _artifact()
    dataset = GeneratedFeatureMaterializer(adapter, sandbox=FastSandbox()).materialize(
        artifact, _request(assets, start)
    )
    assert dataset.point_in_time
    assert dataset.features == ("generated:generated-momentum",)
    assert dataset.metadata["generated_feature_digest"] == artifact.digest
    assert dataset.metadata["source_dataset_digest"]
    panel = dataset.get_split("test")
    assert panel.feature_values.flags.writeable is False
    assert np.isfinite(panel.feature_values[:, :, 0]).sum() > 20


def test_window_materialization_prevents_future_panel_access():
    source = 'def compute_feature(inputs):\n    return [inputs["close"][-1] for _ in inputs["close"]]\n'
    artifact = _artifact(field="close", lookback=3, source=source)
    left, assets, start = _adapter(future_multiplier=1.0)
    right, _, _ = _adapter(future_multiplier=5.0)
    request = DatasetRequest(
        universe=(assets[0],),
        features=("close",),
        labels=("forward_simple_return_1",),
        splits={"test": TimeRange(start + timedelta(days=20), start + timedelta(days=40))},
        dataset_id="causality-check",
    )
    left_ds = GeneratedFeatureMaterializer(left, sandbox=LocalFeatureSandbox()).materialize(artifact, request)
    right_ds = GeneratedFeatureMaterializer(right, sandbox=LocalFeatureSandbox()).materialize(artifact, request)
    left_panel = left_ds.get_split("test")
    right_panel = right_ds.get_split("test")
    cutoff = start + timedelta(days=30)
    rows = [i for i, ts in enumerate(left_panel.timestamps) if ts <= cutoff]
    assert np.allclose(
        left_panel.feature_values[rows, 0, 0],
        right_panel.feature_values[rows, 0, 0],
        equal_nan=True,
    )


def test_real_feature_evaluation_reports_ic_turnover_net_return_and_pvalue():
    adapter, assets, start = _adapter()
    artifact = _artifact()
    dataset = GeneratedFeatureMaterializer(adapter, sandbox=FastSandbox()).materialize(
        artifact, _request(assets, start)
    )
    trace = evaluate_generated_feature_dataset(
        dataset,
        feature_digest=artifact.digest,
        config=GeneratedFeatureEvaluationConfig(min_periods=5, transaction_cost_bps=10.0),
    )
    assert trace.metrics["mean_ic"] > 0.5
    assert trace.metrics["mean_turnover"] >= 0.0
    assert trace.metrics["evaluated_periods"] >= 5
    assert 0.0 <= trace.pvalue <= 1.0
    assert len(trace.net_returns) == len(trace.timestamps)


def test_evaluator_persists_real_return_trace_for_family_validation(tmp_path):
    adapter, assets, start = _adapter()
    artifact = _artifact()
    feature_store = SQLiteGeneratedFeatureStore(tmp_path / "state.db")
    feature_store.register(artifact)
    evidence_store = SQLiteGeneratedFeatureResearchStore(tmp_path / "state.db")
    evaluator = GeneratedFeatureEvaluator(
        adapter=adapter,
        feature_store=feature_store,
        dataset_request=_request(assets, start),
        research_store=evidence_store,
        sandbox=FastSandbox(),
        config=GeneratedFeatureEvaluationConfig(min_periods=5),
    )
    from finagent.domain.experiments import ExperimentSpec
    spec = ExperimentSpec(
        experiment_id="exp-generated",
        hypothesis=artifact.spec.hypothesis,
        dataset=adapter.build_dataset(_request(assets, start)).artifact,
        code=artifact.code_artifact_ref(),
        universe=assets,
        parameters={},
        seed=7,
        metadata={"generated_feature_digest": artifact.digest},
    )
    result = evaluator(spec)
    assert result.passed
    assert result.metrics["evaluated_periods"] >= 5
    persisted = evidence_store.get("exp-generated")
    assert persisted.feature_digest == artifact.digest
    assert persisted.net_returns

    registry = SimpleNamespace(
        family_members=lambda family_id: (SimpleNamespace(experiment_id="exp-generated"),)
    )
    inputs = GeneratedFeatureFamilyValidationInputProvider(registry, evidence_store)("family-generated")
    assert set(inputs.trial_returns) == {"exp-generated"}
    assert set(inputs.pvalues) == {"exp-generated"}


def test_generated_feature_runs_through_nested_purged_walk_forward():
    adapter, assets, start = _adapter(n=55)
    artifact = _artifact()
    splitter = NestedPurgedWalkForwardSplitter(
        NestedWalkForwardConfig(
            outer=WalkForwardConfig(train_size=28, test_size=6, step_size=6, purge_bars=1),
            inner=WalkForwardConfig(train_size=10, test_size=5, step_size=5, purge_bars=1),
        )
    )
    study = GeneratedFeatureNestedWalkForwardStudy(
        adapter=adapter,
        splitter=splitter,
        sandbox=FastSandbox(),
        config=GeneratedFeatureEvaluationConfig(min_periods=3, transaction_cost_bps=5.0),
    )
    result = study.run(
        artifact,
        universe=assets,
        start=start,
        end=start + timedelta(days=55),
    )
    assert result.folds
    assert all(fold.inner_validation for fold in result.folds)
    assert result.outer_net_returns
