from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

from finagent.data.minute_store import (
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    fetch_plan_rows,
    manifest_from_huggingface_snapshot,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    load_trading_calendar_evidence_json,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_CALENDAR_ID,
    FROZEN_CLEANING_ID,
    FROZEN_COMMON_ALL_ASSET_END,
    FROZEN_SOURCE_REVISION,
    REGIME_ANCHOR_ASSET,
    validate_us_r2_frozen_protocol,
)
from finagent.research.us_r2_regime_projection_v2 import (
    USR2RegimeProjectionPlanV2,
    build_us_r2_regime_projection_evidence_v2,
    build_us_r2_regime_projection_plan_v2,
)

INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
MAX_PROJECTION_ROWS = 10_000


@dataclass(frozen=True, slots=True)
class _LocalParquetPlan:
    plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...]


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_new(path: Path) -> Path:
    target = path.expanduser().resolve()
    if target.exists():
        raise SystemExit(f"US-R2 v2 regime projection evidence is immutable; output exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _write_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    path.write_text(
        json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _source_query(calendar: TradingCalendarEvidence) -> MarketDataQuery:
    sessions = tuple(
        item
        for item in calendar.sessions
        if date(2000, 5, 1) <= item.session_date <= FROZEN_COMMON_ALL_ASSET_END
    )
    if not sessions:
        raise SystemExit("US-R2 v2 regime projection calendar contains no source sessions")
    return MarketDataQuery(
        market_id="XNYS",
        assets=(REGIME_ANCHOR_ASSET,),
        start=sessions[0].open_at,
        end=sessions[-1].close_at,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.OPEN, MarketDataField.CLOSE),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )


def _local_parquet_plan(
    plan: USR2RegimeProjectionPlanV2,
    parquet_path: Path,
) -> _LocalParquetPlan:
    return _LocalParquetPlan(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        sql=(
            f"SELECT * FROM read_parquet({_sql_string(parquet_path.as_posix())}) "
            "ORDER BY session_date, fold_id"
        ),
        output_columns=plan.output_columns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the amended US-R2 IWM regime/session projection. V2 preserves the "
            "failed v1 evidence and replaces full-session 1m completeness with a preregistered "
            "15m endpoint-observation policy."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path("reports/us_r2/us_r2_frozen_protocol.json"),
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument(
        "--data-output",
        type=Path,
        default=Path("data/us_r2/regime/us_r2_regime_projection_v2.parquet"),
    )
    parser.add_argument(
        "--plan-output",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_projection_plan_v2.json"),
    )
    parser.add_argument(
        "--evidence-output",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_projection_evidence_v2.json"),
    )
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_r2_regime_v2"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    frozen = validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))
    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=FROZEN_CALENDAR_ID,
    )
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=FROZEN_SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=FROZEN_CLEANING_ID,
    )
    raw_store = DuckDBParquetMinuteStore(manifest)
    sessionized = CalendarSessionizedMinuteStore(raw_store, calendar)
    source_plan, sessionization_evidence = sessionized.plan(_source_query(calendar))
    projection_plan = build_us_r2_regime_projection_plan_v2(
        source_plan,
        sessionization_evidence,
        calendar,
        frozen,
    )

    data_output = _require_new(args.data_output)
    plan_output = _require_new(args.plan_output)
    evidence_output = _require_new(args.evidence_output)
    _write_json(plan_output, projection_plan.to_dict())

    policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    materialization = copy_plan_to_parquet(
        projection_plan,
        data_output,
        overwrite=False,
        policy=policy,
        temp_directory=args.temp_directory,
    )
    if materialization.row_count > MAX_PROJECTION_ROWS:
        raise SystemExit(
            "US-R2 v2 regime projection exceeded bounded review surface: "
            f"{materialization.row_count}>{MAX_PROJECTION_ROWS}"
        )

    local_plan = _local_parquet_plan(projection_plan, data_output)
    rows = fetch_plan_rows(
        local_plan,
        limit=MAX_PROJECTION_ROWS,
        policy=policy,
        temp_directory=args.temp_directory,
    )
    evidence = build_us_r2_regime_projection_evidence_v2(
        projection_plan,
        materialization,
        rows,
    )
    _write_json(evidence_output, evidence.to_dict())

    console = {
        "plan_id": projection_plan.plan_id,
        "endpoint_policy_id": projection_plan.endpoint_policy.policy_id,
        "data_version": projection_plan.data_version,
        "source_asset": projection_plan.source_asset,
        "source_selected_size_bytes": projection_plan.selected_size_bytes,
        "materialization_id": materialization.materialization_id,
        "materialized_row_count": materialization.row_count,
        "materialized_size_bytes": materialization.size_bytes,
        "evidence_id": evidence.evidence_id,
        "minimum_sessions_per_regime": evidence.minimum_sessions_per_regime,
        "fold_summaries": [item.to_dict() for item in evidence.fold_summaries],
        "passed": evidence.passed,
        "blockers": list(evidence.blockers),
        "data_output": str(data_output),
        "plan_output": str(plan_output),
        "evidence_output": str(evidence_output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not evidence.passed:
        raise SystemExit("US-R2 v2 regime projection failed closed; inspect evidence blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
