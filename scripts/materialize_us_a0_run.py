from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
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
from finagent.research.us_agent_value_authority import bind_authorized_us_a0_predecessor
from finagent.research.us_agent_value_evaluation import (
    aggregate_us_a0_run_evaluation,
    bind_us_a0_evaluation,
    bind_us_a0_fold_execution_specs,
    build_run_evaluation_link,
    evaluate_us_a0_fold,
    materialize_us_a0_observations,
)
from finagent.research.us_agent_value_execution import (
    USAgentValueFoldMaterializationManifest,
    build_us_a0_run_evidence_manifest,
    parse_candidate_generation_run,
    validate_us_a0_execution_plan,
)
from finagent.research.us_baseline_authority import bind_current_us_b0_run_spec
from finagent.research.us_baseline_materialization import (
    USBaselineInputPlan,
    build_us_baseline_input_plan,
    write_us_baseline_observation_artifact,
)
from finagent.research.us_baselines import canonical_us_baseline_denominator

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"
MAX_JOINED_ROWS_PER_FOLD = 100_000


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
        return cast(Mapping[str, object], tomllib.load(handle))


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _writable(path: Path, *, overwrite: bool) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not overwrite:
        raise SystemExit(f"output already exists; pass --overwrite explicitly: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _write_json(path: Path, payload: Mapping[str, object] | dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(payload), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _bar_query(assets: tuple[str, ...], *, start: object, end: object) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,  # type: ignore[arg-type]
        end=end,  # type: ignore[arg-type]
        interval=BarInterval.MINUTE_15,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _label_query(assets: tuple[str, ...], *, start: object, end: object) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=start,  # type: ignore[arg-type]
        end=end,  # type: ignore[arg-type]
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _exact_materialization_plan(input_plan: USBaselineInputPlan, path: Path) -> _LocalParquetPlan:
    return _LocalParquetPlan(
        plan_id=input_plan.plan_id,
        data_version=input_plan.data_version,
        sql=f"SELECT * FROM read_parquet({_sql_string(path.as_posix())})",
        output_columns=input_plan.output_columns,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute one preregistered US-A0 generation run through the same certified XNYS "
            "three-fold feature/label/statistical evaluator used by US-B0. Formal financial "
            "execution is fail-closed until docs/status.toml current_stage=US-A0 and reviewed "
            "US-B0 predecessor identities are recorded."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--execution-plan", type=Path, required=True)
    parser.add_argument("--generation-run", type=Path, required=True)
    parser.add_argument(
        "--status",
        type=Path,
        default=Path("docs/status.toml"),
    )
    parser.add_argument(
        "--us-b0-evidence-graph",
        type=Path,
        default=Path("reports/us_b0/us_b0_walkforward_evidence_graph.json"),
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
        default=Path("data/duckdb_temp/us_a0"),
    )
    parser.add_argument(
        "--data-output-root",
        type=Path,
        default=Path("data/us_a0/runs"),
    )
    parser.add_argument(
        "--report-output-root",
        type=Path,
        default=Path("reports/us_a0/runs"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    preregistration = _read_mapping(args.preregistration.expanduser().resolve())
    execution_plan_document = _read_mapping(args.execution_plan.expanduser().resolve())
    protocol, execution_plan = validate_us_a0_execution_plan(
        execution_plan_document,
        preregistration,
    )
    generation_document = _read_mapping(args.generation_run.expanduser().resolve())
    generation_run = parse_candidate_generation_run(generation_document, execution_plan)

    status = _read_status(args.status.expanduser().resolve())
    predecessor_graph = _read_mapping(args.us_b0_evidence_graph.expanduser().resolve())
    predecessor = bind_authorized_us_a0_predecessor(status, predecessor_graph, protocol)

    certification = _read_mapping(args.certification.expanduser().resolve())
    universe = _read_mapping(args.engineering_universe.expanduser().resolve())
    source_us_b0_run_spec, assets = bind_current_us_b0_run_spec(
        certification,
        universe,
        denominator=canonical_us_baseline_denominator(),
    )
    if source_us_b0_run_spec.spec_id != predecessor.us_b0_run_spec_id:
        raise SystemExit(
            "accepted US-B0 predecessor graph and reconstructed certification-bound run spec "
            "do not share the same run-spec identity"
        )
    binding = bind_us_a0_evaluation(
        protocol,
        predecessor,
        generation_run,
        source_us_b0_run_spec,
    )

    run_data_root = args.data_output_root.expanduser().resolve() / generation_run.run_id
    run_report_root = args.report_output_root.expanduser().resolve() / generation_run.run_id
    binding_output = _writable(
        run_report_root / "us_a0_evaluation_binding.json",
        overwrite=args.overwrite,
    )
    _write_json(binding_output, binding.to_dict())

    if not generation_run.accepted_candidates:
        run_evaluation = aggregate_us_a0_run_evaluation(binding, ())
        evaluation_link = build_run_evaluation_link(generation_run, run_evaluation)
        run_manifest = build_us_a0_run_evidence_manifest(
            execution_plan=execution_plan,
            predecessor=predecessor,
            generation_run=generation_run,
            evaluation_binding=binding,
            fold_manifests=(),
            run_evaluation=run_evaluation,
            evaluation_link=evaluation_link,
        )
        _write_json(
            _writable(run_report_root / "us_a0_run_evaluation.json", overwrite=args.overwrite),
            run_evaluation.to_dict(),
        )
        _write_json(
            _writable(run_report_root / "us_a0_run_evaluation_link.json", overwrite=args.overwrite),
            evaluation_link.to_dict(),
        )
        _write_json(
            _writable(run_report_root / "us_a0_run_evidence_manifest.json", overwrite=args.overwrite),
            run_manifest.to_dict(),
        )
        print(
            json.dumps(
                {
                    "run_id": generation_run.run_id,
                    "arm": generation_run.spec.arm.value,
                    "phase": generation_run.spec.phase.value,
                    "status": run_evaluation.status.value,
                    "accepted_candidate_count": 0,
                    "fold_count": 0,
                    "technical_passed": run_manifest.technical_passed,
                    "run_evaluation_report_id": run_evaluation.report_id,
                    "run_evaluation_link_id": evaluation_link.link_id,
                    "run_evidence_manifest_id": run_manifest.manifest_id,
                    "agent_value_gate_authority": False,
                },
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

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

    fold_manifests: list[USAgentValueFoldMaterializationManifest] = []
    fold_reports = []
    execution_specs = bind_us_a0_fold_execution_specs(protocol, binding)
    for execution_spec in execution_specs:
        fold_name = f"fold_{execution_spec.fold_ordinal:02d}"
        fold_data_root = run_data_root / fold_name
        fold_report_root = run_report_root / fold_name
        fold_temp = args.temp_directory.expanduser().resolve() / generation_run.run_id / fold_name
        start = next(
            fold.evaluation_start
            for fold in __import__(
                "finagent.research.us_baseline_walkforward",
                fromlist=["canonical_us_b0_pilot_walk_forward"],
            ).canonical_us_b0_pilot_walk_forward().folds
            if fold.ordinal == execution_spec.fold_ordinal
        )
        end = next(
            fold.evaluation_end
            for fold in __import__(
                "finagent.research.us_baseline_walkforward",
                fromlist=["canonical_us_b0_pilot_walk_forward"],
            ).canonical_us_b0_pilot_walk_forward().folds
            if fold.ordinal == execution_spec.fold_ordinal
        )

        resampled_plan, resampling_evidence = resampled.plan(
            _bar_query(assets, start=start, end=end)
        )
        label_plan, label_evidence = labels.plan(
            _label_query(assets, start=start, end=end),
            canonical_same_session_60m_label_spec(),
        )
        input_plan = build_us_baseline_input_plan(
            resampled_plan,
            label_plan,
            resampling_evidence,
            label_evidence,
            run_spec=binding.run_spec,
        )
        joined_rows = count_plan_rows(
            input_plan,
            policy=execution_policy,
            temp_directory=fold_temp,
        )
        if joined_rows == 0:
            raise SystemExit(f"A0 {fold_name} input plan returned zero rows")
        if joined_rows > MAX_JOINED_ROWS_PER_FOLD:
            raise SystemExit(
                f"A0 {fold_name} exceeds {MAX_JOINED_ROWS_PER_FOLD} joined rows; do not "
                "weaken the bounded Python materialization boundary"
            )

        input_output = _writable(
            fold_data_root / "us_a0_inputs.parquet",
            overwrite=args.overwrite,
        )
        observation_output = _writable(
            fold_data_root / "us_a0_observations.jsonl",
            overwrite=args.overwrite,
        )
        input_materialization = copy_plan_to_parquet(
            input_plan,
            input_output,
            overwrite=args.overwrite,
            policy=execution_policy,
            temp_directory=fold_temp,
        )
        if input_materialization.row_count != joined_rows:
            raise RuntimeError(f"A0 {fold_name} input row count changed during materialization")
        rows = fetch_plan_rows(
            _exact_materialization_plan(input_plan, input_output),
            limit=joined_rows,
            policy=execution_policy,
            temp_directory=fold_temp,
        )
        observations, diagnostics = materialize_us_a0_observations(
            rows,
            binding.denominator,
            expected_assets=assets,
        )
        observation_artifact = write_us_baseline_observation_artifact(
            observations,
            observation_output,
            run_spec=binding.run_spec,
        )

        _write_json(
            _writable(fold_report_root / "us_a0_input_plan.json", overwrite=args.overwrite),
            input_plan.to_dict(),
        )
        _write_json(
            _writable(
                fold_report_root / "us_a0_input_materialization.json",
                overwrite=args.overwrite,
            ),
            input_materialization.to_dict(),
        )
        _write_json(
            _writable(
                fold_report_root / "us_a0_observation_artifact.json",
                overwrite=args.overwrite,
            ),
            observation_artifact.to_dict(),
        )
        _write_json(
            _writable(fold_report_root / "us_a0_diagnostics.json", overwrite=args.overwrite),
            diagnostics.to_dict(),
        )
        if not diagnostics.passed:
            print(
                json.dumps(
                    {
                        "run_id": generation_run.run_id,
                        "fold_ordinal": execution_spec.fold_ordinal,
                        "technical_passed": False,
                        "technical_blockers": list(diagnostics.blockers),
                        "stage_exit_authority": False,
                    },
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 2

        fold_evaluation = evaluate_us_a0_fold(binding, execution_spec, observations)
        fold_evaluation_output = _writable(
            fold_report_root / "us_a0_fold_evaluation.json",
            overwrite=args.overwrite,
        )
        _write_json(fold_evaluation_output, fold_evaluation.to_dict())
        fold_manifest = USAgentValueFoldMaterializationManifest(
            execution_plan_id=execution_plan.plan_id,
            preregistration_bundle_id=execution_plan.preregistration_bundle_id,
            generation_run_id=generation_run.run_id,
            evaluation_binding_id=binding.binding_id,
            fold_execution_spec_id=execution_spec.execution_spec_id,
            fold_ordinal=execution_spec.fold_ordinal,
            input_plan_id=input_plan.plan_id,
            input_materialization_id=input_materialization.materialization_id,
            observation_artifact_id=observation_artifact.artifact_id,
            diagnostics=diagnostics,
            fold_evaluation_report_id=fold_evaluation.report_id,
            engineering_asset_count=len(assets),
        )
        _write_json(
            _writable(
                fold_report_root / "us_a0_fold_materialization_manifest.json",
                overwrite=args.overwrite,
            ),
            fold_manifest.to_dict(),
        )
        fold_manifests.append(fold_manifest)
        fold_reports.append(fold_evaluation)

    run_evaluation = aggregate_us_a0_run_evaluation(binding, tuple(fold_reports))
    evaluation_link = build_run_evaluation_link(generation_run, run_evaluation)
    run_manifest = build_us_a0_run_evidence_manifest(
        execution_plan=execution_plan,
        predecessor=predecessor,
        generation_run=generation_run,
        evaluation_binding=binding,
        fold_manifests=tuple(fold_manifests),
        run_evaluation=run_evaluation,
        evaluation_link=evaluation_link,
    )
    _write_json(
        _writable(run_report_root / "us_a0_run_evaluation.json", overwrite=args.overwrite),
        run_evaluation.to_dict(),
    )
    _write_json(
        _writable(run_report_root / "us_a0_run_evaluation_link.json", overwrite=args.overwrite),
        evaluation_link.to_dict(),
    )
    _write_json(
        _writable(run_report_root / "us_a0_run_evidence_manifest.json", overwrite=args.overwrite),
        run_manifest.to_dict(),
    )
    print(
        json.dumps(
            {
                "run_id": generation_run.run_id,
                "arm": generation_run.spec.arm.value,
                "phase": generation_run.spec.phase.value,
                "accepted_candidate_count": len(generation_run.accepted_candidates),
                "evaluated_candidate_count": run_evaluation.evaluated_candidate_count,
                "valid_candidate_count": run_evaluation.valid_candidate_count,
                "fold_count": len(fold_reports),
                "technical_passed": run_manifest.technical_passed,
                "run_evaluation_report_id": run_evaluation.report_id,
                "run_evaluation_link_id": evaluation_link.link_id,
                "run_evidence_manifest_id": run_manifest.manifest_id,
                "agent_value_gate_authority": False,
                "alpha_authority": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if run_manifest.technical_passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
