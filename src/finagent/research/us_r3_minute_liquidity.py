"""Read-only minute-volume diagnostics for an already frozen economic ledger.

Observed bar volume is an ex-post proxy, never an executable quote, a market
impact model, or an input used to resize the historical orders being audited.
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from finagent.data.minute_store import (
    DuckDBParquetMinuteStore,
    MinuteStoreManifest,
)
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingSession
from finagent.research.us_r3_economic_campaign import (
    AUTHORITY,
    _calendar,
    _sealed,
    digest,
    file_digest,
)
from finagent.research.us_r3_usability import write_immutable_json

MinuteBars = Mapping[tuple[str, datetime], tuple[float, float]]


def audit_ledger(
    ledger: Sequence[Mapping[str, Any]],
    bars: MinuteBars,
    session: TradingSession,
    *,
    opening_capital: float,
    participation_limit: float,
) -> dict[str, Any]:
    """Scale normalized daily-opening shares; no compounding across sessions.

    A reference at 10:45 uses the source minute starting at 10:44, available
    at 10:45. Missing minutes are not forward-filled or replaced by later ones.
    """
    if not math.isfinite(opening_capital) or opening_capital <= 0:
        raise ValueError("opening capital must be positive and finite")
    if not math.isfinite(participation_limit) or not 0 < participation_limit <= 1:
        raise ValueError("participation limit must be in (0, 1]")
    counts = {
        "trade_legs": 0,
        "matched_legs": 0,
        "missing_minutes": 0,
        "zero_volume_legs": 0,
        "over_limit_legs": 0,
        "notional_mismatch_frames": 0,
    }
    ratios: list[float] = []
    ceilings: list[float] = []
    previous = -1
    for frame in ledger:
        index, minutes = frame["bar_index"], frame["reference_minutes"]
        if type(index) is not int or index <= previous or minutes not in (5, 15):
            raise ValueError("invalid or unordered ledger reference")
        previous = index
        clock = session.open_at + timedelta(minutes=(index + 1) * minutes)
        if not session.open_at < clock <= session.close_at:
            raise ValueError("ledger reference outside session")
        notional = 0.0
        complete = True
        for asset, shares in frame["net_trades"].items():
            if not math.isfinite(shares):
                raise ValueError("nonfinite trade quantity")
            if shares == 0:
                continue
            counts["trade_legs"] += 1
            bar = bars.get((asset, clock))
            if bar is None:
                counts["missing_minutes"] += 1
                complete = False
                continue
            close, volume = bar
            if not math.isfinite(close) or close <= 0 or not math.isfinite(volume) or volume < 0:
                raise ValueError("invalid cleaned minute bar")
            counts["matched_legs"] += 1
            notional += abs(shares) * close
            ceilings.append(participation_limit * volume / abs(shares))
            if volume == 0:
                counts["zero_volume_legs"] += 1
                counts["over_limit_legs"] += 1
            else:
                ratio = abs(shares) * opening_capital / volume
                ratios.append(ratio)
                counts["over_limit_legs"] += ratio > participation_limit
        if complete and not math.isclose(
            notional, frame["gross_traded_notional"], rel_tol=1e-9, abs_tol=1e-12
        ):
            counts["notional_mismatch_frames"] += 1
    return {
        **counts,
        "max_positive_volume_participation": max(ratios) if ratios else None,
        "all_legs_volume_proxy_capital_ceiling": min(ceilings)
        if ceilings and not counts["missing_minutes"]
        else None,
    }


def audit_campaign(
    campaign_root: Path,
    manifest: MinuteStoreManifest,
    output: Path,
    *,
    start: date,
    end: date,
    opening_capital: float = 100_000.0,
    participation_limit: float = 0.01,
) -> dict[str, Any]:
    """Audit all fixed strategy arms at 5bp, bounded to one month / 32 assets."""
    import duckdb

    if start > end or (start.year, start.month) != (end.year, end.month):
        raise ValueError("one calendar month per audit required")
    protocol_path = campaign_root / "protocol.json"
    protocol = _sealed(protocol_path, "protocol_id", "us-r3-economic-protocol-")
    universe = protocol["universe"]
    if not universe or len(universe) > 32 or len(set(universe)) != len(universe):
        raise ValueError("bounded unique universe required")
    if 5.0 not in protocol["policy"]["cost_bps"]:
        raise ValueError("preserved 5bp scenario required")
    calendar_path = Path(protocol["inputs"]["calendar"]["path"])
    if file_digest(calendar_path) != protocol["inputs"]["calendar"]["sha256"]:
        raise ValueError("calendar binding changed")
    sessions = [s for s in _calendar(calendar_path).sessions if start <= s.session_date <= end]
    if not sessions or any(
        s.session_date.isoformat() not in protocol["sessions"] for s in sessions
    ):
        raise ValueError("requested sessions outside frozen campaign")
    audit_ledger(
        [],
        {},
        sessions[0],
        opening_capital=opening_capital,
        participation_limit=participation_limit,
    )
    paths = [campaign_root / "sessions" / (s.session_date.isoformat() + ".json") for s in sessions]
    query = MarketDataQuery(
        market_id="XNYS",
        assets=tuple(universe),
        start=sessions[0].open_at,
        end=sessions[-1].close_at + timedelta(minutes=1),
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.AVAILABLE_AT,
    )
    plan = DuckDBParquetMinuteStore(manifest).plan(query)
    selected = [p for p in manifest.partitions if p.month in plan.partition_months]
    bindings = {str(p.path.resolve()): file_digest(p.path) for p in selected}
    ledger_hashes = {p.name: file_digest(p) for p in paths}
    request = {
        "schema_version": "finagent.us-r3-minute-liquidity-request.v1",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": file_digest(protocol_path),
        "implementation_sha256": file_digest(Path(__file__)),
        "minute_plan_id": plan.plan_id,
        "minute_data_version": manifest.data_version,
        "raw_partition_sha256": bindings,
        "session_sha256": ledger_hashes,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "opening_capital_per_session": opening_capital,
        "participation_limit": participation_limit,
        "cost_bps": 5.0,
        "strategies": protocol["strategies"],
        "universe": universe,
        "mode": "ex_post_volume_proxy_no_order_changes_no_impact_estimation",
        **AUTHORITY,
    }
    request["request_id"] = "us-r3-minute-liquidity-request-" + digest(request)
    write_immutable_json(output / "request.json", request)
    daily: list[dict[str, Any]] = []
    with (
        tempfile.TemporaryDirectory(prefix="finagent-minute-liquidity-") as spill,
        duckdb.connect(config={"memory_limit": "512MB", "threads": "2"}) as connection,
    ):
        connection.execute("SET temp_directory = ?", [spill])
        connection.execute("SET max_temp_directory_size = '2GB'")
        connection.execute("CREATE TEMP TABLE minutes AS " + plan.sql)
        for session, path in zip(sessions, paths, strict=True):
            if file_digest(path) != ledger_hashes[path.name]:
                raise ValueError("ledger changed during audit")
            evidence = _sealed(path, "evidence_id", "us-r3-economic-session-")
            if (
                evidence["protocol_id"] != protocol["protocol_id"]
                or evidence["session_date"] != session.session_date.isoformat()
                or set(evidence["results"]) != set(protocol["strategies"])
            ):
                raise ValueError("ledger session/strategy binding mismatch")
            rows = connection.execute(
                "SELECT research_asset_id, available_at AT TIME ZONE 'UTC', close, volume "
                "FROM minutes "
                "WHERE available_at > ? AND available_at <= ?",
                [session.open_at, session.close_at],
            ).fetchall()
            # Fetch a UTC wall clock and attach stdlib UTC explicitly. DuckDB's
            # TIMESTAMPTZ Python conversion otherwise requires undeclared pytz.
            bars = {
                (asset, clock.replace(tzinfo=UTC)): (close, volume)
                for asset, clock, close, volume in rows
            }
            if len(bars) != len(rows):
                raise ValueError("duplicate cleaned minute")
            session_results = {}
            for name in protocol["strategies"]:
                original = evidence["results"][name]["5.0"]
                session_results[name] = {
                    **audit_ledger(
                        original["ledger"],
                        bars,
                        session,
                        opening_capital=opening_capital,
                        participation_limit=participation_limit,
                    ),
                    "original_resolved": original["resolved"],
                }
            daily.append(
                {
                    "session_date": session.session_date.isoformat(),
                    "observed_regular_minutes": len(bars),
                    "expected_regular_minutes": len(universe) * session.regular_minutes,
                    "results": session_results,
                }
            )
    if any(file_digest(Path(p)) != sha for p, sha in bindings.items()):
        raise ValueError("raw partition changed during audit")
    summary = {}
    for name in protocol["strategies"]:
        results = [d["results"][name] for d in daily]
        fields = (
            "trade_legs",
            "matched_legs",
            "missing_minutes",
            "zero_volume_legs",
            "over_limit_legs",
            "notional_mismatch_frames",
        )
        ceilings = [
            r["all_legs_volume_proxy_capital_ceiling"]
            for r in results
            if r["all_legs_volume_proxy_capital_ceiling"] is not None
        ]
        ratios = [
            r["max_positive_volume_participation"]
            for r in results
            if r["max_positive_volume_participation"] is not None
        ]
        complete = all(
            r["original_resolved"]
            and not r["missing_minutes"]
            and not r["notional_mismatch_frames"]
            for r in results
        )
        summary[name] = {
            **{key: sum(r[key] for r in results) for key in fields},
            "complete_ledger_reference_check": complete,
            "max_positive_volume_participation": max(ratios) if ratios else None,
            "all_legs_volume_proxy_capital_ceiling": min(ceilings)
            if ceilings and complete
            else None,
        }
    report = {
        "schema_version": "finagent.us-r3-minute-liquidity.v1",
        "request_id": request["request_id"],
        "scheduled_sessions": len(sessions),
        "daily": daily,
        "strategies": summary,
        **AUTHORITY,
    }
    report["evidence_id"] = "us-r3-minute-liquidity-" + digest(report)
    write_immutable_json(output / "summary.json", report)
    return report
