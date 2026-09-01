from __future__ import annotations

from datetime import UTC, datetime

from finagent.data.minute_transform import (
    D2ActionAuthoritySmokeCheck,
    D2LabelSmokeCheck,
    D2ResampleSmokeCheck,
    D2ScenarioSmokeCheck,
    D2TransformSmokePolicy,
    D2TransformSmokeReport,
)
from finagent.domain.market_bars import BarInterval


def _resample(interval: BarInterval) -> D2ResampleSmokeCheck:
    digest = {
        BarInterval.MINUTE_5: "1",
        BarInterval.MINUTE_15: "2",
        BarInterval.MINUTE_30: "3",
    }[interval] * 64
    return D2ResampleSmokeCheck(
        interval=interval,
        row_count=10,
        complete_row_count=9,
        incomplete_row_count=1,
        minimum_coverage_ratio=0.8,
        materialization_id=f"materialization-{interval.value}",
        content_sha256=digest,
    )


def _labels() -> D2LabelSmokeCheck:
    return D2LabelSmokeCheck(
        row_count=100,
        available_row_count=80,
        target_crosses_session_count=19,
        target_minute_missing_count=1,
        other_unavailable_count=0,
        materialization_id="label-materialization",
        content_sha256="a" * 64,
        label_plan_id="label-plan",
        label_data_version="label-data-version",
    )


def _scenario(name: str) -> D2ScenarioSmokeCheck:
    return D2ScenarioSmokeCheck(
        name=name,
        start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        end=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
        expected_regular_minutes_per_asset=390,
        asset_count=4,
        regular_1m_row_count=1560,
        resamples=(
            _resample(BarInterval.MINUTE_5),
            _resample(BarInterval.MINUTE_15),
            _resample(BarInterval.MINUTE_30),
        ),
        labels=_labels(),
    )


def _actions(*, passing: bool = True) -> D2ActionAuthoritySmokeCheck:
    return D2ActionAuthoritySmokeCheck(
        coverage_id="coverage-id",
        same_session_raw_allowed=True,
        cross_session_raw_denied=passing,
        split_adjusted_denied=True,
        total_return_adjusted_denied=True,
    )


def test_smoke_report_accepts_required_row_free_transform_evidence() -> None:
    policy = D2TransformSmokePolicy(calendar_id="calendar-id")
    report = D2TransformSmokeReport(
        policy=policy,
        calendar_id="calendar-id",
        manifest_id="manifest-id",
        source_data_version="data-version",
        assets=("AMD", "INTC", "MSFT", "NVDA"),
        scenarios=(
            _scenario("half_day"),
            _scenario("pre_dst"),
            _scenario("post_dst"),
        ),
        action_authority=_actions(),
        ran_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert report.passed is True
    assert report.blockers == ()
    assert report.report_id.startswith("us-d2-transform-smoke-")
    payload = report.to_dict()
    assert "open" not in payload
    assert "close" not in payload
    assert payload["passed"] is True


def test_smoke_report_fails_closed_on_missing_scenario_or_action_authority() -> None:
    policy = D2TransformSmokePolicy(calendar_id="calendar-id")
    report = D2TransformSmokeReport(
        policy=policy,
        calendar_id="calendar-id",
        manifest_id="manifest-id",
        source_data_version="data-version",
        assets=("AMD", "INTC", "MSFT", "NVDA"),
        scenarios=(_scenario("half_day"), _scenario("pre_dst")),
        action_authority=_actions(passing=False),
        ran_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert report.passed is False
    assert "scenario:post_dst:missing" in report.blockers
    assert "corporate_action_authority:failed" in report.blockers


def test_resample_and_label_checks_reject_invalid_accounting() -> None:
    try:
        D2ResampleSmokeCheck(
            interval=BarInterval.MINUTE_15,
            row_count=10,
            complete_row_count=8,
            incomplete_row_count=1,
            minimum_coverage_ratio=1.0,
            materialization_id="m",
            content_sha256="b" * 64,
        )
    except ValueError as exc:
        assert "complete + incomplete" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid resample accounting should fail")

    try:
        D2LabelSmokeCheck(
            row_count=10,
            available_row_count=8,
            target_crosses_session_count=1,
            target_minute_missing_count=0,
            other_unavailable_count=0,
            materialization_id="m",
            content_sha256="c" * 64,
            label_plan_id="p",
            label_data_version="v",
        )
    except ValueError as exc:
        assert "available + unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("invalid label accounting should fail")
