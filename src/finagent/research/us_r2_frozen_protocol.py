from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from finagent.research.us_r1_evaluation_policy import (
    canonical_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_protocol import (
    USMultiRegimeFold,
    USMultiRegimeWalkForwardProtocol,
    USRegimeDefinitionPolicy,
    USRegimeFeatureSource,
    USRegimeFeatureSpec,
)

FROZEN_CORPUS_ID = "us-r2-regime-corpus-1d49ef091a1781941820a67f"
FROZEN_INVENTORY_PLAN_ID = "us-r2-corpus-inventory-plan-4d40742a4d0674431c4c247b"
FROZEN_ENGINEERING_UNIVERSE_ID = "engineering-universe-259e3975a25856bef28442ff"
FROZEN_CANDIDATE_DENOMINATOR_ID = "us-r1-denominator-be5184ac3883b0799c00c5dc"
FROZEN_CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"
FROZEN_DATA_VERSION = "minute-data-version-999f210df720fd8d9c998fd9"
FROZEN_MANIFEST_ID = "minute-store-manifest-425d29a05cd26890d972c8f9"
FROZEN_SOURCE_ID = "hf-mito0o852-ohlcv-1m"
FROZEN_SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
FROZEN_CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
FROZEN_COMMON_ALL_ASSET_START = date(2025, 2, 24)
FROZEN_COMMON_ALL_ASSET_END = date(2026, 3, 31)
FROZEN_COMMON_ALL_ASSET_SESSION_COUNT = 277
FROZEN_FIRST_RESEARCH_YEAR = 2001
FROZEN_LAST_RESEARCH_YEAR = 2026
REGIME_ANCHOR_ASSET = "IWM"
REGIME_LOOKBACK_SESSIONS = 20
FROZEN_ASSETS = (
    "AAPL",
    "AMD",
    "AMZN",
    "AVGO",
    "COIN",
    "EEM",
    "GLD",
    "GOOG",
    "GOOGL",
    "INTC",
    "IWM",
    "JPM",
    "META",
    "MSFT",
    "MSTR",
    "MU",
    "NFLX",
    "NVDA",
    "ORCL",
    "PLTR",
    "SNDK",
    "TSLA",
    "TSM",
    "XLE",
    "XOM",
)
FROZEN_REGIME_LABELS = (
    "DOWN_HIGH_VOL",
    "DOWN_LOW_VOL",
    "UP_HIGH_VOL",
    "UP_LOW_VOL",
)
_REQUIRED_LIMITATIONS = frozenset(
    {
        "universe:engineering_integration_only_not_pit_research_universe",
        "universe:current_symbol_fixed_universe_is_survivorship_conditioned",
        "identity:no_point_in_time_security_master",
        "history:first_last_observed_session_not_listing_or_delisting_authority",
        "research:no_candidate_performance_read_or_filter",
        "authority:inventory_does_not_establish_robust_alpha_or_execution_readiness",
    }
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise TypeError(f"{field_name} must be an integer")


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    return float(value)


def _date(value: object, field_name: str) -> date:
    try:
        return date.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _require_identity(document: Mapping[str, object], field_name: str, expected: str) -> None:
    actual = _text(document.get(field_name), field_name)
    if actual != expected:
        raise ValueError(f"{field_name} differs from the frozen US-R2 inventory binding")


def _require_false(document: Mapping[str, object], field_name: str) -> None:
    if document.get(field_name) is not False:
        raise ValueError(f"{field_name} must remain false for US-R2 protocol freeze")


@dataclass(frozen=True, slots=True)
class USR2HistoricalCrossSectionPolicy:
    corpus_id: str
    engineering_universe_id: str
    allowed_assets: tuple[str, ...]
    minimum_cross_section: int
    first_research_year: int
    eligibility_clock: str = "FORMATION_AVAILABLE_AT"
    asset_eligibility_semantics: str = (
        "dynamic_source_bar_feature_and_label_availability_only_no_static_asset_exclusion"
    )
    same_session_only: bool = True
    require_complete_candidate_bars: bool = True
    partial_label_policy: str = "omit_entire_formation_cross_section"
    schema_version: str = "finagent.us-r2-historical-cross-section-policy.v1"

    def __post_init__(self) -> None:
        if not self.corpus_id.strip() or not self.engineering_universe_id.strip():
            raise ValueError("US-R2 cross-section identities must be non-empty")
        assets = tuple(sorted(dict.fromkeys(item.strip() for item in self.allowed_assets if item.strip())))
        if assets != FROZEN_ASSETS:
            raise ValueError("US-R2 first replication must retain the complete frozen 25-name set")
        object.__setattr__(self, "allowed_assets", assets)
        r1 = canonical_us_r1_statistical_evaluation_policy()
        if self.minimum_cross_section != r1.minimum_cross_section:
            raise ValueError("US-R2 first replication must inherit the R1 minimum cross-section")
        if self.first_research_year != FROZEN_FIRST_RESEARCH_YEAR:
            raise ValueError("US-R2 first research year differs from the inventory-derived freeze")
        if self.eligibility_clock != "FORMATION_AVAILABLE_AT":
            raise ValueError("US-R2 historical eligibility must use formation available_at")
        if self.asset_eligibility_semantics != (
            "dynamic_source_bar_feature_and_label_availability_only_no_static_asset_exclusion"
        ):
            raise ValueError("US-R2 cannot add a static historical asset filter")
        if not self.same_session_only or not self.require_complete_candidate_bars:
            raise ValueError("US-R2 first replication preserves R1 same-session complete-bar semantics")
        if self.partial_label_policy != "omit_entire_formation_cross_section":
            raise ValueError("US-R2 must preserve symmetric complete-case label omission")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-cross-section-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "corpus_id": self.corpus_id,
            "engineering_universe_id": self.engineering_universe_id,
            "allowed_assets": list(self.allowed_assets),
            "allowed_asset_count": len(self.allowed_assets),
            "minimum_cross_section": self.minimum_cross_section,
            "minimum_cross_section_source": "accepted_us_r1_statistical_evaluation_policy",
            "first_research_year": self.first_research_year,
            "eligibility_clock": self.eligibility_clock,
            "asset_eligibility_semantics": self.asset_eligibility_semantics,
            "same_session_only": self.same_session_only,
            "require_complete_candidate_bars": self.require_complete_candidate_bars,
            "partial_label_policy": self.partial_label_policy,
            "static_asset_exclusion_allowed": False,
            "candidate_performance_filter_allowed": False,
            "history_boundary_is_listing_authority": False,
            "point_in_time_security_master_available": False,
            "survivorship_safe_market_claim": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2RegimeClassifierPolicy:
    regime_policy_id: str
    anchor_asset: str
    return_feature_id: str
    volatility_feature_id: str
    lookback_sessions: int
    labels: tuple[str, ...]
    return_threshold: float = 0.0
    return_zero_tie_break: str = "UP"
    volatility_threshold_method: str = "TRAIN_MEDIAN"
    volatility_threshold_quantile: float = 0.5
    volatility_equal_tie_break: str = "LOW_VOL"
    threshold_fit_scope: str = "EACH_FOLD_TRAIN_ONLY"
    session_return_semantics: str = "regular_session_close_div_open_minus_one_raw_same_session"
    rolling_return_semantics: str = "arithmetic_mean_over_consecutive_completed_session_returns"
    rolling_volatility_semantics: str = (
        "population_std_over_consecutive_completed_session_returns"
    )
    schema_version: str = "finagent.us-r2-regime-classifier-policy.v1"

    def __post_init__(self) -> None:
        if not self.regime_policy_id.strip() or not self.anchor_asset.strip():
            raise ValueError("US-R2 classifier identities must be non-empty")
        if self.anchor_asset != REGIME_ANCHOR_ASSET:
            raise ValueError("US-R2 v1 regime anchor must remain IWM")
        if self.lookback_sessions != REGIME_LOOKBACK_SESSIONS:
            raise ValueError("US-R2 v1 regime lookback must remain 20 completed sessions")
        labels = tuple(sorted(dict.fromkeys(item.strip() for item in self.labels if item.strip())))
        if labels != FROZEN_REGIME_LABELS:
            raise ValueError("US-R2 regime label set differs from the frozen four-state classifier")
        object.__setattr__(self, "labels", labels)
        if self.return_threshold != 0.0 or self.return_zero_tie_break != "UP":
            raise ValueError("US-R2 direction threshold semantics are frozen at zero with UP tie-break")
        if self.volatility_threshold_method != "TRAIN_MEDIAN":
            raise ValueError("US-R2 volatility threshold must be the fold-training median")
        if self.volatility_threshold_quantile != 0.5:
            raise ValueError("US-R2 volatility threshold quantile must remain 0.5")
        if self.volatility_equal_tie_break != "LOW_VOL":
            raise ValueError("US-R2 volatility median equality must map to LOW_VOL")
        if self.threshold_fit_scope != "EACH_FOLD_TRAIN_ONLY":
            raise ValueError("US-R2 regime thresholds may use fold TRAIN only")
        if self.session_return_semantics != (
            "regular_session_close_div_open_minus_one_raw_same_session"
        ):
            raise ValueError("US-R2 regime direction cannot use cross-session raw price returns")
        if self.rolling_return_semantics != (
            "arithmetic_mean_over_consecutive_completed_session_returns"
        ):
            raise ValueError("US-R2 rolling direction semantics differ from the freeze")
        if self.rolling_volatility_semantics != (
            "population_std_over_consecutive_completed_session_returns"
        ):
            raise ValueError("US-R2 rolling volatility semantics differ from the freeze")

    @property
    def classifier_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-classifier")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "regime_policy_id": self.regime_policy_id,
            "anchor_asset": self.anchor_asset,
            "return_feature_id": self.return_feature_id,
            "volatility_feature_id": self.volatility_feature_id,
            "lookback_sessions": self.lookback_sessions,
            "availability_lag_sessions": 1,
            "labels": list(self.labels),
            "return_threshold": self.return_threshold,
            "return_zero_tie_break": self.return_zero_tie_break,
            "volatility_threshold_method": self.volatility_threshold_method,
            "volatility_threshold_quantile": self.volatility_threshold_quantile,
            "volatility_equal_tie_break": self.volatility_equal_tie_break,
            "threshold_fit_scope": self.threshold_fit_scope,
            "session_return_semantics": self.session_return_semantics,
            "rolling_return_semantics": self.rolling_return_semantics,
            "rolling_volatility_semantics": self.rolling_volatility_semantics,
            "price_basis": "RAW_SAME_SESSION_ONLY",
            "cross_session_price_return_used": False,
            "candidate_performance_inputs_allowed": False,
            "candidate_rank_ic_inputs_allowed": False,
            "future_label_inputs_allowed": False,
        }
        if include_id:
            payload["classifier_id"] = self.classifier_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2FrozenResearchProtocol:
    inventory_corpus_id: str
    inventory_plan_id: str
    cross_section_policy: USR2HistoricalCrossSectionPolicy
    regime_policy: USRegimeDefinitionPolicy
    classifier_policy: USR2RegimeClassifierPolicy
    walk_forward_protocol: USMultiRegimeWalkForwardProtocol
    observed_common_all_asset_start: date
    observed_common_all_asset_end: date
    observed_common_all_asset_session_count: int
    direction_source_fold_id: str = "us-r2-fold-01"
    direction_statistic: str = "mean_cross_sectional_rank_ic"
    direction_frozen_across_evaluation_folds: bool = True
    static_all_asset_intersection_rejected: bool = True
    schema_version: str = "finagent.us-r2-frozen-research-protocol.v1"

    def __post_init__(self) -> None:
        if self.inventory_corpus_id != FROZEN_CORPUS_ID:
            raise ValueError("US-R2 frozen protocol must bind the reviewed corpus inventory")
        if self.inventory_plan_id != FROZEN_INVENTORY_PLAN_ID:
            raise ValueError("US-R2 frozen protocol must bind the reviewed inventory plan")
        if self.cross_section_policy.corpus_id != self.inventory_corpus_id:
            raise ValueError("US-R2 cross-section policy/corpus identity mismatch")
        if self.walk_forward_protocol.corpus_id != self.inventory_corpus_id:
            raise ValueError("US-R2 walk-forward/corpus identity mismatch")
        if self.walk_forward_protocol.candidate_denominator_id != FROZEN_CANDIDATE_DENOMINATOR_ID:
            raise ValueError("US-R2 walk-forward must preserve the complete R1 denominator")
        if self.walk_forward_protocol.regime_policy.policy_id != self.regime_policy.policy_id:
            raise ValueError("US-R2 walk-forward/regime policy identity mismatch")
        if self.classifier_policy.regime_policy_id != self.regime_policy.policy_id:
            raise ValueError("US-R2 classifier/regime policy identity mismatch")
        if self.observed_common_all_asset_start != FROZEN_COMMON_ALL_ASSET_START:
            raise ValueError("US-R2 all-asset common-window start differs from inventory")
        if self.observed_common_all_asset_end != FROZEN_COMMON_ALL_ASSET_END:
            raise ValueError("US-R2 all-asset common-window end differs from inventory")
        if self.observed_common_all_asset_session_count != FROZEN_COMMON_ALL_ASSET_SESSION_COUNT:
            raise ValueError("US-R2 all-asset common-session count differs from inventory")
        if not self.static_all_asset_intersection_rejected:
            raise ValueError("277 sessions cannot be promoted into a synthetic multi-regime program")
        if self.direction_source_fold_id != "us-r2-fold-01":
            raise ValueError("US-R2 first replication freezes factor direction from fold-01 TRAIN")
        if self.direction_statistic != "mean_cross_sectional_rank_ic":
            raise ValueError("US-R2 factor direction must preserve the R1 RankIC statistic")
        if not self.direction_frozen_across_evaluation_folds:
            raise ValueError("US-R2 first replication must keep one direction across OOS folds")

    @property
    def freeze_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-frozen-protocol")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "inventory_corpus_id": self.inventory_corpus_id,
            "inventory_plan_id": self.inventory_plan_id,
            "cross_section_policy": self.cross_section_policy.to_dict(),
            "regime_policy": self.regime_policy.to_dict(),
            "classifier_policy": self.classifier_policy.to_dict(),
            "walk_forward_protocol": self.walk_forward_protocol.to_dict(),
            "observed_common_all_asset_start": self.observed_common_all_asset_start.isoformat(),
            "observed_common_all_asset_end": self.observed_common_all_asset_end.isoformat(),
            "observed_common_all_asset_session_count": self.observed_common_all_asset_session_count,
            "static_all_asset_intersection_rejected": self.static_all_asset_intersection_rejected,
            "direction_source_fold_id": self.direction_source_fold_id,
            "direction_statistic": self.direction_statistic,
            "direction_frozen_across_evaluation_folds": self.direction_frozen_across_evaluation_folds,
            "candidate_denominator_preserved": True,
            "performance_filter_applied": False,
            "new_agent_candidates_admitted": False,
            "point_in_time_security_master_available": False,
            "survivorship_safe_market_claim": False,
            "report_storage_policy": "local_reports_ignored_git_binds_content_addressed_ids_only",
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
        }
        if include_id:
            payload["freeze_id"] = self.freeze_id
        return payload


def _canonical_regime_policy() -> USRegimeDefinitionPolicy:
    return_feature = USRegimeFeatureSpec(
        name="iwm_20_session_direction",
        source=USRegimeFeatureSource.MARKET_ANCHOR_RETURN,
        lookback_sessions=REGIME_LOOKBACK_SESSIONS,
        availability_lag_sessions=1,
        anchor_asset=REGIME_ANCHOR_ASSET,
    )
    volatility_feature = USRegimeFeatureSpec(
        name="iwm_20_session_volatility",
        source=USRegimeFeatureSource.MARKET_ANCHOR_REALIZED_VOLATILITY,
        lookback_sessions=REGIME_LOOKBACK_SESSIONS,
        availability_lag_sessions=1,
        anchor_asset=REGIME_ANCHOR_ASSET,
    )
    return USRegimeDefinitionPolicy(
        features=(return_feature, volatility_feature),
        minimum_distinct_regimes=4,
    )


def _canonical_classifier(regime_policy: USRegimeDefinitionPolicy) -> USR2RegimeClassifierPolicy:
    by_name = {item.name: item for item in regime_policy.features}
    return USR2RegimeClassifierPolicy(
        regime_policy_id=regime_policy.policy_id,
        anchor_asset=REGIME_ANCHOR_ASSET,
        return_feature_id=by_name["iwm_20_session_direction"].feature_id,
        volatility_feature_id=by_name["iwm_20_session_volatility"].feature_id,
        lookback_sessions=REGIME_LOOKBACK_SESSIONS,
        labels=FROZEN_REGIME_LABELS,
    )


def _canonical_folds() -> tuple[USMultiRegimeFold, ...]:
    windows = (
        ("us-r2-fold-01", date(2001, 1, 1), date(2006, 1, 1), date(2006, 1, 1), date(2010, 1, 1)),
        ("us-r2-fold-02", date(2005, 1, 1), date(2010, 1, 1), date(2010, 1, 1), date(2014, 1, 1)),
        ("us-r2-fold-03", date(2009, 1, 1), date(2014, 1, 1), date(2014, 1, 1), date(2018, 1, 1)),
        ("us-r2-fold-04", date(2013, 1, 1), date(2018, 1, 1), date(2018, 1, 1), date(2022, 1, 1)),
        ("us-r2-fold-05", date(2017, 1, 1), date(2022, 1, 1), date(2022, 1, 1), date(2026, 4, 1)),
    )
    return tuple(
        USMultiRegimeFold(
            fold_id=fold_id,
            train_start=train_start,
            train_end=train_end,
            evaluation_start=evaluation_start,
            evaluation_end=evaluation_end,
            expected_regimes=FROZEN_REGIME_LABELS,
        )
        for fold_id, train_start, train_end, evaluation_start, evaluation_end in windows
    )


def canonical_us_r2_frozen_protocol() -> USR2FrozenResearchProtocol:
    r1_evaluation = canonical_us_r1_statistical_evaluation_policy()
    r1_protocol = canonical_us_r1_research_protocol()
    regime_policy = _canonical_regime_policy()
    cross_section = USR2HistoricalCrossSectionPolicy(
        corpus_id=FROZEN_CORPUS_ID,
        engineering_universe_id=FROZEN_ENGINEERING_UNIVERSE_ID,
        allowed_assets=FROZEN_ASSETS,
        minimum_cross_section=r1_evaluation.minimum_cross_section,
        first_research_year=FROZEN_FIRST_RESEARCH_YEAR,
    )
    walk_forward = USMultiRegimeWalkForwardProtocol(
        corpus_id=FROZEN_CORPUS_ID,
        candidate_denominator_id=FROZEN_CANDIDATE_DENOMINATOR_ID,
        r1_protocol_id=r1_protocol.protocol_id,
        regime_policy=regime_policy,
        folds=_canonical_folds(),
    )
    return USR2FrozenResearchProtocol(
        inventory_corpus_id=FROZEN_CORPUS_ID,
        inventory_plan_id=FROZEN_INVENTORY_PLAN_ID,
        cross_section_policy=cross_section,
        regime_policy=regime_policy,
        classifier_policy=_canonical_classifier(regime_policy),
        walk_forward_protocol=walk_forward,
        observed_common_all_asset_start=FROZEN_COMMON_ALL_ASSET_START,
        observed_common_all_asset_end=FROZEN_COMMON_ALL_ASSET_END,
        observed_common_all_asset_session_count=FROZEN_COMMON_ALL_ASSET_SESSION_COUNT,
    )


def _validate_inventory_document(document: Mapping[str, object]) -> None:
    _require_identity(document, "corpus_id", FROZEN_CORPUS_ID)
    _require_identity(document, "schema_version", "finagent.us-r2-regime-research-corpus.v1")
    _require_identity(document, "engineering_universe_id", FROZEN_ENGINEERING_UNIVERSE_ID)
    _require_identity(document, "candidate_denominator_id", FROZEN_CANDIDATE_DENOMINATOR_ID)
    _require_identity(document, "source_id", FROZEN_SOURCE_ID)
    _require_identity(document, "source_revision", FROZEN_SOURCE_REVISION)
    _require_identity(document, "cleaning_identity", FROZEN_CLEANING_ID)
    if document.get("passed") is not True:
        raise ValueError("US-R2 protocol freeze requires a passed corpus inventory")
    blockers = _sequence(document.get("blockers"), "blockers")
    if blockers:
        raise ValueError("US-R2 protocol freeze requires an inventory without blockers")
    for field_name in (
        "candidate_performance_read",
        "performance_filter_applied",
        "point_in_time_security_master_available",
        "survivorship_safe_market_claim",
        "stage_exit_authority",
        "alpha_authority",
        "execution_authority",
        "order_authority",
    ):
        _require_false(document, field_name)
    limitations = {_text(item, "limitations[]") for item in _sequence(document.get("limitations"), "limitations")}
    if not _REQUIRED_LIMITATIONS.issubset(limitations):
        raise ValueError("US-R2 inventory lost one or more frozen authority limitations")

    common_start = _date(document.get("common_all_asset_start"), "common_all_asset_start")
    common_end = _date(document.get("common_all_asset_end"), "common_all_asset_end")
    common_count = _integer(document.get("common_all_asset_session_count"), "common_all_asset_session_count")
    if (
        common_start != FROZEN_COMMON_ALL_ASSET_START
        or common_end != FROZEN_COMMON_ALL_ASSET_END
        or common_count != FROZEN_COMMON_ALL_ASSET_SESSION_COUNT
    ):
        raise ValueError("US-R2 all-25 common window differs from the reviewed inventory")

    plan = _mapping(document.get("plan"), "plan")
    _require_identity(plan, "plan_id", FROZEN_INVENTORY_PLAN_ID)
    _require_identity(plan, "manifest_id", FROZEN_MANIFEST_ID)
    _require_identity(plan, "data_version", FROZEN_DATA_VERSION)
    _require_identity(plan, "calendar_id", FROZEN_CALENDAR_ID)
    if plan.get("candidate_dependent_scan") is not False:
        raise ValueError("US-R2 inventory scan must remain candidate independent")
    if plan.get("source_rows_emitted") is not False:
        raise ValueError("US-R2 inventory evidence must remain row-free")
    plan_assets = tuple(sorted(_text(item, "plan.assets[]") for item in _sequence(plan.get("assets"), "plan.assets")))
    if plan_assets != FROZEN_ASSETS:
        raise ValueError("US-R2 inventory plan does not retain the frozen 25-name engineering set")

    raw_asset_coverages = _sequence(document.get("asset_coverages"), "asset_coverages")
    asset_coverages: dict[str, Mapping[str, object]] = {}
    for index, raw in enumerate(raw_asset_coverages):
        item = _mapping(raw, f"asset_coverages[{index}]")
        asset = _text(item.get("asset"), f"asset_coverages[{index}].asset")
        if asset in asset_coverages:
            raise ValueError(f"US-R2 inventory repeats asset coverage for {asset}")
        asset_coverages[asset] = item
    if tuple(sorted(asset_coverages)) != FROZEN_ASSETS:
        raise ValueError("US-R2 asset coverage summaries must retain all 25 frozen assets")
    iwm = asset_coverages[REGIME_ANCHOR_ASSET]
    if _date(iwm.get("first_observed_session"), "IWM.first_observed_session") > date(2000, 5, 26):
        raise ValueError("IWM history starts too late for the frozen 2001 research start")
    if _date(iwm.get("last_observed_session"), "IWM.last_observed_session") < FROZEN_COMMON_ALL_ASSET_END:
        raise ValueError("IWM history does not reach the frozen corpus end")
    if _number(
        iwm.get("active_span_regular_minute_coverage_ratio"),
        "IWM.active_span_regular_minute_coverage_ratio",
    ) < 0.90:
        raise ValueError("IWM source coverage is below the preregistered 90% anchor floor")
    if _integer(iwm.get("active_span_missing_session_count"), "IWM.active_span_missing_session_count") > 5:
        raise ValueError("IWM has too many missing sessions for the frozen regime anchor")

    raw_years = _sequence(document.get("year_breadth"), "year_breadth")
    years: dict[int, Mapping[str, object]] = {}
    for index, raw in enumerate(raw_years):
        item = _mapping(raw, f"year_breadth[{index}]")
        year = _integer(item.get("year"), f"year_breadth[{index}].year")
        if year in years:
            raise ValueError(f"US-R2 inventory repeats year breadth for {year}")
        years[year] = item
    r1_minimum = canonical_us_r1_statistical_evaluation_policy().minimum_cross_section
    for year in range(FROZEN_FIRST_RESEARCH_YEAR, FROZEN_LAST_RESEARCH_YEAR + 1):
        item = years.get(year)
        if item is None:
            raise ValueError(f"US-R2 inventory lacks year-breadth evidence for {year}")
        minimum_observed = _integer(
            item.get("minimum_observed_asset_count"),
            f"year_breadth[{year}].minimum_observed_asset_count",
        )
        if minimum_observed < r1_minimum:
            raise ValueError(
                f"US-R2 year {year} falls below inherited minimum cross-section "
                f"{minimum_observed}<{r1_minimum}"
            )


def freeze_us_r2_protocol_from_inventory(
    document: Mapping[str, object],
) -> USR2FrozenResearchProtocol:
    _validate_inventory_document(document)
    return canonical_us_r2_frozen_protocol()


def validate_us_r2_frozen_protocol(
    document: Mapping[str, object],
) -> USR2FrozenResearchProtocol:
    expected = canonical_us_r2_frozen_protocol()
    if dict(document) != expected.to_dict():
        raise ValueError("US-R2 frozen protocol differs from canonical preregistration")
    return expected
