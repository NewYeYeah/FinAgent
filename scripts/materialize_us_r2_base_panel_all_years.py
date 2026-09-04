from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from finagent.research.us_r2_base_panel_batch import (
    USR2BasePanelBatchRun,
    canonical_us_r2_base_panel_years,
    normalize_us_r2_base_panel_years,
    orchestrate_us_r2_base_panel_batch,
)


def _read_mapping(path: Path) -> Mapping[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return value


def _write_batch_evidence(path: Path, run: USR2BasePanelBatchRun) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    document = run.evidence.to_dict()
    if target.exists():
        existing = _read_mapping(target)
        if existing.get("evidence_id") != document["evidence_id"]:
            raise SystemExit(
                "US-R2 batch evidence output already exists with a different content-addressed ID: "
                f"{target}"
            )
        return
    target.write_text(
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _year_command(
    *,
    root: Path,
    year: int,
    frozen_protocol: Path,
    regime_evidence: Path,
    calendar: Path,
    data_root: Path,
    report_root: Path,
    memory_limit: str,
    threads: int,
    max_temp_directory_size: str,
    temp_directory: Path,
) -> list[str]:
    annual_script = Path(__file__).with_name("materialize_us_r2_base_panel_year.py").resolve()
    return [
        sys.executable,
        str(annual_script),
        str(root),
        "--year",
        str(year),
        "--frozen-protocol",
        str(frozen_protocol),
        "--regime-evidence",
        str(regime_evidence),
        "--calendar",
        str(calendar),
        "--data-root",
        str(data_root),
        "--report-root",
        str(report_root),
        "--memory-limit",
        memory_limit,
        "--threads",
        str(threads),
        "--max-temp-directory-size",
        max_temp_directory_size,
        "--temp-directory",
        str(temp_directory),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resume US-R2 annual 15m/60m base-panel materialization across the frozen 2001-2026 "
            "research range. A valid existing annual Parquet/plan/evidence triplet is verified and "
            "skipped without touching raw 1m data; partial or inconsistent triplets fail closed."
        )
    )
    parser.add_argument("root", type=Path, help="Local admitted OHLCV-1m snapshot root")
    parser.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=None,
        help="Optional subset of frozen years. Default: all 2001-2026 years.",
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
    parser.add_argument(
        "--batch-evidence-output",
        type=Path,
        default=Path("reports/us_r2/base/us_r2_base_panel_batch_evidence.json"),
    )
    parser.add_argument("--memory-limit", default="16GB")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--max-temp-directory-size", default="40GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_r2_base"),
    )
    return parser


def _requested_years(raw_years: Sequence[int] | None) -> tuple[int, ...]:
    if raw_years is None:
        return canonical_us_r2_base_panel_years()
    return normalize_us_r2_base_panel_years(raw_years)


def main() -> int:
    args = build_parser().parse_args()
    years = _requested_years(args.years)
    data_root = args.data_root.expanduser().resolve()
    report_root = args.report_root.expanduser().resolve()

    def materialize_year(year: int) -> None:
        command = _year_command(
            root=args.root,
            year=year,
            frozen_protocol=args.frozen_protocol,
            regime_evidence=args.regime_evidence,
            calendar=args.calendar,
            data_root=data_root,
            report_root=report_root,
            memory_limit=str(args.memory_limit),
            threads=int(args.threads),
            max_temp_directory_size=str(args.max_temp_directory_size),
            temp_directory=args.temp_directory,
        )
        subprocess.run(command, check=True)

    run = orchestrate_us_r2_base_panel_batch(
        years=years,
        data_root=data_root,
        report_root=report_root,
        materialize_year=materialize_year,
    )
    _write_batch_evidence(args.batch_evidence_output, run)
    console = run.to_dict()
    console["batch_evidence_output"] = str(args.batch_evidence_output.expanduser().resolve())
    print(json.dumps(console, sort_keys=True, indent=2, ensure_ascii=False))
    if not run.evidence.passed:
        raise SystemExit("US-R2 all-year base-panel batch failed closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
