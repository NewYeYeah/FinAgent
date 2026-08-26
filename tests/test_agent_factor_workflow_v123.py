from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from finagent.agents.domain import AgentTask
from finagent.agents.generated_features import FeatureCodeValidator, FeatureSpec, GeneratedFeatureArtifact
from finagent.domain.assets import AssetId, AssetType
from finagent.domain.research import DatasetRequest, TimeRange
from finagent.research import (
    AgentFactorResearchWorkflow,
    AgentMarketCandidate,
    AgentMarketResearchResult,
)


NOW = datetime(2026, 8, 26, 6, 0, tzinfo=UTC)


def _artifact(feature_id: str, multiplier: float) -> GeneratedFeatureArtifact:
    source = (
        "def compute_feature(inputs):\n"
        f"    return [x * {multiplier!r} for x in inputs[\"simple_return_1\"]]\n"
    )
    validator = FeatureCodeValidator()
    return GeneratedFeatureArtifact(
        spec=FeatureSpec(
            feature_id=feature_id,
            name=feature_id,
            description=f"candidate {feature_id}",
            hypothesis=f"scaled short-horizon return signal {multiplier}",
            input_fields=("simple_return_1",),
            lookback=3,
        ),
        source=source,
        validation=validator.validate(source),
        generated_at=NOW,
        generator_id="workflow-test",
        smoke_output_digest=f"smoke-{feature_id}",
    )


class _DiscoveryResult:
    def __init__(self, candidates) -> None:
        self.candidates = tuple(candidates)
        self.development_data_id = "factor-dev-workflow"
        self.discovery_id = "factor-discovery-workflow-001"


class _DiscoveryLoop:
    def __init__(self, candidates, *, data_version: str = "snapshot-v1") -> None:
        self._result = _DiscoveryResult(candidates)
        self.calls = 0
        self.analyzer = SimpleNamespace(
            adapter=SimpleNamespace(data_version=data_version),
            config=SimpleNamespace(
                label_name="forward_simple_return_1",
                split_name="development",
            ),
        )

    def run(self, **kwargs):
        self.calls += 1
        return self._result


class _ValidationRunner:
    def __init__(self, *, data_version: str = "snapshot-v1", drop_last: bool = False) -> None:
        self.adapter = SimpleNamespace(data_version=data_version)
        self.config = SimpleNamespace(
            label_name="forward_simple_return_1",
            max_candidates=8,
        )
        self.drop_last = drop_last
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        candidates = tuple(kwargs["candidates"])
        if self.drop_last:
            candidates = candidates[:-1]
        return AgentMarketResearchResult(
            study_id="validation-study-001",
            task_id=kwargs["task"].task_id,
            program_id=kwargs["program_id"],
            family_id=kwargs["family_id"],
            provider="synthetic",
            data_version=self.adapter.data_version,
            universe=tuple(asset.key for asset in kwargs["universe"]),
            candidates=tuple(AgentMarketCandidate.from_artifact(item) for item in candidates),
            folds=(),
            aggregate_portfolio_metrics={"sharpe": 1.0},
            promotion_eligible_folds=0,
        )


def _inputs(*, validation_start_offset: int = 20):
    universe = tuple(
        AssetId(symbol, AssetType.ETF, venue="ARCX", currency="USD")
        for symbol in ("SPY", "QQQ", "IWM")
    )
    development_start = datetime(2025, 1, 2, tzinfo=UTC)
    development_end = development_start + timedelta(days=20)
    validation_start = development_start + timedelta(days=validation_start_offset)
    validation_end = validation_start + timedelta(days=60)
    request = DatasetRequest(
        universe=universe,
        features=("simple_return_1", "log_volume_change_1"),
        labels=("forward_simple_return_1",),
        splits={"development": TimeRange(development_start, development_end)},
        dataset_id="development-request",
    )
    task = AgentTask(
        task_id="agent-factor-workflow",
        objective="Discover and validate interpretable short-horizon ETF factors.",
        created_at=NOW,
        metadata={"market": "us_equity"},
    )
    return universe, request, task, development_end, validation_start, validation_end


def test_workflow_passes_complete_adaptive_search_to_formal_validation() -> None:
    candidates = (_artifact("factor-a", 1.0), _artifact("factor-b", -1.0))
    discovery = _DiscoveryLoop(candidates)
    validation = _ValidationRunner()
    workflow = AgentFactorResearchWorkflow(
        discovery_loop=discovery,
        validation_runner=validation,
    )
    universe, request, task, development_end, validation_start, validation_end = _inputs()

    result = workflow.run(
        task=task,
        development_request=request,
        approved_input_fields=("simple_return_1",),
        smoke_inputs={"simple_return_1": [0.01, -0.02, 0.03]},
        validation_universe=universe,
        validation_start=validation_start,
        validation_end=validation_end,
        program_id="program-factor-001",
        family_id="family-factor-001",
    )

    assert discovery.calls == 1
    assert len(validation.calls) == 1
    call = validation.calls[0]
    assert tuple(item.digest for item in call["candidates"]) == tuple(
        item.digest for item in candidates
    )
    assert call["start"] == validation_start
    assert call["end"] == validation_end
    assert call["task"].metadata["factor_discovery_id"] == result.discovery.discovery_id
    assert call["task"].metadata["development_end"] == development_end.isoformat()
    assert result.development_end == validation_start
    assert result.validation.family_id == "family-factor-001"
    assert result.workflow_id.startswith("agent-factor-workflow-")
    assert result.to_dict()["candidate_digests"] == [item.digest for item in candidates]


def test_workflow_rejects_development_validation_overlap_before_agent_search() -> None:
    candidates = (_artifact("factor-a", 1.0), _artifact("factor-b", -1.0))
    discovery = _DiscoveryLoop(candidates)
    validation = _ValidationRunner()
    workflow = AgentFactorResearchWorkflow(
        discovery_loop=discovery,
        validation_runner=validation,
    )
    universe, request, task, _, validation_start, validation_end = _inputs(
        validation_start_offset=19
    )

    with pytest.raises(ValueError, match="development must end"):
        workflow.run(
            task=task,
            development_request=request,
            approved_input_fields=("simple_return_1",),
            smoke_inputs={"simple_return_1": [0.01, -0.02, 0.03]},
            validation_universe=universe,
            validation_start=validation_start,
            validation_end=validation_end,
            program_id="program-factor-001",
            family_id="family-factor-001",
        )

    assert discovery.calls == 0
    assert validation.calls == []


def test_workflow_detects_formal_validation_denominator_drift() -> None:
    candidates = (_artifact("factor-a", 1.0), _artifact("factor-b", -1.0))
    workflow = AgentFactorResearchWorkflow(
        discovery_loop=_DiscoveryLoop(candidates),
        validation_runner=_ValidationRunner(drop_last=True),
    )
    universe, request, task, _, validation_start, validation_end = _inputs()

    with pytest.raises(ValueError, match="denominator differs"):
        workflow.run(
            task=task,
            development_request=request,
            approved_input_fields=("simple_return_1",),
            smoke_inputs={"simple_return_1": [0.01, -0.02, 0.03]},
            validation_universe=universe,
            validation_start=validation_start,
            validation_end=validation_end,
            program_id="program-factor-001",
            family_id="family-factor-001",
        )


def test_workflow_requires_same_data_version_for_discovery_and_validation() -> None:
    candidates = (_artifact("factor-a", 1.0), _artifact("factor-b", -1.0))
    discovery = _DiscoveryLoop(candidates, data_version="development-v1")
    validation = _ValidationRunner(data_version="validation-v2")
    workflow = AgentFactorResearchWorkflow(
        discovery_loop=discovery,
        validation_runner=validation,
    )
    universe, request, task, _, validation_start, validation_end = _inputs()

    with pytest.raises(ValueError, match="data versions differ"):
        workflow.run(
            task=task,
            development_request=request,
            approved_input_fields=("simple_return_1",),
            smoke_inputs={"simple_return_1": [0.01, -0.02, 0.03]},
            validation_universe=universe,
            validation_start=validation_start,
            validation_end=validation_end,
            program_id="program-factor-001",
            family_id="family-factor-001",
        )

    assert discovery.calls == 0
