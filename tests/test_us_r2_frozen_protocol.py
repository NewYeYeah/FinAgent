from __future__ import annotations

from copy import deepcopy
from itertools import pairwise

import pytest

from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    FROZEN_CANDIDATE_DENOMINATOR_ID,
    FROZEN_CLEANING_ID,
    FROZEN_COMMON_ALL_ASSET_END,
    FROZEN_COMMON_ALL_ASSET_SESSION_COUNT,
    FROZEN_COMMON_ALL_ASSET_START,
    FROZEN_CORPUS_ID,
    FROZEN_DATA_VERSION,
    FROZEN_ENGINEERING_UNIVERSE_ID,
    FROZEN_INVENTORY_PLAN_ID,
    FROZEN_MANIFEST_ID,
    FROZEN_SOURCE_ID,
    FROZEN_SOURCE_REVISION,
    REGIME_ANCHOR_ASSET,
    canonical_us_r2_frozen_protocol,
    freeze_us_r2_protocol_from_inventory,
    validate_us_r2_frozen_protocol,
)


def _inventory_document() -> dict[str, object]:
    asset_coverages: list[dict[str, object]] = []
    for asset in FROZEN_ASSETS:
        coverage: dict[str, object] = {
            "asset": asset,
            "first_observed_session": "2001-01-02",
            "last_observed_session": "2026-03-31",
            "active_span_regular_minute_coverage_ratio": 0.95,
            "active_span_missing_session_count": 2,
        }
        if asset == REGIME_ANCHOR_ASSET:
            coverage["first_observed_session"] = "2000-05-26"
            coverage["active_span_regular_minute_coverage_ratio"] = 0.925663089253101
            coverage["active_span_missing_session_count"] = 3
        asset_coverages.append(coverage)
    return {
        "schema_version": "finagent.us-r2-regime-research-corpus.v1",
        "corpus_id": FROZEN_CORPUS_ID,
        "passed": True,
        "blockers": [],
        "candidate_denominator_id": FROZEN_CANDIDATE_DENOMINATOR_ID,
        "candidate_performance_read": False,
        "performance_filter_applied": False,
        "engineering_universe_id": FROZEN_ENGINEERING_UNIVERSE_ID,
        "source_id": FROZEN_SOURCE_ID,
        "source_revision": FROZEN_SOURCE_REVISION,
        "cleaning_identity": FROZEN_CLEANING_ID,
        "point_in_time_security_master_available": False,
        "survivorship_safe_market_claim": False,
        "stage_exit_authority": False,
        "alpha_authority": False,
        "execution_authority": False,
        "order_authority": False,
        "common_all_asset_start": FROZEN_COMMON_ALL_ASSET_START.isoformat(),
        "common_all_asset_end": FROZEN_COMMON_ALL_ASSET_END.isoformat(),
        "common_all_asset_session_count": FROZEN_COMMON_ALL_ASSET_SESSION_COUNT,
        "limitations": [
            "universe:engineering_integration_only_not_pit_research_universe",
            "universe:current_symbol_fixed_universe_is_survivorship_conditioned",
            "identity:no_point_in_time_security_master",
            "history:first_last_observed_session_not_listing_or_delisting_authority",
            "research:no_candidate_performance_read_or_filter",
            "authority:inventory_does_not_establish_robust_alpha_or_execution_readiness",
        ],
        "plan": {
            "plan_id": FROZEN_INVENTORY_PLAN_ID,
            "manifest_id": FROZEN_MANIFEST_ID,
            "data_version": FROZEN_DATA_VERSION,
            "calendar_id": FROZEN_CALENDAR_ID,
            "assets": list(FROZEN_ASSETS),
            "candidate_dependent_scan": False,
            "source_rows_emitted": False,
        },
        "asset_coverages": asset_coverages,
        "year_breadth": [
            {"year": year, "minimum_observed_asset_count": 16 if year < 2022 else 12}
            for year in range(2001, 2027)
        ],
    }


def test_freeze_binds_dynamic_cross_section_and_five_long_oos_folds() -> None:
    frozen = freeze_us_r2_protocol_from_inventory(_inventory_document())

    assert frozen.inventory_corpus_id == FROZEN_CORPUS_ID
    assert frozen.cross_section_policy.allowed_assets == FROZEN_ASSETS
    assert frozen.cross_section_policy.minimum_cross_section == 10
    assert frozen.cross_section_policy.to_dict()["static_asset_exclusion_allowed"] is False
    assert frozen.static_all_asset_intersection_rejected is True
    assert frozen.observed_common_all_asset_session_count == 277
    assert frozen.classifier_policy.anchor_asset == "IWM"
    assert frozen.classifier_policy.to_dict()["cross_session_price_return_used"] is False
    assert frozen.walk_forward_protocol.candidate_denominator_id == FROZEN_CANDIDATE_DENOMINATOR_ID
    assert frozen.walk_forward_protocol.to_dict()["performance_filter_applied"] is False
    assert frozen.direction_source_fold_id == "us-r2-fold-01"
    assert frozen.direction_frozen_across_evaluation_folds is True

    folds = frozen.walk_forward_protocol.folds
    assert len(folds) == 5
    assert folds[0].train_start.isoformat() == "2001-01-01"
    assert folds[0].evaluation_start.isoformat() == "2006-01-01"
    assert folds[-1].evaluation_start.isoformat() == "2022-01-01"
    assert folds[-1].evaluation_end.isoformat() == "2026-04-01"
    assert all(left.evaluation_end <= right.evaluation_start for left, right in pairwise(folds))


def test_serialized_frozen_protocol_is_exactly_canonical() -> None:
    frozen = canonical_us_r2_frozen_protocol()
    assert validate_us_r2_frozen_protocol(frozen.to_dict()) == frozen

    changed = frozen.to_dict()
    changed["performance_filter_applied"] = True
    with pytest.raises(ValueError, match="differs from canonical preregistration"):
        validate_us_r2_frozen_protocol(changed)


def test_freeze_rejects_candidate_performance_or_static_universe_mutation() -> None:
    document = _inventory_document()
    document["candidate_performance_read"] = True
    with pytest.raises(ValueError, match="candidate_performance_read must remain false"):
        freeze_us_r2_protocol_from_inventory(document)

    document = _inventory_document()
    plan = document["plan"]
    assert isinstance(plan, dict)
    plan["assets"] = list(FROZEN_ASSETS[:-1])
    with pytest.raises(ValueError, match="does not retain the frozen 25-name"):
        freeze_us_r2_protocol_from_inventory(document)


def test_freeze_rejects_short_all_asset_intersection_being_rewritten() -> None:
    document = _inventory_document()
    document["common_all_asset_session_count"] = 278
    with pytest.raises(ValueError, match="common window differs"):
        freeze_us_r2_protocol_from_inventory(document)


def test_freeze_rejects_year_breadth_below_inherited_r1_minimum() -> None:
    document = _inventory_document()
    raw_years = document["year_breadth"]
    assert isinstance(raw_years, list)
    year_2024 = next(item for item in raw_years if item["year"] == 2024)
    year_2024["minimum_observed_asset_count"] = 9
    with pytest.raises(ValueError, match="2024 falls below inherited minimum cross-section 9<10"):
        freeze_us_r2_protocol_from_inventory(document)


def test_freeze_rejects_weak_or_late_iwm_anchor_coverage() -> None:
    document = _inventory_document()
    raw_coverages = document["asset_coverages"]
    assert isinstance(raw_coverages, list)
    iwm = next(item for item in raw_coverages if item["asset"] == "IWM")
    iwm["active_span_regular_minute_coverage_ratio"] = 0.89
    with pytest.raises(ValueError, match="below the preregistered 90% anchor floor"):
        freeze_us_r2_protocol_from_inventory(document)

    document = deepcopy(_inventory_document())
    raw_coverages = document["asset_coverages"]
    assert isinstance(raw_coverages, list)
    iwm = next(item for item in raw_coverages if item["asset"] == "IWM")
    iwm["first_observed_session"] = "2001-01-02"
    with pytest.raises(ValueError, match="starts too late"):
        freeze_us_r2_protocol_from_inventory(document)


def test_freeze_rejects_pit_or_authority_promotion() -> None:
    document = _inventory_document()
    document["point_in_time_security_master_available"] = True
    with pytest.raises(ValueError, match="point_in_time_security_master_available must remain false"):
        freeze_us_r2_protocol_from_inventory(document)

    document = _inventory_document()
    document["alpha_authority"] = True
    with pytest.raises(ValueError, match="alpha_authority must remain false"):
        freeze_us_r2_protocol_from_inventory(document)
