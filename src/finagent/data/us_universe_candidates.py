from __future__ import annotations

import hashlib
import importlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finagent.data.minute_store import (
    DEFAULT_DUCKDB_EXECUTION_POLICY,
    DuckDBExecutionPolicy,
    DuckDBParquetMinuteStore,
    configure_duckdb_connection,
    manifest_from_huggingface_snapshot,
    select_partitions,
)
from finagent.data.minute_transform import CalendarSessionizedMinuteStore
from finagent.data.query import MarketDataField, MarketDataQuery, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.domain.trading_calendar import TradingCalendarEvidence


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _duckdb() -> Any:
    try:
        return importlib.import_module("duckdb")
    except ImportError as exc:  # pragma: no cover - optional dependency boundary
        raise RuntimeError(
            "US-I0 candidate selection requires DuckDB in the active environment"
        ) from exc


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_aware_datetime(value: object, field_name: str) -> datetime:
    rendered = _text(value, field_name).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(rendered)
    return _aware_utc(parsed, field_name)


@dataclass(frozen=True, slots=True)
class USUniverseCandidateSelectionPolicy:
    start: datetime
    end: datetime
    calendar_id: str
    top_n: int = 40
    minimum_selected_count: int = 20
    minimum_active_sessions: int = 20
    minimum_active_session_ratio: float = 0.80
    minimum_median_regular_coverage_ratio: float = 0.80
    minimum_median_session_close: float = 1.0
    minimum_median_daily_notional_proxy: float = 0.0
    exact_symbol_match_only: bool = True
    require_tradable: bool = True
    require_visible: bool = False
    seed_symbols: tuple[str, ...] = ("AMD", "INTC", "MSFT", "NVDA")
    schema_version: str = "finagent.us-universe-candidate-selection-policy.v1"

    def __post_init__(self) -> None:
        start = _aware_utc(self.start, "start")
        end = _aware_utc(self.end, "end")
        if end <= start:
            raise ValueError("end must be later than start")
        calendar_id = self.calendar_id.strip()
        if not calendar_id:
            raise ValueError("calendar_id must be non-empty")
        if not 1 <= self.top_n <= 200:
            raise ValueError("top_n must be in 1..200")
        if not 1 <= self.minimum_selected_count <= self.top_n:
            raise ValueError("minimum_selected_count must be in 1..top_n")
        if self.minimum_active_sessions < 1:
            raise ValueError("minimum_active_sessions must be >= 1")
        for name, value in (
            ("minimum_active_session_ratio", self.minimum_active_session_ratio),
            (
                "minimum_median_regular_coverage_ratio",
                self.minimum_median_regular_coverage_ratio,
            ),
        ):
            if not 0 <= value <= 1:
                raise ValueError(f"{name} must be in [0, 1]")
        if self.minimum_median_session_close < 0:
            raise ValueError("minimum_median_session_close must be >= 0")
        if self.minimum_median_daily_notional_proxy < 0:
            raise ValueError("minimum_median_daily_notional_proxy must be >= 0")
        if not self.exact_symbol_match_only:
            raise ValueError("v1 candidate selection requires exact symbol text matching")
        if not self.require_tradable:
            raise ValueError("v1 candidate selection requires broker tradability")
        seeds = tuple(
            sorted(dict.fromkeys(item.strip() for item in self.seed_symbols if item.strip()))
        )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "seed_symbols", seeds)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-universe-candidate-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "calendar_id": self.calendar_id,
            "top_n": self.top_n,
            "minimum_selected_count": self.minimum_selected_count,
            "minimum_active_sessions": self.minimum_active_sessions,
            "minimum_active_session_ratio": self.minimum_active_session_ratio,
            "minimum_median_regular_coverage_ratio": (
                self.minimum_median_regular_coverage_ratio
            ),
            "minimum_median_session_close": self.minimum_median_session_close,
            "minimum_median_daily_notional_proxy": (
                self.minimum_median_daily_notional_proxy
            ),
            "exact_symbol_match_only": self.exact_symbol_match_only,
            "require_tradable": self.require_tradable,
            "require_visible": self.require_visible,
            "seed_symbols": list(self.seed_symbols),
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class USUniverseCandidate:
    research_symbol: str
    broker_symbol: str
    broker_path: str
    broker_visible: bool
    broker_tradable: bool
    active_session_count: int
    expected_session_count: int
    active_session_ratio: float
    total_regular_minute_count: int
    median_regular_minute_count: float
    median_regular_coverage_ratio: float
    median_daily_notional_proxy: float
    median_session_close: float
    first_observed_at: datetime
    last_observed_at: datetime
    current_spread_bps: float | None
    rank: int = 0
    schema_version: str = "finagent.us-universe-candidate.v1"

    @property
    def visibility_action_required(self) -> bool:
        return not self.broker_visible

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "rank": self.rank,
            "research_symbol": self.research_symbol,
            "broker_symbol": self.broker_symbol,
            "broker_path": self.broker_path,
            "broker_visible": self.broker_visible,
            "broker_tradable": self.broker_tradable,
            "visibility_action_required": self.visibility_action_required,
            "active_session_count": self.active_session_count,
            "expected_session_count": self.expected_session_count,
            "active_session_ratio": self.active_session_ratio,
            "total_regular_minute_count": self.total_regular_minute_count,
            "median_regular_minute_count": self.median_regular_minute_count,
            "median_regular_coverage_ratio": self.median_regular_coverage_ratio,
            "median_daily_notional_proxy": self.median_daily_notional_proxy,
            "median_session_close": self.median_session_close,
            "first_observed_at": self.first_observed_at.astimezone(UTC).isoformat(),
            "last_observed_at": self.last_observed_at.astimezone(UTC).isoformat(),
            "current_spread_bps": self.current_spread_bps,
        }


@dataclass(frozen=True, slots=True)
class USUniverseCandidateSelectionReport:
    policy: USUniverseCandidateSelectionPolicy
    source_revision: str
    inventory_id: str
    manifest_id: str
    source_data_version: str
    calendar_id: str
    mt5_probe_id: str
    broker_server: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    expected_session_count: int
    research_symbol_count: int
    broker_tradable_symbol_count: int
    exact_intersection_count: int
    eligible_candidate_count: int
    candidates: tuple[USUniverseCandidate, ...]
    missing_seed_symbols: tuple[str, ...]
    generated_at: datetime
    schema_version: str = "finagent.us-universe-candidate-selection-report.v1"

    @property
    def manual_visibility_required_symbols(self) -> tuple[str, ...]:
        return tuple(
            item.broker_symbol for item in self.candidates if item.visibility_action_required
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.expected_session_count <= 0:
            blockers.append("calendar:no_sessions_in_selection_window")
        if self.exact_intersection_count <= 0:
            blockers.append("identity:no_exact_research_broker_symbol_intersection")
        if len(self.candidates) < self.policy.minimum_selected_count:
            blockers.append(
                "selection:insufficient_candidates:"
                f"{len(self.candidates)}<{self.policy.minimum_selected_count}"
            )
        blockers.extend(f"seed:{symbol}:not_eligible" for symbol in self.missing_seed_symbols)
        return tuple(blockers)

    @property
    def ready_for_spread_probe(self) -> bool:
        return not self.blockers

    @property
    def limitations(self) -> tuple[str, ...]:
        values = [
            "universe:engineering_candidate_set_only",
            "universe:not_survivorship_unbiased",
            "identity:exact_symbol_text_is_not_same_security_proof",
            "identity:operator_mapping_attestation_still_required",
            "identity:broker_path_not_exchange_authority",
            "identity:no_point_in_time_security_master",
            "liquidity:daily_notional_is_close_times_source_volume_proxy",
            "spread:current_samples_are_diagnostic_not_historical_cost_authority",
        ]
        if self.manual_visibility_required_symbols:
            values.append("broker_visibility:manual_market_watch_selection_required")
        return tuple(values)

    @property
    def selection_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy.policy_id,
            "source_revision": self.source_revision,
            "inventory_id": self.inventory_id,
            "manifest_id": self.manifest_id,
            "source_data_version": self.source_data_version,
            "calendar_id": self.calendar_id,
            "mt5_probe_id": self.mt5_probe_id,
            "broker_server": self.broker_server,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "expected_session_count": self.expected_session_count,
            "research_symbol_count": self.research_symbol_count,
            "broker_tradable_symbol_count": self.broker_tradable_symbol_count,
            "exact_intersection_count": self.exact_intersection_count,
            "eligible_candidate_count": self.eligible_candidate_count,
            "candidates": [item.to_dict() for item in self.candidates],
            "missing_seed_symbols": list(self.missing_seed_symbols),
        }
        return _canonical_hash(payload, prefix="us-universe-candidate-selection")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "selection_id": self.selection_id,
            "ready_for_spread_probe": self.ready_for_spread_probe,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "policy": self.policy.to_dict(),
            "source_revision": self.source_revision,
            "inventory_id": self.inventory_id,
            "manifest_id": self.manifest_id,
            "source_data_version": self.source_data_version,
            "calendar_id": self.calendar_id,
            "mt5_probe_id": self.mt5_probe_id,
            "broker_server": self.broker_server,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "expected_session_count": self.expected_session_count,
            "research_symbol_count": self.research_symbol_count,
            "broker_tradable_symbol_count": self.broker_tradable_symbol_count,
            "exact_intersection_count": self.exact_intersection_count,
            "eligible_candidate_count": self.eligible_candidate_count,
            "selected_candidate_count": len(self.candidates),
            "spread_probe_symbols": [item.broker_symbol for item in self.candidates],
            "manual_visibility_required_symbols": list(
                self.manual_visibility_required_symbols
            ),
            "missing_seed_symbols": list(self.missing_seed_symbols),
            "candidates": [item.to_dict() for item in self.candidates],
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
        }


def _broker_inventory(
    probe: Mapping[str, object],
    policy: USUniverseCandidateSelectionPolicy,
) -> tuple[str, str, dict[str, Mapping[str, object]], dict[str, float]]:
    if not _boolean(probe.get("read_only"), "read_only"):
        raise ValueError("candidate selection requires a read-only MT5 probe")
    if _boolean(probe.get("mutation_authority"), "mutation_authority"):
        raise ValueError("candidate selection rejects MT5 mutation authority")
    probe_id = _text(probe.get("probe_id"), "probe_id")
    terminal = _mapping(probe.get("terminal"), "terminal")
    if not _boolean(terminal.get("connected"), "terminal.connected"):
        raise ValueError("candidate selection requires a connected MT5 probe")
    broker_server = _text(terminal.get("broker_server"), "terminal.broker_server")

    symbols: dict[str, Mapping[str, object]] = {}
    for raw in _sequence(probe.get("symbols"), "symbols"):
        row = _mapping(raw, "symbols[]")
        symbol = _text(row.get("symbol"), "symbols[].symbol")
        if symbol in symbols:
            raise ValueError(f"duplicate broker symbol in probe: {symbol}")
        tradable = _boolean(row.get("tradable"), "symbols[].tradable")
        visible = _boolean(row.get("visible"), "symbols[].visible")
        if policy.require_tradable and not tradable:
            continue
        if policy.require_visible and not visible:
            continue
        symbols[symbol] = row

    spreads: dict[str, tuple[datetime, float]] = {}
    for raw in _sequence(probe.get("spread_samples", ()), "spread_samples"):
        row = _mapping(raw, "spread_samples[]")
        symbol = _text(row.get("symbol"), "spread_samples[].symbol")
        sampled_at = _parse_aware_datetime(
            row.get("sampled_at"),
            "spread_samples[].sampled_at",
        )
        bid = _number(row.get("bid"), "spread_samples[].bid")
        ask = _number(row.get("ask"), "spread_samples[].ask")
        midpoint = (bid + ask) / 2.0
        if bid <= 0 or ask < bid or midpoint <= 0:
            continue
        bps = (ask - bid) / midpoint * 10_000.0
        previous = spreads.get(symbol)
        if previous is None or sampled_at > previous[0]:
            spreads[symbol] = (sampled_at, bps)
    return probe_id, broker_server, symbols, {
        symbol: value[1] for symbol, value in spreads.items()
    }


def _discover_research_symbols(
    partition_paths: tuple[Path, ...],
    *,
    start: datetime,
    end: datetime,
    execution_policy: DuckDBExecutionPolicy,
    temp_directory: str | Path | None,
) -> tuple[str, ...]:
    rendered_paths = ", ".join(_sql_string(path.as_posix()) for path in partition_paths)
    connection = _duckdb().connect(database=":memory:")
    try:
        configure_duckdb_connection(
            connection,
            execution_policy,
            temp_directory=temp_directory,
        )
        rows = connection.execute(
            f"""
            SELECT DISTINCT ticker
            FROM read_parquet([{rendered_paths}])
            WHERE timestamp >= TIMESTAMPTZ {_sql_string(start.isoformat())}
              AND timestamp < TIMESTAMPTZ {_sql_string(end.isoformat())}
              AND ticker IS NOT NULL
              AND TRIM(ticker) <> ''
            ORDER BY ticker
            """
        ).fetchall()
        return tuple(str(row[0]) for row in rows)
    finally:
        connection.close()


def _candidate_sort_key(candidate: USUniverseCandidate) -> tuple[object, ...]:
    return (
        -candidate.active_session_ratio,
        -candidate.median_regular_coverage_ratio,
        -candidate.median_daily_notional_proxy,
        -candidate.median_session_close,
        candidate.research_symbol,
    )


def _candidate_is_eligible(
    candidate: USUniverseCandidate,
    policy: USUniverseCandidateSelectionPolicy,
) -> bool:
    return (
        candidate.active_session_count >= policy.minimum_active_sessions
        and candidate.active_session_ratio >= policy.minimum_active_session_ratio
        and candidate.median_regular_coverage_ratio
        >= policy.minimum_median_regular_coverage_ratio
        and candidate.median_session_close >= policy.minimum_median_session_close
        and candidate.median_daily_notional_proxy
        >= policy.minimum_median_daily_notional_proxy
    )


def _rank_candidates(
    eligible: tuple[USUniverseCandidate, ...],
    policy: USUniverseCandidateSelectionPolicy,
) -> tuple[USUniverseCandidate, ...]:
    ordered = sorted(eligible, key=_candidate_sort_key)
    selected_symbols = {item.research_symbol for item in ordered[: policy.top_n]}
    eligible_by_symbol = {item.research_symbol: item for item in ordered}
    selected_symbols.update(
        symbol for symbol in policy.seed_symbols if symbol in eligible_by_symbol
    )
    while len(selected_symbols) > policy.top_n:
        removable = [
            item
            for item in reversed(ordered)
            if item.research_symbol in selected_symbols
            and item.research_symbol not in policy.seed_symbols
        ]
        if not removable:
            break
        selected_symbols.remove(removable[0].research_symbol)
    final = [item for item in ordered if item.research_symbol in selected_symbols]
    return tuple(
        USUniverseCandidate(
            research_symbol=item.research_symbol,
            broker_symbol=item.broker_symbol,
            broker_path=item.broker_path,
            broker_visible=item.broker_visible,
            broker_tradable=item.broker_tradable,
            active_session_count=item.active_session_count,
            expected_session_count=item.expected_session_count,
            active_session_ratio=item.active_session_ratio,
            total_regular_minute_count=item.total_regular_minute_count,
            median_regular_minute_count=item.median_regular_minute_count,
            median_regular_coverage_ratio=item.median_regular_coverage_ratio,
            median_daily_notional_proxy=item.median_daily_notional_proxy,
            median_session_close=item.median_session_close,
            first_observed_at=item.first_observed_at,
            last_observed_at=item.last_observed_at,
            current_spread_bps=item.current_spread_bps,
            rank=index,
        )
        for index, item in enumerate(final, start=1)
    )


def select_us_universe_candidates(
    root: str | Path,
    *,
    mt5_probe: Mapping[str, object],
    calendar: TradingCalendarEvidence,
    policy: USUniverseCandidateSelectionPolicy,
    expected_revision: str,
    expected_inventory_id: str,
    cleaning_identity: str,
    execution_policy: DuckDBExecutionPolicy = DEFAULT_DUCKDB_EXECUTION_POLICY,
    temp_directory: str | Path | None = None,
    generated_at: datetime | None = None,
) -> USUniverseCandidateSelectionReport:
    if calendar.calendar_id != policy.calendar_id:
        raise ValueError("calendar identity does not match candidate-selection policy")
    probe_id, broker_server, broker_symbols, spread_bps = _broker_inventory(
        mt5_probe,
        policy,
    )
    manifest = manifest_from_huggingface_snapshot(
        root,
        expected_revision=expected_revision,
        expected_inventory_id=expected_inventory_id,
        cleaning_identity=cleaning_identity,
    )
    router_query = MarketDataQuery(
        market_id=calendar.market_id,
        assets=("__partition_router__",),
        start=policy.start,
        end=policy.end,
        interval=BarInterval.MINUTE_1,
        fields=(MarketDataField.CLOSE,),
        session_policy=SessionPolicy.ALL_OBSERVED,
        adjustment_policy=ResearchPriceBasis.RAW,
        availability_policy=AvailabilityPolicy.EVENT_TIME,
    )
    partitions = select_partitions(manifest, router_query)
    research_symbols = _discover_research_symbols(
        tuple(item.path for item in partitions),
        start=policy.start,
        end=policy.end,
        execution_policy=execution_policy,
        temp_directory=temp_directory,
    )
    intersection = tuple(sorted(set(research_symbols) & set(broker_symbols)))
    expected_sessions = tuple(
        session
        for session in calendar.sessions
        if session.open_at < policy.end and session.close_at > policy.start
    )

    candidates: list[USUniverseCandidate] = []
    selected_size_bytes = sum(item.size_bytes for item in partitions)
    if intersection and expected_sessions:
        raw_store = DuckDBParquetMinuteStore(manifest)
        sessionized_store = CalendarSessionizedMinuteStore(raw_store, calendar)
        query = MarketDataQuery(
            market_id=calendar.market_id,
            assets=intersection,
            start=policy.start,
            end=policy.end,
            interval=BarInterval.MINUTE_1,
            fields=(MarketDataField.CLOSE, MarketDataField.VOLUME),
            session_policy=SessionPolicy.REGULAR,
            adjustment_policy=ResearchPriceBasis.RAW,
            availability_policy=AvailabilityPolicy.EVENT_TIME,
        )
        plan, _evidence = sessionized_store.plan(query)
        selected_size_bytes = plan.selected_size_bytes
        connection = _duckdb().connect(database=":memory:")
        try:
            configure_duckdb_connection(
                connection,
                execution_policy,
                temp_directory=temp_directory,
            )
            rows = connection.execute(
                f"""
                WITH sessionized AS (
                    {plan.sql}
                ),
                daily AS (
                    SELECT
                        research_asset_id,
                        session_date,
                        count(*)::BIGINT AS minute_count,
                        date_diff('minute', min(session_open), max(session_close))::BIGINT
                            AS expected_minute_count,
                        sum(CAST(close AS DOUBLE) * CAST(volume AS DOUBLE))::DOUBLE
                            AS daily_notional_proxy,
                        arg_max(CAST(close AS DOUBLE), event_time)::DOUBLE
                            AS session_close_price,
                        min(event_time) AS first_event_at,
                        max(event_time) AS last_event_at
                    FROM sessionized
                    GROUP BY research_asset_id, session_date
                )
                SELECT
                    research_asset_id,
                    count(*)::BIGINT AS active_session_count,
                    sum(minute_count)::BIGINT AS total_regular_minute_count,
                    median(CAST(minute_count AS DOUBLE))::DOUBLE
                        AS median_regular_minute_count,
                    median(
                        CAST(minute_count AS DOUBLE)
                        / NULLIF(CAST(expected_minute_count AS DOUBLE), 0.0)
                    )::DOUBLE AS median_regular_coverage_ratio,
                    median(daily_notional_proxy)::DOUBLE AS median_daily_notional_proxy,
                    median(session_close_price)::DOUBLE AS median_session_close,
                    CAST(min(first_event_at) AS VARCHAR) AS first_observed_at,
                    CAST(max(last_event_at) AS VARCHAR) AS last_observed_at
                FROM daily
                GROUP BY research_asset_id
                ORDER BY research_asset_id
                """
            ).fetchall()
        finally:
            connection.close()

        expected_count = len(expected_sessions)
        for row in rows:
            symbol = str(row[0])
            broker = broker_symbols[symbol]
            active_count = int(row[1])
            candidates.append(
                USUniverseCandidate(
                    research_symbol=symbol,
                    broker_symbol=symbol,
                    broker_path=str(broker.get("path", "")).strip(),
                    broker_visible=_boolean(
                        broker.get("visible"),
                        "symbols[].visible",
                    ),
                    broker_tradable=_boolean(
                        broker.get("tradable"),
                        "symbols[].tradable",
                    ),
                    active_session_count=active_count,
                    expected_session_count=expected_count,
                    active_session_ratio=active_count / expected_count,
                    total_regular_minute_count=int(row[2]),
                    median_regular_minute_count=float(row[3]),
                    median_regular_coverage_ratio=float(row[4]),
                    median_daily_notional_proxy=float(row[5]),
                    median_session_close=float(row[6]),
                    first_observed_at=_parse_aware_datetime(row[7], "first_observed_at"),
                    last_observed_at=_parse_aware_datetime(row[8], "last_observed_at"),
                    current_spread_bps=spread_bps.get(symbol),
                )
            )

    eligible = tuple(
        item for item in candidates if _candidate_is_eligible(item, policy)
    )
    ranked = _rank_candidates(eligible, policy)
    eligible_symbols = {item.research_symbol for item in eligible}
    missing_seeds = tuple(
        symbol for symbol in policy.seed_symbols if symbol not in eligible_symbols
    )
    timestamp = generated_at or datetime.now(UTC)
    return USUniverseCandidateSelectionReport(
        policy=policy,
        source_revision=expected_revision,
        inventory_id=expected_inventory_id,
        manifest_id=manifest.manifest_id,
        source_data_version=manifest.data_version,
        calendar_id=calendar.calendar_id,
        mt5_probe_id=probe_id,
        broker_server=broker_server,
        partition_months=tuple(item.month for item in partitions),
        selected_size_bytes=selected_size_bytes,
        expected_session_count=len(expected_sessions),
        research_symbol_count=len(research_symbols),
        broker_tradable_symbol_count=len(broker_symbols),
        exact_intersection_count=len(intersection),
        eligible_candidate_count=len(eligible),
        candidates=ranked,
        missing_seed_symbols=missing_seeds,
        generated_at=_aware_utc(timestamp, "generated_at"),
    )
