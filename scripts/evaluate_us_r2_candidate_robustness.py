from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import duckdb

from finagent.research.us_r2_candidate_robustness import (
    ROBUSTNESS_METRIC_EVIDENCE_FILENAME,
    ROBUSTNESS_METRIC_FILENAME,
    ROBUSTNESS_PLAN_FILENAME,
    ROBUSTNESS_REPORT_FILENAME,
    build_us_r2_annual_candidate_robustness_evidence,
    build_us_r2_candidate_robustness_plan,
    build_us_r2_candidate_robustness_report,
    evaluate_us_r2_annual_candidate_robustness,
    inspect_completed_us_r2_candidate_robustness_metric,
    load_us_r2_robustness_metric_npz,
    parse_us_r2_robustness_base_row,
    validate_us_r2_candidate_denominator_document,
    validate_us_r2_robustness_base_batch_gate,
    write_deterministic_us_r2_robustness_metric_npz,
)
from finagent.research.us_r2_evaluation_policy import (
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import validate_us_r2_frozen_protocol
from finagent.research.us_r2_pooled_inference import (
    parse_us_r2_primary_statistics_plan,
    validate_and_load_us_r2_primary_metric_year,
    validate_us_r2_primary_statistics_report_gate,
)
from finagent.research.us_r2_primary_runtime import parse_us_r2_primary_direction_evidence
from finagent.research.us_r2_primary_statistics import (
    PRIMARY_DIRECTION_FILENAME,
    PRIMARY_METRIC_EVIDENCE_FILENAME,
    PRIMARY_METRIC_FILENAME,
    PRIMARY_PLAN_FILENAME,
    PRIMARY_STATISTICS_REPORT_FILENAME,
    build_us_r2_regime_session_map,
)
from finagent.research.us_r2_robustness_base import (
    ROBUSTNESS_BASE_FILENAME,
    canonical_us_r2_robustness_slices,
)
from finagent.research.us_r2_robustness_batch import (
    ROBUSTNESS_BATCH_EVIDENCE_FILENAME,
    canonical_us_r2_robustness_years,
    inspect_completed_us_r2_annual_robustness_base,
    us_r2_annual_robustness_paths,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _write_or_verify_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        if dict(_read_mapping(target)) != expected:
            raise SystemExit(f"US-R2 immutable evidence differs from expected content: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _regime_rows(path: Path) -> tuple[Mapping[str, object], ...]:
    target = path.expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"US-R2 regime projection Parquet is missing: {target}")
    connection = duckdb.connect(database=":memory:")
    try:
        cursor = connection.execute(
            "SELECT fold_id, session_date, regime_label, regime_available, unavailable_reason "
            "FROM read_parquet(?) ORDER BY fold_id, session_date",
            [str(target)],
        )
        columns = tuple(item[0] for item in cursor.description)
        return tuple(dict(zip(columns, row, strict=True)) for row in cursor.fetchall())
    finally:
        connection.close()


def _load_annual_robustness_rows(
    path: Path,
) -> tuple[dict[str, tuple[object, ...]], int]:
    target = path.expanduser().resolve()
    if not target.is_file() or target.name != ROBUSTNESS_BASE_FILENAME:
        raise FileNotFoundError(f"US-R2 annual robustness-base Parquet is missing: {target}")
    connection = duckdb.connect(database=":memory:")
    try:
        # One physical annual Parquet scan. All four slice reads below hit only this temp relation.
        connection.execute(
            """
            CREATE TEMP TABLE robustness_year AS
            SELECT
                slice_id,
                research_asset_id,
                session_date,
                session_id,
                CAST(event_time AS VARCHAR) AS event_time,
                CAST(available_at AS VARCHAR) AS available_at,
                bar_index,
                open,
                high,
                low,
                close,
                volume,
                is_complete,
                label_value,
                label_available,
                unavailable_reason,
                label_row_present
            FROM read_parquet(?)
            """,
            [str(target)],
        )
        result: dict[str, tuple[object, ...]] = {}
        for spec in canonical_us_r2_robustness_slices():
            cursor = connection.execute(
                """
                SELECT
                    slice_id,
                    research_asset_id,
                    session_date,
                    session_id,
                    event_time,
                    available_at,
                    bar_index,
                    open,
                    high,
                    low,
                    close,
                    volume,
                    is_complete,
                    label_value,
                    label_available,
                    unavailable_reason,
                    label_row_present
                FROM robustness_year
                WHERE slice_id = ?
                ORDER BY available_at, research_asset_id
                """,
                [spec.slice_id],
            )
            columns = tuple(str(item[0]) for item in cursor.description)
            rows = tuple(
                parse_us_r2_robustness_base_row(dict(zip(columns, row, strict=True)))
                for row in cursor.fetchall()
            )
            result[spec.slice_id] = rows
        return result, 1
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate US-R2 frequency/decay robustness for the full frozen 37-candidate denominator. "
            "Alternative 5m/30m and 30m/120m metrics come only from the exact robustness-base "
            "Parquets; primary 15m/60m RankIC is reused from the reviewed compact primary caches. "
            "No raw minute source, primary candidate cache, candidate selection or Alpha Gate is used."
        )
    )
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path("reports/us_r2/us_r2_frozen_protocol.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument(
        "--robustness-base-data-root",
        type=Path,
        default=Path("data/us_r2/robustness/base"),
    )
    parser.add_argument(
        "--robustness-base-report-root",
        type=Path,
        default=Path("reports/us_r2/robustness/base"),
    )
    parser.add_argument(
        "--robustness-base-batch-evidence",
        type=Path,
        default=Path(
            "reports/us_r2/robustness/base/" + ROBUSTNESS_BATCH_EVIDENCE_FILENAME
        ),
    )
    parser.add_argument(
        "--regime-data",
        type=Path,
        default=Path("data/us_r2/regime/us_r2_regime_projection_v2.parquet"),
    )
    parser.add_argument(
        "--regime-evidence",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_projection_evidence_v2.json"),
    )
    parser.add_argument(
        "--primary-data-root",
        type=Path,
        default=Path("data/us_r2/primary"),
    )
    parser.add_argument(
        "--primary-report-root",
        type=Path,
        default=Path("reports/us_r2/primary"),
    )
    parser.add_argument(
        "--output-data-root",
        type=Path,
        default=Path("data/us_r2/robustness/candidate"),
    )
    parser.add_argument(
        "--output-report-root",
        type=Path,
        default=Path("reports/us_r2/robustness/candidate"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))
    denominator = validate_us_r2_candidate_denominator_document(
        _read_mapping(args.candidate_denominator)
    )
    base_batch = validate_us_r2_robustness_base_batch_gate(
        _read_mapping(args.robustness_base_batch_evidence)
    )
    policy = canonical_us_r2_statistical_evaluation_policy()

    primary_report_root = args.primary_report_root.expanduser().resolve()
    primary_plan = parse_us_r2_primary_statistics_plan(
        _read_mapping(primary_report_root / PRIMARY_PLAN_FILENAME),
        denominator,
    )
    direction = parse_us_r2_primary_direction_evidence(
        _read_mapping(primary_report_root / PRIMARY_DIRECTION_FILENAME),
        plan=primary_plan,
    )
    primary_report_gate = validate_us_r2_primary_statistics_report_gate(
        _read_mapping(primary_report_root / PRIMARY_STATISTICS_REPORT_FILENAME),
        plan=primary_plan,
        direction=direction,
        policy=policy,
    )
    regime_evidence_document = _read_mapping(args.regime_evidence)
    regime_map = build_us_r2_regime_session_map(
        _regime_rows(args.regime_data),
        regime_evidence_document,
    )
    if regime_map.evidence_id != primary_plan.regime_projection_evidence_id:
        raise SystemExit("US-R2 robustness regime projection differs from reviewed primary statistics")

    plan = build_us_r2_candidate_robustness_plan(
        denominator,
        robustness_base_batch_evidence_id=base_batch.evidence_id,
        regime_projection_evidence_id=regime_map.evidence_id,
        primary_plan=primary_plan,
        primary_direction=direction,
        primary_statistics_report_id=primary_report_gate.report_id,
    )
    output_data_root = args.output_data_root.expanduser().resolve()
    output_report_root = args.output_report_root.expanduser().resolve()
    _write_or_verify_json(output_report_root / ROBUSTNESS_PLAN_FILENAME, plan.to_dict())

    expected_base_evidence = dict(
        zip(base_batch.requested_years, base_batch.annual_evidence_ids, strict=True)
    )
    expected_base_materialization = dict(
        zip(base_batch.requested_years, base_batch.annual_materialization_ids, strict=True)
    )
    robustness_base_data_root = args.robustness_base_data_root.expanduser().resolve()
    robustness_base_report_root = args.robustness_base_report_root.expanduser().resolve()

    completed_base = {}
    for year in canonical_us_r2_robustness_years():
        paths = us_r2_annual_robustness_paths(
            year=year,
            data_root=robustness_base_data_root,
            report_root=robustness_base_report_root,
        )
        completed = inspect_completed_us_r2_annual_robustness_base(paths)
        if completed is None:
            raise SystemExit(f"US-R2 robustness-base annual triplet is missing: {year}")
        if completed.evidence_id != expected_base_evidence[year]:
            raise SystemExit(f"US-R2 robustness-base annual evidence differs from batch: {year}")
        if completed.materialization_id != expected_base_materialization[year]:
            raise SystemExit(f"US-R2 robustness-base materialization differs from batch: {year}")
        completed_base[year] = completed

    preexisting_years: list[int] = []
    materialized_years: list[int] = []
    annual_metric_evidence = {}
    annual_robustness_base_parquet_scan_count = 0
    feature_interval_evaluation_count = 0
    node_series_evaluation_count = 0
    for year in canonical_us_r2_robustness_years():
        data_path = output_data_root / f"year={year:04d}" / ROBUSTNESS_METRIC_FILENAME
        evidence_path = (
            output_report_root / f"year_{year:04d}" / ROBUSTNESS_METRIC_EVIDENCE_FILENAME
        )
        base = completed_base[year]
        completed_metric = inspect_completed_us_r2_candidate_robustness_metric(
            data_path=data_path,
            evidence_path=evidence_path,
            plan=plan,
            expected_year=year,
            expected_base_evidence_id=base.evidence_id,
            expected_base_materialization_id=base.materialization_id,
        )
        if completed_metric is not None:
            preexisting_years.append(year)
            annual_metric_evidence[year] = completed_metric
            continue

        base_path = robustness_base_data_root / f"year={year:04d}" / ROBUSTNESS_BASE_FILENAME
        raw_rows_by_slice, scan_count = _load_annual_robustness_rows(base_path)
        rows_by_slice = {
            slice_id: cast(tuple, rows) for slice_id, rows in raw_rows_by_slice.items()
        }
        annual_robustness_base_parquet_scan_count += scan_count
        arrays, stats = evaluate_us_r2_annual_candidate_robustness(
            rows_by_slice,
            year=year,
            plan=plan,
            regime_sessions=regime_map,
            policy=policy,
        )
        feature_interval_evaluation_count += stats.feature_interval_evaluation_count
        node_series_evaluation_count += stats.node_series_evaluation_count
        content_sha256, output_size_bytes = write_deterministic_us_r2_robustness_metric_npz(
            data_path,
            arrays,
        )
        evidence = build_us_r2_annual_candidate_robustness_evidence(
            plan=plan,
            year=year,
            robustness_base_evidence_id=base.evidence_id,
            robustness_base_materialization_id=base.materialization_id,
            arrays=arrays,
            stats=stats,
            output_filename=data_path.name,
            output_size_bytes=output_size_bytes,
            content_sha256=content_sha256,
        )
        if not evidence.passed:
            raise SystemExit(f"US-R2 annual candidate robustness evidence failed: {year}")
        _write_or_verify_json(evidence_path, evidence.to_dict())
        annual_metric_evidence[year] = evidence
        materialized_years.append(year)

    robustness_arrays = []
    robustness_metric_npz_scan_count = 0
    robustness_evidence_ids: list[str] = []
    for year in canonical_us_r2_robustness_years():
        evidence = annual_metric_evidence[year]
        data_path = output_data_root / f"year={year:04d}" / ROBUSTNESS_METRIC_FILENAME
        robustness_arrays.append(load_us_r2_robustness_metric_npz(data_path))
        robustness_metric_npz_scan_count += 1
        robustness_evidence_ids.append(evidence.evidence_id)

    primary_data_root = args.primary_data_root.expanduser().resolve()
    primary_arrays = []
    primary_metric_npz_scan_count = 0
    primary_evidence_ids: list[str] = []
    expected_primary_ids = dict(
        zip(
            canonical_us_r2_robustness_years(),
            primary_report_gate.annual_metric_evidence_ids,
            strict=True,
        )
    )
    for year in canonical_us_r2_robustness_years():
        evidence_path = (
            primary_report_root / f"year_{year:04d}" / PRIMARY_METRIC_EVIDENCE_FILENAME
        )
        arrays, evidence = validate_and_load_us_r2_primary_metric_year(
            year=year,
            data_path=primary_data_root / f"year={year:04d}" / PRIMARY_METRIC_FILENAME,
            evidence_document=_read_mapping(evidence_path),
            expected_evidence_id=expected_primary_ids[year],
            plan=primary_plan,
        )
        primary_arrays.append(arrays)
        primary_metric_npz_scan_count += 1
        primary_evidence_ids.append(evidence.evidence_id)

    report = build_us_r2_candidate_robustness_report(
        robustness_arrays,
        primary_arrays,
        plan=plan,
        direction_evidence=direction,
        annual_robustness_metric_evidence_ids=robustness_evidence_ids,
        annual_primary_metric_evidence_ids=primary_evidence_ids,
        policy=policy,
    )
    report_path = output_report_root / ROBUSTNESS_REPORT_FILENAME
    _write_or_verify_json(report_path, report.to_dict())

    console = {
        "plan_id": plan.plan_id,
        "evaluation_policy_id": policy.policy_id,
        "robustness_base_batch_evidence_id": base_batch.evidence_id,
        "robustness_base_total_row_count": base_batch.total_row_count,
        "candidate_count": len(plan.candidate_ids),
        "regime_count": 4,
        "robustness_slice_count": 4,
        "preexisting_metric_years": preexisting_years,
        "materialized_metric_years": materialized_years,
        "annual_robustness_base_parquet_scan_count": annual_robustness_base_parquet_scan_count,
        "feature_interval_evaluation_count": feature_interval_evaluation_count,
        "node_series_evaluation_count": node_series_evaluation_count,
        "robustness_metric_npz_scan_count": robustness_metric_npz_scan_count,
        "primary_metric_npz_scan_count": primary_metric_npz_scan_count,
        "primary_direction_evidence_id": direction.evidence_id,
        "primary_statistics_report_id": primary_report_gate.report_id,
        "candidate_robustness_report_id": report.report_id,
        "robustness_passed_candidate_count": sum(
            item.robustness_passed for item in report.candidates
        ),
        "frequency_robustness_evaluated": True,
        "decay_robustness_evaluated": True,
        "candidate_selection_applied": False,
        "performance_filter_applied": False,
        "raw_minute_source_access": False,
        "primary_candidate_cache_access": False,
        "primary_feature_recomputation": False,
        "alpha_gate_evaluated": False,
        "terminal_authority": False,
        "passed": report.passed,
        "blockers": list(report.blockers),
        "report_output": str(report_path),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not report.passed:
        raise SystemExit("US-R2 candidate robustness evidence failed closed; inspect report blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
