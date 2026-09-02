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
    load_trading_calendar_evidence_json,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_baseline_materialization import bind_us_b0_run_spec
from finagent.research.us_baselines import canonical_us_baseline_denominator
from finagent.research.us_r1_authority import require_us_r1_stage_authority
from finagent.research.us_r1_contracts import validate_us_r1_protocol_document
from finagent.research.us_r1_handoff import (
    parse_us_r1_candidate_denominator,
    validate_terminal_a0_review_document,
)
from finagent.research.us_r1_materialization import (
    USR1FoldMaterializationManifest,
    USR1InputPlan,
    USR1ObservationRole,
    build_us_r1_materialization_slice,
    canonical_us_r1_feature_formation_policy,
    materialize_us_r1_candidate_observations,
    write_us_r1_observation_artifact,
)
from finagent.research.us_r1_materialization_evidence import (
    build_authoritative_us_r1_input_plan,
    canonical_us_r1_label_spec,
    merge_us_r1_observation_blockers,
    parse_minute_materialization,
    parse_us_r1_fold_materialization_manifest,
    parse_us_r1_observation_artifact,
    parse_us_r1_observation_diagnostics,
    validate_us_r1_input_plan_document,
    validate_us_r1_input_rows,
    verify_us_r1_observation_file,
)
from finagent.research.us_r1_walkforward import (
    bind_us_r1_fold_execution_specs,
    validate_us_r1_walk_forward_document,
    verify_us_r1_fold_gap,
)

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
    value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bar_query(
    assets: tuple[str, ...],
    *,
    start: datetime,
    end: datetime,
    interval: BarInterval,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,
        end=end,
        interval=interval,
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


def _exact_plan(input_plan: USR1InputPlan, parquet_path: Path) -> _LocalParquetPlan:
    return _LocalParquetPlan(
        plan_id=input_plan.plan_id,
        data_version=input_plan.data_version,
        sql=f"SELECT * FROM read_parquet({_sql_string(parquet_path.as_posix())})",
        output_columns=input_plan.output_columns,
    )


def _slice_name(
    role: USR1ObservationRole,
    interval: BarInterval,
    horizon: int,
) -> str:
    return f"{role.value.lower()}_{interval.value}_{horizon}m"


def _require_new(path: Path) -> Path:
    target = path.expanduser().resolve()
    if target.exists():
        raise SystemExit(f"US-R1 formal evidence is immutable; output already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _write_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    path.write_text(
        json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize one exact US-R1 purged/embargoed fold. Produces the frozen train "
            "15m/60m slice plus OOS 5m/60m, 15m/30m, 15m/60m, 15m/120m and 30m/60m "
            "slices. Requires accepted US-A0 stage authority and never computes Alpha Gate results."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--fold-ordinal", type=int, choices=(1, 2, 3), required=True)
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument(
        "--research-protocol",
        type=Path,
        default=Path("reports/us_r1/us_r1_research_protocol.json"),
    )
    parser.add_argument(
        "--walk-forward",
        type=Path,
        default=Path("reports/us_r1/us_r1_walk_forward.json"),
    )
    parser.add_argument(
        "--formation-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_feature_formation_policy.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument("--a0-gate-review", type=Path, required=True)
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
        default=Path("data/duckdb_temp/us_r1"),
    )
    parser.add_argument("--data-root", type=Path, default=Path("data/us_r1/folds"))
    parser.add_argument("--report-root", type=Path, default=Path("reports/us_r1/folds"))
    return parser


def main() -> int:
    args = build_parser().parse_args()

    # All project/A0 authority checks happen before local dataset discovery or DuckDB setup.
    status = _read_status(args.status)
    authority = require_us_r1_stage_authority(status)
    review_document = _read_mapping(args.a0_gate_review)
    review_id, review_phase, review_decision, review_experiment_id = (
        validate_terminal_a0_review_document(review_document, authority=authority)
    )
    research_protocol = validate_us_r1_protocol_document(
        dict(_read_mapping(args.research_protocol))
    )
    walk_forward = validate_us_r1_walk_forward_document(
        dict(_read_mapping(args.walk_forward))
    )
    formation_policy = canonical_us_r1_feature_formation_policy()
    if dict(_read_mapping(args.formation_policy)) != formation_policy.to_dict():
        raise SystemExit("US-R1 feature-formation policy differs from canonical preregistration")
    denominator = parse_us_r1_candidate_denominator(_read_mapping(args.candidate_denominator))
    if denominator.protocol_id != research_protocol.protocol_id:
        raise SystemExit("US-R1 denominator/research protocol identity mismatch")
    if denominator.a0_gate_review_id != review_id:
        raise SystemExit("US-R1 denominator/A0 terminal review identity mismatch")
    if denominator.a0_experiment_id != review_experiment_id:
        raise SystemExit("US-R1 denominator/A0 experiment identity mismatch")
    if denominator.a0_phase is not review_phase or denominator.a0_gate_decision is not review_decision:
        raise SystemExit("US-R1 denominator/A0 terminal phase or decision mismatch")

    execution_specs = bind_us_r1_fold_execution_specs(walk_forward, denominator)
    execution_spec = execution_specs[args.fold_ordinal - 1]
    fold = walk_forward.folds[args.fold_ordinal - 1]

    # Reuse the accepted B0 certification/universe parser solely for technical asset binding.
    # The returned B0 run-spec is deliberately not serialized into R1 evidence.
    _technical_run_spec, assets = bind_us_b0_run_spec(
        _read_mapping(args.certification),
        _read_mapping(args.engineering_universe),
        denominator=canonical_us_baseline_denominator(),
    )

    calendar = load_trading_calendar_evidence_json(
        args.calendar,
        expected_calendar_id=CALENDAR_ID,
    )
    verified_gap_minutes = verify_us_r1_fold_gap(fold, calendar)

    execution_policy = DuckDBExecutionPolicy(
        memory_limit=args.memory_limit,
        threads=args.threads,
        allow_temp_spill=True,
        max_temp_directory_size=args.max_temp_directory_size,
        preserve_insertion_order=False,
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

    slices = (
        (USR1ObservationRole.TRAIN, BarInterval.MINUTE_15, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_5, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 30),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 60),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_15, 120),
        (USR1ObservationRole.EVALUATION, BarInterval.MINUTE_30, 60),
    )
    fold_data_root = args.data_root / f"fold_{args.fold_ordinal:02d}"
    fold_report_root = args.report_root / f"fold_{args.fold_ordinal:02d}"
    materialized_slices = []

    for role, interval, horizon in slices:
        start = execution_spec.train_start if role is USR1ObservationRole.TRAIN else execution_spec.evaluation_start
        end = execution_spec.train_end if role is USR1ObservationRole.TRAIN else execution_spec.evaluation_end
        resampled_plan, resampling_evidence = resampled.plan(
            _bar_query(assets, start=start, end=end, interval=interval)
        )
        label_plan, label_evidence = labels.plan(
            _label_query(assets, start=start, end=end),
            canonical_us_r1_label_spec(horizon),
        )
        input_plan = build_authoritative_us_r1_input_plan(
            resampled_plan,
            label_plan,
            resampling_evidence,
            label_evidence,
            execution_spec=execution_spec,
            denominator=denominator,
            role=role,
            label_horizon_trading_minutes=horizon,
        )
        joined_rows = count_plan_rows(
            input_plan,
            policy=execution_policy,
            temp_directory=args.temp_directory,
        )
        if joined_rows == 0:
            raise SystemExit(
                f"US-R1 {_slice_name(role, interval, horizon)} input plan returned zero rows"
            )
        if joined_rows > MAX_JOINED_ROWS:
            raise SystemExit(
                "US-R1 evidence slice exceeds 100000 joined rows; keep the bounded Python "
                "boundary and change the implementation rather than weakening the frozen fold"
            )

        slice_name = _slice_name(role, interval, horizon)
        data_dir = fold_data_root / slice_name
        report_dir = fold_report_root / slice_name
        input_output = _require_new(data_dir / "us_r1_inputs.parquet")
        observation_output = _require_new(data_dir / "us_r1_observations.jsonl")
        input_plan_output = _require_new(report_dir / "us_r1_input_plan.json")
        input_materialization_output = _require_new(
            report_dir / "us_r1_input_materialization.json"
        )
        observation_artifact_output = _require_new(
            report_dir / "us_r1_observation_artifact.json"
        )
        diagnostics_output = _require_new(report_dir / "us_r1_observation_diagnostics.json")
        slice_output = _require_new(report_dir / "us_r1_materialization_slice.json")

        _write_json(input_plan_output, input_plan.to_dict())
        validate_us_r1_input_plan_document(_read_mapping(input_plan_output))
        input_materialization = copy_plan_to_parquet(
            input_plan,
            input_output,
            overwrite=False,
            policy=execution_policy,
            temp_directory=args.temp_directory,
        )
        if input_materialization.row_count != joined_rows:
            raise RuntimeError("US-R1 input row count changed during materialization")
        _write_json(input_materialization_output, input_materialization.to_dict())
        parse_minute_materialization(_read_mapping(input_materialization_output))
        rows = fetch_plan_rows(
            _exact_plan(input_plan, input_output),
            limit=joined_rows,
            policy=execution_policy,
            temp_directory=args.temp_directory,
        )
        row_blockers = validate_us_r1_input_rows(rows, expected_assets=assets)
        observations, diagnostics = materialize_us_r1_candidate_observations(
            rows,
            denominator,
            role=role,
            signal_interval=interval,
            label_horizon_trading_minutes=horizon,
            expected_assets=assets,
        )
        diagnostics = merge_us_r1_observation_blockers(diagnostics, row_blockers)
        observation_artifact = write_us_r1_observation_artifact(
            observations,
            observation_output,
            execution_spec=execution_spec,
            denominator=denominator,
            input_plan=input_plan,
        )
        verify_us_r1_observation_file(observation_output, observation_artifact)
        _write_json(observation_artifact_output, observation_artifact.to_dict())
        parse_us_r1_observation_artifact(_read_mapping(observation_artifact_output))
        _write_json(diagnostics_output, diagnostics.to_dict())
        parse_us_r1_observation_diagnostics(_read_mapping(diagnostics_output))
        materialized_slice = build_us_r1_materialization_slice(
            input_plan=input_plan,
            input_materialization=input_materialization,
            observation_artifact=observation_artifact,
            diagnostics=diagnostics,
        )
        _write_json(slice_output, materialized_slice.to_dict())
        materialized_slices.append(materialized_slice)

    fold_manifest = USR1FoldMaterializationManifest(
        research_protocol_id=research_protocol.protocol_id,
        walk_forward_protocol_id=walk_forward.protocol_id,
        execution_spec_id=execution_spec.execution_spec_id,
        denominator_id=denominator.denominator_id,
        formation_policy_id=formation_policy.policy_id,
        fold_id=execution_spec.fold_id,
        fold_ordinal=execution_spec.fold_ordinal,
        verified_gap_trading_minutes=verified_gap_minutes,
        required_gap_trading_minutes=fold.required_gap_trading_minutes,
        slices=tuple(materialized_slices),
    )
    manifest_output = _require_new(fold_report_root / "us_r1_fold_materialization_manifest.json")
    _write_json(manifest_output, fold_manifest.to_dict())
    parse_us_r1_fold_materialization_manifest(_read_mapping(manifest_output))

    print(
        json.dumps(
            {
                "manifest_id": fold_manifest.manifest_id,
                "passed": fold_manifest.passed,
                "blockers": list(fold_manifest.blockers),
                "fold_id": execution_spec.fold_id,
                "fold_ordinal": execution_spec.fold_ordinal,
                "execution_spec_id": execution_spec.execution_spec_id,
                "research_protocol_id": research_protocol.protocol_id,
                "walk_forward_protocol_id": walk_forward.protocol_id,
                "formation_policy_id": formation_policy.policy_id,
                "denominator_id": denominator.denominator_id,
                "a0_gate_review_id": review_id,
                "verified_gap_trading_minutes": verified_gap_minutes,
                "slice_count": len(materialized_slices),
                "slice_ids": [item.observation_artifact_id for item in materialized_slices],
                "market_data_read": True,
                "inference_computed": False,
                "alpha_gate_assessed": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "alpha_authority": False,
                "manifest_output": str(manifest_output),
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if fold_manifest.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
