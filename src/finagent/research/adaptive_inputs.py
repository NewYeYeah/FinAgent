"""Bounded adapter from existing R2 Parquet/calendar evidence to R4 panels."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from finagent.domain.research import TimeRange
from finagent.domain.trading_calendar import TradingCalendarEvidence
from finagent.research.market_state import MarketStateSource
from finagent.research.us_a1_factor_panel_materialization import FactorPanelAsset
from finagent.research.us_baselines import _canonical_hash
from finagent.research.us_r3_economic_campaign import _calendar, aligned_session, file_digest
from finagent.research.us_r3_usability import FEATURE_QUERY, SLICE_ID, _session_assets


@dataclass(frozen=True)
class DevelopmentPanelSource:
    path: Path
    identity: MarketStateSource
    calendar: TradingCalendarEvidence
    universe: tuple[str, ...]
    bindings: tuple[tuple[str, str], ...]
    year: int

    def verify_unchanged(self) -> None:
        if any(file_digest(Path(path)) != digest for path, digest in self.bindings):
            raise ValueError("bound development input changed")

    def read(self, window: TimeRange) -> tuple[tuple[FactorPanelAsset, ...], ...]:
        """Retain the calendar denominator, including wholly missing sessions.

        Require complete sessions at both edges; an observed tail never invents
        an earlier market close. Labels are absent from the SQL projection.
        """
        import duckdb

        self.verify_unchanged()
        earliest = datetime.combine(self.calendar.sessions[0].session_date, time(), UTC)
        latest = datetime.combine(
            self.calendar.sessions[-1].session_date + timedelta(days=1), time(), UTC
        )
        if window.start < earliest or window.end > latest:
            raise ValueError("requested window extends beyond calendar coverage")
        if (
            window.start.astimezone(UTC).year != self.year
            or (window.end.astimezone(UTC) - timedelta(microseconds=1)).year != self.year
        ):
            raise ValueError("requested window extends beyond bound source year")
        selected = tuple(
            s
            for s in self.calendar.sessions
            if s.open_at < window.end and s.close_at > window.start
        )
        if not selected or len(selected) > 252:
            raise ValueError("bounded covered calendar window required")
        if any(s.open_at < window.start or s.close_at > window.end for s in selected):
            raise ValueError("window must include complete calendar sessions")
        if not self.calendar.covers(selected[0].session_date) or not self.calendar.covers(
            selected[-1].session_date
        ):
            raise ValueError("calendar does not cover window")
        # Reuse the exact no-label R3 projection and session parser. Predicate
        # pushdown bounds this read to the requested fit/evaluation window.
        query = FEATURE_QUERY.replace(
            "WHERE slice_id = ?",
            "WHERE slice_id = ? AND event_time >= to_timestamp(?) AND event_time < to_timestamp(?)",
        )
        observed: dict[str, list[tuple[Any, ...]]] = {}
        with duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as connection:
            connection.execute(
                query, [str(self.path), SLICE_ID, window.start.timestamp(), window.end.timestamp()]
            )
            while batch := connection.fetchmany(512):
                for row in batch:
                    if row[2] not in self.universe:
                        raise ValueError("source contains an asset outside the explicit universe")
                    bucket = observed.setdefault(row[0], [])
                    if len(bucket) >= 32 * 64 or len(observed) > 252:
                        raise ValueError("bounded session row count exceeded")
                    bucket.append(row)
        if set(observed) - {s.session_date.isoformat() for s in selected}:
            raise ValueError("source rows outside accepted calendar")
        result = tuple(
            aligned_session(
                _session_assets(observed[s.session_date.isoformat()])
                if s.session_date.isoformat() in observed
                else (),
                s,
                list(self.universe),
            )
            for s in selected
        )
        self.verify_unchanged()
        return result


def bind_development_source(
    source: Path,
    calendar_path: Path,
    base_plan_path: Path,
    evidence_path: Path,
    *,
    source_id: str,
    source_revision: str,
    universe: tuple[str, ...],
) -> DevelopmentPanelSource:
    """Verify locally trusted R2 lineage; this is not upstream source authentication.

    Universe is explicitly supplied before any values are inspected, never
    inferred from future symbol presence or forward-label coverage.
    """
    import duckdb

    if (
        not 2 <= len(universe) <= 32
        or len(set(universe)) != len(universe)
        or any(not a.strip() for a in universe)
    ):
        raise ValueError("explicit bounded unique universe required")
    bindings = tuple(
        (str(path.resolve()), file_digest(path))
        for path in (source, calendar_path, base_plan_path, evidence_path)
    )
    calendar = _calendar(calendar_path)
    plan = json.loads(base_plan_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if (
        evidence.get("passed") is not True
        or evidence.get("blockers") != []
        or any(evidence.get(k) != plan.get(k) for k in ("plan_id", "policy_id", "year"))
        or plan.get("calendar_id") != calendar.calendar_id
        or any(
            not isinstance(plan.get(k), str) or not plan[k].strip()
            for k in ("plan_id", "policy_id", "source_data_version", "data_version")
        )
        or type(plan.get("year")) is not int
        or not 1990 <= plan["year"] <= 2100
        or type(evidence.get("row_count")) is not int
        or evidence["row_count"] <= 0
    ):
        raise ValueError("R2 source/calendar evidence mismatch")
    with duckdb.connect(config={"memory_limit": "256MiB", "threads": "1"}) as connection:
        metadata = connection.execute(
            "SELECT source_data_version, data_version, robustness_policy_id, count(*) "
            "FROM read_parquet(?) GROUP BY ALL",
            [str(source)],
        ).fetchall()
        if metadata != [
            (
                plan["source_data_version"],
                plan["data_version"],
                plan["policy_id"],
                evidence["row_count"],
            )
        ]:
            raise ValueError("Parquet versions/row count do not match R2 evidence")
        years = connection.execute(
            "SELECT DISTINCT year(session_date) FROM read_parquet(?)", [str(source)]
        ).fetchall()
        if years != [(plan["year"],)]:
            raise ValueError("R2 annual artifact year mismatch")
    if not calendar.covers(date(plan["year"], 1, 1)) and not any(
        s.session_date.year == plan["year"] for s in calendar.sessions
    ):
        raise ValueError("calendar has no source-year sessions")
    result = DevelopmentPanelSource(
        source,
        MarketStateSource(
            source_id,
            source_revision,
            plan["data_version"],
            str(_canonical_hash({"plan": plan, "evidence": evidence}, prefix="r4-local-lineage")),
            calendar.calendar_id,
        ),
        calendar,
        tuple(sorted(universe)),
        bindings,
        plan["year"],
    )
    result.verify_unchanged()
    return result
