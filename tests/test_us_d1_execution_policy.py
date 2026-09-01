from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.data.minute_store import (
    DEFAULT_MINUTE_STORE_SMOKE_POLICY,
    DuckDBExecutionPolicy,
    MinuteMaterialization,
    MinuteQueryPlan,
    MinuteStoreSmokeReport,
    inspect_execution_settings,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval


def _query(*, asset_count: int = 4) -> MarketDataQuery:
    assets = ("MSFT", "NVDA", "AMD", "INTC")[:asset_count]
    return MarketDataQuery(
        market_id="XNYS",
        assets=assets,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 3, 1, tzinfo=UTC),
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )


def _plan(*, asset_count: int = 4, partition_count: int = 2) -> MinuteQueryPlan:
    months = ("2026-01", "2026-02")[:partition_count]
    return MinuteQueryPlan(
        query=_query(asset_count=asset_count),
        manifest_id="minute-store-manifest-test",
        data_version="minute-store-data-version-test",
        sql="SELECT 1 AS close, 1 AS volume",
        partition_months=months,
        selected_size_bytes=1234,
        output_columns=("close", "volume"),
    )


def _materialization(plan: MinuteQueryPlan, filename: str) -> MinuteMaterialization:
    return MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=42,
        size_bytes=1024,
        content_sha256="a" * 64,
        output_filename=filename,
    )


def test_execution_policy_applies_memory_threads_and_bounded_spill(tmp_path: Path) -> None:
    policy = DuckDBExecutionPolicy(
        memory_limit="128MB",
        threads=1,
        allow_temp_spill=True,
        max_temp_directory_size="64MB",
        preserve_insertion_order=False,
    )

    settings = inspect_execution_settings(
        policy=policy,
        temp_directory=tmp_path / "duckdb-spill",
    )

    assert settings.policy_id == policy.policy_id
    assert settings.observed_threads == 1
    assert not settings.observed_preserve_insertion_order
    assert settings.temp_spill_enabled
    assert settings.temp_directory_configured
    assert settings.observed_memory_limit
    assert settings.observed_max_temp_directory_size
    assert not settings.observed_max_temp_directory_size.startswith("0")


def test_execution_policy_disables_spill_with_zero_capacity() -> None:
    policy = DuckDBExecutionPolicy(
        memory_limit="128MB",
        threads=1,
        allow_temp_spill=False,
        max_temp_directory_size="4GB",
    )

    settings = inspect_execution_settings(policy=policy)

    assert policy.max_temp_directory_size == "0B"
    assert not settings.temp_spill_enabled
    assert not settings.temp_directory_configured
    assert settings.observed_max_temp_directory_size.startswith("0")


def test_no_spill_policy_rejects_explicit_temp_directory(tmp_path: Path) -> None:
    policy = DuckDBExecutionPolicy(allow_temp_spill=False)

    with pytest.raises(ValueError, match="allow_temp_spill=false"):
        inspect_execution_settings(policy=policy, temp_directory=tmp_path)


def test_materialization_identity_is_content_based_not_filename_based() -> None:
    plan = _plan()
    primary = _materialization(plan, "bounded.parquet")
    replay = _materialization(plan, "bounded.replay.parquet")

    assert primary.materialization_id == replay.materialization_id


def test_smoke_report_passes_exact_replay_under_bound_policy(tmp_path: Path) -> None:
    plan = _plan()
    policy = DuckDBExecutionPolicy(
        memory_limit="128MB",
        threads=1,
        max_temp_directory_size="64MB",
    )
    settings = inspect_execution_settings(
        policy=policy,
        temp_directory=tmp_path / "duckdb-spill",
    )
    primary = _materialization(plan, "bounded.parquet")
    replay = _materialization(plan, "bounded.replay.parquet")

    report = MinuteStoreSmokeReport(
        plan=plan,
        smoke_policy=DEFAULT_MINUTE_STORE_SMOKE_POLICY,
        execution_policy=policy,
        execution_settings=settings,
        actual_rows=42,
        primary_materialization=primary,
        replay_materialization=replay,
        replay_match=True,
        ran_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert report.passed
    assert report.blockers == ()
    assert report.report_id.startswith("minute-store-smoke-")
    assert report.to_dict()["execution_settings"] == settings.to_dict()


def test_smoke_report_fails_closed_for_insufficient_scope_and_missing_replay() -> None:
    plan = _plan(asset_count=1, partition_count=1)
    policy = DuckDBExecutionPolicy(allow_temp_spill=False)
    settings = inspect_execution_settings(policy=policy)
    primary = MinuteMaterialization(
        plan_id=plan.plan_id,
        data_version=plan.data_version,
        row_count=42,
        size_bytes=1024,
        content_sha256="a" * 64,
        output_filename="bounded.parquet",
    )

    report = MinuteStoreSmokeReport(
        plan=plan,
        smoke_policy=DEFAULT_MINUTE_STORE_SMOKE_POLICY,
        execution_policy=policy,
        execution_settings=settings,
        actual_rows=42,
        primary_materialization=primary,
        replay_materialization=None,
        replay_match=None,
        ran_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert not report.passed
    assert report.blockers == (
        "query:insufficient_assets",
        "query:insufficient_partitions",
        "replay:not_verified_or_mismatch",
    )
