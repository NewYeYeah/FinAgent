from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from .capabilities import MT5CapabilityProbeReport
from .client import RECOMMENDED_MT5_PACKAGE_VERSION


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _normalized_symbols(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


@dataclass(frozen=True, slots=True)
class MT5P0AcceptancePolicy:
    representative_symbols: tuple[str, ...]
    tick_probe_symbols: tuple[str, ...] = ()
    expected_package_version: str = RECOMMENDED_MT5_PACKAGE_VERSION
    minimum_inventory_symbols: int = 1
    require_visible: bool = True
    require_tradable: bool = True
    require_m1_history: bool = True
    require_tick_measurement: bool = True
    minimum_tick_window_m1_bars: int = 1
    require_spread: bool = True
    max_spread_staleness_seconds_at_probe_start: float = 300.0
    maximum_history_window_skew_minutes: int = 360
    schema_version: str = "finagent.mt5-p0-acceptance-policy.v2"

    def __post_init__(self) -> None:
        normalized = _normalized_symbols(self.representative_symbols)
        if not normalized:
            raise ValueError("MT5-P0 acceptance requires representative_symbols")
        object.__setattr__(self, "representative_symbols", normalized)

        tick_symbols = _normalized_symbols(self.tick_probe_symbols)
        if not tick_symbols:
            tick_symbols = (normalized[0],)
        if not set(tick_symbols).issubset(normalized):
            raise ValueError("tick_probe_symbols must be a subset of representative_symbols")
        object.__setattr__(self, "tick_probe_symbols", tick_symbols)

        version = self.expected_package_version.strip()
        if not version:
            raise ValueError("expected_package_version must be non-empty")
        object.__setattr__(self, "expected_package_version", version)
        if self.minimum_inventory_symbols < 1:
            raise ValueError("minimum_inventory_symbols must be >= 1")
        if self.minimum_tick_window_m1_bars < 1:
            raise ValueError("minimum_tick_window_m1_bars must be >= 1")
        if self.max_spread_staleness_seconds_at_probe_start < 0:
            raise ValueError("max_spread_staleness_seconds_at_probe_start must be >= 0")
        if self.maximum_history_window_skew_minutes < 0:
            raise ValueError("maximum_history_window_skew_minutes must be >= 0")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-p0-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "representative_symbols": list(self.representative_symbols),
            "tick_probe_symbols": list(self.tick_probe_symbols),
            "expected_package_version": self.expected_package_version,
            "minimum_inventory_symbols": self.minimum_inventory_symbols,
            "require_visible": self.require_visible,
            "require_tradable": self.require_tradable,
            "require_m1_history": self.require_m1_history,
            "require_tick_measurement": self.require_tick_measurement,
            "minimum_tick_window_m1_bars": self.minimum_tick_window_m1_bars,
            "require_spread": self.require_spread,
            "max_spread_staleness_seconds_at_probe_start": (
                self.max_spread_staleness_seconds_at_probe_start
            ),
            "maximum_history_window_skew_minutes": (
                self.maximum_history_window_skew_minutes
            ),
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class MT5P0AcceptanceAssessment:
    probe_id: str
    policy_id: str
    accepted: bool
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    representative_symbols: tuple[str, ...]
    tick_probe_symbols: tuple[str, ...]
    schema_version: str = "finagent.mt5-p0-acceptance-assessment.v2"

    @property
    def assessment_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "probe_id": self.probe_id,
            "policy_id": self.policy_id,
            "accepted": self.accepted,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "representative_symbols": list(self.representative_symbols),
            "tick_probe_symbols": list(self.tick_probe_symbols),
        }
        return _canonical_hash(payload, prefix="mt5-p0-assessment")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "probe_id": self.probe_id,
            "policy_id": self.policy_id,
            "accepted": self.accepted,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "representative_symbols": list(self.representative_symbols),
            "tick_probe_symbols": list(self.tick_probe_symbols),
        }


def assess_mt5_p0(
    report: MT5CapabilityProbeReport,
    policy: MT5P0AcceptancePolicy,
) -> MT5P0AcceptanceAssessment:
    blockers: list[str] = []
    limitations: list[str] = []

    if not report.read_only:
        blockers.append("report:not_read_only")
    if report.mutation_authority:
        blockers.append("report:mutation_authority_present")
    if not report.terminal.connected:
        blockers.append("terminal:not_connected")
    if report.terminal.package_version != policy.expected_package_version:
        blockers.append(
            "terminal:package_version_mismatch:"
            f"{report.terminal.package_version}!={policy.expected_package_version}"
        )
    if not report.terminal.broker_server:
        blockers.append("terminal:broker_server_missing")
    if report.terminal.terminal_build <= 0:
        blockers.append("terminal:build_missing")
    if len(report.symbols) < policy.minimum_inventory_symbols:
        blockers.append("inventory:below_minimum")

    if not report.terminal.trade_allowed:
        limitations.append("terminal:automated_trading_not_allowed")
    if report.terminal.tradeapi_disabled:
        limitations.append("terminal:trade_api_disabled")

    symbol_by_name = {item.symbol: item for item in report.symbols}
    history_by_name = {item.symbol: item for item in report.history}
    spread_by_name = {item.symbol: item for item in report.spread_samples}

    for symbol in policy.representative_symbols:
        spec = symbol_by_name.get(symbol)
        if spec is None:
            blockers.append(f"symbol:{symbol}:missing")
            continue
        if policy.require_visible and not spec.visible:
            blockers.append(f"symbol:{symbol}:not_visible")
        if policy.require_tradable and not spec.tradable:
            blockers.append(f"symbol:{symbol}:not_tradable")

        history = history_by_name.get(symbol)
        if policy.require_m1_history and (history is None or history.m1_bar_count <= 0):
            blockers.append(f"history:{symbol}:m1_missing")
        elif policy.require_m1_history and history is not None:
            assert history.m1_first_at is not None
            assert history.m1_last_at is not None
            skew = timedelta(minutes=policy.maximum_history_window_skew_minutes)
            if (
                history.m1_last_at < history.requested_bar_start - skew
                or history.m1_first_at >= history.requested_bar_end + skew
            ):
                blockers.append(f"history:{symbol}:m1_outside_requested_window")

        spread = spread_by_name.get(symbol)
        if policy.require_spread:
            if spread is None:
                blockers.append(f"spread:{symbol}:missing")
            elif (
                spread.bid <= 0
                or spread.ask <= 0
                or spread.ask < spread.bid
                or spread.spread_points is None
            ):
                blockers.append(f"spread:{symbol}:invalid")
            else:
                stale_seconds = (report.probed_at - spread.sampled_at).total_seconds()
                if stale_seconds > policy.max_spread_staleness_seconds_at_probe_start:
                    limitations.append(f"spread:{symbol}:stale_at_probe_start")

    if policy.require_tick_measurement:
        for symbol in policy.tick_probe_symbols:
            history = history_by_name.get(symbol)
            if (
                history is None
                or history.requested_tick_start is None
                or history.requested_tick_end is None
            ):
                blockers.append(f"history:{symbol}:tick_measurement_missing")
                continue
            if history.tick_window_m1_bar_count < policy.minimum_tick_window_m1_bars:
                blockers.append(f"history:{symbol}:tick_window_not_m1_anchored")
                continue
            if history.tick_count <= 0:
                limitations.append(
                    f"history:{symbol}:tick_history_unavailable_in_observed_m1_window"
                )

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_limitations = tuple(dict.fromkeys(limitations))
    return MT5P0AcceptanceAssessment(
        probe_id=report.probe_id,
        policy_id=policy.policy_id,
        accepted=not unique_blockers,
        blockers=unique_blockers,
        limitations=unique_limitations,
        representative_symbols=policy.representative_symbols,
        tick_probe_symbols=policy.tick_probe_symbols,
    )
