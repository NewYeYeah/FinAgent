from __future__ import annotations

import argparse
import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import cast

import duckdb

from finagent.research.us_r2_candidate_cache import (
    CANDIDATE_CACHE_EVIDENCE_FILENAME,
    CANDIDATE_CACHE_FILENAME,
    USR2AnnualCandidateCacheArrays,
    USR2AnnualCandidateCacheEvidence,
    parse_us_r2_annual_candidate_cache_evidence,
)
from finagent.research.us_r2_evaluation_policy import (
    canonical_us_r2_statistical_evaluation_policy,
)
from finagent.research.us_r2_frozen_protocol import validate_us_r2_frozen_protocol
from finagent.research.us_r2_primary_direction import (
    build_us_r2_primary_direction_evidence_exact,
)
from finagent.research.us_r2_primary_runtime import (
    build_us_r2_primary_metric_materialization_evidence,
    parse_us_r2_primary_direction_evidence,
)
from finagent.research.us_r2_primary_statistics import (
    FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID,
    PRIMARY_DIRECTION_FILENAME,
    PRIMARY_METRIC_EVIDENCE_FILENAME,
    PRIMARY_METRIC_FILENAME,
    PRIMARY_PLAN_FILENAME,
    PRIMARY_POLICY_FILENAME,
    PRIMARY_STATISTICS_REPORT_FILENAME,
    USR2AnnualPrimaryMetricArrays,
    USR2AnnualPrimaryMetricEvidence,
    build_us_r2_primary_statistics_plan,
    build_us_r2_primary_statistics_report,
    build_us_r2_regime_session_map,
    evaluate_us_r2_annual_primary_metrics,
    inspect_completed_us_r2_primary_metric_cache,
    load_us_r2_primary_metric_npz,
    validate_and_load_us_r2_candidate_year,
    validate_us_r2_candidate_cache_batch_gate,
    validate_us_r2_candidate_cache_plan_gate,
    write_deterministic_us_r2_primary_metric_npz,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate the preregistered US-R2 primary 15m/60m fold x regime statistics from the "
            "reviewed annual candidate NPZ cache. Direction is frozen from fold-01 TRAIN only. "
            "No raw 1m, annual base Parquet, candidate feature recomputation or Alpha Gate is used."
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
        "--candidate-cache-plan",
        type=Path,
        default=Path("reports/us_r2/candidates/us_r2_candidate_cache_plan.json"),
    )
    parser.add_argument(
        "--candidate-cache-batch-evidence",
        type=Path,
        default=Path("reports/us_r2/candidates/us_r2_candidate_cache_batch_evidence.json"),
    )
    parser.add_argument(
        "--candidate-data-root",
        type=Path,
        default=Path("data/us_r2/candidates"),
    )
    parser.add_argument(
        "--candidate-report-root",
        type=Path,
        default=Path("reports/us_r2/candidates"),
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
    parser.add_argument("--output-data-root", type=Path, default=Path("data/us_r2/primary"))
    parser.add_argument(
        "--output-report-root",
        type=Path,
        default=Path("reports/us_r2/primary"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    # Resolve all content-addressed authority before opening any candidate NPZ.
    validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))
    candidate_plan, denominator = validate_us_r2_candidate_cache_plan_gate(
        _read_mapping(args.candidate_cache_plan),
        _read_mapping(args.candidate_denominator),
    )
    cache_batch = validate_us_r2_candidate_cache_batch_gate(
        _read_mapping(args.candidate_cache_batch_evidence)
    )
    if cache_batch.evidence_id != FROZEN_CANDIDATE_CACHE_BATCH_EVIDENCE_ID:
        raise SystemExit("US-R2 candidate-cache batch identity changed after validation")
    regime_evidence_document = _read_mapping(args.regime_evidence)
    regime_map = build_us_r2_regime_session_map(
        _regime_rows(args.regime_data),
        regime_evidence_document,
    )
    plan = build_us_r2_primary_statistics_plan(
        candidate_plan,
        denominator,
        candidate_cache_batch_evidence_id=cache_batch.evidence_id,
        regime_projection_evidence_id=regime_map.evidence_id,
    )
    policy = canonical_us_r2_statistical_evaluation_policy()
    output_data_root = args.output_data_root.expanduser().resolve()
    output_report_root = args.output_report_root.expanduser().resolve()
    _write_or_verify_json(output_report_root / PRIMARY_POLICY_FILENAME, policy.to_dict())
    _write_or_verify_json(output_report_root / PRIMARY_PLAN_FILENAME, plan.to_dict())

    expected_source_id = dict(
        zip(cache_batch.requested_years, cache_batch.annual_evidence_ids, strict=True)
    )
    source_evidence: dict[int, USR2AnnualCandidateCacheEvidence] = {}
    candidate_report_root = args.candidate_report_root.expanduser().resolve()
    candidate_data_root = args.candidate_data_root.expanduser().resolve()
    for year in cache_batch.requested_years:
        evidence_path = (
            candidate_report_root / f"year_{year:04d}" / CANDIDATE_CACHE_EVIDENCE_FILENAME
        )
        candidate_evidence = parse_us_r2_annual_candidate_cache_evidence(
            _read_mapping(evidence_path)
        )
        if candidate_evidence.evidence_id != expected_source_id[year]:
            raise SystemExit(f"US-R2 candidate-cache annual evidence differs from batch: {year}")
        if (
            candidate_evidence.plan_id != candidate_plan.plan_id
            or candidate_evidence.year != year
            or not candidate_evidence.passed
        ):
            raise SystemExit(f"US-R2 candidate-cache annual evidence is not admitted: {year}")
        source_evidence[year] = candidate_evidence

    candidate_npz_scan_count = 0
    direction_path = output_report_root / PRIMARY_DIRECTION_FILENAME
    direction_materialized = False
    if direction_path.exists():
        direction = parse_us_r2_primary_direction_evidence(
            _read_mapping(direction_path),
            plan=plan,
        )
        expected_direction_ids = tuple(
            source_evidence[year].evidence_id for year in range(2001, 2006)
        )
        if direction.source_annual_evidence_ids != expected_direction_ids:
            raise SystemExit("US-R2 primary direction source annual evidence changed")
    else:
        direction_materialized = True

        def direction_inputs() -> Iterator[tuple[int, USR2AnnualCandidateCacheArrays]]:
            nonlocal candidate_npz_scan_count
            for year in range(2001, 2006):
                data_path = candidate_data_root / f"year={year:04d}" / CANDIDATE_CACHE_FILENAME
                arrays, _candidate_evidence = validate_and_load_us_r2_candidate_year(
                    year=year,
                    data_path=data_path,
                    evidence_document=source_evidence[year].to_dict(),
                    expected_evidence_id=source_evidence[year].evidence_id,
                    expected_plan_id=candidate_plan.plan_id,
                )
                candidate_npz_scan_count += 1
                yield year, arrays

        direction = build_us_r2_primary_direction_evidence_exact(
            direction_inputs(),
            plan=plan,
            source_annual_evidence_ids={
                year: source_evidence[year].evidence_id for year in range(2001, 2006)
            },
            policy=policy,
        )
        _write_or_verify_json(direction_path, direction.to_dict())
    if not direction.passed:
        console = {
            "plan_id": plan.plan_id,
            "evaluation_policy_id": policy.policy_id,
            "candidate_cache_batch_evidence_id": cache_batch.evidence_id,
            "direction_evidence_id": direction.evidence_id,
            "direction_passed": False,
            "direction_blocked_candidate_count": sum(not item.passed for item in direction.candidates),
            "candidate_npz_scan_count": candidate_npz_scan_count,
            "raw_minute_source_access": False,
            "annual_base_parquet_access": False,
            "candidate_feature_recomputation": False,
        }
        print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
        raise SystemExit("US-R2 primary direction freeze failed closed; inspect direction evidence")

    preexisting_years: list[int] = []
    materialized_years: list[int] = []
    annual_metric_evidence: dict[int, USR2AnnualPrimaryMetricEvidence] = {}
    for year in range(2006, 2027):
        source = source_evidence[year]
        data_path = output_data_root / f"year={year:04d}" / PRIMARY_METRIC_FILENAME
        evidence_path = (
            output_report_root / f"year_{year:04d}" / PRIMARY_METRIC_EVIDENCE_FILENAME
        )
        completed = inspect_completed_us_r2_primary_metric_cache(
            data_path=data_path,
            evidence_path=evidence_path,
            plan=plan,
            source_evidence=source,
        )
        if completed is not None:
            preexisting_years.append(year)
            annual_metric_evidence[year] = completed
            continue

        source_data_path = candidate_data_root / f"year={year:04d}" / CANDIDATE_CACHE_FILENAME
        candidate_arrays, _candidate_evidence = validate_and_load_us_r2_candidate_year(
            year=year,
            data_path=source_data_path,
            evidence_document=source.to_dict(),
            expected_evidence_id=source.evidence_id,
            expected_plan_id=candidate_plan.plan_id,
        )
        candidate_npz_scan_count += 1
        metric_arrays, fold_id, source_formations, unavailable_sessions = (
            evaluate_us_r2_annual_primary_metrics(
                candidate_arrays,
                year=year,
                plan=plan,
                regime_sessions=regime_map,
                policy=policy,
            )
        )
        content_sha256, output_size_bytes = write_deterministic_us_r2_primary_metric_npz(
            data_path,
            metric_arrays,
        )
        metric_evidence = build_us_r2_primary_metric_materialization_evidence(
            plan=plan,
            year=year,
            fold_id=fold_id,
            source_evidence=source,
            source_formation_count=source_formations,
            regime_unavailable_session_count=unavailable_sessions,
            arrays=metric_arrays,
            output_filename=data_path.name,
            content_sha256=content_sha256,
            output_size_bytes=output_size_bytes,
        )
        if not metric_evidence.passed:
            raise SystemExit(f"US-R2 primary metric materialization evidence failed: {year}")
        _write_or_verify_json(evidence_path, metric_evidence.to_dict())
        annual_metric_evidence[year] = metric_evidence
        materialized_years.append(year)

    # Primary report reads only the compact period-metric caches. Candidate feature caches are not reopened.
    fold_ids = tuple(
        item.fold_id
        for item in validate_us_r2_frozen_protocol(
            _read_mapping(args.frozen_protocol)
        ).walk_forward_protocol.folds
    )
    metrics_by_fold: dict[str, list[USR2AnnualPrimaryMetricArrays]] = {
        fold_id: [] for fold_id in fold_ids
    }
    primary_metric_npz_scan_count = 0
    annual_metric_ids: list[str] = []
    for year in range(2006, 2027):
        metric_evidence = annual_metric_evidence[year]
        data_path = output_data_root / f"year={year:04d}" / PRIMARY_METRIC_FILENAME
        arrays = load_us_r2_primary_metric_npz(data_path)
        primary_metric_npz_scan_count += 1
        metrics_by_fold[metric_evidence.fold_id].append(arrays)
        annual_metric_ids.append(metric_evidence.evidence_id)

    report = build_us_r2_primary_statistics_report(
        metrics_by_fold,
        plan=plan,
        direction_evidence=direction,
        annual_metric_evidence_ids=annual_metric_ids,
        policy=policy,
    )
    report_path = output_report_root / PRIMARY_STATISTICS_REPORT_FILENAME
    _write_or_verify_json(report_path, report.to_dict())

    console = {
        "plan_id": plan.plan_id,
        "evaluation_policy_id": policy.policy_id,
        "candidate_cache_batch_evidence_id": cache_batch.evidence_id,
        "candidate_cache_total_row_count": cache_batch.total_row_count,
        "candidate_count": len(plan.candidate_ids),
        "direction_evidence_id": direction.evidence_id,
        "direction_materialized": direction_materialized,
        "direction_passed": direction.passed,
        "preexisting_metric_years": preexisting_years,
        "materialized_metric_years": materialized_years,
        "candidate_npz_scan_count": candidate_npz_scan_count,
        "primary_metric_npz_scan_count": primary_metric_npz_scan_count,
        "regime_projection_evidence_id": regime_map.evidence_id,
        "primary_statistics_report_id": report.report_id,
        "primary_slice_count": len(report.slices),
        "primary_blocker_count": len(report.blockers),
        "passed": report.passed,
        "raw_minute_source_access": False,
        "annual_base_parquet_access": False,
        "candidate_feature_recomputation": False,
        "candidate_selection_applied": False,
        "alpha_gate_evaluated": False,
        "terminal_authority": False,
        "report_output": str(report_path),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not report.passed:
        raise SystemExit("US-R2 primary fold-regime statistics failed closed; inspect report blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
