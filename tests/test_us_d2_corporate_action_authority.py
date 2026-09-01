from __future__ import annotations

from datetime import UTC, datetime

import pytest

from finagent.data.minute_transform import (
    CorporateActionCoverageEvidence,
    CorporateActionCoverageStatus,
    assess_research_price_authority,
    unavailable_us_minute_corporate_action_coverage,
)
from finagent.domain.corporate_actions import CorporateActionEvent, CorporateActionEventType
from finagent.domain.labels import ResearchPriceBasis


def _dt(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=UTC)


def _event(
    *,
    event_id: str,
    action_type: CorporateActionEventType,
    effective_at: datetime,
) -> CorporateActionEvent:
    kwargs: dict[str, object] = {}
    if action_type is CorporateActionEventType.SPLIT:
        kwargs["split_ratio"] = 2.0
    else:
        kwargs["cash_amount"] = 0.5
    return CorporateActionEvent(
        event_id=event_id,
        asset="MSFT",
        action_type=action_type,
        effective_at=effective_at,
        available_at=effective_at,
        source="synthetic-actions",
        source_revision="synthetic-v1",
        **kwargs,  # type: ignore[arg-type]
    )


def _complete_coverage(
    events: tuple[CorporateActionEvent, ...] = (),
) -> CorporateActionCoverageEvidence:
    return CorporateActionCoverageEvidence(
        market_id="XNYS",
        assets=("MSFT",),
        coverage_start=_dt(1),
        coverage_end=_dt(31),
        source="synthetic-actions",
        source_revision="synthetic-v1",
        status=CorporateActionCoverageStatus.COMPLETE_FOR_DECLARED_TYPES,
        covered_types=frozenset(CorporateActionEventType),
        events=events,
    )


def test_bound_ohlcv_source_allows_same_session_raw_but_denies_cross_session() -> None:
    coverage = unavailable_us_minute_corporate_action_coverage(("MSFT",))

    same_session = assess_research_price_authority(
        coverage,
        asset="MSFT",
        start=_dt(9, 14),
        end=_dt(9, 20),
        price_basis=ResearchPriceBasis.RAW,
        allow_cross_session=False,
    )
    cross_session = assess_research_price_authority(
        coverage,
        asset="MSFT",
        start=_dt(9, 14),
        end=_dt(10, 14),
        price_basis=ResearchPriceBasis.RAW,
        allow_cross_session=True,
    )

    assert same_session.allowed is True
    assert same_session.blockers == ()
    assert cross_session.allowed is False
    assert cross_session.blockers == ("corporate_actions:coverage_unavailable",)
    assert coverage.status is CorporateActionCoverageStatus.UNAVAILABLE
    assert coverage.events == ()


def test_complete_coverage_can_prove_raw_cross_session_continuity_when_no_event_occurs() -> None:
    decision = assess_research_price_authority(
        _complete_coverage(),
        asset="MSFT",
        start=_dt(9),
        end=_dt(10),
        price_basis=ResearchPriceBasis.RAW,
        allow_cross_session=True,
    )

    assert decision.allowed is True
    assert decision.blockers == ()
    assert decision.observed_event_ids == ()


@pytest.mark.parametrize(
    "action_type",
    (
        CorporateActionEventType.SPLIT,
        CorporateActionEventType.CASH_DIVIDEND,
        CorporateActionEventType.CASH_EVENT,
    ),
)
def test_observed_action_makes_raw_cross_session_price_discontinuous(
    action_type: CorporateActionEventType,
) -> None:
    event = _event(event_id=f"event-{action_type.value}", action_type=action_type, effective_at=_dt(10))
    decision = assess_research_price_authority(
        _complete_coverage((event,)),
        asset="MSFT",
        start=_dt(9),
        end=_dt(10),
        price_basis=ResearchPriceBasis.RAW,
        allow_cross_session=True,
    )

    assert decision.allowed is False
    assert decision.blockers == ("corporate_actions:raw_price_discontinuity_observed",)
    assert decision.observed_event_ids == (event.event_id,)


def test_adjusted_price_requests_fail_closed_even_with_synthetic_complete_coverage() -> None:
    coverage = _complete_coverage()

    split = assess_research_price_authority(
        coverage,
        asset="MSFT",
        start=_dt(9),
        end=_dt(10),
        price_basis=ResearchPriceBasis.SPLIT_ADJUSTED,
        allow_cross_session=True,
    )
    total_return = assess_research_price_authority(
        coverage,
        asset="MSFT",
        start=_dt(9),
        end=_dt(10),
        price_basis=ResearchPriceBasis.TOTAL_RETURN_ADJUSTED,
        allow_cross_session=True,
    )

    assert split.allowed is False
    assert split.blockers == ("transform:split_adjusted_not_implemented",)
    assert total_return.allowed is False
    assert total_return.blockers == ("transform:total_return_adjusted_not_implemented",)


def test_coverage_identity_is_order_independent_for_assets_and_events() -> None:
    split = _event(
        event_id="split",
        action_type=CorporateActionEventType.SPLIT,
        effective_at=_dt(10),
    )
    dividend = _event(
        event_id="dividend",
        action_type=CorporateActionEventType.CASH_DIVIDEND,
        effective_at=_dt(11),
    )
    left = CorporateActionCoverageEvidence(
        market_id="XNYS",
        assets=("MSFT", "NVDA"),
        coverage_start=_dt(1),
        coverage_end=_dt(31),
        source="synthetic-actions",
        source_revision="synthetic-v1",
        status=CorporateActionCoverageStatus.COMPLETE_FOR_DECLARED_TYPES,
        covered_types=frozenset(CorporateActionEventType),
        events=(dividend, split),
    )
    right = CorporateActionCoverageEvidence(
        market_id="XNYS",
        assets=("NVDA", "MSFT"),
        coverage_start=_dt(1),
        coverage_end=_dt(31),
        source="synthetic-actions",
        source_revision="synthetic-v1",
        status=CorporateActionCoverageStatus.COMPLETE_FOR_DECLARED_TYPES,
        covered_types=frozenset(CorporateActionEventType),
        events=(split, dividend),
    )

    assert left.coverage_id == right.coverage_id


def test_coverage_rejects_events_outside_declared_asset_or_type() -> None:
    split = _event(
        event_id="split",
        action_type=CorporateActionEventType.SPLIT,
        effective_at=_dt(10),
    )
    with pytest.raises(ValueError, match="not declared covered"):
        CorporateActionCoverageEvidence(
            market_id="XNYS",
            assets=("MSFT",),
            coverage_start=_dt(1),
            coverage_end=_dt(31),
            source="synthetic-actions",
            source_revision="synthetic-v1",
            status=CorporateActionCoverageStatus.COMPLETE_FOR_DECLARED_TYPES,
            covered_types=frozenset({CorporateActionEventType.CASH_DIVIDEND}),
            events=(split,),
        )
