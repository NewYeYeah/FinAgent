#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from finagent.backtest import StrategyDecisionSeriesProjection
from finagent.data import (
    AshareBarFrequency,
    LocalAshareDatasetLayout,
    LocalAshareFrozenManifest,
    materialize_local_ashare_market_bar_rows,
    write_market_bar_series,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
_CERTIFIED_AC2_FREQUENCIES = (
    AshareBarFrequency.DAILY,
    AshareBarFrequency.MINUTE_1,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize authoritative MarketBarSeries evidence from frozen local "
            "A-share OHLC. The frozen manifest is mandatory so MarketBarSeries uses "
            "the same content-certified data_version as A2.6/A4/V4-0 instead of an "
            "adapter-local fast fingerprint. This host-side command is not exposed "
            "through the generic Workbench Control Plane."
        )
    )
    parser.add_argument("strategy_manifest", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--frozen-manifest", type=Path, required=True)
    parser.add_argument(
        "--frequency",
        choices=tuple(value.value for value in _CERTIFIED_AC2_FREQUENCIES),
        default=AshareBarFrequency.DAILY.value,
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--data", type=Path)
    parser.add_argument("--verify-content", action="store_true")
    return parser


def _dimensions(projection: StrategyDecisionSeriesProjection) -> tuple[tuple[str, ...], str, str]:
    manifest = projection.manifest
    if manifest.start_date is None or manifest.end_date is None:
        raise ValueError("StrategyDecisionSeries has no date range")
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - dependency guidance
        raise RuntimeError("MarketBarSeries materialization requires the local-parquet extra") from exc
    connection = duckdb.connect()
    try:
        assets = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT asset FROM read_parquet(?) ORDER BY asset",
                (str(projection.data_path),),
            ).fetchall()
        )
    finally:
        connection.close()
    if not assets:
        raise ValueError("StrategyDecisionSeries contains no assets")
    return assets, manifest.start_date, manifest.end_date


def main() -> int:
    args = _parser().parse_args()
    strategy = StrategyDecisionSeriesProjection(args.strategy_manifest)
    assets, start_date, end_date = _dimensions(strategy)
    frequency = AshareBarFrequency(args.frequency)
    start_day = datetime.fromisoformat(start_date).date()
    end_day = datetime.fromisoformat(end_date).date()
    start = datetime.combine(start_day, time.min, tzinfo=SHANGHAI)
    # Daily local queries compare dates inclusively, while intraday queries use a
    # half-open timestamp range. Keep the final strategy session exact in both cases.
    end = (
        datetime.combine(end_day, time.max, tzinfo=SHANGHAI)
        if frequency is AshareBarFrequency.DAILY
        else datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=SHANGHAI)
    )
    layout = LocalAshareDatasetLayout(args.root)
    frozen = LocalAshareFrozenManifest.read_json(args.frozen_manifest)
    if frequency.value not in frozen.frequencies:
        raise ValueError(
            f"frozen local A-share manifest does not include frequency {frequency.value!r}"
        )
    frozen.verify(layout, verify_content=bool(args.verify_content))
    if frozen.dataset_version != strategy.manifest.data_version:
        raise ValueError(
            "MarketBarSeries frozen dataset version differs from StrategyDecisionSeries: "
            f"{frozen.dataset_version!r} != {strategy.manifest.data_version!r}"
        )

    (
        rows,
        interval,
        timestamp_convention,
        session_spec,
        label_horizon_policy,
        data_version,
    ) = materialize_local_ashare_market_bar_rows(
        layout=layout,
        asset_keys=assets,
        start=start,
        end=end,
        frequency=frequency,
        data_version=frozen.dataset_version,
    )
    if data_version != strategy.manifest.data_version:
        raise ValueError(
            "MarketBarSeries refuses to bind a data version that differs from the "
            "StrategyDecisionSeries: "
            f"{data_version!r} != {strategy.manifest.data_version!r}"
        )
    strategy_path = Path(args.strategy_manifest).resolve()
    stem = strategy_path.name.removesuffix(".json")
    manifest_path = (
        args.manifest or strategy_path.with_name(f"{stem}.market-bars.json")
    ).resolve()
    data_path = (
        args.data or strategy_path.with_name(f"{stem}.market-bars.parquet")
    ).resolve()
    manifest = write_market_bar_series(
        linked_strategy_series_id=strategy.manifest.series_id,
        portfolio_validation_id=strategy.manifest.portfolio_validation_id,
        source_identity=(
            f"local_ashare_frozen:{frozen.dataset_version}:"
            f"{Path(args.frozen_manifest).resolve().name}"
        ),
        data_version=data_version,
        interval=interval,
        timestamp_convention=timestamp_convention,
        session_spec=session_spec,
        label_horizon_policy=label_horizon_policy,
        rows=rows,
        manifest_path=manifest_path,
        data_path=data_path,
    )
    print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
