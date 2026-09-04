from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
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
    FROZEN_ASSETS,
    FROZEN_CALENDAR_ID,
    FROZEN_CLEANING_ID,
    FROZEN_SOURCE_REVISION,
    validate_us_r2_frozen_protocol,
)
from finagent.research.us_r2_robustness_base import (
    ROBUSTNESS_BASE_EVIDENCE_FILENAME,
    ROBUSTNESS_BASE_FILENAME,
    ROBUSTNESS_BASE_PLAN_FILENAME,
    ROBUSTNESS_FIRST_YEAR,
    ROBUSTNESS_LAST_YEAR,
    USR2AnnualRobustnessBasePlan,
    build_us_r2_annual_robustness_base_evidence,
    build_us_r2_annual_robustness_base_plan,
    build_us_r2_robustness_summary_plan,
    canonical_us_r2_robustness_materialization_policy,
)

INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
ROBUSTNESS_POLICY_FILENAME = "us_r2_robustness_materialization_policy.json"


@dataclass(frozen=True, slots=True)
class _LocalRelationPlan:
    plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...]


def _read_mapping(path: Path) -> Mapping[str, object]:
    target = path.expanduser().resolve()
    value: object = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {target}")
    return cast(Mapping[str, object], value)


def _write_or_verify_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        if dict(_read_mapping(target)) != expected:
            raise SystemExit(f"US-R2 immutable robustness evidence differs: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _require_new(path: Path) -> Path:
    target = path.expanduser().resolve()
    if target.exists():
        raise SystemExit(f"US-R2 annual robustness output is immutable; file exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


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


def _local_relation(plan: USR2AnnualRobustnessBasePlan, path: Path) -> _LocalRelationPlan:
    escaped = path.as_posix().replace("'", "''")
    return _LocalRelationPlan(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        sql=f"SELECT * FROM read_parquet('{escaped}')",
        output_columns=plan.output_columns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize one immutable annual US-R2 exact robustness base from the frozen 25-name "
            "1m source. One shared MATERIALIZED source relation produces 5m/15m/30m bars and exact "
            "same-session 30m/60m/120m labels for the four preregistered robustness slices."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--year",
        type=int,
        choices=range(ROBUSTNESS_FIRST_YEAR, ROBUSTNESS_LAST_YEAR + 1),
        required=True,
    )
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
        "--data-root",
        type=Path,
        default=Path("data/us_r2/robustness/base"),
    )
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path("reports/us_r2/robustness/base"),
    )
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-temp-directory-size", default="40GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_r2_robustness_base"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    year = int(args.year)
    frozen = validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))
    policy_document = canonical_us_r2_robustness_materialization_policy().to_dict()
    _write_or_verify_json(args.report_root / ROBUSTNESS_POLICY_FILENAME, policy_document)

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
    source_plan, sessionization_evidence = sessionized.plan(_source_query(calendar, year))
    plan = build_us_r2_annual_robustness_base_plan(
        source_plan,
        sessionization_evidence,
        year=year,
    )
    if plan.frozen_protocol_id != frozen.freeze_id:
        raise SystemExit("US-R2 robustness plan/frozen protocol identity mismatch")

    data_output = _require_new(
        args.data_root / f"year={year:04d}" / ROBUSTNESS_BASE_FILENAME
    )
    plan_output = _require_new(
        args.report_root / f"year_{year:04d}" / ROBUSTNESS_BASE_PLAN_FILENAME
    )
    evidence_output = _require_new(
        args.report_root / f"year_{year:04d}" / ROBUSTNESS_BASE_EVIDENCE_FILENAME
    )
    _write_or_verify_json(plan_output, plan.to_dict())

    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    # Do not count the raw plan before COPY: that would execute the annual source relation twice.
    materialization = copy_plan_to_parquet(
        plan,
        data_output,
        overwrite=False,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    local_relation = _local_relation(plan, data_output)
    summary_plan = build_us_r2_robustness_summary_plan(
        plan,
        relation_sql=local_relation.sql,
    )
    summary_rows = fetch_plan_rows(
        summary_plan,
        limit=16,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    evidence = build_us_r2_annual_robustness_base_evidence(
        plan,
        materialization,
        summary_rows,
    )
    _write_or_verify_json(evidence_output, evidence.to_dict())

    console = {
        "year": year,
        "policy_id": plan.policy_id,
        "pooled_inference_report_id": policy_document["pooled_inference_report_id"],
        "plan_id": plan.plan_id,
        "data_version": plan.data_version,
        "source_partition_months": list(plan.partition_months),
        "source_selected_size_bytes": plan.selected_size_bytes,
        "source_scan_relation_count": 1,
        "candidate_dependent_scan": False,
        "candidate_performance_read": False,
        "materialization_id": materialization.materialization_id,
        "materialized_row_count": materialization.row_count,
        "materialized_size_bytes": materialization.size_bytes,
        "evidence_id": evidence.evidence_id,
        "slices": [item.to_dict() for item in evidence.slices],
        "passed": evidence.passed,
        "blockers": list(evidence.blockers),
        "candidate_selection_applied": False,
        "alpha_gate_evaluated": False,
        "terminal_authority": False,
        "data_output": str(data_output),
        "plan_output": str(plan_output),
        "evidence_output": str(evidence_output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not evidence.passed:
        raise SystemExit("US-R2 annual robustness base failed closed; inspect blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
