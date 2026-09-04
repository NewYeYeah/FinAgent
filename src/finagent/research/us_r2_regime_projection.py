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
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_COMMON_ALL_ASSET_END,
    FROZEN_FIRST_RESEARCH_YEAR,
    REGIME_ANCHOR_ASSET,
    REGIME_LOOKBACK_SESSIONS,
    USR2FrozenResearchProtocol,
    canonical_us_r2_frozen_protocol,
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
        raise ValueError("US-R2 regime projection calendar window contains no sessions")
    return sessions


def _calendar_relation_sql(sessions: tuple[TradingSession, ...]) -> str:
    rows = []
    for item in sessions:
        rows.append(
            "("
            f"DATE {_sql_string(item.session_date.isoformat())}, "
            f"{item.regular_minutes}::BIGINT"
            ")"
        )
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
    counts = []
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
class USR2RegimeProjectionPlan:
    frozen_protocol_id: str
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
        "regime_direction",
        "regime_volatility",
        "train_volatility_threshold",
        "train_volatility_observation_count",
        "regime_label",
        "regime_available",
        "unavailable_reason",
        "frozen_protocol_id",
        "data_version",
    )
    schema_version: str = "finagent.us-r2-regime-projection-plan.v1"

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
                "source_plan_id": self.source_plan_id,
                "sessionization_evidence_id": self.sessionization_evidence_id,
                "calendar_id": self.calendar_id,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "expected_evaluation_sessions": [
                    {"fold_id": fold_id, "session_count": count}
                    for fold_id, count in self.expected_evaluation_sessions
                ],
                "source_asset": self.source_asset,
                "output_columns": list(self.output_columns),
            },
            prefix="us-r2-regime-projection-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "frozen_protocol_id": self.frozen_protocol_id,
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
            "regime_state_availability_lag_sessions": 1,
            "output_columns": list(self.output_columns),
            "alpha_authority": False,
            "execution_authority": False,
        }


@dataclass(frozen=True, slots=True)
class USR2RegimeFoldProjectionSummary:
    fold_id: str
    expected_session_count: int
    observed_session_count: int
    available_session_count: int
    unavailable_session_count: int
    label_counts: tuple[tuple[str, int], ...]
    schema_version: str = "finagent.us-r2-regime-fold-projection-summary.v1"

    def __post_init__(self) -> None:
        if not self.fold_id.strip():
            raise ValueError("fold_id must be non-empty")
        counts = (
            self.expected_session_count,
            self.observed_session_count,
            self.available_session_count,
            self.unavailable_session_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("US-R2 regime summary counts must be non-negative")
        if self.available_session_count + self.unavailable_session_count != self.observed_session_count:
            raise ValueError("US-R2 available/unavailable counts must sum to observed sessions")
        if sum(value for _label, value in self.label_counts) != self.available_session_count:
            raise ValueError("US-R2 regime label counts must sum to available sessions")

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
            "label_counts": {label: count for label, count in self.label_counts},
            "observed_regimes": list(self.observed_regimes),
        }


@dataclass(frozen=True, slots=True)
class USR2RegimeProjectionEvidence:
    plan_id: str
    frozen_protocol_id: str
    materialization_id: str
    materialized_row_count: int
    fold_summaries: tuple[USR2RegimeFoldProjectionSummary, ...]
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-projection-evidence.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-projection")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "frozen_protocol_id": self.frozen_protocol_id,
            "materialization_id": self.materialization_id,
            "materialized_row_count": self.materialized_row_count,
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


def build_us_r2_regime_projection_plan(
    source_plan: MinuteQueryPlan,
    sessionization_evidence: SessionizationEvidence,
    calendar: TradingCalendarEvidence,
    frozen: USR2FrozenResearchProtocol,
) -> USR2RegimeProjectionPlan:
    canonical = canonical_us_r2_frozen_protocol()
    if frozen.freeze_id != canonical.freeze_id:
        raise ValueError("US-R2 regime projection requires the canonical frozen protocol")
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
    if calendar.calendar_id != frozen.walk_forward_protocol.regime_policy.features[0].to_dict().get(
        "calendar_id", calendar.calendar_id
    ):
        raise ValueError("US-R2 regime calendar identity mismatch")

    required_fields = {item.value for item in query.fields}
    if not {"open", "close"}.issubset(required_fields):
        raise ValueError("US-R2 IWM session-return source requires open and close")

    calendar_start = date(FROZEN_FIRST_RESEARCH_YEAR - 1, 5, 1)
    sessions = _calendar_sessions(
        calendar,
        start=calendar_start,
        end=FROZEN_COMMON_ALL_ASSET_END,
    )
    calendar_sql = _calendar_relation_sql(sessions)
    fold_sql = _fold_relation_sql(frozen)
    frozen_id_literal = _sql_string(frozen.freeze_id)
    data_version = _canonical_hash(
        {
            "frozen_protocol_id": frozen.freeze_id,
            "source_plan_id": source_plan.plan_id,
            "sessionization_evidence_id": sessionization_evidence.evidence_id,
            "calendar_id": calendar.calendar_id,
            "source_asset": REGIME_ANCHOR_ASSET,
            "session_return": "regular_close_div_open_minus_one_raw",
            "regime_lookback_sessions": REGIME_LOOKBACK_SESSIONS,
            "availability_lag_sessions": 1,
            "volatility_threshold": "fold_train_median",
        },
        prefix="us-r2-regime-projection-data-version",
    )
    data_version_literal = _sql_string(data_version)

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
                CASE
                    WHEN o.observed_regular_minute_count = c.expected_regular_minute_count
                     AND o.minimum_minute_offset = 0
                     AND o.maximum_minute_offset = c.expected_regular_minute_count - 1
                    THEN CAST(o.session_close_price / o.session_open_price - 1.0 AS DOUBLE)
                    ELSE NULL
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
            CAST(regime_direction AS DOUBLE) AS regime_direction,
            CAST(regime_volatility AS DOUBLE) AS regime_volatility,
            CAST(train_volatility_threshold AS DOUBLE) AS train_volatility_threshold,
            train_volatility_observation_count,
            CASE
                WHEN regime_source_session_count <> {REGIME_LOOKBACK_SESSIONS} THEN NULL
                WHEN regime_direction IS NULL OR regime_volatility IS NULL THEN NULL
                WHEN train_volatility_threshold IS NULL THEN NULL
                WHEN regime_direction >= 0.0 AND regime_volatility <= train_volatility_threshold
                    THEN 'UP_LOW_VOL'
                WHEN regime_direction >= 0.0 AND regime_volatility > train_volatility_threshold
                    THEN 'UP_HIGH_VOL'
                WHEN regime_direction < 0.0 AND regime_volatility <= train_volatility_threshold
                    THEN 'DOWN_LOW_VOL'
                ELSE 'DOWN_HIGH_VOL'
            END AS regime_label,
            (
                regime_source_session_count = {REGIME_LOOKBACK_SESSIONS}
                AND regime_direction IS NOT NULL
                AND regime_volatility IS NOT NULL
                AND train_volatility_threshold IS NOT NULL
            ) AS regime_available,
            CASE
                WHEN regime_source_session_count <> {REGIME_LOOKBACK_SESSIONS}
                    THEN 'REGIME_LOOKBACK_INCOMPLETE'
                WHEN regime_direction IS NULL OR regime_volatility IS NULL
                    THEN 'REGIME_STATE_NUMERIC_UNAVAILABLE'
                WHEN train_volatility_threshold IS NULL
                    THEN 'TRAIN_VOLATILITY_THRESHOLD_UNAVAILABLE'
                ELSE NULL
            END AS unavailable_reason,
            {frozen_id_literal} AS frozen_protocol_id,
            {data_version_literal} AS data_version
        FROM evaluation_sessions
        ORDER BY session_date, fold_id
    """.strip()

    return USR2RegimeProjectionPlan(
        frozen_protocol_id=frozen.freeze_id,
        source_plan_id=source_plan.plan_id,
        sessionization_evidence_id=sessionization_evidence.evidence_id,
        calendar_id=calendar.calendar_id,
        data_version=data_version,
        sql=sql,
        partition_months=source_plan.partition_months,
        selected_size_bytes=source_plan.selected_size_bytes,
        expected_evaluation_sessions=_expected_evaluation_sessions(calendar, frozen),
    )


def build_us_r2_regime_projection_evidence(
    plan: USR2RegimeProjectionPlan,
    materialization: MinuteMaterialization,
    rows: Sequence[Mapping[str, object]],
) -> USR2RegimeProjectionEvidence:
    if materialization.plan_id != plan.plan_id:
        raise ValueError("US-R2 regime projection materialization/plan mismatch")
    if materialization.data_version != plan.data_version:
        raise ValueError("US-R2 regime projection materialization data-version mismatch")
    if materialization.row_count != len(rows):
        raise ValueError("US-R2 regime projection row preview must cover the complete small projection")

    expected_by_fold = dict(plan.expected_evaluation_sessions)
    known_labels = set(canonical_us_r2_frozen_protocol().classifier_policy.labels)
    seen_keys: set[tuple[str, date]] = set()
    grouped: dict[str, list[Mapping[str, object]]] = {fold_id: [] for fold_id in expected_by_fold}
    blockers: list[str] = []
    for index, row in enumerate(rows):
        fold_id = _text(row.get("fold_id"), f"rows[{index}].fold_id")
        if fold_id not in grouped:
            raise ValueError(f"US-R2 regime projection contains unknown fold {fold_id}")
        session_date = _date_value(row.get("session_date"), f"rows[{index}].session_date")
        key = (fold_id, session_date)
        if key in seen_keys:
            raise ValueError(f"US-R2 regime projection repeats {fold_id}/{session_date}")
        seen_keys.add(key)
        available = _boolean(row.get("regime_available"), f"rows[{index}].regime_available")
        label_value = row.get("regime_label")
        unavailable_reason = row.get("unavailable_reason")
        if available:
            label = _text(label_value, f"rows[{index}].regime_label")
            if label not in known_labels:
                raise ValueError(f"US-R2 regime projection contains unknown label {label}")
            if unavailable_reason is not None:
                raise ValueError("available US-R2 regime row cannot carry unavailable_reason")
            for numeric_field in (
                "regime_direction",
                "regime_volatility",
                "train_volatility_threshold",
            ):
                if _optional_float(row.get(numeric_field), f"rows[{index}].{numeric_field}") is None:
                    raise ValueError(f"available US-R2 regime row requires {numeric_field}")
        else:
            if label_value is not None:
                raise ValueError("unavailable US-R2 regime row cannot carry a regime label")
            _text(unavailable_reason, f"rows[{index}].unavailable_reason")
        grouped[fold_id].append(row)

    summaries: list[USR2RegimeFoldProjectionSummary] = []
    for fold_id, expected_count in plan.expected_evaluation_sessions:
        fold_rows = grouped[fold_id]
        observed_count = len(fold_rows)
        available_rows = [row for row in fold_rows if row.get("regime_available") is True]
        label_counts = tuple(
            (label, sum(1 for row in available_rows if row.get("regime_label") == label))
            for label in sorted(known_labels)
        )
        summary = USR2RegimeFoldProjectionSummary(
            fold_id=fold_id,
            expected_session_count=expected_count,
            observed_session_count=observed_count,
            available_session_count=len(available_rows),
            unavailable_session_count=observed_count - len(available_rows),
            label_counts=label_counts,
        )
        summaries.append(summary)
        if observed_count != expected_count:
            blockers.append(f"evaluation_calendar_mismatch:{fold_id}:{observed_count}!={expected_count}")
        missing_regimes = sorted(known_labels.difference(summary.observed_regimes))
        if missing_regimes:
            blockers.append(f"missing_expected_regimes:{fold_id}:{','.join(missing_regimes)}")

    return USR2RegimeProjectionEvidence(
        plan_id=plan.plan_id,
        frozen_protocol_id=plan.frozen_protocol_id,
        materialization_id=materialization.materialization_id,
        materialized_row_count=materialization.row_count,
        fold_summaries=tuple(summaries),
        blockers=tuple(sorted(blockers)),
    )
