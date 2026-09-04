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
from finagent.research.us_r2_base_panel import (
    FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID,
    USR2AnnualBasePanelPlan,
    build_us_r2_annual_base_panel_evidence,
    build_us_r2_annual_base_panel_plan,
    build_us_r2_base_panel_summary_plan,
    validate_us_r2_regime_projection_v2_gate,
)
from finagent.research.us_r2_frozen_protocol import (
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    FROZEN_CLEANING_ID,
    FROZEN_FIRST_RESEARCH_YEAR,
    FROZEN_LAST_RESEARCH_YEAR,
    FROZEN_SOURCE_REVISION,
    validate_us_r2_frozen_protocol,
)

INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"


@dataclass(frozen=True, slots=True)
class _LocalRelationPlan:
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
        raise SystemExit(f"US-R2 annual base-panel output is immutable; file exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _write_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    path.write_text(
        json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _year_sessions(calendar: TradingCalendarEvidence, year: int) -> tuple[object, ...]:
    sessions = tuple(item for item in calendar.sessions if item.session_date.year == year)
    if not sessions:
        raise SystemExit(f"US-R2 calendar has no XNYS sessions for {year}")
    return sessions


def _source_query(calendar: TradingCalendarEvidence, year: int) -> MarketDataQuery:
    sessions = tuple(item for item in calendar.sessions if item.session_date.year == year)
    if not sessions:
        raise SystemExit(f"US-R2 calendar has no XNYS sessions for {year}")
    return MarketDataQuery(
        market_id="XNYS",
        assets=FROZEN_ASSETS,
        start=sessions[0].open_at,
        end=sessions[-1].close_at,
        interval=BarInterval.MINUTE_1,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )


def _local_relation(plan: USR2AnnualBasePanelPlan, path: Path) -> _LocalRelationPlan:
    return _LocalRelationPlan(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        sql=f"SELECT * FROM read_parquet({_sql_string(path.as_posix())})",
        output_columns=plan.output_columns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize one immutable annual US-R2 canonical 15m + same-session 60m base-panel "
            "partition. Bars and labels share one MATERIALIZED sessionized source CTE; no candidate "
            "is evaluated and the raw minute source is not counted/scanned before COPY."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--year",
        type=int,
        choices=range(FROZEN_FIRST_RESEARCH_YEAR, FROZEN_LAST_RESEARCH_YEAR + 1),
        required=True,
    )
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path("reports/us_r2/us_r2_frozen_protocol.json"),
    )
    parser.add_argument(
        "--regime-evidence",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_projection_evidence_v2.json"),
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data/us_r2/base"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/us_r2/base"))
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-temp-directory-size", default="40GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_r2_base"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    year = int(args.year)

    frozen = validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))
    regime_id = validate_us_r2_regime_projection_v2_gate(_read_mapping(args.regime_evidence))
    if regime_id != FROZEN_REGIME_PROJECTION_V2_EVIDENCE_ID:
        raise SystemExit("US-R2 base panel did not bind the reviewed v2 regime evidence")

    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=FROZEN_CALENDAR_ID,
    )
    _year_sessions(calendar, year)
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=FROZEN_SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=FROZEN_CLEANING_ID,
    )
    raw_store = DuckDBParquetMinuteStore(manifest)
    sessionized = CalendarSessionizedMinuteStore(raw_store, calendar)
    source_plan, sessionization_evidence = sessionized.plan(_source_query(calendar, year))
    plan = build_us_r2_annual_base_panel_plan(
        source_plan,
        sessionization_evidence,
        year=year,
        regime_projection_evidence_id=regime_id,
    )
    if plan.frozen_protocol_id != frozen.freeze_id:
        raise SystemExit("US-R2 annual base-panel plan/frozen protocol identity mismatch")

    data_output = _require_new(
        args.data_root / f"year={year:04d}" / "us_r2_15m60m_base.parquet"
    )
    plan_output = _require_new(
        args.report_root / f"year_{year:04d}" / "us_r2_base_panel_plan.json"
    )
    evidence_output = _require_new(
        args.report_root / f"year_{year:04d}" / "us_r2_base_panel_evidence.json"
    )
    _write_json(plan_output, plan.to_dict())

    policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )

    # Do not call count_plan_rows(plan): that would execute the expensive annual source scan twice.
    materialization = copy_plan_to_parquet(
        plan,
        data_output,
        overwrite=False,
        policy=policy,
        temp_directory=args.temp_directory,
    )

    local_relation = _local_relation(plan, data_output)
    summary_plan = build_us_r2_base_panel_summary_plan(
        plan,
        relation_sql=local_relation.sql,
    )
    summary_rows = fetch_plan_rows(
        summary_plan,
        limit=1,
        policy=policy,
        temp_directory=args.temp_directory,
    )
    if len(summary_rows) != 1:
        raise SystemExit("US-R2 annual base-panel summary did not return exactly one row")
    evidence = build_us_r2_annual_base_panel_evidence(
        plan,
        materialization,
        summary_rows[0],
    )
    _write_json(evidence_output, evidence.to_dict())

    console = {
        "year": year,
        "plan_id": plan.plan_id,
        "data_version": plan.data_version,
        "regime_projection_evidence_id": plan.regime_projection_evidence_id,
        "source_partition_months": list(plan.partition_months),
        "source_selected_size_bytes": plan.selected_size_bytes,
        "source_scan_relation_count": 1,
        "candidate_dependent_scan": False,
        "materialization_id": materialization.materialization_id,
        "materialized_row_count": materialization.row_count,
        "materialized_size_bytes": materialization.size_bytes,
        "evidence_id": evidence.evidence_id,
        "asset_count": evidence.asset_count,
        "formation_count": evidence.formation_count,
        "formation_count_at_minimum_cross_section": evidence.formation_count_at_minimum_cross_section,
        "minimum_joint_breadth": evidence.minimum_joint_breadth,
        "maximum_joint_breadth": evidence.maximum_joint_breadth,
        "passed": evidence.passed,
        "blockers": list(evidence.blockers),
        "data_output": str(data_output),
        "plan_output": str(plan_output),
        "evidence_output": str(evidence_output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not evidence.passed:
        raise SystemExit("US-R2 annual base-panel evidence failed closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
