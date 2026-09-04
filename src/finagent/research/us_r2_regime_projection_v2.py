from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import SessionizationEvidence
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r1_evaluation_policy import (
    canonical_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_COMMON_ALL_ASSET_END,
    FROZEN_FIRST_RESEARCH_YEAR,
    REGIME_ANCHOR_ASSET,
    REGIME_LOOKBACK_SESSIONS,
    USR2FrozenResearchProtocol,
    canonical_us_r2_frozen_protocol,
)

ENDPOINT_BAND_MINUTES = 15
MINIMUM_ENDPOINT_OBSERVATIONS = 2


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


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric or null")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _date_value(value: object, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value, field_name))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO date") from exc


def _calendar_sessions(
    calendar: TradingCalendarEvidence,
    *,
    start: date,
    end: date,
) -> tuple[TradingSession, ...]:
    sessions = tuple(item for item in calendar.sessions if start <= item.session_date <= end)
    if not sessions:
        raise ValueError("US-R2 v2 regime projection calendar window contains no sessions")
    return sessions


def _calendar_relation_sql(sessions: tuple[TradingSession, ...]) -> str:
    rows = [
        "("
        f"DATE {_sql_string(item.session_date.isoformat())}, "
        f"{item.regular_minutes}::BIGINT"
        ")"
        for item in sessions
    ]
    return (
        "SELECT * FROM (VALUES\n                "
        + ",\n                ".join(rows)
        + ") AS sessions(session_date, expected_regular_minute_count)"
    )


def _fold_relation_sql(protocol: USR2FrozenResearchProtocol) -> str:
    rows = []
    for fold in protocol.walk_forward_protocol.folds:
        rows.append(
            "("
            f"{_sql_string(fold.fold_id)}, "
            f"DATE {_sql_string(fold.train_start.isoformat())}, "
            f"DATE {_sql_string(fold.train_end.isoformat())}, "
            f"DATE {_sql_string(fold.evaluation_start.isoformat())}, "
            f"DATE {_sql_string(fold.evaluation_end.isoformat())}"
            ")"
        )
    return (
        "SELECT * FROM (VALUES\n                "
        + ",\n                ".join(rows)
        + ") AS folds(fold_id, train_start, train_end, evaluation_start, evaluation_end)"
    )


def _expected_evaluation_sessions(
    calendar: TradingCalendarEvidence,
    protocol: USR2FrozenResearchProtocol,
) -> tuple[tuple[str, int], ...]:
    counts: list[tuple[str, int]] = []
    for fold in protocol.walk_forward_protocol.folds:
        count = sum(
            1
            for session in calendar.sessions
            if fold.evaluation_start <= session.session_date < fold.evaluation_end
        )
        if count < 1:
            raise ValueError(f"US-R2 fold {fold.fold_id} has no calendar evaluation sessions")
        counts.append((fold.fold_id, count))
    return tuple(counts)


@dataclass(frozen=True, slots=True)
class USR2RegimeEndpointPolicy:
    endpoint_band_minutes: int = ENDPOINT_BAND_MINUTES
    minimum_endpoint_observations: int = MINIMUM_ENDPOINT_OBSERVATIONS
    interior_minute_completeness_required: bool = False
    open_price_semantics: str = "open_of_first_observed_regular_minute"
    close_price_semantics: str = "close_of_last_observed_regular_minute"
    endpoint_clock: str = "minute_offset_from_calendar_regular_open"
    schema_version: str = "finagent.us-r2-regime-endpoint-policy.v1"

    def __post_init__(self) -> None:
        if self.endpoint_band_minutes != 15:
            raise ValueError("US-R2 endpoint band must remain the canonical 15m signal interval")
        if self.minimum_endpoint_observations != 2:
            raise ValueError("US-R2 endpoint return requires at least two observed regular minutes")
        if self.interior_minute_completeness_required:
            raise ValueError("US-R2 endpoint return must not require irrelevant interior 1m completeness")
        if self.open_price_semantics != "open_of_first_observed_regular_minute":
            raise ValueError("US-R2 endpoint open semantics differ from preregistration")
        if self.close_price_semantics != "close_of_last_observed_regular_minute":
            raise ValueError("US-R2 endpoint close semantics differ from preregistration")
        if self.endpoint_clock != "minute_offset_from_calendar_regular_open":
            raise ValueError("US-R2 endpoint clock differs from preregistration")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-endpoint-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "endpoint_band_minutes": self.endpoint_band_minutes,
            "endpoint_band_source": "canonical_15m_signal_interval_not_result_tuned",
            "minimum_endpoint_observations": self.minimum_endpoint_observations,
            "interior_minute_completeness_required": self.interior_minute_completeness_required,
            "open_price_semantics": self.open_price_semantics,
            "close_price_semantics": self.close_price_semantics,
            "endpoint_clock": self.endpoint_clock,
            "same_session_raw_price_only": True,
            "candidate_performance_input": False,
            "candidate_rank_ic_input": False,
            "future_label_input": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


def canonical_us_r2_regime_endpoint_policy() -> USR2RegimeEndpointPolicy:
    return USR2RegimeEndpointPolicy()


@dataclass(frozen=True, slots=True)
class USR2RegimeProjectionPlanV2:
    frozen_protocol_id: str
    endpoint_policy: USR2RegimeEndpointPolicy
    source_plan_id: str
    sessionization_evidence_id: str
    calendar_id: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    expected_evaluation_sessions: tuple[tuple[str, int], ...]
    source_asset: str = REGIME_ANCHOR_ASSET
    output_columns: tuple[str, ...] = (
        "fold_id",
        "session_date",
        "regime_source_end_session",
        "regime_source_session_count",
        "regime_direction",
        "regime_volatility",
        "train_volatility_threshold",
        "train_volatility_observation_count",
        "regime_label",
        "regime_available",
        "unavailable_reason",
        "endpoint_policy_id",
        "frozen_protocol_id",
        "data_version",
    )
    schema_version: str = "finagent.us-r2-regime-projection-plan.v2"

    def __post_init__(self) -> None:
        for field_name in (
            "frozen_protocol_id",
            "source_plan_id",
            "sessionization_evidence_id",
            "calendar_id",
            "data_version",
            "sql",
            "source_asset",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} must be non-empty")
        if self.endpoint_policy != canonical_us_r2_regime_endpoint_policy():
            raise ValueError("US-R2 v2 requires the canonical endpoint-observation amendment")
        if self.source_asset != REGIME_ANCHOR_ASSET:
            raise ValueError("US-R2 regime projection source asset must remain IWM")
        if self.selected_size_bytes < 0:
            raise ValueError("selected_size_bytes must be non-negative")
        if len(self.expected_evaluation_sessions) != 5:
            raise ValueError("US-R2 regime projection must retain five frozen evaluation folds")
        if any(count < 1 for _fold_id, count in self.expected_evaluation_sessions):
            raise ValueError("every US-R2 evaluation fold requires at least one calendar session")

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "frozen_protocol_id": self.frozen_protocol_id,
                "endpoint_policy_id": self.endpoint_policy.policy_id,
                "source_plan_id": self.source_plan_id,
                "sessionization_evidence_id": self.sessionization_evidence_id,
                "calendar_id": self.calendar_id,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "expected_evaluation_sessions": list(self.expected_evaluation_sessions),
                "source_asset": self.source_asset,
                "output_columns": list(self.output_columns),
            },
            prefix="us-r2-regime-projection-plan-v2",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "frozen_protocol_id": self.frozen_protocol_id,
            "endpoint_policy": self.endpoint_policy.to_dict(),
            "source_plan_id": self.source_plan_id,
            "sessionization_evidence_id": self.sessionization_evidence_id,
            "calendar_id": self.calendar_id,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "expected_evaluation_sessions": [
                {"fold_id": fold_id, "session_count": count}
                for fold_id, count in self.expected_evaluation_sessions
            ],
            "source_asset": self.source_asset,
            "source_scan_asset_count": 1,
            "candidate_dependent_scan": False,
            "candidate_performance_read": False,
            "current_session_return_emitted": False,
            "source_price_emitted": False,
            "regime_state_availability_lag_sessions": 1,
            "output_columns": list(self.output_columns),
            "alpha_authority": False,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USR2RegimeFoldProjectionSummaryV2:
    fold_id: str
    expected_session_count: int
    observed_session_count: int
    available_session_count: int
    unavailable_session_count: int
    label_counts: tuple[tuple[str, int], ...]
    unavailable_reason_counts: tuple[tuple[str, int], ...]
    schema_version: str = "finagent.us-r2-regime-fold-projection-summary.v2"

    @property
    def observed_regimes(self) -> tuple[str, ...]:
        return tuple(label for label, count in self.label_counts if count > 0)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "fold_id": self.fold_id,
            "expected_session_count": self.expected_session_count,
            "observed_session_count": self.observed_session_count,
            "available_session_count": self.available_session_count,
            "unavailable_session_count": self.unavailable_session_count,
            "available_session_ratio": (
                self.available_session_count / self.observed_session_count
                if self.observed_session_count
                else 0.0
            ),
            "label_counts": dict(self.label_counts),
            "unavailable_reason_counts": dict(self.unavailable_reason_counts),
            "observed_regimes": list(self.observed_regimes),
        }


@dataclass(frozen=True, slots=True)
class USR2RegimeProjectionEvidenceV2:
    plan_id: str
    frozen_protocol_id: str
    endpoint_policy_id: str
    materialization_id: str
    materialized_row_count: int
    minimum_sessions_per_regime: int
    fold_summaries: tuple[USR2RegimeFoldProjectionSummaryV2, ...]
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-projection-evidence.v2"

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-projection-v2")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "frozen_protocol_id": self.frozen_protocol_id,
            "endpoint_policy_id": self.endpoint_policy_id,
            "materialization_id": self.materialization_id,
            "materialized_row_count": self.materialized_row_count,
            "minimum_sessions_per_regime": self.minimum_sessions_per_regime,
            "minimum_sessions_per_regime_source": "accepted_us_r1_minimum_oos_periods_per_fold",
            "fold_summaries": [item.to_dict() for item in self.fold_summaries],
            "blockers": list(self.blockers),
            "passed": self.passed,
            "candidate_performance_read": False,
            "candidate_dependent_scan": False,
            "current_session_return_emitted": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        return payload


def build_us_r2_regime_projection_plan_v2(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    calendar: TradingCalendarEvidence,
    frozen: USR2FrozenResearchProtocol,
) -> USR2RegimeProjectionPlanV2:
    canonical = canonical_us_r2_frozen_protocol()
    if frozen.freeze_id != canonical.freeze_id:
        raise ValueError("US-R2 v2 regime projection requires the canonical frozen protocol")
    query = source_plan.query
    if query.assets != (REGIME_ANCHOR_ASSET,):
        raise ValueError("US-R2 regime source query must contain IWM only")
    if query.interval is not BarInterval.MINUTE_1:
        raise ValueError("US-R2 regime source query must use 1m sessionized input")
    if query.availability_policy is not AvailabilityPolicy.EVENT_TIME:
        raise ValueError("US-R2 regime session aggregation must use minute event_time")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-R2 regime source must preserve raw same-session prices")
    if sessionization_evidence.sessionized_plan_id != source_plan.plan_id:
        raise ValueError("US-R2 sessionization evidence/source plan mismatch")
    if sessionization_evidence.calendar_id != calendar.calendar_id:
        raise ValueError("US-R2 sessionization/calendar identity mismatch")
    required_fields = {item.value for item in query.fields}
    if not {"open", "close"}.issubset(required_fields):
        raise ValueError("US-R2 IWM session-return source requires open and close")

    endpoint_policy = canonical_us_r2_regime_endpoint_policy()
    calendar_start = date(FROZEN_FIRST_RESEARCH_YEAR - 1, 5, 1)
    sessions = _calendar_sessions(calendar, start=calendar_start, end=FROZEN_COMMON_ALL_ASSET_END)
    calendar_sql = _calendar_relation_sql(sessions)
    fold_sql = _fold_relation_sql(frozen)
    frozen_id_literal = _sql_string(frozen.freeze_id)
    endpoint_id_literal = _sql_string(endpoint_policy.policy_id)
    data_version = _canonical_hash(
        {
            "frozen_protocol_id": frozen.freeze_id,
            "endpoint_policy_id": endpoint_policy.policy_id,
            "source_plan_id": source_plan.plan_id,
            "sessionization_evidence_id": sessionization_evidence.evidence_id,
            "calendar_id": calendar.calendar_id,
            "source_asset": REGIME_ANCHOR_ASSET,
            "session_return": "first_last_observed_regular_endpoint_return_raw_same_session",
            "regime_lookback_sessions": REGIME_LOOKBACK_SESSIONS,
            "availability_lag_sessions": 1,
            "volatility_threshold": "fold_train_median",
        },
        prefix="us-r2-regime-projection-data-version-v2",
    )
    data_version_literal = _sql_string(data_version)
    band = endpoint_policy.endpoint_band_minutes
    minimum_observations = endpoint_policy.minimum_endpoint_observations

    sql = f"""
        WITH source_rows AS (
            {source_plan.sql}
        ),
        calendar_sessions AS (
            {calendar_sql}
        ),
        observed_sessions AS (
            SELECT
                d.session_date,
                arg_min(CAST(d.open AS DOUBLE), d.event_time) AS session_open_price,
                arg_max(CAST(d.close AS DOUBLE), d.event_time) AS session_close_price,
                count(*)::BIGINT AS observed_regular_minute_count,
                min(d.minute_offset)::BIGINT AS minimum_minute_offset,
                max(d.minute_offset)::BIGINT AS maximum_minute_offset
            FROM source_rows AS d
            WHERE d.is_regular_session
            GROUP BY d.session_date
        ),
        calendar_joined AS (
            SELECT
                c.session_date,
                c.expected_regular_minute_count,
                COALESCE(o.observed_regular_minute_count, 0)::BIGINT AS observed_regular_minute_count,
                o.minimum_minute_offset,
                o.maximum_minute_offset,
                CASE
                    WHEN COALESCE(o.observed_regular_minute_count, 0) < {minimum_observations} THEN NULL
                    WHEN o.minimum_minute_offset >= {band} THEN NULL
                    WHEN o.maximum_minute_offset < c.expected_regular_minute_count - {band} THEN NULL
                    WHEN o.session_open_price IS NULL OR o.session_close_price IS NULL THEN NULL
                    WHEN o.session_open_price <= 0.0 OR o.session_close_price <= 0.0 THEN NULL
                    ELSE CAST(o.session_close_price / o.session_open_price - 1.0 AS DOUBLE)
                END AS session_return
            FROM calendar_sessions AS c
            LEFT JOIN observed_sessions AS o USING (session_date)
        ),
        rolling_unlagged AS (
            SELECT
                session_date,
                count(session_return) OVER (
                    ORDER BY session_date
                    ROWS BETWEEN {REGIME_LOOKBACK_SESSIONS - 1} PRECEDING AND CURRENT ROW
                )::BIGINT AS rolling_session_count,
                avg(session_return) OVER (
                    ORDER BY session_date
                    ROWS BETWEEN {REGIME_LOOKBACK_SESSIONS - 1} PRECEDING AND CURRENT ROW
                ) AS rolling_direction,
                stddev_pop(session_return) OVER (
                    ORDER BY session_date
                    ROWS BETWEEN {REGIME_LOOKBACK_SESSIONS - 1} PRECEDING AND CURRENT ROW
                ) AS rolling_volatility
            FROM calendar_joined
        ),
        lagged_state AS (
            SELECT
                session_date,
                lag(session_date, 1) OVER (ORDER BY session_date) AS regime_source_end_session,
                lag(rolling_session_count, 1) OVER (ORDER BY session_date) AS regime_source_session_count,
                lag(rolling_direction, 1) OVER (ORDER BY session_date) AS regime_direction,
                lag(rolling_volatility, 1) OVER (ORDER BY session_date) AS regime_volatility
            FROM rolling_unlagged
        ),
        folds AS (
            {fold_sql}
        ),
        thresholds AS (
            SELECT
                f.fold_id,
                median(s.regime_volatility) AS train_volatility_threshold,
                count(s.regime_volatility)::BIGINT AS train_volatility_observation_count
            FROM folds AS f
            LEFT JOIN lagged_state AS s
              ON s.session_date >= f.train_start
             AND s.session_date < f.train_end
             AND s.regime_source_session_count = {REGIME_LOOKBACK_SESSIONS}
             AND s.regime_volatility IS NOT NULL
            GROUP BY f.fold_id
        ),
        evaluation_sessions AS (
            SELECT
                f.fold_id,
                s.session_date,
                s.regime_source_end_session,
                s.regime_source_session_count,
                s.regime_direction,
                s.regime_volatility,
                t.train_volatility_threshold,
                t.train_volatility_observation_count
            FROM folds AS f
            INNER JOIN lagged_state AS s
              ON s.session_date >= f.evaluation_start
             AND s.session_date < f.evaluation_end
            LEFT JOIN thresholds AS t USING (fold_id)
        )
        SELECT
            fold_id,
            session_date,
            regime_source_end_session,
            regime_source_session_count,
            CAST(regime_direction AS DOUBLE) AS regime_direction,
            CAST(regime_volatility AS DOUBLE) AS regime_volatility,
            CAST(train_volatility_threshold AS DOUBLE) AS train_volatility_threshold,
            train_volatility_observation_count,
            CASE
                WHEN regime_source_session_count <> {REGIME_LOOKBACK_SESSIONS} THEN NULL
                WHEN regime_direction IS NULL OR regime_volatility IS NULL THEN NULL
                WHEN train_volatility_threshold IS NULL THEN NULL
                WHEN regime_direction >= 0.0 AND regime_volatility <= train_volatility_threshold THEN 'UP_LOW_VOL'
                WHEN regime_direction >= 0.0 AND regime_volatility > train_volatility_threshold THEN 'UP_HIGH_VOL'
                WHEN regime_direction < 0.0 AND regime_volatility <= train_volatility_threshold THEN 'DOWN_LOW_VOL'
                ELSE 'DOWN_HIGH_VOL'
            END AS regime_label,
            (
                regime_source_session_count = {REGIME_LOOKBACK_SESSIONS}
                AND regime_direction IS NOT NULL
                AND regime_volatility IS NOT NULL
                AND train_volatility_threshold IS NOT NULL
            ) AS regime_available,
            CASE
                WHEN regime_source_session_count <> {REGIME_LOOKBACK_SESSIONS} THEN 'REGIME_LOOKBACK_INCOMPLETE'
                WHEN regime_direction IS NULL OR regime_volatility IS NULL THEN 'REGIME_STATE_NUMERIC_UNAVAILABLE'
                WHEN train_volatility_threshold IS NULL THEN 'TRAIN_VOLATILITY_THRESHOLD_UNAVAILABLE'
                ELSE NULL
            END AS unavailable_reason,
            {endpoint_id_literal} AS endpoint_policy_id,
            {frozen_id_literal} AS frozen_protocol_id,
            {data_version_literal} AS data_version
        FROM evaluation_sessions
        ORDER BY session_date, fold_id
    """.strip()

    return USR2RegimeProjectionPlanV2(
        frozen_protocol_id=frozen.freeze_id,
        endpoint_policy=endpoint_policy,
        source_plan_id=source_plan.plan_id,
        sessionization_evidence_id=sessionization_evidence.evidence_id,
        calendar_id=calendar.calendar_id,
        data_version=data_version,
        sql=sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
        expected_evaluation_sessions=_expected_evaluation_sessions(calendar, frozen),
    )


def build_us_r2_regime_projection_evidence_v2(
    plan: USR2RegimeProjectionPlanV2,
    materialization: MinuteMaterialization,
    rows: Sequence[Mapping[str, object]],
) -> USR2RegimeProjectionEvidenceV2:
    if materialization.plan_id != plan.plan_id:
        raise ValueError("US-R2 v2 regime projection materialization/plan mismatch")
    if materialization.data_version != plan.data_version:
        raise ValueError("US-R2 v2 regime projection materialization data-version mismatch")
    if materialization.row_count != len(rows):
        raise ValueError("US-R2 v2 row preview must cover the complete small projection")

    expected_by_fold = dict(plan.expected_evaluation_sessions)
    known_labels = set(canonical_us_r2_frozen_protocol().classifier_policy.labels)
    minimum_per_regime = canonical_us_r1_statistical_evaluation_policy().minimum_oos_periods_per_fold
    known_reasons = {
        "REGIME_LOOKBACK_INCOMPLETE",
        "REGIME_STATE_NUMERIC_UNAVAILABLE",
        "TRAIN_VOLATILITY_THRESHOLD_UNAVAILABLE",
    }
    grouped: dict[str, list[Mapping[str, object]]] = {fold_id: [] for fold_id in expected_by_fold}
    seen_keys: set[tuple[str, date]] = set()

    for index, row in enumerate(rows):
        fold_id = _text(row.get("fold_id"), f"rows[{index}].fold_id")
        if fold_id not in grouped:
            raise ValueError(f"US-R2 v2 contains unknown fold {fold_id}")
        session_date = _date_value(row.get("session_date"), f"rows[{index}].session_date")
        key = (fold_id, session_date)
        if key in seen_keys:
            raise ValueError(f"US-R2 v2 repeats {fold_id}/{session_date}")
        seen_keys.add(key)
        if _text(row.get("endpoint_policy_id"), f"rows[{index}].endpoint_policy_id") != plan.endpoint_policy.policy_id:
            raise ValueError("US-R2 v2 row endpoint-policy identity mismatch")
        available = _boolean(row.get("regime_available"), f"rows[{index}].regime_available")
        source_end = row.get("regime_source_end_session")
        if source_end is not None and _date_value(source_end, "regime_source_end_session") >= session_date:
            raise ValueError("US-R2 v2 regime state must end before the evaluation session")
        if available:
            label = _text(row.get("regime_label"), f"rows[{index}].regime_label")
            if label not in known_labels:
                raise ValueError(f"US-R2 v2 contains unknown regime label {label}")
            if row.get("unavailable_reason") is not None:
                raise ValueError("available US-R2 v2 row cannot carry unavailable_reason")
            if _integer(row.get("regime_source_session_count"), "regime_source_session_count") != REGIME_LOOKBACK_SESSIONS:
                raise ValueError("available US-R2 v2 row requires the complete 20-session state")
            for field_name in ("regime_direction", "regime_volatility", "train_volatility_threshold"):
                if _optional_float(row.get(field_name), field_name) is None:
                    raise ValueError(f"available US-R2 v2 row requires {field_name}")
        else:
            if row.get("regime_label") is not None:
                raise ValueError("unavailable US-R2 v2 row cannot carry a regime label")
            reason = _text(row.get("unavailable_reason"), f"rows[{index}].unavailable_reason")
            if reason not in known_reasons:
                raise ValueError(f"US-R2 v2 contains unknown unavailable reason {reason}")
        grouped[fold_id].append(row)

    blockers: list[str] = []
    summaries: list[USR2RegimeFoldProjectionSummaryV2] = []
    for fold_id, expected_count in plan.expected_evaluation_sessions:
        fold_rows = grouped[fold_id]
        observed_count = len(fold_rows)
        available_rows = [row for row in fold_rows if row.get("regime_available") is True]
        label_counts = tuple(
            (label, sum(1 for row in available_rows if row.get("regime_label") == label))
            for label in sorted(known_labels)
        )
        reason_counts = tuple(
            (reason, sum(1 for row in fold_rows if row.get("unavailable_reason") == reason))
            for reason in sorted(known_reasons)
        )
        summary = USR2RegimeFoldProjectionSummaryV2(
            fold_id=fold_id,
            expected_session_count=expected_count,
            observed_session_count=observed_count,
            available_session_count=len(available_rows),
            unavailable_session_count=observed_count - len(available_rows),
            label_counts=label_counts,
            unavailable_reason_counts=reason_counts,
        )
        summaries.append(summary)
        if observed_count != expected_count:
            blockers.append(f"evaluation_calendar_mismatch:{fold_id}:{observed_count}!={expected_count}")
        for label, count in label_counts:
            if count < minimum_per_regime:
                blockers.append(
                    f"insufficient_regime_sessions:{fold_id}:{label}:{count}<{minimum_per_regime}"
                )

    return USR2RegimeProjectionEvidenceV2(
        plan_id=plan.plan_id,
        frozen_protocol_id=plan.frozen_protocol_id,
        endpoint_policy_id=plan.endpoint_policy.policy_id,
        materialization_id=materialization.materialization_id,
        materialized_row_count=materialization.row_count,
        minimum_sessions_per_regime=minimum_per_regime,
        fold_summaries=tuple(summaries),
        blockers=tuple(sorted(blockers)),
    )
