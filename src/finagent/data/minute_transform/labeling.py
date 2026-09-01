from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from finagent.data.minute_store import MinuteQueryPlan
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import (
    AvailabilityPolicy,
    LabelHorizonUnit,
    LabelMetric,
    LabelSpec,
    ResearchPriceBasis,
)
from finagent.domain.market_bars import BarInterval

from .sessionize import CalendarSessionizedMinuteStore, SessionizationEvidence

CANONICAL_US_60M_LABEL_NAME = "us_same_session_60m_simple_return_raw"


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def canonical_same_session_60m_label_spec() -> LabelSpec:
    return LabelSpec(
        metric=LabelMetric.SIMPLE_RETURN,
        horizon=60,
        horizon_unit=LabelHorizonUnit.TRADING_MINUTES,
        allow_cross_session=False,
        price_basis=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        name=CANONICAL_US_60M_LABEL_NAME,
    )


@dataclass(frozen=True, slots=True)
class LabelMaterializationSpec:
    label_spec: LabelSpec
    calendar_id: str
    source_interval: BarInterval = BarInterval.MINUTE_1
    source_price_field: MarketDataField = MarketDataField.CLOSE
    target_match_policy: str = "exact_same_session_minute_offset"
    emit_unavailable_rows: bool = True
    schema_version: str = "finagent.label-materialization-spec.v1"

    def __post_init__(self) -> None:
        calendar_id = self.calendar_id.strip()
        if not calendar_id:
            raise ValueError("calendar_id must be non-empty")
        if self.source_interval is not BarInterval.MINUTE_1:
            raise ValueError("v1 labels require source_interval=1m")
        if self.source_price_field is not MarketDataField.CLOSE:
            raise ValueError("v1 labels use close as the source/target price")
        if self.label_spec.horizon_unit is not LabelHorizonUnit.TRADING_MINUTES:
            raise ValueError("v1 labels require trading-minute horizons")
        if self.label_spec.allow_cross_session:
            raise ValueError("v1 labels must be same-session")
        if self.label_spec.price_basis is not ResearchPriceBasis.RAW:
            raise ValueError("v1 labels require raw price basis until action transforms exist")
        if self.label_spec.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
            raise ValueError("v1 labels require available_at PIT semantics")
        if self.target_match_policy != "exact_same_session_minute_offset":
            raise ValueError("v1 labels require exact same-session minute-offset targets")
        if not self.emit_unavailable_rows:
            raise ValueError("v1 labels preserve unavailable rows and reasons")
        object.__setattr__(self, "calendar_id", calendar_id)

    @property
    def spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="label-materialization-spec")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "label_spec": self.label_spec.to_dict(),
            "calendar_id": self.calendar_id,
            "source_interval": self.source_interval.value,
            "source_price_field": self.source_price_field.value,
            "target_match_policy": self.target_match_policy,
            "emit_unavailable_rows": self.emit_unavailable_rows,
        }
        if include_id:
            payload["spec_id"] = self.spec_id
        return payload


@dataclass(frozen=True, slots=True)
class LabelQueryPlan:
    source_query: MarketDataQuery
    materialization_spec_id: str
    label_spec_id: str
    source_plan_id: str
    source_data_version: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.label-query-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "source_query_id": self.source_query.query_id,
                "materialization_spec_id": self.materialization_spec_id,
                "label_spec_id": self.label_spec_id,
                "source_plan_id": self.source_plan_id,
                "source_data_version": self.source_data_version,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
            },
            prefix="label-query-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "source_query": self.source_query.to_dict(),
            "materialization_spec_id": self.materialization_spec_id,
            "label_spec_id": self.label_spec_id,
            "source_plan_id": self.source_plan_id,
            "source_data_version": self.source_data_version,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
        }


@dataclass(frozen=True, slots=True)
class LabelSeriesEvidence:
    materialization_spec_id: str
    label_spec_id: str
    calendar_id: str
    sessionization_evidence_id: str
    source_plan_id: str
    label_plan_id: str
    source_data_version: str
    label_data_version: str
    schema_version: str = "finagent.label-series-evidence.v1"

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="label-series")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "materialization_spec_id": self.materialization_spec_id,
            "label_spec_id": self.label_spec_id,
            "calendar_id": self.calendar_id,
            "sessionization_evidence_id": self.sessionization_evidence_id,
            "source_plan_id": self.source_plan_id,
            "label_plan_id": self.label_plan_id,
            "source_data_version": self.source_data_version,
            "label_data_version": self.label_data_version,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def _label_data_version(
    *,
    source_data_version: str,
    spec: LabelMaterializationSpec,
) -> str:
    return _canonical_hash(
        {
            "source_data_version": source_data_version,
            "materialization_spec_id": spec.spec_id,
            "label_spec_id": spec.label_spec.label_id,
            "calendar_id": spec.calendar_id,
        },
        prefix="label-data-version",
    )


def _label_value_sql(metric: LabelMetric) -> str:
    if metric is LabelMetric.SIMPLE_RETURN:
        return "CAST(t.close / s.close - 1.0 AS DOUBLE)"
    if metric is LabelMetric.LOG_RETURN:
        return "CAST(ln(t.close / s.close) AS DOUBLE)"
    raise ValueError(f"unsupported label metric {metric!r}")  # pragma: no cover


def _require_label_source_query(query: MarketDataQuery, label_spec: LabelSpec) -> None:
    if query.interval is not BarInterval.MINUTE_1:
        raise ValueError("label source query interval must be 1m")
    if query.session_policy is not SessionPolicy.REGULAR:
        raise ValueError("label source query session_policy must be regular")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("label source query must use raw prices")
    if query.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
        raise ValueError("label source query must use available_at")
    if query.fields != (MarketDataField.CLOSE,):
        raise ValueError("label source query fields must be exactly (close,)")
    if query.adjustment_policy is not label_spec.price_basis:
        raise ValueError("label source price basis must match LabelSpec")
    if query.availability_policy is not label_spec.availability_policy:
        raise ValueError("label source availability policy must match LabelSpec")


def build_same_session_label_plan(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    source_query: MarketDataQuery,
    materialization_spec: LabelMaterializationSpec,
) -> tuple[LabelQueryPlan, LabelSeriesEvidence]:
    horizon = materialization_spec.label_spec.horizon
    label_spec_id = materialization_spec.label_spec.label_id
    materialization_spec_id = materialization_spec.spec_id
    data_version = _label_data_version(
        source_data_version=source_plan.data_version,
        spec=materialization_spec,
    )
    value_sql = _label_value_sql(materialization_spec.label_spec.metric)
    label_id_literal = _sql_string(label_spec_id)
    materialization_spec_literal = _sql_string(materialization_spec_id)
    calendar_literal = _sql_string(materialization_spec.calendar_id)
    data_version_literal = _sql_string(data_version)
    source_start_literal = _sql_string(source_query.start.isoformat())
    source_end_literal = _sql_string(source_query.end.isoformat())
    output_columns = (
        "research_asset_id",
        "session_date",
        "source_event_time",
        "source_available_at",
        "source_minute_offset",
        "source_price",
        "target_event_time",
        "target_available_at",
        "target_minute_offset",
        "target_price",
        "label_value",
        "label_available",
        "unavailable_reason",
        "label_spec_id",
        "materialization_spec_id",
        "calendar_id",
        "source_id",
        "source_revision",
        "source_data_version",
        "data_version",
    )
    sql = f"""
        WITH source_rows AS (
            {source_plan.sql}
        ),
        source_candidates AS (
            SELECT *
            FROM source_rows AS d
            WHERE d.available_at >= TIMESTAMPTZ {source_start_literal}
              AND d.available_at < TIMESTAMPTZ {source_end_literal}
        ),
        labeled AS (
            SELECT
                s.research_asset_id,
                s.session_date,
                s.event_time AS source_event_time,
                s.available_at AS source_available_at,
                s.minute_offset AS source_minute_offset,
                CAST(s.close AS DOUBLE) AS source_price,
                t.event_time AS target_event_time,
                t.available_at AS target_available_at,
                s.minute_offset + {horizon} AS target_minute_offset,
                CAST(t.close AS DOUBLE) AS target_price,
                CASE
                    WHEN s.minute_offset + {horizon}
                        >= date_diff('minute', s.session_open, s.session_close)
                    THEN NULL
                    WHEN t.event_time IS NULL THEN NULL
                    ELSE {value_sql}
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
                END AS unavailable_reason,
                {label_id_literal} AS label_spec_id,
                {materialization_spec_literal} AS materialization_spec_id,
                {calendar_literal} AS calendar_id,
                s.source_id,
                s.source_revision,
                {_sql_string(source_plan.data_version)} AS source_data_version,
                {data_version_literal} AS data_version
            FROM source_candidates AS s
            LEFT JOIN source_rows AS t
              ON t.research_asset_id = s.research_asset_id
             AND t.session_date = s.session_date
             AND t.minute_offset = s.minute_offset + {horizon}
        )
        SELECT {', '.join(output_columns)}
        FROM labeled
        ORDER BY source_event_time, research_asset_id
    """.strip()
    plan = LabelQueryPlan(
        source_query=source_query,
        materialization_spec_id=materialization_spec_id,
        label_spec_id=label_spec_id,
        source_plan_id=source_plan.plan_id,
        source_data_version=source_plan.data_version,
        data_version=data_version,
        sql=sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
        output_columns=output_columns,
    )
    evidence = LabelSeriesEvidence(
        materialization_spec_id=materialization_spec_id,
        label_spec_id=label_spec_id,
        calendar_id=materialization_spec.calendar_id,
        sessionization_evidence_id=sessionization_evidence.evidence_id,
        source_plan_id=source_plan.plan_id,
        label_plan_id=plan.plan_id,
        source_data_version=source_plan.data_version,
        label_data_version=data_version,
    )
    return plan, evidence


class SameSessionLabelStore:
    def __init__(self, sessionized_store: CalendarSessionizedMinuteStore) -> None:
        self.sessionized_store = sessionized_store

    def plan(
        self,
        source_query: MarketDataQuery,
        label_spec: LabelSpec,
    ) -> tuple[LabelQueryPlan, LabelSeriesEvidence]:
        _require_label_source_query(source_query, label_spec)
        materialization_spec = LabelMaterializationSpec(
            label_spec=label_spec,
            calendar_id=self.sessionized_store.calendar.calendar_id,
        )
        expanded_query = MarketDataQuery(
            market_id=source_query.market_id,
            assets=source_query.assets,
            start=source_query.start,
            end=source_query.end + timedelta(minutes=label_spec.horizon),
            interval=BarInterval.MINUTE_1,
            fields=(MarketDataField.CLOSE,),
            session_policy=SessionPolicy.REGULAR,
            adjustment_policy=source_query.adjustment_policy,
            availability_policy=AvailabilityPolicy.AVAILABLE_AT,
        )
        source_plan, sessionization_evidence = self.sessionized_store.plan(expanded_query)
        return build_same_session_label_plan(
            source_plan,
            sessionization_evidence,
            source_query,
            materialization_spec,
        )
