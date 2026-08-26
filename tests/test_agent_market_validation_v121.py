from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.agents.generated_features import (
    FeatureCodeValidator,
    FeatureSpec,
    GeneratedFeatureArtifact,
    SQLiteGeneratedFeatureStore,
)
from finagent.data.ingestion.diff import ProviderDiffReport
from finagent.research import (
    AgentMarketCandidate,
    AgentMarketFoldResult,
    AgentMarketResearchResult,
    AgentMarketValidationPolicy,
    ResearchProgram,
    SQLiteAgentMarketValidationStore,
    SQLiteResearchProgramStore,
    agent_market_result_from_dict,
    frozen_feature_family,
    read_agent_market_result,
    validate_agent_market_results,
)
from finagent.sandbox import FeatureSandboxRequest, LocalFeatureSandbox


def _candidate(feature_id: str, digest: str) -> AgentMarketCandidate:
    return AgentMarketCandidate(
        feature_id=feature_id,
        feature_digest=digest,
        hypothesis=f"hypothesis {feature_id}",
        description=f"description {feature_id}",
        lookback=3,
        input_fields=("simple_return_1",),
    )


def _fold(
    index: int,
    selected: AgentMarketCandidate,
    *,
    accepted: bool = True,
    sharpe: float = 1.0,
) -> AgentMarketFoldResult:
    candidates = {"digest-a": 0.4, "digest-b": 0.2}
    return AgentMarketFoldResult(
        outer_fold_index=index,
        selected_feature_id=selected.feature_id,
        selected_feature_digest=selected.feature_digest,
        statistically_accepted=accepted,
        inner_mean_scores=candidates,
        inner_raw_pvalues={"digest-a": 0.01, "digest-b": 0.20},
        inner_adjusted_pvalues={"digest-a": 0.02, "digest-b": 0.20},
        signal_outer_metrics={"net_sharpe": sharpe},
        portfolio_outer_metrics={"sharpe": sharpe, "total_return": 0.05 * sharpe},
        outer_start=f"2025-0{index + 1}-01T00:00:00+00:00",
        outer_end=f"2025-0{index + 2}-01T00:00:00+00:00",
    )


def _result(
    *,
    study_id: str = "study-left",
    provider: str = "alpaca",
    data_version: str = "alpaca-v1",
    sharpe: float = 1.0,
    second_selected: str = "a",
) -> AgentMarketResearchResult:
    a = _candidate("feature-a", "digest-a")
    b = _candidate("feature-b", "digest-b")
    second = a if second_selected == "a" else b
    return AgentMarketResearchResult(
        study_id=study_id,
        task_id="task-us-etf",
        program_id="program-us-etf",
        family_id="family-us-etf-001",
        provider=provider,
        data_version=data_version,
        universe=(
            "etf:ARCX:DIA:USD",
            "etf:ARCX:IWM:USD",
            "etf:XNAS:QQQ:USD",
            "etf:ARCX:SPY:USD",
        ),
        candidates=(a, b),
        folds=(
            _fold(0, a, accepted=True, sharpe=sharpe),
            _fold(1, second, accepted=False, sharpe=sharpe),
        ),
        aggregate_portfolio_metrics={
            "oos_periods": 20.0,
            "sharpe": sharpe,
            "total_return": 0.10 * sharpe,
        },
        promotion_eligible_folds=1,
    )


def _provider_diff(*, calendar_match: bool = True) -> ProviderDiffReport:
    return ProviderDiffReport(
        left_provider="alpaca",
        right_provider="akshare",
        common_rows=100,
        missing_left=() if calendar_match else ("etf:ARCX:SPY:USD@2025-01-03",),
        missing_right=(),
        max_close_abs_error=0.01,
        max_close_rel_error=0.0001,
        max_volume_rel_error=0.01,
    )


def _artifact() -> GeneratedFeatureArtifact:
    source = 'def compute_feature(inputs):\n    return inputs["simple_return_1"]\n'
    spec = FeatureSpec(
        feature_id="frozen-feature",
        name="Frozen feature",
        description="immutable replay fixture",
        hypothesis="one-day continuation",
        input_fields=("simple_return_1",),
        lookback=3,
    )
    validator = FeatureCodeValidator()
    validation = validator.validate(source)
    smoke = LocalFeatureSandbox(validator=validator).run(
        FeatureSandboxRequest(spec, source, {"simple_return_1": [0.1, 0.2, 0.3]})
    )
    return GeneratedFeatureArtifact(
        spec=spec,
        source=source,
        validation=validation,
        generated_at=datetime(2026, 8, 26, tzinfo=UTC),
        generator_id="unit-test",
        smoke_output_digest=smoke.output_digest,
    )


def test_result_parser_roundtrip_and_exact_replay(tmp_path: Path) -> None:
    left = _result()
    path = tmp_path / "result.json"
    path.write_text(json.dumps(left.to_dict()), encoding="utf-8")
    right = read_agent_market_result(path)
    assert right.to_dict() == left.to_dict()
    assert agent_market_result_from_dict(left.to_dict()).to_dict() == left.to_dict()

    report = validate_agent_market_results(
        left,
        right,
        policy=AgentMarketValidationPolicy.replay(),
    )
    assert report.passed
    assert report.exact_payload_match
    assert report.selection_agreement == 1.0


def test_exact_replay_fails_on_metric_drift() -> None:
    report = validate_agent_market_results(
        _result(sharpe=1.0),
        _result(sharpe=1.01),
        policy=AgentMarketValidationPolicy.replay(),
    )
    assert not report.passed
    assert any("payload differs" in value for value in report.policy_violations)


def test_cross_provider_defaults_to_structural_evidence_not_arbitrary_financial_gate() -> None:
    left = _result(sharpe=1.0)
    right = _result(
        study_id="study-right",
        provider="akshare",
        data_version="akshare-v1",
        sharpe=0.2,
        second_selected="b",
    )
    report = validate_agent_market_results(
        left,
        right,
        policy=AgentMarketValidationPolicy.cross_provider(),
        provider_diff=_provider_diff(),
    )
    assert report.passed
    assert not report.exact_payload_match
    assert report.selection_agreement == pytest.approx(0.5)
    assert report.aggregate_abs_differences["sharpe"] == pytest.approx(0.8)


def test_cross_provider_optional_pre_registered_metric_limit_catches_drift() -> None:
    report = validate_agent_market_results(
        _result(sharpe=1.0),
        _result(
            study_id="study-right",
            provider="akshare",
            data_version="akshare-v1",
            sharpe=0.7,
        ),
        policy=AgentMarketValidationPolicy.cross_provider(
            aggregate_abs_limits={"sharpe": 0.1}
        ),
        provider_diff=_provider_diff(),
    )
    assert not report.passed
    assert any("sharpe" in value for value in report.policy_violations)


def test_cross_provider_requires_exact_normalized_calendar_evidence() -> None:
    report = validate_agent_market_results(
        _result(),
        _result(
            study_id="study-right",
            provider="akshare",
            data_version="akshare-v1",
        ),
        policy=AgentMarketValidationPolicy.cross_provider(),
        provider_diff=_provider_diff(calendar_match=False),
    )
    assert not report.passed
    assert report.provider_calendar_match is False
    assert "provider calendars differ" in report.policy_violations


def test_validation_store_is_append_only_and_idempotent(tmp_path: Path) -> None:
    report = validate_agent_market_results(
        _result(),
        _result(),
        policy=AgentMarketValidationPolicy.replay(),
    )
    store = SQLiteAgentMarketValidationStore(tmp_path / "validation.sqlite")
    store.register(report)
    store.register(report)
    stored = store.get(report.validation_id)
    assert stored["passed"] is True
    assert stored["mode"] == "replay"


def test_frozen_feature_family_reconstructs_exact_artifact_and_checks_fields(tmp_path: Path) -> None:
    artifact = _artifact()
    store = SQLiteGeneratedFeatureStore(tmp_path / "features.sqlite")
    store.register(artifact)
    reference = AgentMarketResearchResult(
        study_id="frozen-study",
        task_id="task-us-etf",
        program_id="program-us-etf",
        family_id="family-us-etf-001",
        provider="alpaca",
        data_version="alpaca-v1",
        universe=("etf:ARCX:SPY:USD", "etf:XNAS:QQQ:USD"),
        candidates=(AgentMarketCandidate.from_artifact(artifact),),
        folds=(),
        aggregate_portfolio_metrics={"sharpe": 0.0},
        promotion_eligible_folds=0,
    )
    loaded = frozen_feature_family(
        store,
        reference,
        approved_input_fields=("simple_return_1",),
    )
    assert loaded == (artifact,)
    with pytest.raises(PermissionError, match="unapproved fields"):
        frozen_feature_family(
            store,
            reference,
            approved_input_fields=("simple_return_5",),
        )


def test_reusing_same_frozen_plan_does_not_double_spend_program_budget(tmp_path: Path) -> None:
    class Plan:
        program_id = "program-us-etf"
        family_id = "family-us-etf-001"
        alpha = 0.05
        variants = ("digest-a", "digest-b")

        @staticmethod
        def fingerprint(task_id: str) -> str:
            return f"frozen:{task_id}:digest-a:digest-b"

    store = SQLiteResearchProgramStore(tmp_path / "program.sqlite")
    store.register(
        ResearchProgram(
            program_id="program-us-etf",
            alpha_budget=0.05,
            max_families=2,
            max_experiments=4,
        )
    )
    first = store.reserve_plan(Plan(), task_id="task-us-etf")
    second = store.reserve_plan(Plan(), task_id="task-us-etf")
    assert first.plan_fingerprint == second.plan_fingerprint
    budget = store.budget_snapshot("program-us-etf")
    assert budget.family_count == 1
    assert budget.experiment_count == 2
    assert budget.alpha_spent == pytest.approx(0.05)
