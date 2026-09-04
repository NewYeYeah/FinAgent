from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_r2_robustness_batch import (
    ROBUSTNESS_BATCH_EVIDENCE_FILENAME,
    canonical_us_r2_robustness_years,
    materialize_us_r2_robustness_batch,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], value)


def _write_or_verify_json(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        if dict(_read_mapping(target)) != expected:
            raise SystemExit(f"US-R2 immutable robustness batch evidence differs: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume the exact US-R2 robustness base across 2006-2026. Completed annual Parquet/"
            "plan/evidence triplets are content-validated and skipped without touching raw 1m; "
            "partial or inconsistent triplets fail closed."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--years",
        type=int,
        nargs="*",
        default=list(canonical_us_r2_robustness_years()),
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
    data_root = args.data_root.expanduser().resolve()
    report_root = args.report_root.expanduser().resolve()
    annual_script = Path(__file__).with_name("materialize_us_r2_robustness_base_year.py").resolve()

    def materialize_year(year: int) -> None:
        command = [
            sys.executable,
            str(annual_script),
            str(args.root),
            "--year",
            str(year),
            "--frozen-protocol",
            str(args.frozen_protocol),
            "--calendar",
            str(args.calendar),
            "--data-root",
            str(data_root),
            "--report-root",
            str(report_root),
            "--memory-limit",
            str(args.memory_limit),
            "--threads",
            str(args.threads),
            "--max-temp-directory-size",
            str(args.max_temp_directory_size),
            "--temp-directory",
            str(args.temp_directory),
        ]
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            raise SystemExit(f"US-R2 robustness annual materializer failed for {year}")

    evidence, preexisting, materialized = materialize_us_r2_robustness_batch(
        years=tuple(args.years),
        data_root=data_root,
        report_root=report_root,
        materialize_year=materialize_year,
    )
    evidence_output = report_root / ROBUSTNESS_BATCH_EVIDENCE_FILENAME
    _write_or_verify_json(evidence_output, evidence.to_dict())

    console = {
        "evidence_id": evidence.evidence_id,
        "policy_id": evidence.policy_id,
        "requested_years": list(evidence.requested_years),
        "preexisting_years": list(preexisting),
        "materialized_years": list(materialized),
        "completed_years": list(evidence.requested_years),
        "raw_source_invocation_count": len(materialized),
        "annual_evidence_count": len(evidence.annual_evidence_ids),
        "total_row_count": evidence.total_row_count,
        "candidate_dependent_scan": False,
        "candidate_performance_read": False,
        "candidate_selection_applied": False,
        "alpha_gate_evaluated": False,
        "terminal_authority": False,
        "passed": evidence.passed,
        "batch_evidence_output": str(evidence_output),
    }
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not evidence.passed:
        raise SystemExit("US-R2 robustness base batch failed closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
