from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .capabilities import MT5CapabilityProbeReport, MT5SymbolSpec

FX_ENGINEERING_FIXTURE = "fx_continuous_engineering_fixture"
METAQUOTES_DELAYED_US_EQUITY = "metaquotes_demo_delayed_us_equity_reference"
TARGET_BROKER_CURRENT_US_EQUITY_OR_CFD = "target_broker_current_us_equity_or_cfd"
MT5_FEED_REGIME_LANES = (
    FX_ENGINEERING_FIXTURE,
    METAQUOTES_DELAYED_US_EQUITY,
    TARGET_BROKER_CURRENT_US_EQUITY_OR_CFD,
)


def _canonical_hash(payload: object, *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        mapped = asdict()
        if isinstance(mapped, Mapping):
            return mapped
    raise TypeError(f"{field_name} must be mapping/namedtuple-like")


def _boolish(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise TypeError(f"{field_name} must be boolean or 0/1")


def _optional_bool(value: object, field_name: str) -> bool | None:
    if value is None:
        return None
    return _boolish(value, field_name)


def _optional_non_negative_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{field_name} must be >= 0")
    return parsed


def _validate_lane(value: str) -> str:
    lane = value.strip()
    if lane not in MT5_FEED_REGIME_LANES:
        raise ValueError(f"unsupported MT5 feed regime lane {lane!r}")
    return lane


@dataclass(frozen=True, slots=True)
class MT5FeedRegimeEvidence:
    """Read-only diagnostic fingerprint for one bound MT5 symbol/feed regime.

    This evidence intentionally carries no US-I0, MT5-D0, US-D3, PAPER,
    execution or live-market authority. The feed lane is explicit input and is
    never inferred from ticker shape, quote age, or contract fields.
    """

    broker_server: str
    capability_probe_id: str
    symbol: str
    symbol_spec_id: str
    feed_lane: str
    observed_at: datetime
    visible: bool
    subscription_delay: bool | None
    chart_mode: int | None
    trade_exemode: int | None
    ticks_bookdepth: int | None
    schema_version: str = "finagent.mt5-feed-regime-evidence.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "broker_server", _text(self.broker_server, "broker_server"))
        object.__setattr__(
            self,
            "capability_probe_id",
            _text(self.capability_probe_id, "capability_probe_id"),
        )
        object.__setattr__(self, "symbol", _text(self.symbol, "symbol"))
        object.__setattr__(
            self,
            "symbol_spec_id",
            _text(self.symbol_spec_id, "symbol_spec_id"),
        )
        object.__setattr__(self, "feed_lane", _validate_lane(self.feed_lane))
        object.__setattr__(self, "observed_at", _aware_utc(self.observed_at, "observed_at"))
        if not isinstance(self.visible, bool):
            raise TypeError("visible must be boolean")
        if not self.visible and self.subscription_delay is not None:
            raise ValueError(
                "subscription_delay must remain unknown when the symbol is not visible"
            )
        for field_name in ("chart_mode", "trade_exemode", "ticks_bookdepth"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be >= 0 when present")

    @property
    def unknown_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        for field_name in (
            "subscription_delay",
            "chart_mode",
            "trade_exemode",
            "ticks_bookdepth",
        ):
            if getattr(self, field_name) is None:
                fields.append(field_name)
        return tuple(fields)

    @property
    def limitations(self) -> tuple[str, ...]:
        limitations: list[str] = []
        if not self.visible:
            limitations.append("symbol:not_visible")
            limitations.append("subscription_delay:unavailable_symbol_not_visible")
        elif self.subscription_delay is None:
            limitations.append("subscription_delay:unavailable_not_inferred")
        for field_name in ("chart_mode", "trade_exemode", "ticks_bookdepth"):
            if getattr(self, field_name) is None:
                limitations.append(f"{field_name}:unavailable_not_inferred")
        return tuple(limitations)

    @property
    def evidence_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False, include_authority=False),
            prefix="mt5-feed-regime-evidence",
        )

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_authority: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "broker_server": self.broker_server,
            "capability_probe_id": self.capability_probe_id,
            "symbol": self.symbol,
            "symbol_spec_id": self.symbol_spec_id,
            "feed_lane": self.feed_lane,
            "observed_at": self.observed_at.isoformat(),
            "visible": self.visible,
            "subscription_delay": self.subscription_delay,
            "chart_mode": self.chart_mode,
            "trade_exemode": self.trade_exemode,
            "ticks_bookdepth": self.ticks_bookdepth,
            "unknown_fields": list(self.unknown_fields),
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["evidence_id"] = self.evidence_id
        if include_authority:
            payload.update(_diagnostic_authority())
        return payload


@dataclass(frozen=True, slots=True)
class MT5FeedRegimeIssue:
    symbol: str
    reasons: tuple[str, ...]
    schema_version: str = "finagent.mt5-feed-regime-issue.v1"

    def __post_init__(self) -> None:
        symbol = _text(self.symbol, "symbol")
        reasons = tuple(dict.fromkeys(item.strip() for item in self.reasons if item.strip()))
        if not reasons:
            raise ValueError("feed regime issue requires at least one reason")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reasons", reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class MT5FeedRegimeReport:
    broker_server: str
    capability_probe_id: str
    feed_lane: str
    requested_symbols: tuple[str, ...]
    evidence: tuple[MT5FeedRegimeEvidence, ...]
    issues: tuple[MT5FeedRegimeIssue, ...]
    generated_at: datetime
    schema_version: str = "finagent.mt5-feed-regime-report.v1"

    def __post_init__(self) -> None:
        server = _text(self.broker_server, "broker_server")
        probe_id = _text(self.capability_probe_id, "capability_probe_id")
        lane = _validate_lane(self.feed_lane)
        requested = tuple(
            dict.fromkeys(item.strip() for item in self.requested_symbols if item.strip())
        )
        if not requested:
            raise ValueError("requested_symbols must be non-empty")
        evidence_symbols = tuple(item.symbol for item in self.evidence)
        issue_symbols = tuple(item.symbol for item in self.issues)
        if len(evidence_symbols) != len(set(evidence_symbols)):
            raise ValueError("feed regime report cannot repeat evidence symbols")
        if len(issue_symbols) != len(set(issue_symbols)):
            raise ValueError("feed regime report cannot repeat issue symbols")
        if set(evidence_symbols) & set(issue_symbols):
            raise ValueError("a symbol cannot have both evidence and an issue")
        if set(evidence_symbols) | set(issue_symbols) != set(requested):
            raise ValueError("every requested symbol must resolve to evidence or an issue")
        for item in self.evidence:
            if item.broker_server != server:
                raise ValueError("evidence broker server mismatch")
            if item.capability_probe_id != probe_id:
                raise ValueError("evidence capability probe mismatch")
            if item.feed_lane != lane:
                raise ValueError("evidence feed lane mismatch")
        object.__setattr__(self, "broker_server", server)
        object.__setattr__(self, "capability_probe_id", probe_id)
        object.__setattr__(self, "feed_lane", lane)
        object.__setattr__(self, "requested_symbols", requested)
        object.__setattr__(self, "generated_at", _aware_utc(self.generated_at, "generated_at"))

    @property
    def complete_for_diagnostic(self) -> bool:
        return not self.issues and len(self.evidence) == len(self.requested_symbols)

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False, include_authority=False),
            prefix="mt5-feed-regime-report",
        )

    def to_dict(
        self,
        *,
        include_id: bool = True,
        include_authority: bool = True,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "broker_server": self.broker_server,
            "capability_probe_id": self.capability_probe_id,
            "feed_lane": self.feed_lane,
            "requested_symbols": list(self.requested_symbols),
            "complete_for_diagnostic": self.complete_for_diagnostic,
            "evidence": [
                item.to_dict(include_authority=include_authority) for item in self.evidence
            ],
            "issues": [item.to_dict() for item in self.issues],
            "generated_at": self.generated_at.isoformat(),
        }
        if include_id:
            payload["report_id"] = self.report_id
        if include_authority:
            payload.update(_diagnostic_authority())
        return payload


def _diagnostic_authority() -> dict[str, object]:
    return {
        "scope": "mt5_feed_regime_diagnostic_only",
        "stage_exit_authority": False,
        "research_universe_authority": False,
        "us_i0_authority": False,
        "mt5_d0_authority": False,
        "us_d3_authority": False,
        "paper_authority": False,
        "execution_authority": False,
        "live_market_data_authority": False,
        "live_executable_spread_authority": False,
    }


def build_mt5_feed_regime_evidence(
    *,
    broker_server: str,
    capability_probe_id: str,
    symbol_spec: MT5SymbolSpec,
    raw_symbol_info: object,
    feed_lane: str,
    observed_at: datetime,
) -> MT5FeedRegimeEvidence:
    raw_symbol_mapping = _mapping(raw_symbol_info, "raw_symbol_info")
    raw_symbol = _text(
        raw_symbol_mapping.get("name", raw_symbol_mapping.get("symbol")),
        "raw_symbol_info.symbol",
    )
    if raw_symbol != symbol_spec.symbol:
        raise ValueError(
            f"raw symbol {raw_symbol!r} does not match symbol spec {symbol_spec.symbol!r}"
        )
    raw_visible_value = raw_symbol_mapping.get("visible")
    visible = (
        symbol_spec.visible
        if raw_visible_value is None
        else _boolish(raw_visible_value, "raw_symbol_info.visible")
    )
    if visible != symbol_spec.visible:
        raise ValueError("raw symbol visibility does not match bound symbol spec")

    subscription_delay = None
    if visible:
        subscription_delay = _optional_bool(
            raw_symbol_mapping.get("subscription_delay"),
            "raw_symbol_info.subscription_delay",
        )

    return MT5FeedRegimeEvidence(
        broker_server=broker_server,
        capability_probe_id=capability_probe_id,
        symbol=symbol_spec.symbol,
        symbol_spec_id=symbol_spec.spec_id,
        feed_lane=feed_lane,
        observed_at=observed_at,
        visible=visible,
        subscription_delay=subscription_delay,
        chart_mode=_optional_non_negative_int(
            raw_symbol_mapping.get("chart_mode"),
            "raw_symbol_info.chart_mode",
        ),
        trade_exemode=_optional_non_negative_int(
            raw_symbol_mapping.get("trade_exemode"),
            "raw_symbol_info.trade_exemode",
        ),
        ticks_bookdepth=_optional_non_negative_int(
            raw_symbol_mapping.get("ticks_bookdepth"),
            "raw_symbol_info.ticks_bookdepth",
        ),
    )


def build_mt5_feed_regime_report(
    capability_report: MT5CapabilityProbeReport,
    raw_inventory_rows: Sequence[object],
    requested_symbols: Sequence[str],
    *,
    feed_lane: str,
    generated_at: datetime | None = None,
) -> MT5FeedRegimeReport:
    lane = _validate_lane(feed_lane)
    requested = tuple(
        dict.fromkeys(item.strip() for item in requested_symbols if item.strip())
    )
    if not requested:
        raise ValueError("requested_symbols must be non-empty")

    specs = {item.symbol: item for item in capability_report.symbols}
    raw_by_symbol: dict[str, object] = {}
    duplicate_raw_symbols: set[str] = set()
    for row in raw_inventory_rows:
        raw_mapping = _mapping(row, "raw_inventory_rows[]")
        symbol = _text(
            raw_mapping.get("name", raw_mapping.get("symbol")),
            "raw_inventory_rows[].symbol",
        )
        if symbol in raw_by_symbol:
            duplicate_raw_symbols.add(symbol)
        else:
            raw_by_symbol[symbol] = row

    evidence: list[MT5FeedRegimeEvidence] = []
    issues: list[MT5FeedRegimeIssue] = []
    observed_at = generated_at or capability_report.probed_at
    server = capability_report.terminal.broker_server

    for symbol in requested:
        reasons: list[str] = []
        spec = specs.get(symbol)
        raw_row = raw_by_symbol.get(symbol)
        if symbol in duplicate_raw_symbols:
            reasons.append("duplicate_raw_inventory_symbol")
        if spec is None:
            reasons.append("missing_symbol_spec")
        if raw_row is None:
            reasons.append("missing_raw_inventory")
        if reasons:
            issues.append(MT5FeedRegimeIssue(symbol=symbol, reasons=tuple(reasons)))
            continue
        assert spec is not None and raw_row is not None
        try:
            evidence.append(
                build_mt5_feed_regime_evidence(
                    broker_server=server,
                    capability_probe_id=capability_report.probe_id,
                    symbol_spec=spec,
                    raw_symbol_info=raw_row,
                    feed_lane=lane,
                    observed_at=observed_at,
                )
            )
        except (TypeError, ValueError) as exc:
            issues.append(
                MT5FeedRegimeIssue(
                    symbol=symbol,
                    reasons=(f"invalid_feed_fingerprint:{exc}",),
                )
            )

    return MT5FeedRegimeReport(
        broker_server=server,
        capability_probe_id=capability_report.probe_id,
        feed_lane=lane,
        requested_symbols=requested,
        evidence=tuple(evidence),
        issues=tuple(issues),
        generated_at=observed_at,
    )
