"""Controlled within-year OHLCV fixture over the existing R2 Parquet contract."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime, timedelta

import duckdb

from finagent.application.adaptive_portfolio import run_adaptive_portfolio
from finagent.domain.research import TimeRange
from finagent.domain.trading_calendar import TradingCalendarEvidence, TradingSession
from finagent.research.adaptive_inputs import bind_development_source
from finagent.research.adaptive_walkforward import WalkForwardFold
from finagent.research.factor_library import FactorLibrary, FactorOrigin, FactorRegistration
from finagent.research.market_state import MarketFeatureConfig
from finagent.research.us_r3_alpha_catalog import build_us_r3_executable_frontier_candidates
from finagent.research.us_r3_economics import EconomicPolicy
from tests.test_us_r3_economic_campaign import fixture_inputs


def portfolio_inputs(root):
    paths = fixture_inputs(root)
    days, day = [], date(2025, 1, 2)
    while len(days) < 33:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    sessions = tuple(
        TradingSession(
            d,
            datetime(d.year, d.month, d.day, 14, 30, tzinfo=UTC),
            datetime(d.year, d.month, d.day, 21, tzinfo=UTC),
        )
        for d in days
    )
    calendar = TradingCalendarEvidence(
        "XNYS", "America/New_York", "controlled-walkforward-fixture", "v1", sessions
    )
    paths[1].write_text(json.dumps({"passed": True, "evidence": calendar.to_dict()}))
    rows = []
    for d, session in enumerate(sessions):
        direction = 1 if (d // 3) % 2 == 0 else -1
        for asset in range(4):
            for i in range(26):
                clock = session.open_at + timedelta(minutes=15 * i)
                close = (
                    100
                    + asset * 10
                    + direction
                    * (
                        0.03 * (asset - 1.5) * i
                        + 0.001 * (d + 1) * i
                        + 0.2 * math.sin(0.55 * i + 0.7 * asset + 0.2 * d)
                    )
                )
                rows.append(
                    (
                        "decay_15m_30m",
                        session.session_date,
                        "XNYS:" + session.session_date.isoformat(),
                        "A" + str(asset),
                        clock,
                        clock + timedelta(minutes=15),
                        close + 0.02 * math.sin(i),
                        close + 0.1 + 0.02 * (4 - asset),
                        close - 0.1 - 0.03 * (asset + 1) - 0.01 * math.sin(i + d),
                        close,
                        1000
                        + 37 * asset
                        + 11 * i
                        + d % 4 * 18
                        + (asset + 1) * 25 * math.sin(0.6 * i + 0.2 * d),
                        True,
                        "15m",
                        999.0,
                        "source-v1",
                        "base-v1",
                        "policy-v1",
                        clock + timedelta(minutes=15),
                        close,
                    )
                )
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE bars AS SELECT * FROM read_parquet(?) WHERE false", [str(paths[0])]
        )
        connection.executemany(
            "INSERT INTO bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(paths[0])])
    plan = json.loads(paths[2].read_text())
    plan["calendar_id"] = calendar.calendar_id
    paths[2].write_text(json.dumps(plan))
    evidence = json.loads(paths[3].read_text())
    evidence["row_count"] = len(rows)
    paths[3].write_text(json.dumps(evidence))
    folds = tuple(
        WalkForwardFold(
            "fold-" + str(j + 1),
            TimeRange(sessions[j * 11].open_at, sessions[j * 11 + 7].close_at),
            sessions[j * 11 + 2].close_at,
            TimeRange(sessions[j * 11 + 8].open_at, sessions[j * 11 + 10].close_at),
        )
        for j in range(3)
    )
    factors = tuple(
        sorted(
            (
                FactorRegistration(
                    c.graph,
                    c.strategy.slug,
                    c.strategy.mechanism,
                    c.hypothesis.summary,
                    FactorOrigin.MANUAL,
                    (("prior_terminal", "WORKFLOW_VERIFIED_NO_CONFIRMED_ALPHA"),),
                    folds[0].train.start,
                )
                for c in build_us_r3_executable_frontier_candidates()
            ),
            key=lambda f: f.factor_id,
        )
    )
    library_path = root / "library.sqlite"
    library = FactorLibrary(library_path)
    for factor in factors:
        library.register(factor)
    library.close()
    (root / "folds.json").write_text(json.dumps([f.to_dict() for f in folds]))
    source = rebind(paths)
    return {
        "source": source,
        "factors": factors,
        "folds": folds,
        "paths": paths,
        "library": library_path,
        "economics": EconomicPolicy(minimum_breadth=3, selection_count=1),
    }


def rebind(paths):
    return bind_development_source(
        *paths,
        source_id="synthetic-walkforward",
        source_revision="v1",
        universe=("A0", "A1", "A2", "A3"),
    )


def execute(values, output, **kwargs):
    return run_adaptive_portfolio(
        values["source"],
        values["factors"],
        values["folds"],
        output,
        economics=values["economics"],
        feature_config=MarketFeatureConfig("A0"),
        **kwargs,
    )


def mutated_source(values, destination, statement):
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE bars AS SELECT * FROM read_parquet(?)", [str(values["paths"][0])]
        )
        connection.execute(statement)
        connection.execute("COPY bars TO ? (FORMAT PARQUET)", [str(destination)])
    return {**values, "source": rebind((destination, *values["paths"][1:]))}
