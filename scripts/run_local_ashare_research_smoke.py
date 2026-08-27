#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import tomllib
from datetime import UTC, date, datetime, time
from pathlib import Path

import numpy as np
from scipy.stats import rankdata

from finagent.data import (
    AshareBarFrequency,
    AshareSupplementalDataStore,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    LocalAshareParquetDataAdapter,
    LocalAshareSecurityMaster,
    SupplementedAshareSecurityMaster,
)
from finagent.domain.research import DatasetRequest, TimeRange


def _date(value: object, name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"{name} must use YYYY-MM-DD") from exc


def _range(start: date, end: date) -> TimeRange:
    if end <= start:
        raise ValueError("research split end must be after start")
    # Local A-share daily bars become available at 16:00 Asia/Shanghai. Midnight
    # boundaries are converted by the adapter from aware UTC timestamps.
    from zoneinfo import ZoneInfo

    shanghai = ZoneInfo("Asia/Shanghai")
    return TimeRange(
        datetime.combine(start, time.min, tzinfo=shanghai).astimezone(UTC),
        datetime.combine(end, time.min, tzinfo=shanghai).astimezone(UTC),
    )


def _load(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        payload = tomllib.load(handle)
    values = payload.get("local_ashare_research_smoke")
    if not isinstance(values, dict):
        raise TypeError("configuration must contain [local_ashare_research_smoke]")
    return values


def _rank_ic(
    factor: np.ndarray,
    label: np.ndarray,
    eligibility: np.ndarray,
    *,
    min_cross_section: int,
) -> tuple[float, int]:
    values: list[float] = []
    for row in range(factor.shape[0]):
        mask = eligibility[row] & np.isfinite(factor[row]) & np.isfinite(label[row])
        if int(mask.sum()) < min_cross_section:
            continue
        left = rankdata(factor[row][mask], method="average")
        right = rankdata(label[row][mask], method="average")
        if float(np.std(left)) <= 1e-15 or float(np.std(right)) <= 1e-15:
            continue
        value = float(np.corrcoef(left, right)[0, 1])
        if math.isfinite(value):
            values.append(value)
    if not values:
        return 0.0, 0
    return float(np.mean(values)), len(values)


def _split_report(dataset, split_name: str, primary_feature: str, primary_label: str, min_cs: int):
    panel = dataset.get_split(split_name)
    if np.isinf(panel.feature_values).any() or np.isinf(panel.label_values).any():
        raise RuntimeError(f"split {split_name!r} contains +/-inf")
    eligibility = np.asarray(panel.eligibility_mask, dtype=bool)
    feature = panel.feature_panel(primary_feature)
    label = panel.label_panel(primary_label)
    eligible_cells = int(eligibility.sum())
    finite_feature = int((eligibility & np.isfinite(feature)).sum())
    finite_label = int((eligibility & np.isfinite(label)).sum())
    rank_ic, periods = _rank_ic(
        feature,
        label,
        eligibility,
        min_cross_section=min_cs,
    )
    return {
        "timestamps": panel.n_times,
        "assets": panel.n_assets,
        "eligible_cells": eligible_cells,
        "primary_feature_coverage": (
            float(finite_feature / eligible_cells) if eligible_cells else 0.0
        ),
        "primary_label_coverage": (
            float(finite_label / eligible_cells) if eligible_cells else 0.0
        ),
        "primary_rank_ic": rank_ic,
        "rank_ic_periods": periods,
        "start": panel.timestamps[0].isoformat(),
        "end": panel.timestamps[-1].isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a historical-only local A-share system smoke through the canonical "
            "ResearchDataset interface. No A-share execution or realtime API is used."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument("--root", type=Path, help="override local dataset root")
    parser.add_argument("--manifest", type=Path, help="override frozen manifest")
    parser.add_argument("--report", type=Path, help="override report path")
    parser.add_argument(
        "--verify-content",
        action="store_true",
        help="re-hash every frozen file in the selected daily manifest before research",
    )
    args = parser.parse_args()

    values = _load(args.config)
    root = args.root or Path(str(values["root"]))
    manifest_path = args.manifest or Path(str(values["frozen_manifest"]))
    report_path = args.report or Path(str(values["report_path"]))
    layout = LocalAshareDatasetLayout(root)

    frozen = LocalAshareFrozenManifest.read_json(manifest_path)
    if AshareBarFrequency.DAILY.value not in frozen.frequencies:
        raise ValueError("frozen manifest does not include daily A-share data")
    frozen.verify(layout, verify_content=True if args.verify_content else False)

    base_master = LocalAshareSecurityMaster.from_parquet(layout.basic_path)
    supplement_path = Path(str(values.get("supplement_root", "reference_data/a_share")))
    supplement = AshareSupplementalDataStore.from_directory(supplement_path)
    master = SupplementedAshareSecurityMaster(base_master, supplement)

    raw_symbols = values.get("symbols")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ValueError("symbols must be a non-empty array")
    requested_codes = tuple(str(value).strip().upper() for value in raw_symbols)
    by_code = {record.ts_code: record.asset for record in master.records}
    missing = sorted(set(requested_codes) - set(by_code))
    if missing:
        raise KeyError(f"security master has no requested symbols: {missing}")
    universe = tuple(by_code[code] for code in requested_codes)

    features_raw = values.get("features")
    labels_raw = values.get("labels")
    if not isinstance(features_raw, list) or not isinstance(labels_raw, list):
        raise TypeError("features and labels must be arrays")
    features = tuple(str(value) for value in features_raw)
    labels = tuple(str(value) for value in labels_raw)
    primary_feature = str(values["primary_feature"])
    primary_label = str(values["primary_label"])
    if primary_feature not in features or primary_label not in labels:
        raise ValueError("primary_feature/primary_label must be included in features/labels")

    development = _range(
        _date(values["development_start"], "development_start"),
        _date(values["development_end_exclusive"], "development_end_exclusive"),
    )
    validation = _range(
        _date(values["validation_start"], "validation_start"),
        _date(values["validation_end_exclusive"], "validation_end_exclusive"),
    )
    if development.end > validation.start:
        raise ValueError("development and validation windows overlap")

    adapter = LocalAshareParquetDataAdapter(
        layout,
        frequency=AshareBarFrequency.DAILY,
        security_master=master,
        data_version=frozen.dataset_version,
    )
    dataset = adapter.build_dataset(
        DatasetRequest(
            universe=universe,
            features=features,
            labels=labels,
            splits={"development": development, "validation": validation},
            dataset_id="local-ashare-system-smoke",
            metadata={
                "frozen_manifest": str(manifest_path),
                "supplement_version": supplement.data_version,
                "test_scope": "historical_daily_only_no_execution",
            },
        )
    )
    min_cs = int(values.get("min_cross_section", 5))
    min_periods = int(values.get("min_periods", 20))
    split_reports = {
        name: _split_report(dataset, name, primary_feature, primary_label, min_cs)
        for name in ("development", "validation")
    }
    for name, report in split_reports.items():
        if int(report["rank_ic_periods"]) < min_periods:
            raise RuntimeError(
                f"split {name!r} has only {report['rank_ic_periods']} usable RankIC periods; "
                f"minimum is {min_periods}"
            )

    payload = {
        "schema_version": "finagent.local-ashare-system-smoke.v1",
        "scope": "historical_daily_research_only_no_execution_no_realtime",
        "passed": True,
        "frozen_dataset_version": frozen.dataset_version,
        "supplement": supplement.to_manifest(),
        "security_master": {
            "data_version": master.data_version,
            "survivorship_certified": master.survivorship_certified,
            "limitations": list(master.limitations),
        },
        "research_dataset": {
            "artifact_id": dataset.artifact.artifact_id,
            "digest": dataset.artifact.digest,
            "data_version": adapter.data_version,
            "universe": [asset.key for asset in universe],
            "features": list(features),
            "labels": list(labels),
        },
        "diagnostic": {
            "primary_feature": primary_feature,
            "primary_label": primary_label,
            "note": "RankIC is a deterministic system smoke diagnostic, not promotion evidence.",
        },
        "splits": split_reports,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
