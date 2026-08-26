from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
)
from finagent.data import InMemoryPriceDataAdapter
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.market import PriceBar
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research import (
    AgentFactorDiscoveryConfig,
    AgentFactorDiscoveryLoop,
    FactorAgentFeedback,
    FactorCandidateDiagnostics,
    FactorDevelopmentAnalyzer,
    FactorFamilyDiagnostics,
    FeedbackAwareMarketFeatureCandidateGenerator,
    GeneratedFeatureEvaluationConfig,
)


NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _artifact(
    feature_id: str,
    source: str,
    *,
    hypothesis: str,
    input_fields: tuple[str, ...] = ("simple_return_1",),
    lookback: int = 3,
) -> GeneratedFeatureArtifact:
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id=feature_id,
            name=feature_id,
            description=f"diagnostic feature {feature_id}",
            hypothesis=hypothesis,
            input_fields=input_fields,
            lookback=lookback,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=NOW,
        generator_id="unit-test",
        smoke_output_digest=f"smoke-{feature_id}",
    )


def _adapter(days: int = 42):
    assets = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM")
    )
    start = datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    histories = {}
    for asset_index, asset in enumerate(assets):
        price = 100.0 + 9.0 * asset_index
        bars = []
        for day in range(days):
            event_time = start + timedelta(days=day)
            return_component = (
                0.0004 * (asset_index + 1)
                + 0.0030 * np.sin((day + 2.0 * asset_index) / 4.0)
            )
            price *= 1.0 + return_component
            volume = 1_500_000.0 * (
                1.0 + 0.08 * np.cos((day + asset_index) / 5.0)
            )
            bars.append(
                PriceBar(
                    event_time=event_time,
                    available_at=event_time + timedelta(hours=6, minutes=30),
                    open=price * 0.999,
                    high=price * 1.004,
                    low=price * 0.996,
                    close=price,
                    volume=volume,
                )
            )
        histories[asset] = tuple(bars)
    return InMemoryPriceDataAdapter(histories, data_version="factor-dev-v1"), assets, start


def _development_request(adapter, universe, start) -> DatasetRequest:
    available_start = start + timedelta(hours=6, minutes=30)
    return DatasetRequest(
        universe=universe,
        features=("simple_return_1", "log_volume_change_1"),
        labels=("forward_simple_return_1",),
        splits={
            "development": TimeRange(
                available_start + timedelta(days=8),
                available_start + timedelta(days=36),
            )
        },
        dataset_id="factor-development",
        metadata={"purpose": "agent-factor-discovery"},
    )


def test_factor_development_analyzer_reports_quant_diagnostics_and_redundancy() -> None:
    adapter, universe, start = _adapter()
    request = _development_request(adapter, universe, start)
    momentum = _artifact(
        "momentum",
        'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
        hypothesis="one-day continuation",
    )
    reversal = _artifact(
        "reversal",
        'def compute_feature(inputs):\n    return [-x for x in inputs["simple_return_1"]]\n',
        hypothesis="one-day reversal",
    )
    analyzer = FactorDevelopmentAnalyzer(
        adapter,
        config=GeneratedFeatureEvaluationConfig(
            split_name="development",
            label_name="forward_simple_return_1",
            transaction_cost_bps=1.0,
            min_cross_section=2,
            min_periods=8,
        ),
    )

    report = analyzer.analyze((momentum, reversal), request=request, round_index=1)

    assert report.round_index == 1
    assert report.data_version == adapter.data_version
    assert report.development_data_id.startswith("factor-dev-")
    assert len(report.candidates) == 2
    for candidate in report.candidates:
        assert {
            "mean_ic",
            "icir",
            "net_sharpe",
            "mean_one_way_turnover",
            "coverage",
            "evaluated_periods",
        }.issubset(candidate.metrics)
        assert 0.0 <= candidate.metrics["coverage"] <= 1.0
        assert candidate.metrics["evaluated_periods"] >= 8
        assert 0.0 <= candidate.pvalue <= 1.0
    assert len(report.net_return_correlations) == 1
    correlation = next(iter(report.net_return_correlations.values()))
    assert -1.0 <= correlation <= 1.0
    assert report.best_feature_digest in {momentum.digest, reversal.digest}


def test_agent_feedback_contains_development_factor_metrics_only() -> None:
    candidate = FactorCandidateDiagnostics(
        feature_id="factor-a",
        feature_digest="a" * 64,
        hypothesis="momentum after volume confirmation",
        description="test candidate",
        lookback=20,
        input_fields=("simple_return_1",),
        metrics={
            "mean_ic": 0.04,
            "icir": 0.30,
            "annualized_icir": 4.76,
            "mean_net_return": 0.0005,
            "net_sharpe": 1.1,
            "mean_one_way_turnover": 0.35,
            "mean_gross_traded_weight": 0.70,
            "coverage": 0.98,
            "evaluated_periods": 100.0,
            "ic_periods": 95.0,
            # Even if a future diagnostics implementation carries extra metrics,
            # the Agent feedback contract exposes only the explicit whitelist.
            "internal_debug_metric": 123.0,
        },
        pvalue=0.02,
    )
    diagnostics = FactorFamilyDiagnostics(
        round_index=1,
        development_data_id="factor-dev-test",
        data_version="v1",
        split_name="development",
        selection_metric="net_sharpe",
        candidates=(candidate,),
        net_return_correlations={},
        best_feature_digest=candidate.feature_digest,
    )

    feedback = FactorAgentFeedback.from_diagnostics(diagnostics)
    payload = feedback.to_dict()
    encoded = feedback.to_json().lower()

    exposed = payload["candidates"][0]["metrics"]
    assert "internal_debug_metric" not in exposed
    assert exposed["mean_ic"] == 0.04
    assert exposed["net_sharpe"] == 1.1
    assert "outer" not in encoded
    assert "holdout" in encoded  # only the explicit statement that holdout evidence is absent
    assert "paper evidence" in encoded
    assert "gross_returns" not in encoded
    assert "net_returns" not in encoded


class _ScriptedCandidateGenerator:
    def __init__(self, batches):
        self.batches = list(batches)
        self.tasks: list[AgentTask] = []

    def generate(self, *, task, count, approved_input_fields, smoke_inputs):
        self.tasks.append(task)
        batch = self.batches.pop(0)
        assert len(batch) == count
        assert tuple(approved_input_fields) == ("simple_return_1",)
        assert set(smoke_inputs) == {"simple_return_1"}
        return batch


class _FastAnalyzer:
    def __init__(self, data_version: str = "dev-v1") -> None:
        self.adapter = type("Adapter", (), {"data_version": data_version})()
        self.selection_metric = "net_sharpe"

    def analyze(self, candidates, *, request, round_index):
        diagnostics = tuple(
            FactorCandidateDiagnostics(
                feature_id=artifact.spec.feature_id,
                feature_digest=artifact.digest,
                hypothesis=artifact.spec.hypothesis,
                description=artifact.spec.description,
                lookback=artifact.spec.lookback,
                input_fields=artifact.spec.input_fields,
                metrics={
                    "mean_ic": 0.01 * (index + round_index),
                    "icir": 0.20 + 0.05 * index,
                    "annualized_icir": 3.0 + index,
                    "mean_net_return": 0.0002 * (index + 1),
                    "net_sharpe": 0.5 + 0.4 * index + 0.1 * round_index,
                    "mean_one_way_turnover": 0.20 + 0.10 * index,
                    "mean_gross_traded_weight": 0.40 + 0.20 * index,
                    "coverage": 0.95,
                    "evaluated_periods": 50.0,
                    "ic_periods": 45.0,
                },
                pvalue=0.05 + 0.01 * index,
            )
            for index, artifact in enumerate(candidates)
        )
        best = max(diagnostics, key=lambda item: item.metrics["net_sharpe"])
        return FactorFamilyDiagnostics(
            round_index=round_index,
            development_data_id="factor-dev-loop",
            data_version=self.adapter.data_version,
            split_name="development",
            selection_metric="net_sharpe",
            candidates=diagnostics,
            net_return_correlations={},
            best_feature_digest=best.feature_digest,
        )


def test_discovery_loop_feeds_quant_feedback_into_next_agent_round() -> None:
    first = (
        _artifact(
            "round1-a",
            'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n',
            hypothesis="continuation",
        ),
        _artifact(
            "round1-b",
            'def compute_feature(inputs):\n    return [-x for x in inputs["simple_return_1"]]\n',
            hypothesis="reversal",
        ),
    )
    second = (
        _artifact(
            "round2-a",
            'def compute_feature(inputs):\n    return [x * 0.5 for x in inputs["simple_return_1"]]\n',
            hypothesis="scaled continuation",
        ),
        _artifact(
            "round2-b",
            'def compute_feature(inputs):\n    return [x * -0.5 for x in inputs["simple_return_1"]]\n',
            hypothesis="scaled reversal",
        ),
    )
    scripted = _ScriptedCandidateGenerator((first, second))
    generator = FeedbackAwareMarketFeatureCandidateGenerator(scripted)
    loop = AgentFactorDiscoveryLoop(
        generator=generator,
        analyzer=_FastAnalyzer(),
        config=AgentFactorDiscoveryConfig(rounds=2, candidates_per_round=2, max_total_candidates=4),
    )
    adapter, universe, start = _adapter()
    request = _development_request(adapter, universe, start)
    task = AgentTask(
        task_id="factor-loop",
        objective="Find interpretable short-horizon ETF factors.",
        created_at=NOW,
        metadata={"market": "us_equity"},
    )

    result = loop.run(
        task=task,
        request=request,
        approved_input_fields=("simple_return_1",),
        smoke_inputs={"simple_return_1": [0.01, -0.02, 0.03]},
    )

    assert len(result.rounds) == 2
    assert len(result.candidates) == 4
    assert len({artifact.digest for artifact in result.candidates}) == 4
    assert result.development_data_id == "factor-dev-loop"
    assert "DEVELOPMENT-ONLY QUANTITATIVE FACTOR FEEDBACK" not in scripted.tasks[0].objective
    assert "DEVELOPMENT-ONLY QUANTITATIVE FACTOR FEEDBACK" in scripted.tasks[1].objective
    assert result.rounds[0].feedback.feedback_id in scripted.tasks[1].metadata["factor_feedback_id"]
    assert "net_sharpe" in scripted.tasks[1].objective
    assert "mean_ic" in scripted.tasks[1].objective
    assert result.final_feedback.round_index == 2
    assert result.to_dict()["scope"].startswith("adaptive development-only")


def test_discovery_config_caps_adaptive_search_budget() -> None:
    try:
        AgentFactorDiscoveryConfig(rounds=3, candidates_per_round=4, max_total_candidates=8)
    except ValueError as exc:
        assert "exceeds max_total_candidates" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected adaptive factor search budget validation")
