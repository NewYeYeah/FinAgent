from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import (
    SessionizationEvidence,
    canonical_same_session_60m_label_spec,
)
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_materialization import (
    canonical_us_r1_feature_formation_policy,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    FROZEN_FIRST_RESEARCH_YEAR,
    FROZEN_LAST_RESEARCH_YEAR,
    canonical_us_r2_frozen_protocol,
)
from finagent.research.us_r2_regime_projection_v2 import (
    canonical_us_r2_regime_endpoint_policy,
)

FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID = "us-r2-regime-projection-v2-337a6ce4272376aa401d4f4b"
FROZEN_REGIME_PROJECTION_V2_PLAN_ID = "us-r2-regime-projection-plan-v2-1dc872be45ecbfb49107a7c0"
FROZEN_REGIME_PROJECTION_V2_MATERIALIZATION_ID = "minute-materialization-938010968243986f7129bae8"
BASE_INTERVAL_MINUTES = 15
LABEL_HORIZON_MINUTES = 60


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


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
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


def validate_us_r2_regime_projection_v2_gate(document: Mapping[str, object]) -> str:
    """Bind R2-1b to the reviewed real v2 regime evidence without reading candidate results."""

    expected_freeze = canonical_us_r2_frozen_protocol().freeze_id
    expected_endpoint = canonical_us_r2_regime_endpoint_policy().policy_id
    if _text(document.get("schema_version"), "regime.schema_version") != (
        "finagent.us-r2-regime-projection-evidence.v2"
    ):
        raise ValueError("R2-1b requires US-R2 regime projection evidence v2")
    if _text(document.get("evidence_id"), "regime.evidence_id") != (
        FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID
    ):
        raise ValueError("R2-1b regime evidence identity differs from the reviewed workstation run")
    if _text(document.get("plan_id"), "regime.plan_id") != FROZEN_REGIME_PROJECTION_V2_PLAN_ID:
        raise ValueError("R2-1b regime plan identity differs from the reviewed workstation run")
    if _text(document.get("materialization_id"), "regime.materialization_id") != (
        FROZEN_REGIME_PROJECTION_V2_MATERIALIZATION_ID
    ):
        raise ValueError("R2-1b regime materialization identity differs from the reviewed workstation run")
    if _text(document.get("frozen_protocol_id"), "regime.frozen_protocol_id") != expected_freeze:
        raise ValueError("R2-1b regime evidence/frozen protocol identity mismatch")
    if _text(document.get("endpoint_policy_id"), "regime.endpoint_policy_id") != expected_endpoint:
        raise ValueError("R2-1b regime endpoint-policy identity mismatch")
    if document.get("passed") is not True or document.get("blockers") != []:
        raise ValueError("R2-1b requires a passed blocker-free regime projection")
    if document.get("candidate_performance_read") is not False:
        raise ValueError("R2-1b regime gate must not have read candidate performance")
    if document.get("candidate_dependent_scan") is not False:
        raise ValueError("R2-1b regime gate must remain candidate independent")
    minimum = _integer(document.get("minimum_sessions_per_regime"), "minimum_sessions_per_regime")
    if minimum != 20:
        raise ValueError("R2-1b regime gate must preserve the reviewed 20-session minimum")
    summaries = document.get("fold_summaries")
    if not isinstance(summaries, list) or len(summaries) != 5:
        raise ValueError("R2-1b requires five reviewed regime fold summaries")
    labels = set(canonical_us_r2_frozen_protocol().classifier_policy.labels)
    for index, raw in enumerate(summaries):
        summary = _mapping(raw, f"fold_summaries[{index}]")
        label_counts = _mapping(summary.get("label_counts"), f"fold_summaries[{index}].label_counts")
        if set(str(item) for item in label_counts) != labels:
            raise ValueError("R2-1b regime summary label set differs from the frozen classifier")
        for label in labels:
            if _integer(label_counts.get(label), f"fold_summaries[{index}].label_counts.{label}") < minimum:
                raise ValueError("R2-1b regime summary falls below the reviewed minimum")
    return FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID


@dataclass(frozen=True, slots=True)
class USR2AnnualBasePanelPlan:
    frozen_protocol_id: str
    regime_projection_evidence_id: str
    year: int
    source_plan_id: str
    sessionization_evidence_id: str
    calendar_id: str
    source_data_version: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...] = (
        "research_asset_id",
        "session_date",
        "session_id",
        "event_time",
        "available_at",
        "interval",
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
        "frozen_protocol_id",
        "regime_projection_evidence_id",
        "data_version",
    )
    schema_version: str = "finagent.us-r2-annual-base-panel-plan.v1"

    def __post_init__(self) -> None:
        if not FROZEN_FIRST_RESEARCH_YEAR <= self.year <= FROZEN_LAST_RESEARCH_YEAR:
            raise ValueError("US-R2 base-panel year is outside the frozen research range")
        for field_name in (
            "frozen_protocol_id",
            "regime_projection_evidence_id",
            "source_plan_id",
            "sessionization_evidence_id",
            "calendar_id",
            "source_data_version",
            "data_version",
            "sql",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.regime_projection_evidence_id != FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID:
            raise ValueError("US-R2 base panel must bind the reviewed regime v2 evidence")
        if self.calendar_id != FROZEN_CALENDAR_ID:
            raise ValueError("US-R2 base panel must preserve the frozen XNYS calendar")
        if self.selected_size_bytes < 0:
            raise ValueError("selected_size_bytes must be non-negative")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "frozen_protocol_id": self.frozen_protocol_id,
                "regime_projection_evidence_id": self.regime_projection_evidence_id,
                "year": self.year,
                "source_plan_id": self.source_plan_id,
                "sessionization_evidence_id": self.sessionization_evidence_id,
                "calendar_id": self.calendar_id,
                "source_data_version": self.source_data_version,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
                "source_execution_strategy": "single_materialized_source_cte_for_bars_and_labels",
            },
            prefix="us-r2-base-panel-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "frozen_protocol_id": self.frozen_protocol_id,
            "regime_projection_evidence_id": self.regime_projection_evidence_id,
            "year": self.year,
            "source_plan_id": self.source_plan_id,
            "sessionization_evidence_id": self.sessionization_evidence_id,
            "calendar_id": self.calendar_id,
            "source_data_version": self.source_data_version,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "bar_interval": BarInterval.MINUTE_15.value,
            "label_spec_id": canonical_same_session_60m_label_spec().label_id,
            "formation_policy_id": canonical_us_r1_feature_formation_policy().policy_id,
            "source_scan_relation_count": 1,
            "source_cte_materialized": True,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "output_columns": list(self.output_columns),
            "alpha_authority": False,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USR2BasePanelSummaryPlan:
    base_panel_plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...] = (
        "row_count",
        "asset_count",
        "complete_bar_count",
        "label_available_count",
        "joint_available_count",
        "duplicate_key_count",
        "unexpected_asset_count",
        "formation_count",
        "formation_count_at_minimum_cross_section",
        "minimum_joint_breadth",
        "maximum_joint_breadth",
        "first_session_date",
        "last_session_date",
    )

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "base_panel_plan_id": self.base_panel_plan_id,
                "data_version": self.data_version,
                "output_columns": list(self.output_columns),
            },
            prefix="us-r2-base-panel-summary-plan",
        )


@dataclass(frozen=True, slots=True)
class USR2AnnualBasePanelEvidence:
    plan_id: str
    regime_projection_evidence_id: str
    year: int
    materialization_id: str
    row_count: int
    asset_count: int
    complete_bar_count: int
    label_available_count: int
    joint_available_count: int
    formation_count: int
    formation_count_at_minimum_cross_section: int
    minimum_joint_breadth: int
    maximum_joint_breadth: int
    first_session_date: date | None
    last_session_date: date | None
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-annual-base-panel-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-base-panel")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "regime_projection_evidence_id": self.regime_projection_evidence_id,
            "year": self.year,
            "materialization_id": self.materialization_id,
            "row_count": self.row_count,
            "asset_count": self.asset_count,
            "complete_bar_count": self.complete_bar_count,
            "label_available_count": self.label_available_count,
            "joint_available_count": self.joint_available_count,
            "formation_count": self.formation_count,
            "formation_count_at_minimum_cross_section": self.formation_count_at_minimum_cross_section,
            "minimum_joint_breadth": self.minimum_joint_breadth,
            "maximum_joint_breadth": self.maximum_joint_breadth,
            "first_session_date": self.first_session_date.isoformat() if self.first_session_date else None,
            "last_session_date": self.last_session_date.isoformat() if self.last_session_date else None,
            "blockers": list(self.blockers),
            "passed": self.passed,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_annual_base_panel_plan(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    *,
    year: int,
    regime_projection_evidence_id: str,
) -> USR2AnnualBasePanelPlan:
    frozen = canonical_us_r2_frozen_protocol()
    query = source_plan.query
    if tuple(sorted(query.assets)) != FROZEN_ASSETS:
        raise ValueError("US-R2 base panel requires the complete frozen 25-name source query")
    if query.interval is not BarInterval.MINUTE_1:
        raise ValueError("US-R2 base panel source query must be 1m")
    if query.session_policy.value != "regular":
        raise ValueError("US-R2 base panel source query must be regular-session only")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-R2 base panel source query must preserve raw prices")
    if query.availability_policy is not AvailabilityPolicy.EVENT_TIME:
        raise ValueError("US-R2 base panel source query must use event-time source rows")
    required_fields = {item.value for item in query.fields}
    if required_fields != {"open", "high", "low", "close", "volume"}:
        raise ValueError("US-R2 base panel source query requires exactly OHLCV fields")
    if sessionization_evidence.sessionized_plan_id != source_plan.plan_id:
        raise ValueError("US-R2 base panel sessionization/source plan mismatch")
    if sessionization_evidence.calendar_id != FROZEN_CALENDAR_ID:
        raise ValueError("US-R2 base panel sessionization must bind the frozen calendar")
    if regime_projection_evidence_id != FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID:
        raise ValueError("US-R2 base panel requires the reviewed v2 regime evidence")
    if not FROZEN_FIRST_RESEARCH_YEAR <= year <= FROZEN_LAST_RESEARCH_YEAR:
        raise ValueError("US-R2 base-panel year is outside the frozen research range")

    label_spec = canonical_same_session_60m_label_spec()
    formation_policy = canonical_us_r1_feature_formation_policy()
    frozen_literal = _sql_string(frozen.freeze_id)
    regime_literal = _sql_string(regime_projection_evidence_id)
    source_data_literal = _sql_string(source_plan.data_version)
    data_version = _canonical_hash(
        {
            "frozen_protocol_id": frozen.freeze_id,
            "regime_projection_evidence_id": regime_projection_evidence_id,
            "year": year,
            "source_plan_id": source_plan.plan_id,
            "sessionization_evidence_id": sessionization_evidence.evidence_id,
            "calendar_id": FROZEN_CALENDAR_ID,
            "bar_interval": BarInterval.MINUTE_15.value,
            "formation_policy_id": formation_policy.policy_id,
            "label_spec_id": label_spec.label_id,
            "source_execution_strategy": "single_materialized_source_cte_for_bars_and_labels",
        },
        prefix="us-r2-base-panel-data-version",
    )
    data_literal = _sql_string(data_version)
    interval_literal = _sql_string(BarInterval.MINUTE_15.value)

    sql = f"""
        WITH source_rows AS MATERIALIZED (
            {source_plan.sql}
        ),
        bucketed AS (
            SELECT
                d.*,
                CAST(floor(d.minute_offset / {BASE_INTERVAL_MINUTES}) AS BIGINT) AS bar_index
            FROM source_rows AS d
            WHERE d.is_regular_session
              AND d.minute_offset IS NOT NULL
              AND EXTRACT(year FROM d.session_date) = {year}
        ),
        bars AS (
            SELECT
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bar_index,
                d.session_open + d.bar_index * INTERVAL '{BASE_INTERVAL_MINUTES} minutes' AS event_time,
                d.session_open + (d.bar_index + 1) * INTERVAL '{BASE_INTERVAL_MINUTES} minutes' AS available_at,
                CAST(arg_min(d.open, d.event_time) AS DOUBLE) AS open,
                CAST(max(d.high) AS DOUBLE) AS high,
                CAST(min(d.low) AS DOUBLE) AS low,
                CAST(arg_max(d.close, d.event_time) AS DOUBLE) AS close,
                CAST(sum(d.volume) AS DOUBLE) AS volume,
                count(*)::BIGINT AS observed_minute_count,
                {BASE_INTERVAL_MINUTES}::BIGINT AS expected_minute_count,
                count(*)::DOUBLE / {BASE_INTERVAL_MINUTES}::DOUBLE AS coverage_ratio,
                count(*) = {BASE_INTERVAL_MINUTES} AS is_complete,
                min(d.source_id) AS source_id,
                min(d.source_revision) AS source_revision
            FROM bucketed AS d
            GROUP BY
                d.research_asset_id,
                d.session_date,
                d.session_id,
                d.session_open,
                d.session_close,
                d.bar_index
        ),
        label_sources AS (
            SELECT *
            FROM source_rows AS s
            WHERE s.is_regular_session
              AND s.minute_offset IS NOT NULL
              AND EXTRACT(year FROM s.session_date) = {year}
              AND (s.minute_offset + 1) % {BASE_INTERVAL_MINUTES} = 0
        ),
        labels AS (
            SELECT
                s.research_asset_id,
                s.session_date,
                s.available_at AS source_available_at,
                CAST(s.close AS DOUBLE) AS source_price,
                t.available_at AS target_available_at,
                CASE
                    WHEN s.minute_offset + {LABEL_HORIZON_MINUTES}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN NULL
                    WHEN t.event_time IS NULL THEN NULL
                    ELSE CAST(t.close / s.close - 1.0 AS DOUBLE)
                END AS label_value,
                CASE
                    WHEN s.minute_offset + {LABEL_HORIZON_MINUTES}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN false
                    WHEN t.event_time IS NULL THEN false
                    ELSE true
                END AS label_available,
                CASE
                    WHEN s.minute_offset + {LABEL_HORIZON_MINUTES}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN 'target_crosses_session'
                    WHEN t.event_time IS NULL THEN 'target_minute_missing'
                    ELSE NULL
                END AS unavailable_reason
            FROM label_sources AS s
            LEFT JOIN source_rows AS t
              ON t.research_asset_id = s.research_asset_id
             AND t.session_date = s.session_date
             AND t.minute_offset = s.minute_offset + {LABEL_HORIZON_MINUTES}
        )
        SELECT
            b.research_asset_id,
            b.session_date,
            b.session_id,
            b.event_time,
            b.available_at,
            {interval_literal} AS interval,
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
            l.source_available_at,
            l.source_price,
            l.target_available_at,
            l.label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE WHEN l.source_price IS NULL THEN NULL ELSE abs(b.close - l.source_price) END AS close_anchor_difference,
            b.source_id,
            b.source_revision,
            {source_data_literal} AS source_data_version,
            {frozen_literal} AS frozen_protocol_id,
            {regime_literal} AS regime_projection_evidence_id,
            {data_literal} AS data_version
        FROM bars AS b
        LEFT JOIN labels AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
        ORDER BY b.available_at, b.research_asset_id
    """.strip()

    return USR2AnnualBasePanelPlan(
        frozen_protocol_id=frozen.freeze_id,
        regime_projection_evidence_id=regime_projection_evidence_id,
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


def build_us_r2_base_panel_summary_plan(
    plan: USR2AnnualBasePanelPlan,
    *,
    relation_sql: str,
) -> USR2BasePanelSummaryPlan:
    if not relation_sql.strip():
        raise ValueError("US-R2 base-panel summary relation SQL must be non-empty")
    assets_sql = ", ".join(_sql_string(asset) for asset in FROZEN_ASSETS)
    minimum_cross_section = canonical_us_r2_frozen_protocol().cross_section_policy.minimum_cross_section
    sql = f"""
        WITH panel AS (
            {relation_sql}
        ),
        formation_breadth AS (
            SELECT
                available_at,
                count(*) FILTER (WHERE is_complete AND label_available)::BIGINT AS joint_breadth
            FROM panel
            GROUP BY available_at
        ),
        row_stats AS (
            SELECT
                count(*)::BIGINT AS row_count,
                count(DISTINCT research_asset_id)::BIGINT AS asset_count,
                count(*) FILTER (WHERE is_complete)::BIGINT AS complete_bar_count,
                count(*) FILTER (WHERE label_available)::BIGINT AS label_available_count,
                count(*) FILTER (WHERE is_complete AND label_available)::BIGINT AS joint_available_count,
                (
                    count(*) - count(DISTINCT struct_pack(
                        research_asset_id := research_asset_id,
                        available_at := available_at
                    ))
                )::BIGINT AS duplicate_key_count,
                count(*) FILTER (WHERE research_asset_id NOT IN ({assets_sql}))::BIGINT AS unexpected_asset_count,
                min(session_date) AS first_session_date,
                max(session_date) AS last_session_date
            FROM panel
        ),
        breadth_stats AS (
            SELECT
                count(*)::BIGINT AS formation_count,
                count(*) FILTER (WHERE joint_breadth >= {minimum_cross_section})::BIGINT
                    AS formation_count_at_minimum_cross_section,
                COALESCE(min(joint_breadth), 0)::BIGINT AS minimum_joint_breadth,
                COALESCE(max(joint_breadth), 0)::BIGINT AS maximum_joint_breadth
            FROM formation_breadth
        )
        SELECT
            r.row_count,
            r.asset_count,
            r.complete_bar_count,
            r.label_available_count,
            r.joint_available_count,
            r.duplicate_key_count,
            r.unexpected_asset_count,
            b.formation_count,
            b.formation_count_at_minimum_cross_section,
            b.minimum_joint_breadth,
            b.maximum_joint_breadth,
            r.first_session_date,
            r.last_session_date
        FROM row_stats AS r
        CROSS JOIN breadth_stats AS b
    """.strip()
    return USR2BasePanelSummaryPlan(
        base_panel_plan_id=plan.plan_id,
        data_version=plan.data_version,
        sql=sql,
    )


def build_us_r2_annual_base_panel_evidence(
    plan: USR2AnnualBasePanelPlan,
    materialization: MinuteMaterialization,
    summary: Mapping[str, object],
) -> USR2AnnualBasePanelEvidence:
    if materialization.plan_id != plan.plan_id or materialization.data_version != plan.data_version:
        raise ValueError("US-R2 base-panel materialization identity mismatch")
    row_count = _integer(summary.get("row_count"), "summary.row_count")
    if row_count != materialization.row_count:
        raise ValueError("US-R2 base-panel summary/materialization row-count mismatch")
    asset_count = _integer(summary.get("asset_count"), "summary.asset_count")
    complete_bar_count = _integer(summary.get("complete_bar_count"), "summary.complete_bar_count")
    label_available_count = _integer(summary.get("label_available_count"), "summary.label_available_count")
    joint_available_count = _integer(summary.get("joint_available_count"), "summary.joint_available_count")
    duplicate_key_count = _integer(summary.get("duplicate_key_count"), "summary.duplicate_key_count")
    unexpected_asset_count = _integer(summary.get("unexpected_asset_count"), "summary.unexpected_asset_count")
    formation_count = _integer(summary.get("formation_count"), "summary.formation_count")
    formation_count_at_minimum = _integer(
        summary.get("formation_count_at_minimum_cross_section"),
        "summary.formation_count_at_minimum_cross_section",
    )
    minimum_breadth = _integer(summary.get("minimum_joint_breadth"), "summary.minimum_joint_breadth")
    maximum_breadth = _integer(summary.get("maximum_joint_breadth"), "summary.maximum_joint_breadth")
    first_raw = summary.get("first_session_date")
    last_raw = summary.get("last_session_date")
    first_session = date.fromisoformat(str(first_raw)) if first_raw is not None else None
    last_session = date.fromisoformat(str(last_raw)) if last_raw is not None else None

    blockers: list[str] = []
    if row_count == 0:
        blockers.append("base_panel_empty")
    if duplicate_key_count:
        blockers.append(f"duplicate_asset_formation_keys:{duplicate_key_count}")
    if unexpected_asset_count:
        blockers.append(f"unexpected_assets:{unexpected_asset_count}")
    if asset_count > len(FROZEN_ASSETS):
        blockers.append(f"asset_count_exceeds_frozen_universe:{asset_count}")
    if formation_count and formation_count_at_minimum == 0:
        blockers.append("no_formation_reaches_frozen_minimum_cross_section")
    if first_session is not None and first_session.year != plan.year:
        blockers.append("first_session_outside_plan_year")
    if last_session is not None and last_session.year != plan.year:
        blockers.append("last_session_outside_plan_year")

    return USR2AnnualBasePanelEvidence(
        plan_id=plan.plan_id,
        regime_projection_evidence_id=plan.regime_projection_evidence_id,
        year=plan.year,
        materialization_id=materialization.materialization_id,
        row_count=row_count,
        asset_count=asset_count,
        complete_bar_count=complete_bar_count,
        label_available_count=label_available_count,
        joint_available_count=joint_available_count,
        formation_count=formation_count,
        formation_count_at_minimum_cross_section=formation_count_at_minimum,
        minimum_joint_breadth=minimum_breadth,
        maximum_joint_breadth=maximum_breadth,
        first_session_date=first_session,
        last_session_date=last_session,
        blockers=tuple(sorted(blockers)),
    )
