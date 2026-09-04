from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_r2_frozen_protocol import validate_us_r2_frozen_protocol
from finagent.research.us_r2_pooled_inference import (
    POOLED_INFERENCE_REPORT_FILENAME,
    POOLED_INFERENCE_YEARS,
    build_us_r2_pooled_inference_report,
    validate_and_load_us_r2_primary_metric_year,
    validate_us_r2_pooled_inputs,
)
from finagent.research.us_r2_primary_statistics import (
    PRIMARY_DIRECTION_FILENAME,
    PRIMARY_METRIC_EVIDENCE_FILENAME,
    PRIMARY_METRIC_FILENAME,
    PRIMARY_PLAN_FILENAME,
    PRIMARY_POLICY_FILENAME,
    PRIMARY_STATISTICS_REPORT_FILENAME,
    USR2AnnualPrimaryMetricArrays,
)


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
            raise SystemExit(f"US-R2 immutable pooled inference differs from expected: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate preregistered US-R2 pooled primary inference from the 21 reviewed annual "
            "primary-metric NPZ caches. The operator reuses accepted R1 HAC/session-block "
            "bootstrap semantics and applies Holm/BH over the exact 37-candidate denominator. "
            "It never reads candidate caches, annual base Parquet or raw 1m, and it does not "
            "evaluate frequency/decay robustness or the final Alpha Gate."
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
        "--output",
        type=Path,
        default=Path(f"reports/us_r2/primary/{POOLED_INFERENCE_REPORT_FILENAME}"),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    validate_us_r2_frozen_protocol(_read_mapping(args.frozen_protocol))

    report_root = args.primary_report_root.expanduser().resolve()
    denominator, policy, plan, direction, primary_gate = validate_us_r2_pooled_inputs(
        denominator_document=_read_mapping(args.candidate_denominator),
        policy_document=_read_mapping(report_root / PRIMARY_POLICY_FILENAME),
        plan_document=_read_mapping(report_root / PRIMARY_PLAN_FILENAME),
        direction_document=_read_mapping(report_root / PRIMARY_DIRECTION_FILENAME),
        primary_report_document=_read_mapping(report_root / PRIMARY_STATISTICS_REPORT_FILENAME),
    )

    data_root = args.primary_data_root.expanduser().resolve()
    annual_arrays: list[tuple[int, USR2AnnualPrimaryMetricArrays]] = []
    primary_metric_npz_scan_count = 0
    annual_evidence_ids: list[str] = []
    for offset, year in enumerate(POOLED_INFERENCE_YEARS):
        evidence_path = report_root / f"year_{year:04d}" / PRIMARY_METRIC_EVIDENCE_FILENAME
        data_path = data_root / f"year={year:04d}" / PRIMARY_METRIC_FILENAME
        arrays, evidence = validate_and_load_us_r2_primary_metric_year(
            year=year,
            data_path=data_path,
            evidence_document=_read_mapping(evidence_path),
            expected_evidence_id=primary_gate.annual_metric_evidence_ids[offset],
            plan=plan,
        )
        annual_arrays.append((year, arrays))
        annual_evidence_ids.append(evidence.evidence_id)
        primary_metric_npz_scan_count += 1
    if tuple(annual_evidence_ids) != primary_gate.annual_metric_evidence_ids:
        raise SystemExit("US-R2 pooled inference annual evidence order changed after validation")

    report = build_us_r2_pooled_inference_report(
        annual_arrays,
        plan=plan,
        direction=direction,
        primary_gate=primary_gate,
        denominator=denominator,
        policy=policy,
    )
    _write_or_verify_json(args.output, report.to_dict())

    console = {
        "primary_statistics_report_id": primary_gate.report_id,
        "primary_statistics_plan_id": plan.plan_id,
        "evaluation_policy_id": policy.policy_id,
        "direction_evidence_id": direction.evidence_id,
        "denominator_id": denominator.denominator_id,
        "candidate_count": len(report.candidates),
        "primary_metric_npz_scan_count": primary_metric_npz_scan_count,
        "annual_metric_year_count": len(annual_arrays),
        "multiplicity_denominator_count": len(report.candidates),
        "rank_ic_hac_evaluated": True,
        "rank_ic_session_block_bootstrap_evaluated": True,
        "long_short_hac_diagnostic_evaluated": True,
        "long_short_session_block_bootstrap_diagnostic_evaluated": True,
        "holm_evaluated": True,
        "bh_evaluated": True,
        "frequency_robustness_evaluated": False,
        "decay_robustness_evaluated": False,
        "candidate_selection_applied": False,
        "alpha_gate_evaluated": False,
        "raw_minute_source_access": False,
        "annual_base_parquet_access": False,
        "candidate_cache_npz_access": False,
        "candidate_feature_recomputation": False,
        "terminal_authority": False,
        "pooled_inference_report_id": report.report_id,
        "passed": report.passed,
        "report_output": str(args.output.expanduser().resolve()),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not report.passed:
        raise SystemExit("US-R2 pooled inference failed closed; inspect technical blockers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
