from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

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
    expected_package_version: str = RECOMMENDED_MT5_PACKAGE_VERSION
    minimum_inventory_symbols: int = 1
    require_visible: bool = True
    require_tradable: bool = True
    require_m1_history: bool = True
    require_tick_history: bool = True
    require_spread: bool = True
    schema_version: str = "finagent.mt5-p0-acceptance-policy.v1"

    def __post_init__(self) -> None:
        normalized = _normalized_symbols(self.representative_symbols)
        if not normalized:
            raise ValueError("MT5-P0 acceptance requires representative_symbols")
        object.__setattr__(self, "representative_symbols", normalized)
        version = self.expected_package_version.strip()
        if not version:
            raise ValueError("expected_package_version must be non-empty")
        object.__setattr__(self, "expected_package_version", version)
        if self.minimum_inventory_symbols < 1:
            raise ValueError("minimum_inventory_symbols must be >= 1")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="mt5-p0-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "representative_symbols": list(self.representative_symbols),
            "expected_package_version": self.expected_package_version,
            "minimum_inventory_symbols": self.minimum_inventory_symbols,
            "require_visible": self.require_visible,
            "require_tradable": self.require_tradable,
            "require_m1_history": self.require_m1_history,
            "require_tick_history": self.require_tick_history,
            "require_spread": self.require_spread,
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
    schema_version: str = "finagent.mt5-p0-acceptance-assessment.v1"

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
        if policy.require_tick_history and (history is None or history.tick_count <= 0):
            blockers.append(f"history:{symbol}:ticks_missing")

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

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_limitations = tuple(dict.fromkeys(limitations))
    return MT5P0AcceptanceAssessment(
        probe_id=report.probe_id,
        policy_id=policy.policy_id,
        accepted=not unique_blockers,
        blockers=unique_blockers,
        limitations=unique_limitations,
        representative_symbols=policy.representative_symbols,
    )
