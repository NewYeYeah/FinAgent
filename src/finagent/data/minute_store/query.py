from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from finagent.data.query import MarketDataQuery
from finagent.data.us_minute.quarantine import quarantined_clean_month_select_sql
from finagent.domain.labels import AvailabilityPolicy

from .manifest import MinuteStoreManifest, MinuteStorePartition


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


def _sql_timestamp(value: datetime) -> str:
    return f"TIMESTAMPTZ {_sql_string(value.astimezone(UTC).isoformat())}"


def _month_key(value: datetime, timezone: str) -> str:
    local = value.astimezone(ZoneInfo(timezone))
    return f"{local.year:04d}-{local.month:02d}"


def _month_index(month: str) -> int:
    year_text, month_text = month.split("-", maxsplit=1)
    year = int(year_text)
    month_number = int(month_text)
    if not 1 <= month_number <= 12:
        raise ValueError(f"invalid month label: {month}")
    return year * 12 + month_number - 1


def _event_window(query: MarketDataQuery) -> tuple[datetime, datetime]:
    if query.availability_policy is AvailabilityPolicy.AVAILABLE_AT:
        return query.start - timedelta(minutes=1), query.end - timedelta(minutes=1)
    return query.start, query.end


def select_partitions(
    manifest: MinuteStoreManifest,
    query: MarketDataQuery,
) -> tuple[MinuteStorePartition, ...]:
    event_start, event_end = _event_window(query)
    # `end` is exclusive. Subtract one microsecond only for partition routing so a
    # boundary exactly at the next local month does not pull an unnecessary partition.
    last_event = event_end - timedelta(microseconds=1)
    start_index = _month_index(_month_key(event_start, manifest.timezone))
    end_index = _month_index(_month_key(last_event, manifest.timezone))
    selected = tuple(
        item
        for item in manifest.partitions
        if start_index <= _month_index(item.month) <= end_index
    )
    if not selected:
        raise ValueError("market-data query does not intersect any minute-store partition")
    return selected


@dataclass(frozen=True, slots=True)
class MinuteQueryPlan:
    query: MarketDataQuery
    manifest_id: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.minute-query-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "query_id": self.query.query_id,
                "manifest_id": self.manifest_id,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
            },
            prefix="minute-query-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "query_id": self.query.query_id,
            "manifest_id": self.manifest_id,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
        }


def build_minute_query_plan(
    manifest: MinuteStoreManifest,
    query: MarketDataQuery,
) -> MinuteQueryPlan:
    partitions = select_partitions(manifest, query)
    event_start, event_end = _event_window(query)
    monthly_reads = [
        "(\n"
        + quarantined_clean_month_select_sql(
            item.path,
            tickers=query.assets,
            start=event_start,
            end=event_end,
        )
        + "\n)"
        for item in partitions
    ]
    combined_sql = "\nUNION ALL\n".join(monthly_reads)

    value_columns = tuple(item.value for item in query.fields)
    output_columns = (
        "research_asset_id",
        "session_date",
        "event_time",
        "available_at",
        "interval",
        *value_columns,
        "session_type",
        "source_id",
        "source_revision",
        "data_version",
    )
    value_projection = "\n            ".join(f", d.{name} AS {name}" for name in value_columns)
    clock_expression = (
        "d.timestamp + INTERVAL '1 minute'"
        if query.availability_policy is AvailabilityPolicy.AVAILABLE_AT
        else "d.timestamp"
    )

    sql = f"""
        WITH combined AS (
            {combined_sql}
        ),
        cross_partition_conflicting_keys AS (
            SELECT ticker, timestamp
            FROM combined
            GROUP BY ticker, timestamp
            HAVING COUNT(DISTINCT struct_pack(
                open := open,
                high := high,
                low := low,
                close := close,
                volume := volume
            )) > 1
        ),
        deduplicated AS (
            SELECT DISTINCT c.timestamp, c.open, c.high, c.low, c.close, c.volume, c.ticker
            FROM combined AS c
            WHERE NOT EXISTS (
                SELECT 1
                FROM cross_partition_conflicting_keys AS x
                WHERE x.ticker IS NOT DISTINCT FROM c.ticker
                  AND x.timestamp IS NOT DISTINCT FROM c.timestamp
            )
        )
        SELECT
            d.ticker AS research_asset_id,
            CAST(timezone({_sql_string(manifest.timezone)}, d.timestamp) AS DATE) AS session_date,
            d.timestamp AS event_time,
            d.timestamp + INTERVAL '1 minute' AS available_at,
            '1m' AS interval
            {value_projection},
            'observed_unclassified' AS session_type,
            {_sql_string(manifest.source_id)} AS source_id,
            {_sql_string(manifest.source_revision)} AS source_revision,
            {_sql_string(manifest.data_version)} AS data_version
        FROM deduplicated AS d
        WHERE {clock_expression} >= {_sql_timestamp(query.start)}
          AND {clock_expression} < {_sql_timestamp(query.end)}
        ORDER BY event_time, research_asset_id
    """.strip()

    return MinuteQueryPlan(
        query=query,
        manifest_id=manifest.manifest_id,
        data_version=manifest.data_version,
        sql=sql,
        partition_months=tuple(item.month for item in partitions),
        selected_size_bytes=sum(item.size_bytes for item in partitions),
        output_columns=output_columns,
    )
