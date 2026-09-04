from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

import duckdb

from finagent.research.us_r2_base_panel_batch import (
    inspect_completed_us_r2_annual_base_panel,
    us_r2_annual_base_panel_paths,
)
from finagent.research.us_r2_candidate_cache import (
    CANDIDATE_CACHE_BATCH_EVIDENCE_FILENAME,
    CANDIDATE_CACHE_EVIDENCE_FILENAME,
    CANDIDATE_CACHE_FILENAME,
    CANDIDATE_CACHE_PLAN_FILENAME,
    FROZEN_CANDIDATE_COUNT,
    USR2AnnualCandidateCacheArrays,
    USR2AnnualCandidateCacheEvidence,
    USR2AssetCandidateCache,
    USR2CandidateCacheBatchEvidence,
    USR2CandidateExecution,
    build_us_r2_annual_candidate_cache_evidence,
    build_us_r2_candidate_cache_plan,
    combine_us_r2_asset_candidate_caches,
    inspect_completed_us_r2_candidate_cache,
    validate_us_r2_base_panel_batch_gate,
    validate_us_r2_candidate_denominator,
    validate_us_r2_regime_gate,
    write_deterministic_us_r2_candidate_npz,
)
from finagent.research.us_r2_candidate_runtime import (
    materialize_us_r2_asset_candidate_cache_r1_compatible,
)
from finagent.research.us_r2_frozen_protocol import FROZEN_ASSETS

_BASE_COLUMNS = (
    "research_asset_id",
    "session_date",
    "session_id",
    "event_time",
    "available_at",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "is_complete",
    "source_available_at",
    "source_price",
    "target_available_at",
    "label_value",
    "label_available",
    "unavailable_reason",
    "label_row_present",
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _write_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(dict(document), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _row_mapping(row: Sequence[object]) -> Mapping[str, object]:
    if len(row) != len(_BASE_COLUMNS):
        raise RuntimeError("US-R2 candidate base-panel row width mismatch")
    return dict(zip(_BASE_COLUMNS, row, strict=True))


def _configure_duckdb(
    connection: duckdb.DuckDBPyConnection,
    *,
    memory_limit: str,
    threads: int,
    temp_directory: Path,
    max_temp_directory_size: str,
) -> None:
    if threads < 1:
        raise ValueError("threads must be positive")
    temp = temp_directory.expanduser().resolve()
    temp.mkdir(parents=True, exist_ok=True)
    connection.execute(f"SET memory_limit={_sql_string(memory_limit)}")
    connection.execute(f"SET threads={threads}")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory={_sql_string(temp.as_posix())}")
    connection.execute(f"SET max_temp_directory_size={_sql_string(max_temp_directory_size)}")


def _materialize_year(
    *,
    year: int,
    base_path: Path,
    execution: USR2CandidateExecution,
    output_path: Path,
    memory_limit: str,
    threads: int,
    temp_directory: Path,
    max_temp_directory_size: str,
) -> tuple[USR2AnnualCandidateCacheArrays, str, int, tuple[str, ...]]:
    connection = duckdb.connect(database=":memory:")
    try:
        _configure_duckdb(
            connection,
            memory_limit=memory_limit,
            threads=threads,
            temp_directory=temp_directory / f"year_{year:04d}",
            max_temp_directory_size=max_temp_directory_size,
        )
        select_columns = ", ".join(_BASE_COLUMNS)
        sql = (
            f"SELECT {select_columns} "
            f"FROM read_parquet({_sql_string(base_path.expanduser().resolve().as_posix())}) "
            "ORDER BY research_asset_id, available_at"
        )
        cursor = connection.execute(sql)
        caches: list[USR2AssetCandidateCache] = []
        current_asset: str | None = None
        current_rows: list[Mapping[str, object]] = []
        seen_assets: set[str] = set()

        while True:
            raw_batch = cursor.fetchmany(8192)
            if not raw_batch:
                break
            for raw_tuple in raw_batch:
                row = _row_mapping(raw_tuple)
                asset = str(row["research_asset_id"]).strip()
                if asset not in FROZEN_ASSETS:
                    raise ValueError(f"US-R2 annual base panel contains unexpected asset {asset!r}")
                if current_asset is None:
                    current_asset = asset
                if asset != current_asset:
                    if asset in seen_assets:
                        raise ValueError("US-R2 annual base panel asset order is not contiguous")
                    caches.append(
                        materialize_us_r2_asset_candidate_cache_r1_compatible(
                            current_rows,
                            execution,
                            expected_asset=current_asset,
                        )
                    )
                    seen_assets.add(current_asset)
                    current_asset = asset
                    current_rows = []
                current_rows.append(row)

        if current_asset is not None:
            caches.append(
                materialize_us_r2_asset_candidate_cache_r1_compatible(
                    current_rows,
                    execution,
                    expected_asset=current_asset,
                )
            )
            seen_assets.add(current_asset)
        if not caches:
            raise ValueError(f"US-R2 annual base panel contains no rows for {year}")

        arrays = combine_us_r2_asset_candidate_caches(
            caches,
            candidate_count=FROZEN_CANDIDATE_COUNT,
        )
        content_sha256, output_size_bytes = write_deterministic_us_r2_candidate_npz(
            output_path,
            arrays,
        )
        return arrays, content_sha256, output_size_bytes, tuple(sorted(seen_assets))
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize the frozen 37-candidate US-R2 cache from completed annual 15m/60m "
            "base Parquets. The operator validates the reviewed denominator, full 2001-2026 "
            "base-panel batch and regime-v2 evidence before reading any annual Parquet. It has "
            "no raw 1m fallback."
        )
    )
    parser.add_argument(
        "--base-panel-batch-evidence",
        type=Path,
        default=Path("reports/us_r2/base/us_r2_base_panel_batch_evidence.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument(
        "--regime-evidence",
        type=Path,
        default=Path("reports/us_r2/us_r2_regime_projection_evidence_v2.json"),
    )
    parser.add_argument("--base-data-root", type=Path, default=Path("data/us_r2/base"))
    parser.add_argument("--base-report-root", type=Path, default=Path("reports/us_r2/base"))
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
    parser.add_argument("--memory-limit", default="4GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-temp-directory-size", default="20GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_r2_candidates"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    # Fail closed on all research identities before opening DuckDB or any annual data file.
    base_batch = validate_us_r2_base_panel_batch_gate(
        _read_mapping(args.base_panel_batch_evidence)
    )
    denominator = validate_us_r2_candidate_denominator(
        _read_mapping(args.candidate_denominator)
    )
    regime_evidence_id = validate_us_r2_regime_gate(_read_mapping(args.regime_evidence))
    plan, execution = build_us_r2_candidate_cache_plan(
        denominator,
        base_panel_batch_evidence_id=base_batch.evidence_id,
        regime_projection_evidence_id=regime_evidence_id,
    )

    candidate_data_root = args.candidate_data_root.expanduser().resolve()
    candidate_report_root = args.candidate_report_root.expanduser().resolve()
    plan_path = candidate_report_root / CANDIDATE_CACHE_PLAN_FILENAME
    expected_plan = plan.to_dict()
    if plan_path.exists():
        if dict(_read_mapping(plan_path)) != expected_plan:
            raise SystemExit("US-R2 candidate cache plan differs from the frozen shared-DAG plan")
    else:
        _write_json(plan_path, expected_plan)

    source_by_year = {item.year: item for item in base_batch.annual_panels}
    preexisting_years: list[int] = []
    materialized_years: list[int] = []
    annual_evidence: list[USR2AnnualCandidateCacheEvidence] = []
    observed_assets_by_year: dict[int, tuple[str, ...]] = {}

    for year in base_batch.requested_years:
        source_annual = source_by_year[year]
        source_paths = us_r2_annual_base_panel_paths(
            year=year,
            data_root=args.base_data_root.expanduser().resolve(),
            report_root=args.base_report_root.expanduser().resolve(),
        )
        inspected_source = inspect_completed_us_r2_annual_base_panel(source_paths)
        if inspected_source != source_annual:
            raise SystemExit(f"US-R2 local annual base-panel triplet differs from batch evidence: {year}")

        data_path = candidate_data_root / f"year={year:04d}" / CANDIDATE_CACHE_FILENAME
        evidence_path = (
            candidate_report_root / f"year_{year:04d}" / CANDIDATE_CACHE_EVIDENCE_FILENAME
        )
        completed = inspect_completed_us_r2_candidate_cache(
            data_path=data_path,
            evidence_path=evidence_path,
            plan=plan,
            source_annual=source_annual,
        )
        if completed is not None:
            preexisting_years.append(year)
            annual_evidence.append(completed)
            continue

        arrays, content_sha256, output_size_bytes, observed_assets = _materialize_year(
            year=year,
            base_path=source_paths.data_path,
            execution=execution,
            output_path=data_path,
            memory_limit=args.memory_limit,
            threads=args.threads,
            temp_directory=args.temp_directory,
            max_temp_directory_size=args.max_temp_directory_size,
        )
        evidence = build_us_r2_annual_candidate_cache_evidence(
            plan=plan,
            year=year,
            source_annual=source_annual,
            arrays=arrays,
            output_path=data_path,
            content_sha256=content_sha256,
            output_size_bytes=output_size_bytes,
        )
        if not evidence.passed:
            raise SystemExit(f"US-R2 candidate cache evidence failed for {year}")
        _write_json(evidence_path, evidence.to_dict())
        annual_evidence.append(evidence)
        materialized_years.append(year)
        observed_assets_by_year[year] = observed_assets

    batch = USR2CandidateCacheBatchEvidence(
        plan_id=plan.plan_id,
        requested_years=base_batch.requested_years,
        annual_evidence=tuple(annual_evidence),
    )
    if not batch.passed:
        raise SystemExit("US-R2 candidate cache batch did not cover all frozen years")
    batch_path = candidate_report_root / CANDIDATE_CACHE_BATCH_EVIDENCE_FILENAME
    expected_batch = batch.to_dict()
    if batch_path.exists():
        if dict(_read_mapping(batch_path)) != expected_batch:
            raise SystemExit("US-R2 candidate cache batch evidence differs from completed annual set")
    else:
        _write_json(batch_path, expected_batch)

    console = {
        "plan_id": plan.plan_id,
        "compiled_batch_id": plan.compiled_batch_id,
        "base_panel_batch_evidence_id": base_batch.evidence_id,
        "denominator_id": denominator.denominator_id,
        "regime_projection_evidence_id": regime_evidence_id,
        "candidate_count": len(plan.bindings),
        "naive_node_count": plan.naive_node_count,
        "unique_node_count": plan.unique_node_count,
        "reused_node_count": plan.reused_node_count,
        "requested_years": list(base_batch.requested_years),
        "preexisting_years": preexisting_years,
        "materialized_years": materialized_years,
        "annual_base_parquet_scan_count": len(materialized_years),
        "raw_minute_source_invocation_count": 0,
        "candidate_dependent_scan": False,
        "candidate_performance_read": False,
        "raw_minute_source_access": False,
        "observed_assets_by_materialized_year": {
            str(year): list(assets) for year, assets in observed_assets_by_year.items()
        },
        "batch_evidence_id": batch.evidence_id,
        "total_row_count": sum(item.row_count for item in annual_evidence),
        "passed": batch.passed,
        "batch_evidence_output": str(batch_path),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
