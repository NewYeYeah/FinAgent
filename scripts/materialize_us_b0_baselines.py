from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from finagent.data.minute_store import (
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    count_plan_rows,
    fetch_plan_rows,
    manifest_from_huggingface_snapshot,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    SameSessionLabelStore,
    SessionResampledMinuteStore,
    canonical_same_session_60m_label_spec,
    load_trading_calendar_evidence_json,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_baseline_materialization import (
    USBaselineInputPlan,
    bind_us_b0_run_spec,
    build_us_baseline_input_plan,
    build_us_baseline_materialization_report,
    evaluate_materialized_us_baselines,
    materialize_us_baseline_observations,
    write_us_baseline_observation_artifact,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"
MAX_JOINED_ROWS = 100_000


@dataclass(frozen=True, slots=True)
class _LocalParquetPlan:
    plan_id: str
    data_version: str
    sql: str
    output_columns: tuple[str, ...]


def _read_mapping(path: Path) -> Mapping[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.open("rb") as handle:
        value = tomllib.load(handle)
    return cast(Mapping[str, object], value)


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return cast(Mapping[str, object], value)


def _require_us_b0_stage_authority(status: Mapping[str, object]) -> None:
    if str(status.get("current_stage", "")).strip() != "US-B0":
        raise SystemExit(
            "docs/status.toml has not advanced to US-B0; record the reviewed real US-D3 "
            "evidence first rather than running a formal baseline against pending stage authority"
        )
    stages = _mapping(status.get("stage"), "status.stage")
    us_d3 = _mapping(stages.get("us_d3"), "status.stage.us_d3")
    if str(us_d3.get("status", "")).strip() != "accepted":
        raise SystemExit("status.stage.us_d3 must be accepted before formal US-B0 materialization")
    if us_d3.get("stage_exit_gate_passed") is not True:
        raise SystemExit("status.stage.us_d3.stage_exit_gate_passed must be true")


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware ISO-8601")
    return parsed


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _writable(path: Path, *, overwrite: bool) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _bar_query(
    assets: tuple[str, ...],
    *,
    start: datetime,
    end: datetime,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _label_query(
    assets: tuple[str, ...],
    *,
    start: datetime,
    end: datetime,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _exact_materialization_plan(
    input_plan: USBaselineInputPlan,
    path: Path,
) -> _LocalParquetPlan:
    return _LocalParquetPlan(
        plan_id=input_plan.plan_id,
        data_version=input_plan.data_version,
        sql=f"SELECT * FROM read_parquet({_sql_string(path.as_posix())})",
        output_columns=input_plan.output_columns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the bounded US-B0 manual baseline denominator from the accepted "
            "US-D3 certification and final EngineeringUniverse. This runner is cost-free, "
            "non-Agent and has no factor-selection or Alpha authority."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--start", type=_aware, required=True)
    parser.add_argument("--end", type=_aware, required=True)
    parser.add_argument(
        "--status",
        type=Path,
        default=Path("docs/status.toml"),
    )
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument(
        "--certification",
        type=Path,
        default=Path("reports/us_d3/us_minute_research_certification.json"),
    )
    parser.add_argument(
        "--engineering-universe",
        type=Path,
        default=Path("reports/us_instruments/us_i0_final_engineering_universe.json"),
    )
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_b0"),
    )
    parser.add_argument(
        "--input-output",
        type=Path,
        default=Path("data/us_b0/us_b0_baseline_inputs.parquet"),
    )
    parser.add_argument(
        "--observation-output",
        type=Path,
        default=Path("data/us_b0/us_b0_baseline_observations.jsonl"),
    )
    parser.add_argument(
        "--evaluation-output",
        type=Path,
        default=Path("reports/us_b0/us_b0_baseline_evaluation.json"),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/us_b0/us_b0_baseline_materialization.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.end <= args.start:
        raise SystemExit("--end must be later than --start")

    status_path = args.status.expanduser().resolve()
    _require_us_b0_stage_authority(_read_status(status_path))

    denominator = canonical_us_baseline_denominator()
    certification = _read_mapping(args.certification.expanduser().resolve())
    universe = _read_mapping(args.engineering_universe.expanduser().resolve())
    run_spec, assets = bind_us_b0_run_spec(
        certification,
        universe,
        denominator=denominator,
    )

    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
    )
    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=CALENDAR_ID,
    )
    manifest = manifest_from_huggingface_snapshot(
        args.root,
        expected_revision=SOURCE_REVISION,
        expected_inventory_id=INVENTORY_ID,
        cleaning_identity=CLEANING_ID,
    )
    raw_store = DuckDBParquetMinuteStore(manifest)
    sessionized = CalendarSessionizedMinuteStore(raw_store, calendar)
    resampled = SessionResampledMinuteStore(sessionized)
    labels = SameSessionLabelStore(sessionized)

    resampled_plan, resampling_evidence = resampled.plan(
        _bar_query(assets, start=args.start, end=args.end)
    )
    label_plan, label_evidence = labels.plan(
        _label_query(assets, start=args.start, end=args.end),
        canonical_same_session_60m_label_spec(),
    )
    input_plan = build_us_baseline_input_plan(
        resampled_plan,
        label_plan,
        resampling_evidence,
        label_evidence,
        run_spec=run_spec,
    )

    joined_rows = count_plan_rows(
        input_plan,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    if joined_rows == 0:
        raise SystemExit("US-B0 bounded input plan returned zero rows")
    if joined_rows > MAX_JOINED_ROWS:
        raise SystemExit(
            "US-B0 bounded input exceeds 100000 joined rows; materialize the preregistered "
            "walk-forward folds separately rather than weakening the bounded Python boundary"
        )

    input_output = _writable(args.input_output, overwrite=args.overwrite)
    observation_output = _writable(args.observation_output, overwrite=args.overwrite)
    evaluation_output = _writable(args.evaluation_output, overwrite=args.overwrite)
    report_output = _writable(args.report_output, overwrite=args.overwrite)

    input_materialization = copy_plan_to_parquet(
        input_plan,
        input_output,
        overwrite=args.overwrite,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    if input_materialization.row_count != joined_rows:
        raise RuntimeError("US-B0 input row count changed during materialization")

    exact_plan = _exact_materialization_plan(input_plan, input_output)
    rows = fetch_plan_rows(
        exact_plan,
        limit=joined_rows,
        policy=execution_policy,
        temp_directory=args.temp_directory,
    )
    observations, diagnostics = materialize_us_baseline_observations(
        rows,
        denominator,
        expected_assets=assets,
    )
    observation_artifact = write_us_baseline_observation_artifact(
        observations,
        observation_output,
        run_spec=run_spec,
    )
    evaluation = evaluate_materialized_us_baselines(
        denominator,
        observations,
        run_spec=run_spec,
    )
    evaluation_output.write_text(
        json.dumps(evaluation.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = build_us_baseline_materialization_report(
        run_spec=run_spec,
        input_plan=input_plan,
        input_materialization=input_materialization,
        observation_artifact=observation_artifact,
        diagnostics=diagnostics,
        evaluation_report=evaluation,
        engineering_assets=assets,
    )
    report_output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "report_id": report.report_id,
                "passed": report.passed,
                "blockers": list(report.blockers),
                "run_spec_id": run_spec.spec_id,
                "certification_report_id": run_spec.certification_report_id,
                "engineering_universe_id": run_spec.engineering_universe_id,
                "denominator_id": run_spec.denominator_id,
                "engineering_asset_count": len(assets),
                "input_plan_id": input_plan.plan_id,
                "input_materialization_id": input_materialization.materialization_id,
                "observation_artifact_id": observation_artifact.artifact_id,
                "evaluation_report_id": evaluation.report_id,
                "valid_candidate_count": evaluation.valid_candidate_count,
                "stage_exit_authority": False,
                "evaluation_output": str(evaluation_output),
                "report_output": str(report_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
