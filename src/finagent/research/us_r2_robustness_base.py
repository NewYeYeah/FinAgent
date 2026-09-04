from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import ResamplingSpec, SessionizationEvidence
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_materialization import canonical_us_r1_feature_formation_policy
from finagent.research.us_r1_materialization_evidence import canonical_us_r1_label_spec
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    canonical_us_r2_frozen_protocol,
)

FROZEN_POOLED_INFERENCE_REPORT_ID = "us-r2-pooled-inference-a0a2e40c2ec246fc607fab92"
ROBUSTNESS_FIRST_YEAR = 2006
ROBUSTNESS_LAST_YEAR = 2026
ROBUSTNESS_BASE_FILENAME = "us_r2_robustness_base.parquet"
ROBUSTNESS_BASE_PLAN_FILENAME = "us_r2_robustness_base_plan.json"
ROBUSTNESS_BASE_EVIDENCE_FILENAME = "us_r2_robustness_base_evidence.json"
ROBUSTNESS_BASE_OUTPUT_COLUMNS = (
    "slice_id",
    "slice_kind",
    "signal_interval",
    "label_horizon_trading_minutes",
    "research_asset_id",
    "session_date",
    "session_id",
    "event_time",
    "available_at",
    "bar_index",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "observed_minute_count",
    "expected_minute_count",
    "coverage_ratio",
    "is_complete",
    "is_half_day",
    "source_available_at",
    "source_price",
    "target_available_at",
    "label_value",
    "label_available",
    "unavailable_reason",
    "label_row_present",
    "close_anchor_difference",
    "source_id",
    "source_revision",
    "source_data_version",
    "robustness_policy_id",
    "data_version",
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


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


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


@dataclass(frozen=True, slots=True)
class USR2RobustnessSlice:
    slice_id: str
    kind: str
    signal_interval: BarInterval
    label_horizon_trading_minutes: int

    def __post_init__(self) -> None:
        allowed = {
            ("frequency", BarInterval.MINUTE_5, 60),
            ("frequency", BarInterval.MINUTE_30, 60),
            ("decay", BarInterval.MINUTE_15, 30),
            ("decay", BarInterval.MINUTE_15, 120),
        }
        key = (self.kind, self.signal_interval, self.label_horizon_trading_minutes)
        if key not in allowed:
            raise ValueError("US-R2 robustness slice differs from the frozen R1 robustness set")
        expected_id = (
            f"{self.kind}_{self.signal_interval.value}_{self.label_horizon_trading_minutes}m"
        )
        if self.slice_id != expected_id:
            raise ValueError("US-R2 robustness slice_id is not canonical")

    def to_dict(self) -> dict[str, object]:
        return {
            "slice_id": self.slice_id,
            "kind": self.kind,
            "signal_interval": self.signal_interval.value,
            "label_horizon_trading_minutes": self.label_horizon_trading_minutes,
        }


def canonical_us_r2_robustness_slices() -> tuple[USR2RobustnessSlice, ...]:
    return (
        USR2RobustnessSlice("frequency_5m_60m", "frequency", BarInterval.MINUTE_5, 60),
        USR2RobustnessSlice("frequency_30m_60m", "frequency", BarInterval.MINUTE_30, 60),
        USR2RobustnessSlice("decay_15m_30m", "decay", BarInterval.MINUTE_15, 30),
        USR2RobustnessSlice("decay_15m_120m", "decay", BarInterval.MINUTE_15, 120),
    )


@dataclass(frozen=True, slots=True)
class USR2RobustnessMaterializationPolicy:
    research_protocol_id: str
    formation_policy_id: str
    pooled_inference_report_id: str
    slices: tuple[USR2RobustnessSlice, ...]
    schema_version: str = "finagent.us-r2-robustness-materialization-policy.v1"

    def __post_init__(self) -> None:
        if self.research_protocol_id != canonical_us_r1_research_protocol().protocol_id:
            raise ValueError("US-R2 robustness must inherit the frozen R1 research protocol")
        if self.formation_policy_id != canonical_us_r1_feature_formation_policy().policy_id:
            raise ValueError("US-R2 robustness must inherit the frozen R1 formation policy")
        if self.pooled_inference_report_id != FROZEN_POOLED_INFERENCE_REPORT_ID:
            raise ValueError("US-R2 robustness must bind the reviewed pooled inference")
        if self.slices != canonical_us_r2_robustness_slices():
            raise ValueError("US-R2 robustness slice set/order changed")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-robustness-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "formation_policy_id": self.formation_policy_id,
            "pooled_inference_report_id": self.pooled_inference_report_id,
            "slices": [item.to_dict() for item in self.slices],
            "resampling_spec_ids": {
                interval.value: ResamplingSpec(
                    calendar_id=FROZEN_CALENDAR_ID,
                    target_interval=interval,
                ).spec_id
                for interval in (
                    BarInterval.MINUTE_5,
                    BarInterval.MINUTE_15,
                    BarInterval.MINUTE_30,
                )
            },
            "label_spec_ids": {
                str(horizon): canonical_us_r1_label_spec(horizon).label_id
                for horizon in (30, 60, 120)
            },
            "source_execution_strategy": "one_materialized_sessionized_1m_cte_per_year",
            "raw_1m_required": True,
            "derive_from_primary_15m60m_cache": False,
            "candidate_performance_read": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r2_robustness_materialization_policy() -> USR2RobustnessMaterializationPolicy:
    return USR2RobustnessMaterializationPolicy(
        research_protocol_id=canonical_us_r1_research_protocol().protocol_id,
        formation_policy_id=canonical_us_r1_feature_formation_policy().policy_id,
        pooled_inference_report_id=FROZEN_POOLED_INFERENCE_REPORT_ID,
        slices=canonical_us_r2_robustness_slices(),
    )


@dataclass(frozen=True, slots=True)
class USR2AnnualRobustnessBasePlan:
    policy_id: str
    frozen_protocol_id: str
    year: int
    source_plan_id: str
    sessionization_evidence_id: str
    calendar_id: str
    source_data_version: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...] = ROBUSTNESS_BASE_OUTPUT_COLUMNS
    schema_version: str = "finagent.us-r2-annual-robustness-base-plan.v1"

    def __post_init__(self) -> None:
        if not ROBUSTNESS_FIRST_YEAR <= self.year <= ROBUSTNESS_LAST_YEAR:
            raise ValueError("US-R2 robustness year is outside OOS 2006-2026")
        if self.policy_id != canonical_us_r2_robustness_materialization_policy().policy_id:
            raise ValueError("US-R2 robustness plan policy identity mismatch")
        if self.frozen_protocol_id != canonical_us_r2_frozen_protocol().freeze_id:
            raise ValueError("US-R2 robustness plan frozen protocol identity mismatch")
        if self.calendar_id != FROZEN_CALENDAR_ID:
            raise ValueError("US-R2 robustness plan calendar identity mismatch")
        if self.output_columns != ROBUSTNESS_BASE_OUTPUT_COLUMNS:
            raise ValueError("US-R2 robustness output schema changed")
        if self.selected_size_bytes < 0:
            raise ValueError("selected_size_bytes must be non-negative")
        for field_name in (
            "source_plan_id",
            "sessionization_evidence_id",
            "source_data_version",
            "data_version",
            "sql",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy_id,
                "frozen_protocol_id": self.frozen_protocol_id,
                "year": self.year,
                "source_plan_id": self.source_plan_id,
                "sessionization_evidence_id": self.sessionization_evidence_id,
                "calendar_id": self.calendar_id,
                "source_data_version": self.source_data_version,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
                "source_execution_strategy": "one_materialized_sessionized_1m_cte_per_year",
            },
            prefix="us-r2-robustness-base-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "policy_id": self.policy_id,
            "frozen_protocol_id": self.frozen_protocol_id,
            "year": self.year,
            "source_plan_id": self.source_plan_id,
            "sessionization_evidence_id": self.sessionization_evidence_id,
            "calendar_id": self.calendar_id,
            "source_data_version": self.source_data_version,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "source_scan_relation_count": 1,
            "source_cte_materialized": True,
            "slices": [item.to_dict() for item in canonical_us_r2_robustness_slices()],
            "output_columns": list(self.output_columns),
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
        }


def _bar_ctes(interval: BarInterval) -> tuple[str, str]:
    minutes = interval.minutes
    if minutes not in {5, 15, 30}:
        raise ValueError("US-R2 robustness bar interval must be 5m/15m/30m")
    suffix = str(minutes)
    bucketed = f"bucketed_{suffix}"
    bars = f"bars_{suffix}"
    return bars, f"""
        {bucketed} AS (
            SELECT
                d.*,
                CAST(floor(d.minute_offset / {minutes}) AS BIGINT) AS bar_index
            FROM year_rows AS d
        ),
        {bars} AS (
            SELECT
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bar_index,
                d.session_open + d.bar_index * INTERVAL '{minutes} minutes' AS event_time,
                d.session_open + (d.bar_index + 1) * INTERVAL '{minutes} minutes' AS available_at,
                CAST(arg_min(d.open, d.event_time) AS DOUBLE) AS open,
                CAST(max(d.high) AS DOUBLE) AS high,
                CAST(min(d.low) AS DOUBLE) AS low,
                CAST(arg_max(d.close, d.event_time) AS DOUBLE) AS close,
                CAST(sum(d.volume) AS DOUBLE) AS volume,
                count(*)::BIGINT AS observed_minute_count,
                {minutes}::BIGINT AS expected_minute_count,
                count(*)::DOUBLE / {minutes}::DOUBLE AS coverage_ratio,
                count(*) = {minutes} AS is_complete,
                bool_or(d.is_half_day) AS is_half_day,
                min(d.source_id) AS source_id,
                min(d.source_revision) AS source_revision
            FROM {bucketed} AS d
            GROUP BY
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bar_index
        )
    """.strip()


def _label_cte(horizon: int) -> str:
    if horizon not in {30, 60, 120}:
        raise ValueError("US-R2 robustness label horizon must be 30m/60m/120m")
    return f"""
        label_{horizon} AS (
            SELECT
                s.research_asset_id,
                s.session_date,
                s.available_at AS source_available_at,
                CAST(s.close AS DOUBLE) AS source_price,
                t.available_at AS target_available_at,
                CASE
                    WHEN s.minute_offset + {horizon}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN NULL
                    WHEN t.event_time IS NULL THEN NULL
                    ELSE CAST(t.close / s.close - 1.0 AS DOUBLE)
                END AS label_value,
                CASE
                    WHEN s.minute_offset + {horizon}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN false
                    WHEN t.event_time IS NULL THEN false
                    ELSE true
                END AS label_available,
                CASE
                    WHEN s.minute_offset + {horizon}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN 'target_crosses_session'
                    WHEN t.event_time IS NULL THEN 'target_minute_missing'
                    ELSE NULL
                END AS unavailable_reason
            FROM anchor_rows AS s
            LEFT JOIN year_rows AS t
              ON t.research_asset_id = s.research_asset_id
             AND t.session_date = s.session_date
             AND t.minute_offset = s.minute_offset + {horizon}
        )
    """.strip()


def _slice_select(
    item: USR2RobustnessSlice,
    *,
    bars_relation: str,
    source_data_literal: str,
    policy_literal: str,
    data_literal: str,
) -> str:
    horizon = item.label_horizon_trading_minutes
    return f"""
        SELECT
            {_sql_string(item.slice_id)} AS slice_id,
            {_sql_string(item.kind)} AS slice_kind,
            {_sql_string(item.signal_interval.value)} AS signal_interval,
            {horizon}::BIGINT AS label_horizon_trading_minutes,
            b.research_asset_id,
            b.session_date,
            b.session_id,
            b.event_time,
            b.available_at,
            b.bar_index,
            b.open,
            b.high,
            b.low,
            b.close,
            b.volume,
            b.observed_minute_count,
            b.expected_minute_count,
            b.coverage_ratio,
            b.is_complete,
            b.is_half_day,
            l.source_available_at,
            l.source_price,
            l.target_available_at,
            l.label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE WHEN l.source_price IS NULL THEN NULL ELSE abs(b.close - l.source_price) END
                AS close_anchor_difference,
            b.source_id,
            b.source_revision,
            {source_data_literal} AS source_data_version,
            {policy_literal} AS robustness_policy_id,
            {data_literal} AS data_version
        FROM {bars_relation} AS b
        LEFT JOIN label_{horizon} AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
    """.strip()


def build_us_r2_annual_robustness_base_plan(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    *,
    year: int,
) -> USR2AnnualRobustnessBasePlan:
    query = source_plan.query
    if tuple(sorted(query.assets)) != FROZEN_ASSETS:
        raise ValueError("US-R2 robustness base requires the complete frozen 25-name source query")
    if query.interval is not BarInterval.MINUTE_1:
        raise ValueError("US-R2 robustness source query must be 1m")
    if query.session_policy.value != "regular":
        raise ValueError("US-R2 robustness source query must be regular-session only")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-R2 robustness source query must preserve RAW prices")
    if query.availability_policy is not AvailabilityPolicy.EVENT_TIME:
        raise ValueError("US-R2 robustness source query must use event-time source rows")
    if {item.value for item in query.fields} != {"open", "high", "low", "close", "volume"}:
        raise ValueError("US-R2 robustness source query requires exactly OHLCV")
    if sessionization_evidence.sessionized_plan_id != source_plan.plan_id:
        raise ValueError("US-R2 robustness sessionization/source plan mismatch")
    if sessionization_evidence.calendar_id != FROZEN_CALENDAR_ID:
        raise ValueError("US-R2 robustness sessionization must bind the frozen calendar")
    if not ROBUSTNESS_FIRST_YEAR <= year <= ROBUSTNESS_LAST_YEAR:
        raise ValueError("US-R2 robustness year is outside OOS 2006-2026")

    policy = canonical_us_r2_robustness_materialization_policy()
    frozen = canonical_us_r2_frozen_protocol()
    data_version = _canonical_hash(
        {
            "policy_id": policy.policy_id,
            "frozen_protocol_id": frozen.freeze_id,
            "year": year,
            "source_plan_id": source_plan.plan_id,
            "sessionization_evidence_id": sessionization_evidence.evidence_id,
            "calendar_id": FROZEN_CALENDAR_ID,
            "slices": [item.to_dict() for item in policy.slices],
            "source_execution_strategy": "one_materialized_sessionized_1m_cte_per_year",
        },
        prefix="us-r2-robustness-base-data-version",
    )
    bar_relations: dict[BarInterval, str] = {}
    bar_ctes: list[str] = []
    for interval in (BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30):
        relation, cte = _bar_ctes(interval)
        bar_relations[interval] = relation
        bar_ctes.append(cte)
    slice_selects = [
        _slice_select(
            item,
            bars_relation=bar_relations[item.signal_interval],
            source_data_literal=_sql_string(source_plan.data_version),
            policy_literal=_sql_string(policy.policy_id),
            data_literal=_sql_string(data_version),
        )
        for item in policy.slices
    ]
    sql = f"""
        WITH source_rows AS MATERIALIZED (
            {source_plan.sql}
        ),
        year_rows AS MATERIALIZED (
            SELECT *
            FROM source_rows AS d
            WHERE d.is_regular_session
              AND d.minute_offset IS NOT NULL
              AND EXTRACT(year FROM d.session_date) = {year}
        ),
        {', '.join(bar_ctes)},
        anchor_rows AS MATERIALIZED (
            SELECT *
            FROM year_rows AS s
            WHERE (s.minute_offset + 1) % 5 = 0
        ),
        {', '.join(_label_cte(horizon) for horizon in (30, 60, 120))},
        slices AS (
            {' UNION ALL '.join(slice_selects)}
        )
        SELECT {', '.join(ROBUSTNESS_BASE_OUTPUT_COLUMNS)}
        FROM slices
        ORDER BY available_at, slice_id, research_asset_id
    """.strip()
    return USR2AnnualRobustnessBasePlan(
        policy_id=policy.policy_id,
        frozen_protocol_id=frozen.freeze_id,
        year=year,
        source_plan_id=source_plan.plan_id,
        sessionization_evidence_id=sessionization_evidence.evidence_id,
        calendar_id=FROZEN_CALENDAR_ID,
        source_data_version=source_plan.data_version,
        data_version=data_version,
        sql=sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
    )


@dataclass(frozen=True, slots=True)
class USR2RobustnessSliceSummary:
    slice_id: str
    row_count: int
    asset_count: int
    complete_bar_count: int
    label_available_count: int
    joint_available_count: int
    formation_count: int
    formation_count_at_minimum_cross_section: int
    minimum_joint_breadth: int
    maximum_joint_breadth: int

    def to_dict(self) -> dict[str, object]:
        return {
            "slice_id": self.slice_id,
            "row_count": self.row_count,
            "asset_count": self.asset_count,
            "complete_bar_count": self.complete_bar_count,
            "label_available_count": self.label_available_count,
            "joint_available_count": self.joint_available_count,
            "formation_count": self.formation_count,
            "formation_count_at_minimum_cross_section": self.formation_count_at_minimum_cross_section,
            "minimum_joint_breadth": self.minimum_joint_breadth,
            "maximum_joint_breadth": self.maximum_joint_breadth,
        }


@dataclass(frozen=True, slots=True)
class USR2AnnualRobustnessBaseEvidence:
    plan_id: str
    policy_id: str
    year: int
    materialization_id: str
    row_count: int
    first_session_date: date | None
    last_session_date: date | None
    slices: tuple[USR2RobustnessSliceSummary, ...]
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-annual-robustness-base-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-robustness-base")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "policy_id": self.policy_id,
            "year": self.year,
            "materialization_id": self.materialization_id,
            "row_count": self.row_count,
            "first_session_date": self.first_session_date.isoformat() if self.first_session_date else None,
            "last_session_date": self.last_session_date.isoformat() if self.last_session_date else None,
            "slice_count": len(self.slices),
            "slices": [item.to_dict() for item in self.slices],
            "blockers": list(self.blockers),
            "passed": self.passed,
            "source_scan_relation_count": 1,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "candidate_selection_applied": False,
            "alpha_gate_evaluated": False,
            "terminal_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


@dataclass(frozen=True, slots=True)
class USR2RobustnessSummaryPlan:
    plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...]


def build_us_r2_robustness_summary_plan(
    plan: USR2AnnualRobustnessBasePlan,
    *,
    relation_sql: str,
) -> USR2RobustnessSummaryPlan:
    if not relation_sql.strip():
        raise ValueError("US-R2 robustness summary relation SQL must be non-empty")
    minimum = canonical_us_r2_frozen_protocol().cross_section_policy.minimum_cross_section
    output_columns = (
        "slice_id",
        "row_count",
        "asset_count",
        "complete_bar_count",
        "label_available_count",
        "joint_available_count",
        "formation_count",
        "formation_count_at_minimum_cross_section",
        "minimum_joint_breadth",
        "maximum_joint_breadth",
        "total_row_count",
        "duplicate_key_count",
        "first_session_date",
        "last_session_date",
    )
    sql = f"""
        WITH panel AS (
            {relation_sql}
        ),
        breadth AS (
            SELECT
                slice_id,
                available_at,
                count(*) FILTER (WHERE is_complete AND label_available)::BIGINT AS joint_breadth
            FROM panel
            GROUP BY slice_id, available_at
        ),
        slice_rows AS (
            SELECT
                slice_id,
                count(*)::BIGINT AS row_count,
                count(DISTINCT research_asset_id)::BIGINT AS asset_count,
                count(*) FILTER (WHERE is_complete)::BIGINT AS complete_bar_count,
                count(*) FILTER (WHERE label_available)::BIGINT AS label_available_count,
                count(*) FILTER (WHERE is_complete AND label_available)::BIGINT AS joint_available_count
            FROM panel
            GROUP BY slice_id
        ),
        slice_breadth AS (
            SELECT
                slice_id,
                count(*)::BIGINT AS formation_count,
                count(*) FILTER (WHERE joint_breadth >= {minimum})::BIGINT
                    AS formation_count_at_minimum_cross_section,
                COALESCE(min(joint_breadth), 0)::BIGINT AS minimum_joint_breadth,
                COALESCE(max(joint_breadth), 0)::BIGINT AS maximum_joint_breadth
            FROM breadth
            GROUP BY slice_id
        ),
        global_stats AS (
            SELECT
                count(*)::BIGINT AS total_row_count,
                (
                    count(*) - count(DISTINCT struct_pack(
                        slice_id := slice_id,
                        research_asset_id := research_asset_id,
                        available_at := available_at
                    ))
                )::BIGINT AS duplicate_key_count,
                min(session_date) AS first_session_date,
                max(session_date) AS last_session_date
            FROM panel
        )
        SELECT
            r.slice_id,
            r.row_count,
            r.asset_count,
            r.complete_bar_count,
            r.label_available_count,
            r.joint_available_count,
            b.formation_count,
            b.formation_count_at_minimum_cross_section,
            b.minimum_joint_breadth,
            b.maximum_joint_breadth,
            g.total_row_count,
            g.duplicate_key_count,
            g.first_session_date,
            g.last_session_date
        FROM slice_rows AS r
        JOIN slice_breadth AS b USING (slice_id)
        CROSS JOIN global_stats AS g
        ORDER BY r.slice_id
    """.strip()
    return USR2RobustnessSummaryPlan(
        plan_id=_canonical_hash(
            {"base_plan_id": plan.plan_id, "output_columns": list(output_columns)},
            prefix="us-r2-robustness-summary-plan",
        ),
        data_version=plan.data_version,
        sql=sql,
        output_columns=output_columns,
    )


def build_us_r2_annual_robustness_base_evidence(
    plan: USR2AnnualRobustnessBasePlan,
    materialization: MinuteMaterialization,
    summary_rows: tuple[Mapping[str, object], ...],
) -> USR2AnnualRobustnessBaseEvidence:
    if materialization.plan_id != plan.plan_id or materialization.data_version != plan.data_version:
        raise ValueError("US-R2 robustness materialization identity mismatch")
    if not summary_rows:
        raise ValueError("US-R2 robustness summary is empty")
    expected_ids = tuple(sorted(item.slice_id for item in canonical_us_r2_robustness_slices()))
    observed_ids = tuple(_text(row.get("slice_id"), "summary.slice_id") for row in summary_rows)
    if observed_ids != expected_ids:
        raise ValueError("US-R2 robustness summary slice set/order mismatch")

    total_row_count = _integer(summary_rows[0].get("total_row_count"), "total_row_count")
    duplicate_key_count = _integer(summary_rows[0].get("duplicate_key_count"), "duplicate_key_count")
    if total_row_count != materialization.row_count:
        raise ValueError("US-R2 robustness summary/materialization row-count mismatch")
    first_raw = summary_rows[0].get("first_session_date")
    last_raw = summary_rows[0].get("last_session_date")
    first_session = date.fromisoformat(str(first_raw)) if first_raw is not None else None
    last_session = date.fromisoformat(str(last_raw)) if last_raw is not None else None

    blockers: list[str] = []
    if total_row_count == 0:
        blockers.append("robustness_base_empty")
    if duplicate_key_count:
        blockers.append(f"duplicate_slice_asset_formation_keys:{duplicate_key_count}")
    if first_session is not None and first_session.year != plan.year:
        blockers.append("first_session_outside_plan_year")
    if last_session is not None and last_session.year != plan.year:
        blockers.append("last_session_outside_plan_year")

    minimum = canonical_us_r2_frozen_protocol().cross_section_policy.minimum_cross_section
    slices: list[USR2RobustnessSliceSummary] = []
    for row in summary_rows:
        item = USR2RobustnessSliceSummary(
            slice_id=_text(row.get("slice_id"), "slice_id"),
            row_count=_integer(row.get("row_count"), "row_count"),
            asset_count=_integer(row.get("asset_count"), "asset_count"),
            complete_bar_count=_integer(row.get("complete_bar_count"), "complete_bar_count"),
            label_available_count=_integer(row.get("label_available_count"), "label_available_count"),
            joint_available_count=_integer(row.get("joint_available_count"), "joint_available_count"),
            formation_count=_integer(row.get("formation_count"), "formation_count"),
            formation_count_at_minimum_cross_section=_integer(
                row.get("formation_count_at_minimum_cross_section"),
                "formation_count_at_minimum_cross_section",
            ),
            minimum_joint_breadth=_integer(row.get("minimum_joint_breadth"), "minimum_joint_breadth"),
            maximum_joint_breadth=_integer(row.get("maximum_joint_breadth"), "maximum_joint_breadth"),
        )
        if item.row_count == 0 or item.formation_count == 0:
            blockers.append(f"slice_empty:{item.slice_id}")
        if item.formation_count_at_minimum_cross_section == 0:
            blockers.append(f"slice_never_reaches_minimum_cross_section:{item.slice_id}")
        if item.maximum_joint_breadth < minimum:
            blockers.append(f"slice_maximum_breadth_below_frozen_minimum:{item.slice_id}")
        if not 1 <= item.asset_count <= len(FROZEN_ASSETS):
            blockers.append(f"slice_asset_count_invalid:{item.slice_id}:{item.asset_count}")
        slices.append(item)

    return USR2AnnualRobustnessBaseEvidence(
        plan_id=plan.plan_id,
        policy_id=plan.policy_id,
        year=plan.year,
        materialization_id=materialization.materialization_id,
        row_count=total_row_count,
        first_session_date=first_session,
        last_session_date=last_session,
        slices=tuple(slices),
        blockers=tuple(sorted(set(blockers))),
    )
