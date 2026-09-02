from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from finagent.data.us_candidate_quotes_v2 import (
    USCandidateQuoteProbeReportV2,
    USCandidateQuoteSnapshotV2,
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


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _parse_datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class USSimulationQuoteTimingPolicy:
    """Frozen timing semantics for no-account MetaQuotes-Demo simulation references."""

    source_regime: str = "metaquotes_demo_delayed_reference_without_broker_account"
    expected_broker_server: str = "MetaQuotes-Demo"
    broker_account_required: bool = False
    expected_source_delay_seconds: int = 15 * 60
    maximum_anchor_age_seconds: int = 60
    maximum_future_anchor_skew_seconds: int = 60
    schema_version: str = "finagent.us-simulation-quote-timing-policy.v1"

    def __post_init__(self) -> None:
        if not self.source_regime.strip() or not self.expected_broker_server.strip():
            raise ValueError("simulation quote source regime/server must be non-empty")
        if self.broker_account_required:
            raise ValueError("v1 delayed-reference simulation must not require a broker account")
        if self.expected_source_delay_seconds < 1:
            raise ValueError("expected_source_delay_seconds must be >= 1")
        if self.maximum_anchor_age_seconds < 0:
            raise ValueError("maximum_anchor_age_seconds must be >= 0")
        if self.maximum_future_anchor_skew_seconds < 0:
            raise ValueError("maximum_future_anchor_skew_seconds must be >= 0")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-quote-timing-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_regime": self.source_regime,
            "expected_broker_server": self.expected_broker_server,
            "broker_account_required": self.broker_account_required,
            "expected_source_delay_seconds": self.expected_source_delay_seconds,
            "maximum_anchor_age_seconds": self.maximum_anchor_age_seconds,
            "maximum_future_anchor_skew_seconds": self.maximum_future_anchor_skew_seconds,
            "validation_anchor_semantics": "retrieved_at_utc_minus_expected_source_delay",
            "raw_live_quote_policy_unchanged": True,
            "live_market_data_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY = USSimulationQuoteTimingPolicy()


def us_simulation_quote_timing_policy_from_document(
    document: Mapping[str, object],
) -> USSimulationQuoteTimingPolicy:
    schema = _text(document.get("schema_version"), "simulation_policy.schema_version")
    if schema != "finagent.us-simulation-quote-timing-policy.v1":
        raise ValueError(f"unsupported simulation quote timing policy schema: {schema}")
    policy = USSimulationQuoteTimingPolicy(
        source_regime=_text(document.get("source_regime"), "simulation_policy.source_regime"),
        expected_broker_server=_text(
            document.get("expected_broker_server"),
            "simulation_policy.expected_broker_server",
        ),
        broker_account_required=_boolean(
            document.get("broker_account_required"),
            "simulation_policy.broker_account_required",
        ),
        expected_source_delay_seconds=_integer(
            document.get("expected_source_delay_seconds"),
            "simulation_policy.expected_source_delay_seconds",
        ),
        maximum_anchor_age_seconds=_integer(
            document.get("maximum_anchor_age_seconds"),
            "simulation_policy.maximum_anchor_age_seconds",
        ),
        maximum_future_anchor_skew_seconds=_integer(
            document.get("maximum_future_anchor_skew_seconds"),
            "simulation_policy.maximum_future_anchor_skew_seconds",
        ),
    )
    stored_id = _text(document.get("policy_id"), "simulation_policy.policy_id")
    if stored_id != policy.policy_id:
        raise ValueError("stored simulation quote policy_id does not match policy content")
    return policy


def validate_canonical_us_simulation_quote_timing_policy(
    document: Mapping[str, object],
) -> USSimulationQuoteTimingPolicy:
    policy = us_simulation_quote_timing_policy_from_document(document)
    if policy != CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY:
        raise ValueError("simulation quote timing policy differs from canonical v1")
    return policy


@dataclass(frozen=True, slots=True)
class USDelayedReferenceQuoteAssessment:
    symbol: str
    raw_quote_present: bool
    raw_issue_reasons: tuple[str, ...]
    eligible_for_delay_reinterpretation: bool
    observed_delay_seconds: float | None
    validation_anchor_at_utc: datetime | None
    anchor_age_seconds: float | None
    delay_error_seconds: float | None
    bid: float | None
    ask: float | None
    spread_bps: float | None
    visible: bool | None
    tradable: bool | None
    valid_for_simulation_reference: bool
    reasons: tuple[str, ...]
    schema_version: str = "finagent.us-delayed-reference-quote-assessment.v1"

    def __post_init__(self) -> None:
        symbol = self.symbol.strip()
        if not symbol:
            raise ValueError("delayed-reference quote symbol must be non-empty")
        reasons = tuple(dict.fromkeys(item.strip() for item in self.reasons if item.strip()))
        raw_reasons = tuple(
            dict.fromkeys(item.strip() for item in self.raw_issue_reasons if item.strip())
        )
        if self.valid_for_simulation_reference and reasons:
            raise ValueError("valid delayed-reference assessment cannot carry blockers")
        if self.valid_for_simulation_reference and not self.raw_quote_present:
            raise ValueError("valid delayed-reference assessment requires a raw quote")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "raw_issue_reasons", raw_reasons)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "symbol": self.symbol,
            "raw_quote_present": self.raw_quote_present,
            "raw_issue_reasons": list(self.raw_issue_reasons),
            "eligible_for_delay_reinterpretation": self.eligible_for_delay_reinterpretation,
            "observed_delay_seconds": self.observed_delay_seconds,
            "validation_anchor_at_utc": (
                None
                if self.validation_anchor_at_utc is None
                else self.validation_anchor_at_utc.isoformat()
            ),
            "anchor_age_seconds": self.anchor_age_seconds,
            "delay_error_seconds": self.delay_error_seconds,
            "bid": self.bid,
            "ask": self.ask,
            "spread_bps": self.spread_bps,
            "visible": self.visible,
            "tradable": self.tradable,
            "valid_for_simulation_reference": self.valid_for_simulation_reference,
            "reasons": list(self.reasons),
        }


def _assessment_for_quote(
    quote: USCandidateQuoteSnapshotV2,
    raw_issue_reasons: tuple[str, ...],
    policy: USSimulationQuoteTimingPolicy,
) -> USDelayedReferenceQuoteAssessment:
    allowed_raw_issues = not raw_issue_reasons or raw_issue_reasons == ("stale_quote",)
    anchor = quote.retrieved_at_utc - timedelta(seconds=policy.expected_source_delay_seconds)
    anchor_age = (anchor - quote.normalized_sampled_at_utc).total_seconds()
    observed_delay = quote.quote_age_at_retrieval_seconds
    reasons: list[str] = []
    if not allowed_raw_issues:
        reasons.extend(f"raw_issue_not_delay_only:{item}" for item in raw_issue_reasons)
    if not quote.visible:
        reasons.append("quote_not_visible")
    if not quote.tradable:
        reasons.append("quote_not_tradable")
    if anchor_age > policy.maximum_anchor_age_seconds:
        reasons.append("quote_behind_delayed_reference_anchor")
    if anchor_age < -policy.maximum_future_anchor_skew_seconds:
        reasons.append("quote_ahead_of_delayed_reference_anchor")
    reasons = list(dict.fromkeys(reasons))
    return USDelayedReferenceQuoteAssessment(
        symbol=quote.symbol,
        raw_quote_present=True,
        raw_issue_reasons=raw_issue_reasons,
        eligible_for_delay_reinterpretation=allowed_raw_issues,
        observed_delay_seconds=observed_delay,
        validation_anchor_at_utc=anchor,
        anchor_age_seconds=anchor_age,
        delay_error_seconds=observed_delay - policy.expected_source_delay_seconds,
        bid=quote.bid,
        ask=quote.ask,
        spread_bps=quote.spread_bps,
        visible=quote.visible,
        tradable=quote.tradable,
        valid_for_simulation_reference=not reasons,
        reasons=tuple(reasons),
    )


def _missing_assessment(
    symbol: str,
    raw_issue_reasons: tuple[str, ...],
) -> USDelayedReferenceQuoteAssessment:
    reasons = ["raw_quote_unavailable"]
    reasons.extend(f"raw_issue:{item}" for item in raw_issue_reasons)
    return USDelayedReferenceQuoteAssessment(
        symbol=symbol,
        raw_quote_present=False,
        raw_issue_reasons=raw_issue_reasons,
        eligible_for_delay_reinterpretation=False,
        observed_delay_seconds=None,
        validation_anchor_at_utc=None,
        anchor_age_seconds=None,
        delay_error_seconds=None,
        bid=None,
        ask=None,
        spread_bps=None,
        visible=None,
        tradable=None,
        valid_for_simulation_reference=False,
        reasons=tuple(reasons),
    )


@dataclass(frozen=True, slots=True)
class USDelayedReferenceQuoteReport:
    raw_quote_probe_report_id: str
    raw_quote_policy_id: str
    candidate_selection_id: str
    mt5_capability_probe_id: str
    broker_server: str
    broker_clock_evidence_id: str
    policy: USSimulationQuoteTimingPolicy
    requested_symbols: tuple[str, ...]
    assessments: tuple[USDelayedReferenceQuoteAssessment, ...]
    minimum_valid_quote_count: int
    required_seed_symbols: tuple[str, ...]
    generated_at: datetime
    broker_clock_passed: bool
    schema_version: str = "finagent.us-delayed-reference-quote-report.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "raw_quote_probe_report_id",
            "raw_quote_policy_id",
            "candidate_selection_id",
            "mt5_capability_probe_id",
            "broker_server",
            "broker_clock_evidence_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.minimum_valid_quote_count < 1:
            raise ValueError("minimum_valid_quote_count must be >= 1")
        generated = self.generated_at
        if generated.tzinfo is None or generated.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        object.__setattr__(self, "generated_at", generated.astimezone(UTC))
        requested = tuple(dict.fromkeys(self.requested_symbols))
        if requested != self.requested_symbols:
            raise ValueError("requested_symbols must be unique and stable")
        symbols = tuple(item.symbol for item in self.assessments)
        if symbols != requested:
            raise ValueError("assessments must exactly follow requested_symbols")

    @property
    def valid_symbols(self) -> tuple[str, ...]:
        return tuple(
            item.symbol for item in self.assessments if item.valid_for_simulation_reference
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.broker_server != self.policy.expected_broker_server:
            blockers.append(
                "simulation_quote_probe:broker_server_mismatch:"
                f"{self.broker_server}!={self.policy.expected_broker_server}"
            )
        if not self.broker_clock_passed:
            blockers.append("simulation_quote_probe:broker_clock_evidence_failed")
        valid = set(self.valid_symbols)
        if len(valid) < self.minimum_valid_quote_count:
            blockers.append(
                f"simulation_quote_probe:insufficient_valid_quotes:{len(valid)}"
                f"<{self.minimum_valid_quote_count}"
            )
        blockers.extend(
            f"simulation_quote_probe:seed_quote_invalid:{symbol}"
            for symbol in self.required_seed_symbols
            if symbol not in valid
        )
        return tuple(dict.fromkeys(blockers))

    @property
    def ready_for_simulation_reference(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "raw_quote_probe_report_id": self.raw_quote_probe_report_id,
                "raw_quote_policy_id": self.raw_quote_policy_id,
                "candidate_selection_id": self.candidate_selection_id,
                "mt5_capability_probe_id": self.mt5_capability_probe_id,
                "broker_server": self.broker_server,
                "broker_clock_evidence_id": self.broker_clock_evidence_id,
                "policy_id": self.policy.policy_id,
                "requested_symbols": list(self.requested_symbols),
                "assessments": [item.to_dict() for item in self.assessments],
                "minimum_valid_quote_count": self.minimum_valid_quote_count,
                "required_seed_symbols": list(self.required_seed_symbols),
                "broker_clock_passed": self.broker_clock_passed,
            },
            prefix="us-delayed-reference-quote-report",
        )

    def to_dict(self) -> dict[str, object]:
        delay_errors = [
            item.delay_error_seconds
            for item in self.assessments
            if item.delay_error_seconds is not None
        ]
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "raw_quote_probe_report_id": self.raw_quote_probe_report_id,
            "raw_quote_policy_id": self.raw_quote_policy_id,
            "candidate_selection_id": self.candidate_selection_id,
            "mt5_capability_probe_id": self.mt5_capability_probe_id,
            "broker_server": self.broker_server,
            "broker_clock_evidence_id": self.broker_clock_evidence_id,
            "broker_clock_passed": self.broker_clock_passed,
            "policy": self.policy.to_dict(),
            "requested_symbols": list(self.requested_symbols),
            "minimum_valid_quote_count": self.minimum_valid_quote_count,
            "required_seed_symbols": list(self.required_seed_symbols),
            "valid_quote_count": len(self.valid_symbols),
            "valid_quote_symbols": list(self.valid_symbols),
            "median_delay_error_seconds": (
                None
                if not delay_errors
                else sorted(delay_errors)[len(delay_errors) // 2]
            ),
            "ready_for_simulation_reference": self.ready_for_simulation_reference,
            "blockers": list(self.blockers),
            "assessments": [item.to_dict() for item in self.assessments],
            "generated_at": self.generated_at.isoformat(),
            "simulation_reference_authority": self.ready_for_simulation_reference,
            "engineering_reference_authority": self.ready_for_simulation_reference,
            "broker_account_required": False,
            "broker_account_authority": False,
            "live_market_data_authority": False,
            "live_executable_spread_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
            "alpha_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
        }
        return payload


def build_us_delayed_reference_quote_report(
    raw_report: USCandidateQuoteProbeReportV2,
    policy: USSimulationQuoteTimingPolicy = CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY,
) -> USDelayedReferenceQuoteReport:
    quote_by_symbol = {item.symbol: item for item in raw_report.quotes}
    issues = raw_report.issue_by_symbol
    assessments = tuple(
        _missing_assessment(symbol, issues.get(symbol, ()))
        if quote_by_symbol.get(symbol) is None
        else _assessment_for_quote(
            quote_by_symbol[symbol],
            issues.get(symbol, ()),
            policy,
        )
        for symbol in raw_report.requested_symbols
    )
    return USDelayedReferenceQuoteReport(
        raw_quote_probe_report_id=raw_report.report_id,
        raw_quote_policy_id=raw_report.policy.policy_id,
        candidate_selection_id=raw_report.candidate_selection_id,
        mt5_capability_probe_id=raw_report.mt5_capability_probe_id,
        broker_server=raw_report.broker_server,
        broker_clock_evidence_id=raw_report.broker_clock_evidence.evidence_id,
        policy=policy,
        requested_symbols=raw_report.requested_symbols,
        assessments=assessments,
        minimum_valid_quote_count=raw_report.minimum_valid_quote_count,
        required_seed_symbols=raw_report.required_seed_symbols,
        generated_at=raw_report.generated_at,
        broker_clock_passed=raw_report.broker_clock_evidence.passed,
    )


def us_delayed_reference_quote_report_from_document(
    document: Mapping[str, object],
) -> USDelayedReferenceQuoteReport:
    schema = _text(document.get("schema_version"), "delayed_report.schema_version")
    if schema != "finagent.us-delayed-reference-quote-report.v1":
        raise ValueError(f"unsupported delayed-reference report schema: {schema}")
    policy = us_simulation_quote_timing_policy_from_document(
        _mapping(document.get("policy"), "delayed_report.policy")
    )
    assessments: list[USDelayedReferenceQuoteAssessment] = []
    for raw in _sequence(document.get("assessments"), "delayed_report.assessments"):
        row = _mapping(raw, "delayed_report.assessments[]")
        anchor_raw = row.get("validation_anchor_at_utc")
        anchor = (
            None
            if anchor_raw is None
            else _parse_datetime(anchor_raw, "assessment.validation_anchor_at_utc")
        )
        assessments.append(
            USDelayedReferenceQuoteAssessment(
                symbol=_text(row.get("symbol"), "assessment.symbol"),
                raw_quote_present=_boolean(
                    row.get("raw_quote_present"), "assessment.raw_quote_present"
                ),
                raw_issue_reasons=tuple(
                    _text(item, "assessment.raw_issue_reasons[]")
                    for item in _sequence(
                        row.get("raw_issue_reasons", ()),
                        "assessment.raw_issue_reasons",
                    )
                ),
                eligible_for_delay_reinterpretation=_boolean(
                    row.get("eligible_for_delay_reinterpretation"),
                    "assessment.eligible_for_delay_reinterpretation",
                ),
                observed_delay_seconds=(
                    None
                    if row.get("observed_delay_seconds") is None
                    else _number(
                        row.get("observed_delay_seconds"),
                        "assessment.observed_delay_seconds",
                    )
                ),
                validation_anchor_at_utc=anchor,
                anchor_age_seconds=(
                    None
                    if row.get("anchor_age_seconds") is None
                    else _number(row.get("anchor_age_seconds"), "assessment.anchor_age_seconds")
                ),
                delay_error_seconds=(
                    None
                    if row.get("delay_error_seconds") is None
                    else _number(
                        row.get("delay_error_seconds"), "assessment.delay_error_seconds"
                    )
                ),
                bid=None if row.get("bid") is None else _number(row.get("bid"), "assessment.bid"),
                ask=None if row.get("ask") is None else _number(row.get("ask"), "assessment.ask"),
                spread_bps=(
                    None
                    if row.get("spread_bps") is None
                    else _number(row.get("spread_bps"), "assessment.spread_bps")
                ),
                visible=(
                    None
                    if row.get("visible") is None
                    else _boolean(row.get("visible"), "assessment.visible")
                ),
                tradable=(
                    None
                    if row.get("tradable") is None
                    else _boolean(row.get("tradable"), "assessment.tradable")
                ),
                valid_for_simulation_reference=_boolean(
                    row.get("valid_for_simulation_reference"),
                    "assessment.valid_for_simulation_reference",
                ),
                reasons=tuple(
                    _text(item, "assessment.reasons[]")
                    for item in _sequence(row.get("reasons", ()), "assessment.reasons")
                ),
            )
        )
    report = USDelayedReferenceQuoteReport(
        raw_quote_probe_report_id=_text(
            document.get("raw_quote_probe_report_id"),
            "delayed_report.raw_quote_probe_report_id",
        ),
        raw_quote_policy_id=_text(
            document.get("raw_quote_policy_id"),
            "delayed_report.raw_quote_policy_id",
        ),
        candidate_selection_id=_text(
            document.get("candidate_selection_id"),
            "delayed_report.candidate_selection_id",
        ),
        mt5_capability_probe_id=_text(
            document.get("mt5_capability_probe_id"),
            "delayed_report.mt5_capability_probe_id",
        ),
        broker_server=_text(document.get("broker_server"), "delayed_report.broker_server"),
        broker_clock_evidence_id=_text(
            document.get("broker_clock_evidence_id"),
            "delayed_report.broker_clock_evidence_id",
        ),
        policy=policy,
        requested_symbols=tuple(
            _text(item, "delayed_report.requested_symbols[]")
            for item in _sequence(
                document.get("requested_symbols"), "delayed_report.requested_symbols"
            )
        ),
        assessments=tuple(assessments),
        minimum_valid_quote_count=_integer(
            document.get("minimum_valid_quote_count"),
            "delayed_report.minimum_valid_quote_count",
        ),
        required_seed_symbols=tuple(
            _text(item, "delayed_report.required_seed_symbols[]")
            for item in _sequence(
                document.get("required_seed_symbols", ()),
                "delayed_report.required_seed_symbols",
            )
        ),
        generated_at=_parse_datetime(
            document.get("generated_at"), "delayed_report.generated_at"
        ),
        broker_clock_passed=_boolean(
            document.get("broker_clock_passed"), "delayed_report.broker_clock_passed"
        ),
    )
    stored_id = _text(document.get("report_id"), "delayed_report.report_id")
    if stored_id != report.report_id:
        raise ValueError("stored delayed-reference report_id does not match report content")
    stored_ready = document.get("ready_for_simulation_reference")
    if stored_ready is not None and _boolean(
        stored_ready, "delayed_report.ready_for_simulation_reference"
    ) is not report.ready_for_simulation_reference:
        raise ValueError("stored delayed-reference readiness does not match report content")
    return report
