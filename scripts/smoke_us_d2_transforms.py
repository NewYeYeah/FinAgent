from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from finagent.data.minute_store import (
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    copy_plan_to_parquet,
    count_plan_rows,
    manifest_from_huggingface_snapshot,
)
from finagent.data.minute_transform import (
    CalendarSessionizedMinuteStore,
    SameSessionLabelStore,
    SessionResampledMinuteStore,
    assess_research_price_authority,
    canonical_same_session_60m_label_spec,
    load_trading_calendar_evidence_json,
    unavailable_us_minute_corporate_action_coverage,
)
from finagent.data.minute_transform.smoke import (
    D2ActionAuthoritySmokeCheck,
    D2LabelSmokeCheck,
    D2ResampleSmokeCheck,
    D2ScenarioSmokeCheck,
    D2TransformSmokePolicy,
    D2TransformSmokeReport,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval

SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
INVENTORY_ID = "us-minute-inventory-c2cbf682b456f97eb613ed65"
CLEANING_ID = "us-minute-cleaning-stack-a0d745a4a75d25a63e3a8244"
CALENDAR_ID = "trading-calendar-03a9c29f566d6634aedbbbdc"
DEFAULT_ASSETS = ("MSFT", "NVDA", "AMD", "INTC")


@dataclass(frozen=True, slots=True)
class _Scenario:
    name: str
    start: datetime
    end: datetime
    expected_regular_minutes: int


_SCENARIOS = (
    _Scenario(
        name="half_day",
        start=datetime(2025, 11, 28, 14, 30, tzinfo=UTC),
        end=datetime(2025, 11, 28, 18, 0, tzinfo=UTC),
        expected_regular_minutes=210,
    ),
    _Scenario(
        name="pre_dst",
        start=datetime(2026, 3, 6, 14, 30, tzinfo=UTC),
        end=datetime(2026, 3, 6, 21, 0, tzinfo=UTC),
        expected_regular_minutes=390,
    ),
    _Scenario(
        name="post_dst",
        start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
        end=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
        expected_regular_minutes=390,
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run row-free US-D2 session/resampling/label/action smoke against the admitted "
            "local OHLCV-1m snapshot."
        )
    )
    parser.add_argument("root", type=Path)
    parser.add_argument(
        "--calendar",
        type=Path,
        default=Path("reports/us_calendar/xnys_1992_2026.json"),
    )
    parser.add_argument("--asset", action="append")
    parser.add_argument("--memory-limit", default="512MB")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--max-temp-directory-size", default="4GB")
    parser.add_argument(
        "--temp-directory",
        type=Path,
        default=Path("data/duckdb_temp/us_d2"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/dev_samples/us_d2_smoke"),
    )
    parser.add_argument(
        "--report-output",
        type=Path,
        default=Path("reports/us_d2/us_d2_transform_smoke_report.json"),
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _assets(raw: list[str] | None) -> tuple[str, ...]:
    values = raw or list(DEFAULT_ASSETS)
    assets = tuple(sorted(dict.fromkeys(value.strip() for value in values if value.strip())))
    if len(assets) < 4:
        raise SystemExit("US-D2 smoke requires at least four assets")
    if len(assets) > 32:
        raise SystemExit("US-D2 smoke is capped at 32 assets")
    return assets


def _raw_query(
    assets: tuple[str, ...],
    scenario: _Scenario,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=scenario.start,
        end=scenario.end,
        interval=BarInterval.MINUTE_1,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )


def _resample_query(
    assets: tuple[str, ...],
    scenario: _Scenario,
    interval: BarInterval,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=scenario.start,
        end=scenario.end,
        interval=interval,
        fields=tuple(MarketDataField),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )


def _label_query(
    assets: tuple[str, ...],
    scenario: _Scenario,
) -> MarketDataQuery:
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=scenario.start + timedelta(minutes=1),
        end=scenario.end + timedelta(minutes=1),
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.REGULAR,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _resample_summary(path: Path) -> tuple[int, int, int, float | None]:
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            f"""
            SELECT
                count(*) AS rows,
                count(*) FILTER (WHERE is_complete) AS complete_rows,
                count(*) FILTER (WHERE NOT is_complete) AS incomplete_rows,
                min(coverage_ratio) AS minimum_coverage_ratio
            FROM read_parquet('{path.as_posix()}')
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("resample summary returned no row")
        return (
            int(row[0]),
            int(row[1]),
            int(row[2]),
            float(row[3]) if row[3] is not None else None,
        )
    finally:
        connection.close()


def _label_summary(path: Path) -> tuple[int, int, int, int, int]:
    connection = duckdb.connect(database=":memory:")
    try:
        row = connection.execute(
            f"""
            SELECT
                count(*) AS rows,
                count(*) FILTER (WHERE label_available) AS available_rows,
                count(*) FILTER (WHERE unavailable_reason = 'target_crosses_session') AS crosses,
                count(*) FILTER (WHERE unavailable_reason = 'target_minute_missing') AS missing,
                count(*) FILTER (
                    WHERE NOT label_available
                      AND unavailable_reason NOT IN ('target_crosses_session', 'target_minute_missing')
                ) AS other_unavailable
            FROM read_parquet('{path.as_posix()}')
            """
        ).fetchone()
        if row is None:
            raise RuntimeError("label summary returned no row")
        return (int(row[0]), int(row[1]), int(row[2]), int(row[3]), int(row[4]))
    finally:
        connection.close()


def _action_authority_check(assets: tuple[str, ...]) -> D2ActionAuthoritySmokeCheck:
    coverage = unavailable_us_minute_corporate_action_coverage(assets)
    same_session_allowed = True
    cross_session_denied = True
    split_adjusted_denied = True
    total_return_denied = True
    for asset in assets:
        same_session = assess_research_price_authority(
            coverage,
            asset=asset,
            start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            end=datetime(2026, 3, 9, 20, 0, tzinfo=UTC),
            price_basis=ResearchPriceBasis.RAW,
            allow_cross_session=False,
        )
        cross_session = assess_research_price_authority(
            coverage,
            asset=asset,
            start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            end=datetime(2026, 3, 10, 20, 0, tzinfo=UTC),
            price_basis=ResearchPriceBasis.RAW,
            allow_cross_session=True,
        )
        split = assess_research_price_authority(
            coverage,
            asset=asset,
            start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            end=datetime(2026, 3, 10, 20, 0, tzinfo=UTC),
            price_basis=ResearchPriceBasis.SPLIT_ADJUSTED,
            allow_cross_session=True,
        )
        total = assess_research_price_authority(
            coverage,
            asset=asset,
            start=datetime(2026, 3, 9, 13, 30, tzinfo=UTC),
            end=datetime(2026, 3, 10, 20, 0, tzinfo=UTC),
            price_basis=ResearchPriceBasis.TOTAL_RETURN_ADJUSTED,
            allow_cross_session=True,
        )
        same_session_allowed = same_session_allowed and same_session.allowed
        cross_session_denied = cross_session_denied and not cross_session.allowed
        split_adjusted_denied = split_adjusted_denied and not split.allowed
        total_return_denied = total_return_denied and not total.allowed
    return D2ActionAuthoritySmokeCheck(
        coverage_id=coverage.coverage_id,
        same_session_raw_allowed=same_session_allowed,
        cross_session_raw_denied=cross_session_denied,
        split_adjusted_denied=split_adjusted_denied,
        total_return_adjusted_denied=total_return_denied,
    )


def main() -> int:
    args = build_parser().parse_args()
    assets = _assets(args.asset)
    output_dir = args.output_dir.expanduser().resolve()
    if output_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"output directory already exists: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

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
    sessionized_store = CalendarSessionizedMinuteStore(raw_store, calendar)
    resampled_store = SessionResampledMinuteStore(sessionized_store)
    label_store = SameSessionLabelStore(sessionized_store)
    label_spec = canonical_same_session_60m_label_spec()

    scenario_checks: list[D2ScenarioSmokeCheck] = []
    for scenario in _SCENARIOS:
        regular_plan, _ = sessionized_store.plan(_raw_query(assets, scenario))
        regular_count = count_plan_rows(
            regular_plan,
            policy=execution_policy,
            temp_directory=args.temp_directory,
        )

        resample_checks: list[D2ResampleSmokeCheck] = []
        for interval in (BarInterval.MINUTE_5, BarInterval.MINUTE_15, BarInterval.MINUTE_30):
            resampled_plan, _ = resampled_store.plan(
                _resample_query(assets, scenario, interval)
            )
            target = output_dir / f"{scenario.name}_{interval.value}.parquet"
            materialization = copy_plan_to_parquet(
                resampled_plan,
                target,
                overwrite=True,
                policy=execution_policy,
                temp_directory=args.temp_directory,
            )
            rows, complete, incomplete, minimum_coverage = _resample_summary(target)
            resample_checks.append(
                D2ResampleSmokeCheck(
                    interval=interval,
                    row_count=rows,
                    complete_row_count=complete,
                    incomplete_row_count=incomplete,
                    minimum_coverage_ratio=minimum_coverage,
                    materialization_id=materialization.materialization_id,
                    content_sha256=materialization.content_sha256,
                )
            )

        label_plan, _ = label_store.plan(_label_query(assets, scenario), label_spec)
        label_target = output_dir / f"{scenario.name}_labels.parquet"
        label_materialization = copy_plan_to_parquet(
            label_plan,
            label_target,
            overwrite=True,
            policy=execution_policy,
            temp_directory=args.temp_directory,
        )
        total, available, crosses, missing, other = _label_summary(label_target)
        label_check = D2LabelSmokeCheck(
            row_count=total,
            available_row_count=available,
            target_crosses_session_count=crosses,
            target_minute_missing_count=missing,
            other_unavailable_count=other,
            materialization_id=label_materialization.materialization_id,
            content_sha256=label_materialization.content_sha256,
            label_plan_id=label_plan.plan_id,
            label_data_version=label_plan.data_version,
        )
        scenario_checks.append(
            D2ScenarioSmokeCheck(
                name=scenario.name,
                start=scenario.start,
                end=scenario.end,
                expected_regular_minutes_per_asset=scenario.expected_regular_minutes,
                asset_count=len(assets),
                regular_1m_row_count=regular_count,
                resamples=tuple(resample_checks),
                labels=label_check,
            )
        )

    policy = D2TransformSmokePolicy(calendar_id=CALENDAR_ID)
    report = D2TransformSmokeReport(
        policy=policy,
        calendar_id=calendar.calendar_id,
        manifest_id=manifest.manifest_id,
        source_data_version=manifest.data_version,
        assets=assets,
        scenarios=tuple(scenario_checks),
        action_authority=_action_authority_check(assets),
        ran_at=datetime.now(UTC),
    )
    report_output = args.report_output.expanduser().resolve()
    report_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.write_text(
        json.dumps(report.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {**report.to_dict(), "report_output": str(report_output)},
            sort_keys=True,
            indent=2,
        )
    )
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
