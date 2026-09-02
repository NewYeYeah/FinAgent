from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from finagent.research.us_baseline_evaluation import USBaselineRunSpec
from finagent.research.us_baseline_walkforward import (
    USBaselineWalkForwardFold,
    USBaselineWalkForwardProtocol,
    bind_us_b0_fold_execution_specs,
    canonical_us_b0_pilot_walk_forward,
)


def _run_spec() -> USBaselineRunSpec:
    return USBaselineRunSpec(
        certification_report_id="us-minute-research-cert-test",
        certification_outcome="CERTIFIED_FOR_ENGINEERING_RESEARCH",
        engineering_universe_id="engineering-universe-test",
        denominator_id="us-baseline-denominator-test",
    )


def test_pilot_walk_forward_is_deterministic_and_pre_result() -> None:
    left = canonical_us_b0_pilot_walk_forward()
    right = canonical_us_b0_pilot_walk_forward()

    assert left.protocol_id == right.protocol_id
    assert len(left.folds) == 3
    assert left.folds[0].evaluation_start == datetime(2026, 2, 17, tzinfo=UTC)
    assert left.folds[-1].evaluation_end == datetime(2026, 3, 30, tzinfo=UTC)
    assert left.to_dict()["selection_authority"] is False
    assert left.to_dict()["alpha_authority"] is False


def test_pilot_walk_forward_has_expanding_non_overlapping_evaluation_windows() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()

    for previous, current in zip(protocol.folds, protocol.folds[1:], strict=True):
        assert current.train_start == previous.train_start
        assert current.train_end == previous.validation_end
        assert current.validation_start == previous.evaluation_start
        assert current.evaluation_start == previous.evaluation_end


def test_fold_execution_specs_bind_protocol_and_formal_run_spec() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    run_spec = _run_spec()

    specs = bind_us_b0_fold_execution_specs(protocol, run_spec)

    assert len(specs) == 3
    assert all(item.protocol_id == protocol.protocol_id for item in specs)
    assert all(item.run_spec_id == run_spec.spec_id for item in specs)
    assert [item.fold_ordinal for item in specs] == [1, 2, 3]
    assert specs[1].evaluation_start == protocol.folds[1].evaluation_start
    assert specs[1].evaluation_end == protocol.folds[1].evaluation_end
    assert specs[0].to_dict()["stage_exit_authority"] is False


def test_walk_forward_rejects_overlapping_or_non_contiguous_evaluation_windows() -> None:
    protocol = canonical_us_b0_pilot_walk_forward()
    first, second, third = protocol.folds
    broken_second = replace(
        second,
        evaluation_start=datetime(2026, 3, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="validation->evaluation"):
        USBaselineWalkForwardProtocol(
            calendar_id=protocol.calendar_id,
            source_revision=protocol.source_revision,
            folds=(first, broken_second, third),
        )


def test_fold_requires_timezone_aware_boundaries() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        USBaselineWalkForwardFold(
            ordinal=1,
            train_start=datetime(2026, 1, 2),
            train_end=datetime(2026, 2, 2, tzinfo=UTC),
            validation_start=datetime(2026, 2, 2, tzinfo=UTC),
            validation_end=datetime(2026, 2, 17, tzinfo=UTC),
            evaluation_start=datetime(2026, 2, 17, tzinfo=UTC),
            evaluation_end=datetime(2026, 3, 2, tzinfo=UTC),
        )
