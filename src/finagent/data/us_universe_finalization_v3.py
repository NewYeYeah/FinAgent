from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.data.us_candidate_quotes_v2 import (
    USCandidateQuoteProbeReportV2,
    candidate_quote_probe_report_v2_from_document,
)
from finagent.data.us_universe_finalization import (
    USUniverseFinalizationPolicy,
    USUniverseFinalizationReport,
    finalize_us_engineering_universe,
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


@dataclass(frozen=True, slots=True)
class USUniverseFinalizationPolicyV3:
    target_count: int = 25
    minimum_count: int = 20
    maximum_count: int = 30
    maximum_current_spread_bps: float = 50.0
    maximum_quote_age_seconds: int = 900
    maximum_future_quote_skew_seconds: int = 60
    require_tradable: bool = True
    require_operator_attestation: bool = True
    require_seed_retention: bool = True
    require_probe_identity_match: bool = True
    require_broker_server_match: bool = True
    require_clock_evidence: bool = True
    require_quote_probe_policy_match: bool = True
    schema_version: str = "finagent.us-engineering-universe-finalization-policy.v3"

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_count <= self.target_count <= self.maximum_count:
            raise ValueError("universe counts must satisfy 1 <= minimum <= target <= maximum")
        if self.maximum_current_spread_bps <= 0:
            raise ValueError("maximum_current_spread_bps must be positive")
        if self.maximum_quote_age_seconds < 1:
            raise ValueError("maximum_quote_age_seconds must be >= 1")
        if self.maximum_future_quote_skew_seconds < 0:
            raise ValueError("maximum_future_quote_skew_seconds must be >= 0")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-universe-final-policy")

    def to_v1(self) -> USUniverseFinalizationPolicy:
        return USUniverseFinalizationPolicy(
            target_count=self.target_count,
            minimum_count=self.minimum_count,
            maximum_count=self.maximum_count,
            maximum_current_spread_bps=self.maximum_current_spread_bps,
            require_tradable=self.require_tradable,
            require_operator_attestation=self.require_operator_attestation,
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "target_count": self.target_count,
            "minimum_count": self.minimum_count,
            "maximum_count": self.maximum_count,
            "maximum_current_spread_bps": self.maximum_current_spread_bps,
            "maximum_quote_age_seconds": self.maximum_quote_age_seconds,
            "maximum_future_quote_skew_seconds": self.maximum_future_quote_skew_seconds,
            "require_tradable": self.require_tradable,
            "require_operator_attestation": self.require_operator_attestation,
            "require_seed_retention": self.require_seed_retention,
            "require_probe_identity_match": self.require_probe_identity_match,
            "require_broker_server_match": self.require_broker_server_match,
            "require_clock_evidence": self.require_clock_evidence,
            "require_quote_probe_policy_match": self.require_quote_probe_policy_match,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_US_UNIVERSE_FINALIZATION_POLICY_V3 = USUniverseFinalizationPolicyV3()


@dataclass(frozen=True, slots=True)
class USQuoteEvidenceAssessmentV2:
    candidate_selection_id: str
    candidate_mt5_probe_id: str
    quote_report_id: str
    quote_mt5_probe_id: str
    candidate_broker_server: str
    quote_broker_server: str
    inventory_broker_server: str
    clock_broker_server: str
    clock_evidence_id: str
    quote_probe_ready: bool
    clock_evidence_passed: bool
    quote_probe_policy_matches: bool
    required_seed_symbols: tuple[str, ...]
    fresh_quote_symbols: tuple[str, ...]
    stale_quote_symbols: tuple[str, ...]
    future_quote_symbols: tuple[str, ...]
    assessed_at: datetime
    policy: USUniverseFinalizationPolicyV3
    schema_version: str = "finagent.us-quote-evidence-assessment.v2"

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.quote_probe_ready:
            blockers.append("quote_evidence:quote_probe_not_ready")
        if self.policy.require_clock_evidence and not self.clock_evidence_passed:
            blockers.append("quote_evidence:broker_clock_evidence_failed")
        if self.policy.require_quote_probe_policy_match and not self.quote_probe_policy_matches:
            blockers.append("quote_evidence:quote_probe_policy_mismatch")
        if (
            self.policy.require_probe_identity_match
            and self.candidate_mt5_probe_id != self.quote_mt5_probe_id
        ):
            blockers.append("quote_evidence:mt5_probe_identity_mismatch")
        if self.policy.require_broker_server_match:
            servers = {
                self.candidate_broker_server,
                self.quote_broker_server,
                self.inventory_broker_server,
                self.clock_broker_server,
            }
            if len(servers) != 1:
                blockers.append("quote_evidence:broker_server_mismatch")
        if len(self.fresh_quote_symbols) < self.policy.minimum_count:
            blockers.append(
                f"quote_evidence:insufficient_fresh_quotes:{len(self.fresh_quote_symbols)}"
                f"<{self.policy.minimum_count}"
            )
        fresh = set(self.fresh_quote_symbols)
        blockers.extend(
            f"quote_evidence:seed_quote_not_fresh:{symbol}"
            for symbol in self.required_seed_symbols
            if symbol not in fresh
        )
        return tuple(dict.fromkeys(blockers))

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def assessment_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "candidate_selection_id": self.candidate_selection_id,
                "candidate_mt5_probe_id": self.candidate_mt5_probe_id,
                "quote_report_id": self.quote_report_id,
                "quote_mt5_probe_id": self.quote_mt5_probe_id,
                "candidate_broker_server": self.candidate_broker_server,
                "quote_broker_server": self.quote_broker_server,
                "inventory_broker_server": self.inventory_broker_server,
                "clock_broker_server": self.clock_broker_server,
                "clock_evidence_id": self.clock_evidence_id,
                "quote_probe_ready": self.quote_probe_ready,
                "clock_evidence_passed": self.clock_evidence_passed,
                "quote_probe_policy_matches": self.quote_probe_policy_matches,
                "required_seed_symbols": list(self.required_seed_symbols),
                "fresh_quote_symbols": list(self.fresh_quote_symbols),
                "stale_quote_symbols": list(self.stale_quote_symbols),
                "future_quote_symbols": list(self.future_quote_symbols),
                "assessed_at": self.assessed_at.astimezone(UTC).isoformat(),
            },
            prefix="us-quote-evidence",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "candidate_selection_id": self.candidate_selection_id,
            "candidate_mt5_probe_id": self.candidate_mt5_probe_id,
            "quote_report_id": self.quote_report_id,
            "quote_mt5_probe_id": self.quote_mt5_probe_id,
            "candidate_broker_server": self.candidate_broker_server,
            "quote_broker_server": self.quote_broker_server,
            "inventory_broker_server": self.inventory_broker_server,
            "clock_broker_server": self.clock_broker_server,
            "clock_evidence_id": self.clock_evidence_id,
            "quote_probe_ready": self.quote_probe_ready,
            "clock_evidence_passed": self.clock_evidence_passed,
            "quote_probe_policy_matches": self.quote_probe_policy_matches,
            "required_seed_symbols": list(self.required_seed_symbols),
            "fresh_quote_count": len(self.fresh_quote_symbols),
            "fresh_quote_symbols": list(self.fresh_quote_symbols),
            "stale_quote_symbols": list(self.stale_quote_symbols),
            "future_quote_symbols": list(self.future_quote_symbols),
            "assessed_at": self.assessed_at.astimezone(UTC).isoformat(),
        }


@dataclass(frozen=True, slots=True)
class USUniverseFinalizationReportV3:
    policy: USUniverseFinalizationPolicyV3
    quote_evidence: USQuoteEvidenceAssessmentV2
    base_finalization: USUniverseFinalizationReport | None
    required_seed_symbols: tuple[str, ...]
    generated_at: datetime
    schema_version: str = "finagent.us-engineering-universe-finalization-report.v3"

    @property
    def selected_symbols(self) -> tuple[str, ...]:
        if self.base_finalization is None:
            return ()
        return self.base_finalization.selected_symbols

    @property
    def missing_seed_symbols(self) -> tuple[str, ...]:
        if not self.policy.require_seed_retention:
            return ()
        selected = set(self.selected_symbols)
        return tuple(symbol for symbol in self.required_seed_symbols if symbol not in selected)

    @property
    def universe_id(self) -> str | None:
        if self.base_finalization is None:
            return None
        return self.base_finalization.universe_id

    @property
    def accepted_mapping_count(self) -> int:
        if self.base_finalization is None:
            return 0
        return self.base_finalization.accepted_mapping_count

    @property
    def materialization(self) -> object | None:
        if self.base_finalization is None:
            return None
        return self.base_finalization.materialization

    @property
    def excluded_by_spread(self) -> tuple[str, ...]:
        if self.base_finalization is None:
            return ()
        return self.base_finalization.excluded_by_spread

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers = list(self.quote_evidence.blockers)
        blockers.extend(
            f"universe:required_seed_missing:{symbol}" for symbol in self.missing_seed_symbols
        )
        if self.base_finalization is None:
            blockers.append("universe:base_finalization_not_executed")
        else:
            blockers.extend(self.base_finalization.blockers)
        return tuple(dict.fromkeys(blockers))

    @property
    def accepted(self) -> bool:
        return not self.blockers and self.universe_id is not None

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "quote_evidence_id": self.quote_evidence.assessment_id,
                "base_report_id": (
                    self.base_finalization.report_id
                    if self.base_finalization is not None
                    else None
                ),
                "required_seed_symbols": list(self.required_seed_symbols),
                "generated_at": self.generated_at.astimezone(UTC).isoformat(),
            },
            prefix="us-engineering-universe-finalization",
        )

    def to_dict(self) -> dict[str, object]:
        materialization_payload = (
            self.base_finalization.materialization.to_dict()
            if self.base_finalization is not None
            and self.base_finalization.materialization is not None
            else None
        )
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "policy": self.policy.to_dict(),
            "quote_evidence": self.quote_evidence.to_dict(),
            "base_finalization": (
                self.base_finalization.to_dict()
                if self.base_finalization is not None
                else None
            ),
            "candidate_selection_id": self.quote_evidence.candidate_selection_id,
            "clock_evidence_id": self.quote_evidence.clock_evidence_id,
            "selected_symbols": list(self.selected_symbols),
            "required_seed_symbols": list(self.required_seed_symbols),
            "missing_seed_symbols": list(self.missing_seed_symbols),
            "excluded_by_quote_quality": sorted(
                set(self.quote_evidence.stale_quote_symbols)
                | set(self.quote_evidence.future_quote_symbols)
            ),
            "excluded_by_spread": list(self.excluded_by_spread),
            "materialization": materialization_payload,
            "universe_id": self.universe_id,
            "accepted": self.accepted,
            "accepted_mapping_count": self.accepted_mapping_count,
            "blockers": list(self.blockers),
            "limitations": [
                "universe:engineering_integration_only",
                "universe:not_survivorship_unbiased",
                "identity:no_point_in_time_security_master",
                "identity:exact_symbol_match_requires_operator_attestation",
                "spread:single_quote_snapshot_is_engineering_filter_not_execution_cost_authority",
                "quote_freshness:bounded_at_probe_and_finalization_time",
                "broker_clock:normalization_bound_to_observed_clock_evidence",
            ],
            "generated_at": self.generated_at.astimezone(UTC).isoformat(),
        }


def _required_seeds(candidate_document: Mapping[str, object]) -> tuple[str, ...]:
    candidate_policy = _mapping(candidate_document.get("policy"), "candidate.policy")
    return tuple(
        sorted(
            dict.fromkeys(
                _text(item, "candidate.policy.seed_symbols[]")
                for item in _sequence(
                    candidate_policy.get("seed_symbols", ()),
                    "candidate.policy.seed_symbols",
                )
            )
        )
    )


def _quote_probe_policy_matches(
    quote_report: USCandidateQuoteProbeReportV2,
    policy: USUniverseFinalizationPolicyV3,
) -> bool:
    return (
        quote_report.policy.maximum_quote_age_seconds
        == policy.maximum_quote_age_seconds
        and quote_report.policy.maximum_future_quote_skew_seconds
        == policy.maximum_future_quote_skew_seconds
        and quote_report.policy.require_visible
        and quote_report.policy.require_tradable == policy.require_tradable
    )


def finalize_us_engineering_universe_v3(
    candidate_document: Mapping[str, object],
    quote_document: Mapping[str, object],
    mt5_inventory_document: Mapping[str, object],
    *,
    policy: USUniverseFinalizationPolicyV3 = DEFAULT_US_UNIVERSE_FINALIZATION_POLICY_V3,
    operator_attested: bool = False,
    generated_at: datetime | None = None,
) -> USUniverseFinalizationReportV3:
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    assessed_at = timestamp.astimezone(UTC)

    candidate_id = _text(candidate_document.get("selection_id"), "candidate.selection_id")
    candidate_probe_id = _text(candidate_document.get("mt5_probe_id"), "candidate.mt5_probe_id")
    candidate_server = _text(
        candidate_document.get("broker_server"),
        "candidate.broker_server",
    )
    quote_report = candidate_quote_probe_report_v2_from_document(quote_document)
    if quote_report.candidate_selection_id != candidate_id:
        raise ValueError("quote report does not bind the supplied candidate selection")

    terminal = _mapping(mt5_inventory_document.get("terminal"), "inventory.terminal")
    inventory_server = _text(
        terminal.get("broker_server"),
        "inventory.terminal.broker_server",
    )
    seeds = _required_seeds(candidate_document)

    valid_at_probe = set(quote_report.valid_quote_symbols)
    fresh_rows: list[dict[str, object]] = []
    fresh_symbols: list[str] = []
    stale_symbols: list[str] = []
    future_symbols: list[str] = []
    for quote in quote_report.quotes:
        if quote.symbol not in valid_at_probe:
            continue
        age_seconds = (assessed_at - quote.normalized_sampled_at_utc).total_seconds()
        if age_seconds > policy.maximum_quote_age_seconds:
            stale_symbols.append(quote.symbol)
            continue
        if age_seconds < -policy.maximum_future_quote_skew_seconds:
            future_symbols.append(quote.symbol)
            continue
        fresh_symbols.append(quote.symbol)
        fresh_rows.append(
            {
                "symbol": quote.symbol,
                "spread_bps": quote.spread_bps,
                "tradable": quote.tradable,
            }
        )

    clock = quote_report.broker_clock_evidence
    assessment = USQuoteEvidenceAssessmentV2(
        candidate_selection_id=candidate_id,
        candidate_mt5_probe_id=candidate_probe_id,
        quote_report_id=quote_report.report_id,
        quote_mt5_probe_id=quote_report.mt5_capability_probe_id,
        candidate_broker_server=candidate_server,
        quote_broker_server=quote_report.broker_server,
        inventory_broker_server=inventory_server,
        clock_broker_server=clock.broker_server,
        clock_evidence_id=clock.evidence_id,
        quote_probe_ready=quote_report.ready_for_finalization,
        clock_evidence_passed=clock.passed,
        quote_probe_policy_matches=_quote_probe_policy_matches(quote_report, policy),
        required_seed_symbols=seeds,
        fresh_quote_symbols=tuple(sorted(dict.fromkeys(fresh_symbols))),
        stale_quote_symbols=tuple(sorted(dict.fromkeys(stale_symbols))),
        future_quote_symbols=tuple(sorted(dict.fromkeys(future_symbols))),
        assessed_at=assessed_at,
        policy=policy,
    )

    base_report: USUniverseFinalizationReport | None = None
    if assessment.passed:
        compatibility_quote_document: dict[str, object] = {
            "report_id": quote_report.report_id,
            "candidate_selection_id": candidate_id,
            "ready_for_finalization": True,
            "quotes": fresh_rows,
        }
        base_report = finalize_us_engineering_universe(
            candidate_document,
            compatibility_quote_document,
            mt5_inventory_document,
            policy=policy.to_v1(),
            operator_attested=operator_attested,
            generated_at=assessed_at,
        )

    return USUniverseFinalizationReportV3(
        policy=policy,
        quote_evidence=assessment,
        base_finalization=base_report,
        required_seed_symbols=seeds,
        generated_at=assessed_at,
    )
