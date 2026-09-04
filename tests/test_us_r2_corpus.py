from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from finagent.data.minute_store.execution import DuckDBExecutionPolicy
from finagent.data.minute_store.manifest import MinuteStoreManifest, MinuteStorePartition
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.us_r1_protocol import canonical_us_r1_research_protocol
from finagent.research.us_r2_corpus import (
    build_us_r2_corpus_inventory_plan,
    execute_us_r2_corpus_inventory,
)
from finagent.research.us_r2_protocol import (
    USMultiRegimeFold,
    USMultiRegimeWalkForwardProtocol,
    USRegimeDefinitionPolicy,
    USRegimeFeatureSource,
    USRegimeFeatureSpec,
)


def _calendar() -> TradingCalendarEvidence:
    return TradingCalendarEvidence(
        market_id="XNYS",
        timezone="America/New_York",
        source="synthetic-xnys",
        source_revision="test-v1",
        sessions=(
            TradingSession(
                session_date=date(2026, 1, 2),
                open_at=datetime(2026, 1, 2, 14, 30, tzinfo=UTC),
                close_at=datetime(2026, 1, 2, 14, 32, tzinfo=UTC),
                is_half_day=True,
            ),
        ),
        regular_session_minutes=390,
    )


def _manifest(path: Path) -> MinuteStoreManifest:
    return MinuteStoreManifest(
        source_id="synthetic-us-minute",
        source_revision="revision-1",
        cleaning_identity="cleaning-1",
        inventory_id="inventory-1",
        partitions=(
            MinuteStorePartition(
                month="2026-01",
                path=path,
                size_bytes=path.stat().st_size if path.exists() else 123,
            ),
        ),
    )


def _write_fixture(path: Path) -> None:
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute(
            """
            CREATE TABLE raw (
                timestamp TIMESTAMPTZ,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                volume DOUBLE,
                ticker VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO raw VALUES
                (TIMESTAMPTZ '2026-01-02T14:30:00+00:00', 10, 11, 9, 10.5, 100, 'AAA'),
                (TIMESTAMPTZ '2026-01-02T14:30:00+00:00', 10, 11, 9, 10.5, 100, 'AAA'),
                (TIMESTAMPTZ '2026-01-02T14:31:00+00:00', 10.5, 11, 10, 10.8, 110, 'AAA'),
                (TIMESTAMPTZ '2026-01-02T14:30:00+00:00', 20, 21, 19, 20.5, 200, 'BBB'),
                (TIMESTAMPTZ '2026-01-02T14:31:00+00:00', 20.5, 21, 20, 20.8, 210, 'BBB'),
                (TIMESTAMPTZ '2026-01-02T14:31:00+00:00', 20.5, 21, 20, 20.9, 210, 'BBB'),
                (TIMESTAMPTZ '2026-01-02T13:00:00+00:00', 99, 100, 98, 99.5, 1, 'AAA')
            """
        )
        escaped = path.as_posix().replace("'", "''")
        connection.execute(f"COPY raw TO '{escaped}' (FORMAT PARQUET)")
    finally:
        connection.close()


def test_inventory_plan_uses_one_candidate_independent_aggregate_scan(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path / "ohlcv_2026-01.parquet")
    plan = build_us_r2_corpus_inventory_plan(manifest, _calendar(), ("BBB", "AAA", "AAA"))

    assert plan.assets == ("AAA", "BBB")
    assert plan.sql.count("read_parquet(") == 1
    assert "WHERE p.ticker IN ('AAA', 'BBB')" in plan.sql
    assert "INNER JOIN calendar" in plan.sql
    assert "GROUP BY ticker, timestamp, session_date" in plan.sql
    assert "ORDER BY research_asset_id, partition_month" in plan.sql
    assert "candidate" not in plan.sql.lower()
    assert plan.to_dict()["candidate_dependent_scan"] is False
    assert plan.to_dict()["source_rows_emitted"] is False


def test_inventory_executes_cleaning_and_retains_breadth_without_source_rows(tmp_path: Path) -> None:
    parquet = tmp_path / "ohlcv_2026-01.parquet"
    _write_fixture(parquet)
    manifest = _manifest(parquet)
    calendar = _calendar()
    plan = build_us_r2_corpus_inventory_plan(manifest, calendar, ("AAA", "BBB"))
    corpus = execute_us_r2_corpus_inventory(
        plan,
        manifest,
        calendar,
        engineering_universe_id="engineering-universe-test",
        candidate_denominator_id="us-r1-denominator-test",
        policy=DuckDBExecutionPolicy(
            memory_limit="256MB",
            threads=1,
            allow_temp_spill=False,
            max_temp_directory_size="0B",
            preserve_insertion_order=False,
        ),
    )

    assert corpus.passed
    assert corpus.blockers == ()
    assert len(corpus.month_coverages) == 2
    by_asset = {item.asset: item for item in corpus.month_coverages}
    aaa = by_asset["AAA"]
    bbb = by_asset["BBB"]
    assert aaa.observed_regular_minute_count == 2
    assert aaa.complete_session_count == 1
    assert aaa.exact_duplicate_extra_row_count == 1
    assert aaa.regular_minute_coverage_ratio == pytest.approx(1.0)
    assert bbb.observed_regular_minute_count == 1
    assert bbb.complete_session_count == 0
    assert bbb.conflicting_key_count == 1
    assert bbb.regular_minute_coverage_ratio == pytest.approx(0.5)
    assert corpus.common_all_asset_start == date(2026, 1, 2)
    assert corpus.common_all_asset_end == date(2026, 1, 2)
    assert corpus.common_all_asset_session_count == 1
    assert corpus.year_breadth[0].observed_asset_count_histogram == (0, 0, 1)
    assert corpus.year_breadth[0].complete_asset_count_histogram == (0, 1, 0)
    payload = corpus.to_dict()
    assert payload["candidate_performance_read"] is False
    assert payload["performance_filter_applied"] is False
    assert payload["survivorship_safe_market_claim"] is False


def test_inventory_retains_missing_asset_as_explicit_zero_cell_and_blocker(tmp_path: Path) -> None:
    parquet = tmp_path / "ohlcv_2026-01.parquet"
    _write_fixture(parquet)
    manifest = _manifest(parquet)
    calendar = _calendar()
    plan = build_us_r2_corpus_inventory_plan(manifest, calendar, ("AAA", "MISSING"))
    corpus = execute_us_r2_corpus_inventory(
        plan,
        manifest,
        calendar,
        engineering_universe_id="engineering-universe-test",
        candidate_denominator_id="us-r1-denominator-test",
        policy=DuckDBExecutionPolicy(
            memory_limit="256MB",
            threads=1,
            allow_temp_spill=False,
            max_temp_directory_size="0B",
            preserve_insertion_order=False,
        ),
    )

    assert not corpus.passed
    assert "asset_without_regular_session_history:MISSING" in corpus.blockers
    missing = next(item for item in corpus.month_coverages if item.asset == "MISSING")
    assert missing.expected_session_count == 1
    assert missing.observed_session_count == 0
    assert missing.missing_session_count == 1
    assert len(corpus.month_coverages) == len(plan.assets) * len(plan.partition_months)


def _regime_policy() -> USRegimeDefinitionPolicy:
    return USRegimeDefinitionPolicy(
        features=(
            USRegimeFeatureSpec(
                name="iwm_realized_volatility_20s",
                source=USRegimeFeatureSource.MARKET_ANCHOR_REALIZED_VOLATILITY,
                lookback_sessions=20,
                anchor_asset="IWM",
            ),
            USRegimeFeatureSpec(
                name="cross_sectional_dispersion_20s",
                source=USRegimeFeatureSource.CROSS_SECTIONAL_DISPERSION,
                lookback_sessions=20,
            ),
        )
    )


def test_multi_regime_protocol_preserves_r1_denominator_and_inference_semantics() -> None:
    r1 = canonical_us_r1_research_protocol()
    protocol = USMultiRegimeWalkForwardProtocol(
        corpus_id="us-r2-regime-corpus-test",
        candidate_denominator_id="us-r1-denominator-be5184ac3883b0799c00c5dc",
        r1_protocol_id=r1.protocol_id,
        regime_policy=_regime_policy(),
        folds=(
            USMultiRegimeFold(
                fold_id="fold-01-high-vol",
                train_start=date(2019, 1, 1),
                train_end=date(2020, 1, 1),
                evaluation_start=date(2020, 2, 1),
                evaluation_end=date(2020, 7, 1),
                expected_regimes=("HIGH_VOL",),
            ),
            USMultiRegimeFold(
                fold_id="fold-02-low-vol",
                train_start=date(2021, 1, 1),
                train_end=date(2022, 1, 1),
                evaluation_start=date(2022, 2, 1),
                evaluation_end=date(2022, 7, 1),
                expected_regimes=("LOW_VOL",),
            ),
        ),
    )

    payload = protocol.to_dict()
    assert payload["candidate_denominator_preserved"] is True
    assert payload["performance_filter_applied"] is False
    assert payload["new_agent_candidates_admitted"] is False
    inherited = payload["inherited_research_semantics"]
    assert isinstance(inherited, dict)
    assert inherited["primary_interval"] == "15m"
    assert inherited["label_name"] == "us_same_session_60m_simple_return_raw"
    assert inherited["multiplicity_methods"] == ["HOLM", "BH"]


def test_multi_regime_protocol_rejects_single_regime_relabeling() -> None:
    r1 = canonical_us_r1_research_protocol()
    with pytest.raises(ValueError, match="distinct regimes"):
        USMultiRegimeWalkForwardProtocol(
            corpus_id="us-r2-regime-corpus-test",
            candidate_denominator_id="us-r1-denominator-test",
            r1_protocol_id=r1.protocol_id,
            regime_policy=_regime_policy(),
            folds=(
                USMultiRegimeFold(
                    fold_id="fold-01",
                    train_start=date(2019, 1, 1),
                    train_end=date(2020, 1, 1),
                    evaluation_start=date(2020, 2, 1),
                    evaluation_end=date(2020, 7, 1),
                    expected_regimes=("NORMAL",),
                ),
                USMultiRegimeFold(
                    fold_id="fold-02",
                    train_start=date(2021, 1, 1),
                    train_end=date(2022, 1, 1),
                    evaluation_start=date(2022, 2, 1),
                    evaluation_end=date(2022, 7, 1),
                    expected_regimes=("NORMAL",),
                ),
            ),
        )


def test_regime_features_fail_closed_on_same_session_or_future_inputs() -> None:
    with pytest.raises(ValueError, match="lagged"):
        USRegimeFeatureSpec(
            name="bad-same-session",
            source=USRegimeFeatureSource.CROSS_SECTIONAL_BREADTH,
            lookback_sessions=20,
            availability_lag_sessions=0,
        )
    with pytest.raises(ValueError, match="anchor asset"):
        USRegimeFeatureSpec(
            name="bad-anchor",
            source=USRegimeFeatureSource.MARKET_ANCHOR_RETURN,
            lookback_sessions=20,
        )
