from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.data.us_candidate_quotes_v2 import (
    DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2,
    candidate_quote_probe_report_v2_from_document,
)
from finagent.data.us_delayed_reference_quotes import (
    CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY,
    USDelayedReferenceQuoteReport,
    us_delayed_reference_quote_report_from_document,
)
from finagent.data.us_instruments import (
    EngineeringUniverseMaterialization,
    materialize_engineering_universe_from_mt5_probe,
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
    return float(value)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _parse_datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _candidate_symbols(candidate_document: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        _text(item, "candidate.spread_probe_symbols[]")
        for item in _sequence(
            candidate_document.get("spread_probe_symbols"),
            "candidate.spread_probe_symbols",
        )
    )


def _required_seeds(candidate_document: Mapping[str, object]) -> tuple[str, ...]:
    policy = _mapping(candidate_document.get("policy"), "candidate.policy")
    return tuple(
        sorted(
            dict.fromkeys(
                _text(item, "candidate.policy.seed_symbols[]")
                for item in _sequence(
                    policy.get("seed_symbols", ()),
                    "candidate.policy.seed_symbols",
                )
            )
        )
    )


def _candidate_minimum_count(candidate_document: Mapping[str, object]) -> int:
    policy = _mapping(candidate_document.get("policy"), "candidate.policy")
    return _integer(
        policy.get("minimum_selected_count"),
        "candidate.policy.minimum_selected_count",
    )


@dataclass(frozen=True, slots=True)
class USSimulationUniverseFinalizationPolicy:
    target_count: int = 25
    minimum_count: int = 20
    maximum_count: int = 30
    maximum_reference_spread_bps: float = 50.0
    maximum_inventory_age_seconds: int = 900
    maximum_inventory_future_skew_seconds: int = 60
    require_visible: bool = True
    require_tradable: bool = True
    require_operator_attestation: bool = True
    require_seed_retention: bool = True
    schema_version: str = "finagent.us-simulation-universe-finalization-policy.v1"

    def __post_init__(self) -> None:
        if not 1 <= self.minimum_count <= self.target_count <= self.maximum_count:
            raise ValueError(
                "universe counts must satisfy 1 <= minimum <= target <= maximum"
            )
        if self.maximum_reference_spread_bps <= 0:
            raise ValueError("maximum_reference_spread_bps must be positive")
        if self.maximum_inventory_age_seconds < 1:
            raise ValueError("maximum_inventory_age_seconds must be >= 1")
        if self.maximum_inventory_future_skew_seconds < 0:
            raise ValueError("maximum_inventory_future_skew_seconds must be >= 0")
        if not self.require_visible or not self.require_tradable:
            raise ValueError(
                "simulation universe v1 requires visible and tradable broker symbols"
            )
        if not self.require_operator_attestation or not self.require_seed_retention:
            raise ValueError(
                "simulation universe v1 requires attestation and seed retention"
            )

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-universe-final-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "target_count": self.target_count,
            "minimum_count": self.minimum_count,
            "maximum_count": self.maximum_count,
            "maximum_reference_spread_bps": self.maximum_reference_spread_bps,
            "maximum_inventory_age_seconds": self.maximum_inventory_age_seconds,
            "maximum_inventory_future_skew_seconds": (
                self.maximum_inventory_future_skew_seconds
            ),
            "require_visible": self.require_visible,
            "require_tradable": self.require_tradable,
            "require_operator_attestation": self.require_operator_attestation,
            "require_seed_retention": self.require_seed_retention,
            "spread_semantics": "delayed_reference_diagnostic_only",
            "raw_live_current_v3_finalizer_unchanged": True,
            "live_executable_spread_authority": False,
            "broker_account_required": False,
            "execution_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY = (
    USSimulationUniverseFinalizationPolicy()
)


def us_simulation_universe_policy_from_document(
    document: Mapping[str, object],
) -> USSimulationUniverseFinalizationPolicy:
    schema = _text(
        document.get("schema_version"),
        "simulation_universe_policy.schema_version",
    )
    if schema != "finagent.us-simulation-universe-finalization-policy.v1":
        raise ValueError(f"unsupported simulation universe policy schema: {schema}")
    policy = USSimulationUniverseFinalizationPolicy(
        target_count=_integer(
            document.get("target_count"),
            "simulation_universe_policy.target_count",
        ),
        minimum_count=_integer(
            document.get("minimum_count"),
            "simulation_universe_policy.minimum_count",
        ),
        maximum_count=_integer(
            document.get("maximum_count"),
            "simulation_universe_policy.maximum_count",
        ),
        maximum_reference_spread_bps=_number(
            document.get("maximum_reference_spread_bps"),
            "simulation_universe_policy.maximum_reference_spread_bps",
        ),
        maximum_inventory_age_seconds=_integer(
            document.get("maximum_inventory_age_seconds"),
            "simulation_universe_policy.maximum_inventory_age_seconds",
        ),
        maximum_inventory_future_skew_seconds=_integer(
            document.get("maximum_inventory_future_skew_seconds"),
            "simulation_universe_policy.maximum_inventory_future_skew_seconds",
        ),
        require_visible=_boolean(
            document.get("require_visible"),
            "simulation_universe_policy.require_visible",
        ),
        require_tradable=_boolean(
            document.get("require_tradable"),
            "simulation_universe_policy.require_tradable",
        ),
        require_operator_attestation=_boolean(
            document.get("require_operator_attestation"),
            "simulation_universe_policy.require_operator_attestation",
        ),
        require_seed_retention=_boolean(
            document.get("require_seed_retention"),
            "simulation_universe_policy.require_seed_retention",
        ),
    )
    stored_id = _text(
        document.get("policy_id"),
        "simulation_universe_policy.policy_id",
    )
    if stored_id != policy.policy_id:
        raise ValueError(
            "stored simulation universe policy_id does not match policy content"
        )
    return policy


def validate_canonical_us_simulation_universe_policy(
    document: Mapping[str, object],
) -> USSimulationUniverseFinalizationPolicy:
    policy = us_simulation_universe_policy_from_document(document)
    if policy != CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY:
        raise ValueError("simulation universe policy differs from canonical v1")
    return policy


@dataclass(frozen=True, slots=True)
class USSimulationUniverseFinalizationReport:
    policy: USSimulationUniverseFinalizationPolicy
    candidate_selection_id: str
    candidate_mt5_probe_id: str
    raw_quote_probe_report_id: str
    raw_quote_policy_id: str
    delayed_reference_report_id: str
    simulation_quote_policy_id: str
    broker_clock_evidence_id: str
    inventory_probe_id: str
    broker_server: str
    inventory_probed_at: datetime
    inventory_age_seconds: float
    required_seed_symbols: tuple[str, ...]
    delayed_reference_symbols: tuple[str, ...]
    selected_symbols: tuple[str, ...]
    excluded_by_delayed_quality: tuple[str, ...]
    excluded_by_reference_spread: tuple[str, ...]
    operator_attested: bool
    delayed_reference_ready: bool
    delayed_reference_blockers: tuple[str, ...]
    raw_quote_policy_canonical: bool
    simulation_quote_policy_canonical: bool
    inventory_server_matches: bool
    materialization: EngineeringUniverseMaterialization | None
    generated_at: datetime
    schema_version: str = (
        "finagent.us-simulation-engineering-universe-finalization-report.v1"
    )

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_selection_id",
            "candidate_mt5_probe_id",
            "raw_quote_probe_report_id",
            "raw_quote_policy_id",
            "delayed_reference_report_id",
            "simulation_quote_policy_id",
            "broker_clock_evidence_id",
            "inventory_probe_id",
            "broker_server",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        for field_name in ("inventory_probed_at", "generated_at"):
            value = getattr(self, field_name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")
            object.__setattr__(self, field_name, value.astimezone(UTC))

    @property
    def simulation_universe_id(self) -> str | None:
        if self.materialization is None:
            return None
        universe = self.materialization.universe
        return None if universe is None else universe.universe_id

    @property
    def simulation_accepted_mapping_count(self) -> int:
        if self.materialization is None:
            return 0
        return sum(
            mapping.status.value == "accepted_for_engineering"
            for mapping in self.materialization.mappings
        )

    @property
    def missing_seed_symbols(self) -> tuple[str, ...]:
        if not self.policy.require_seed_retention:
            return ()
        selected = set(self.selected_symbols)
        return tuple(
            symbol for symbol in self.required_seed_symbols if symbol not in selected
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.raw_quote_policy_canonical:
            blockers.append("simulation_universe:raw_quote_policy_not_canonical")
        if not self.simulation_quote_policy_canonical:
            blockers.append(
                "simulation_universe:simulation_quote_policy_not_canonical"
            )
        if not self.delayed_reference_ready:
            blockers.append("simulation_universe:delayed_reference_not_ready")
            blockers.extend(
                f"simulation_universe:upstream:{item}"
                for item in self.delayed_reference_blockers
            )
        if not self.inventory_server_matches:
            blockers.append("simulation_universe:inventory_broker_server_mismatch")
        if self.inventory_age_seconds > self.policy.maximum_inventory_age_seconds:
            blockers.append(
                "simulation_universe:inventory_stale:"
                f"{self.inventory_age_seconds:.3f}>"
                f"{self.policy.maximum_inventory_age_seconds}"
            )
        if self.inventory_age_seconds < -self.policy.maximum_inventory_future_skew_seconds:
            blockers.append(
                "simulation_universe:inventory_future:"
                f"{self.inventory_age_seconds:.3f}<-"
                f"{self.policy.maximum_inventory_future_skew_seconds}"
            )
        if len(self.selected_symbols) < self.policy.target_count:
            blockers.append(
                "simulation_universe:insufficient_reference_spread_eligible:"
                f"{len(self.selected_symbols)}<{self.policy.target_count}"
            )
        blockers.extend(
            f"simulation_universe:required_seed_missing:{symbol}"
            for symbol in self.missing_seed_symbols
        )
        if self.policy.require_operator_attestation and not self.operator_attested:
            blockers.append("simulation_universe:operator_attestation_required")
        if self.materialization is None:
            blockers.append("simulation_universe:materialization_not_executed")
        else:
            blockers.extend(
                f"simulation_universe:{item}"
                for item in self.materialization.blockers
            )
        return tuple(dict.fromkeys(blockers))

    @property
    def accepted_for_simulation_engineering(self) -> bool:
        return not self.blockers and self.simulation_universe_id is not None

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "candidate_selection_id": self.candidate_selection_id,
                "candidate_mt5_probe_id": self.candidate_mt5_probe_id,
                "raw_quote_probe_report_id": self.raw_quote_probe_report_id,
                "raw_quote_policy_id": self.raw_quote_policy_id,
                "delayed_reference_report_id": self.delayed_reference_report_id,
                "simulation_quote_policy_id": self.simulation_quote_policy_id,
                "broker_clock_evidence_id": self.broker_clock_evidence_id,
                "inventory_probe_id": self.inventory_probe_id,
                "broker_server": self.broker_server,
                "inventory_probed_at": self.inventory_probed_at.isoformat(),
                "inventory_age_seconds": self.inventory_age_seconds,
                "required_seed_symbols": list(self.required_seed_symbols),
                "delayed_reference_symbols": list(self.delayed_reference_symbols),
                "selected_symbols": list(self.selected_symbols),
                "excluded_by_delayed_quality": list(
                    self.excluded_by_delayed_quality
                ),
                "excluded_by_reference_spread": list(
                    self.excluded_by_reference_spread
                ),
                "operator_attested": self.operator_attested,
                "delayed_reference_ready": self.delayed_reference_ready,
                "delayed_reference_blockers": list(
                    self.delayed_reference_blockers
                ),
                "raw_quote_policy_canonical": self.raw_quote_policy_canonical,
                "simulation_quote_policy_canonical": (
                    self.simulation_quote_policy_canonical
                ),
                "inventory_server_matches": self.inventory_server_matches,
                "materialization_id": (
                    None
                    if self.materialization is None
                    else self.materialization.materialization_id
                ),
                "generated_at": self.generated_at.isoformat(),
            },
            prefix="us-simulation-engineering-universe-finalization",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "policy": self.policy.to_dict(),
            "candidate_selection_id": self.candidate_selection_id,
            "candidate_mt5_probe_id": self.candidate_mt5_probe_id,
            "raw_quote_probe_report_id": self.raw_quote_probe_report_id,
            "raw_quote_policy_id": self.raw_quote_policy_id,
            "delayed_reference_report_id": self.delayed_reference_report_id,
            "simulation_quote_policy_id": self.simulation_quote_policy_id,
            "broker_clock_evidence_id": self.broker_clock_evidence_id,
            "inventory_probe_id": self.inventory_probe_id,
            "broker_server": self.broker_server,
            "inventory_probed_at": self.inventory_probed_at.isoformat(),
            "inventory_age_seconds": self.inventory_age_seconds,
            "required_seed_symbols": list(self.required_seed_symbols),
            "delayed_reference_symbol_count": len(
                self.delayed_reference_symbols
            ),
            "delayed_reference_symbols": list(self.delayed_reference_symbols),
            "selected_symbols": list(self.selected_symbols),
            "excluded_by_delayed_quality": list(
                self.excluded_by_delayed_quality
            ),
            "excluded_by_reference_spread": list(
                self.excluded_by_reference_spread
            ),
            "operator_attested": self.operator_attested,
            "delayed_reference_ready": self.delayed_reference_ready,
            "delayed_reference_blockers": list(self.delayed_reference_blockers),
            "raw_quote_policy_canonical": self.raw_quote_policy_canonical,
            "simulation_quote_policy_canonical": (
                self.simulation_quote_policy_canonical
            ),
            "inventory_server_matches": self.inventory_server_matches,
            "materialization": (
                None
                if self.materialization is None
                else self.materialization.to_dict()
            ),
            "simulation_universe_id": self.simulation_universe_id,
            "accepted_for_simulation_engineering": (
                self.accepted_for_simulation_engineering
            ),
            "simulation_accepted_mapping_count": (
                self.simulation_accepted_mapping_count
            ),
            "blockers": list(self.blockers),
            "limitations": [
                "universe:simulation_engineering_integration_only",
                "universe:not_survivorship_unbiased",
                "identity:no_point_in_time_security_master",
                "identity:exact_symbol_match_requires_operator_attestation",
                "market_data:metaquotes_demo_delayed_reference_without_broker_account",
                "spread:delayed_reference_diagnostic_only",
                "spread:not_live_executable_spread_authority",
                "inventory:single_read_only_snapshot",
                "live_broker:requires_separate_re_admission",
            ],
            "simulation_engineering_universe_authority": (
                self.accepted_for_simulation_engineering
            ),
            "engineering_reference_authority": (
                self.accepted_for_simulation_engineering
            ),
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
            "raw_live_current_v3_finalizer_unchanged": True,
            "compatible_with_live_current_v3_authority": False,
            "generated_at": self.generated_at.isoformat(),
        }


def _validate_identity_chain(
    candidate_document: Mapping[str, object],
    raw_report_id: str,
    raw_candidate_id: str,
    raw_mt5_probe_id: str,
    raw_policy_id: str,
    raw_broker_server: str,
    raw_clock_evidence_id: str,
    raw_requested_symbols: tuple[str, ...],
    raw_required_seeds: tuple[str, ...],
    delayed: USDelayedReferenceQuoteReport,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    candidate_id = _text(
        candidate_document.get("selection_id"),
        "candidate.selection_id",
    )
    candidate_probe_id = _text(
        candidate_document.get("mt5_probe_id"),
        "candidate.mt5_probe_id",
    )
    candidate_server = _text(
        candidate_document.get("broker_server"),
        "candidate.broker_server",
    )
    candidate_symbols = _candidate_symbols(candidate_document)
    seeds = _required_seeds(candidate_document)

    if raw_candidate_id != candidate_id:
        raise ValueError(
            "raw quote report does not bind supplied candidate selection"
        )
    if raw_mt5_probe_id != candidate_probe_id:
        raise ValueError(
            "raw quote report MT5 probe does not match candidate selection"
        )
    if raw_broker_server != candidate_server:
        raise ValueError(
            "raw quote report broker server does not match candidate selection"
        )
    if raw_requested_symbols != candidate_symbols:
        raise ValueError(
            "raw quote requested symbols do not match candidate selection"
        )
    if tuple(sorted(raw_required_seeds)) != seeds:
        raise ValueError(
            "raw quote seed symbols do not match candidate selection"
        )

    if delayed.raw_quote_probe_report_id != raw_report_id:
        raise ValueError(
            "delayed-reference report does not bind supplied raw quote report"
        )
    if delayed.raw_quote_policy_id != raw_policy_id:
        raise ValueError(
            "delayed-reference raw quote policy id does not match raw report"
        )
    if delayed.candidate_selection_id != candidate_id:
        raise ValueError("delayed-reference candidate selection id mismatch")
    if delayed.mt5_capability_probe_id != candidate_probe_id:
        raise ValueError("delayed-reference MT5 probe id mismatch")
    if delayed.broker_server != candidate_server:
        raise ValueError("delayed-reference broker server mismatch")
    if delayed.broker_clock_evidence_id != raw_clock_evidence_id:
        raise ValueError("delayed-reference broker clock evidence id mismatch")
    if delayed.requested_symbols != candidate_symbols:
        raise ValueError(
            "delayed-reference requested symbols do not match candidate selection"
        )
    if tuple(sorted(delayed.required_seed_symbols)) != seeds:
        raise ValueError(
            "delayed-reference seed symbols do not match candidate selection"
        )

    return candidate_id, candidate_probe_id, candidate_symbols, seeds


def finalize_us_simulation_engineering_universe(
    candidate_document: Mapping[str, object],
    raw_quote_document: Mapping[str, object],
    delayed_reference_document: Mapping[str, object],
    mt5_inventory_document: Mapping[str, object],
    *,
    policy: USSimulationUniverseFinalizationPolicy = (
        CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY
    ),
    operator_attested: bool = False,
    generated_at: datetime | None = None,
) -> USSimulationUniverseFinalizationReport:
    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("generated_at must be timezone-aware")
    assessed_at = timestamp.astimezone(UTC)

    raw = candidate_quote_probe_report_v2_from_document(raw_quote_document)
    delayed = us_delayed_reference_quote_report_from_document(
        delayed_reference_document
    )
    candidate_id, candidate_probe_id, candidate_symbols, seeds = (
        _validate_identity_chain(
            candidate_document,
            raw.report_id,
            raw.candidate_selection_id,
            raw.mt5_capability_probe_id,
            raw.policy.policy_id,
            raw.broker_server,
            raw.broker_clock_evidence.evidence_id,
            raw.requested_symbols,
            raw.required_seed_symbols,
            delayed,
        )
    )

    candidate_minimum = _candidate_minimum_count(candidate_document)
    if candidate_minimum != policy.minimum_count:
        raise ValueError(
            "simulation universe policy minimum_count does not match candidate selection"
        )
    if delayed.minimum_valid_quote_count != policy.minimum_count:
        raise ValueError(
            "simulation universe policy minimum_count does not match delayed reference"
        )

    terminal = _mapping(
        mt5_inventory_document.get("terminal"),
        "inventory.terminal",
    )
    inventory_probe_id = _text(
        mt5_inventory_document.get("probe_id"),
        "inventory.probe_id",
    )
    inventory_server = _text(
        terminal.get("broker_server"),
        "inventory.terminal.broker_server",
    )
    inventory_probed_at = _parse_datetime(
        mt5_inventory_document.get("probed_at"),
        "inventory.probed_at",
    )
    inventory_age = (assessed_at - inventory_probed_at).total_seconds()

    raw_policy_canonical = (
        raw.policy == DEFAULT_US_CANDIDATE_QUOTE_PROBE_POLICY_V2
    )
    simulation_quote_policy_canonical = (
        delayed.policy == CANONICAL_US_SIMULATION_QUOTE_TIMING_POLICY
    )
    inventory_server_matches = (
        inventory_server
        == raw.broker_server
        == delayed.broker_server
        == delayed.policy.expected_broker_server
    )

    assessment_by_symbol = {item.symbol: item for item in delayed.assessments}
    delayed_valid = set(delayed.valid_symbols)
    reference_spreads: dict[str, float] = {}
    excluded_quality: list[str] = []
    excluded_spread: list[str] = []

    for symbol in candidate_symbols:
        assessment = assessment_by_symbol[symbol]
        if (
            symbol not in delayed_valid
            or not assessment.valid_for_simulation_reference
        ):
            excluded_quality.append(symbol)
            continue
        if policy.require_visible and assessment.visible is not True:
            excluded_quality.append(symbol)
            continue
        if policy.require_tradable and assessment.tradable is not True:
            excluded_quality.append(symbol)
            continue
        if assessment.spread_bps is None:
            excluded_quality.append(symbol)
            continue
        if assessment.spread_bps > policy.maximum_reference_spread_bps:
            excluded_spread.append(symbol)
            continue
        reference_spreads[symbol] = assessment.spread_bps

    ranked: list[tuple[int, str]] = []
    seen_candidate_symbols: set[str] = set()
    candidate_symbol_set = set(candidate_symbols)
    for raw_candidate in _sequence(
        candidate_document.get("candidates"),
        "candidate.candidates",
    ):
        row = _mapping(raw_candidate, "candidate.candidates[]")
        symbol = _text(
            row.get("research_symbol"),
            "candidate.candidates[].research_symbol",
        )
        rank = _integer(
            row.get("rank"),
            "candidate.candidates[].rank",
        )
        if symbol in seen_candidate_symbols:
            raise ValueError(f"duplicate candidate research symbol: {symbol}")
        seen_candidate_symbols.add(symbol)
        if symbol not in candidate_symbol_set:
            continue
        if symbol in reference_spreads:
            ranked.append((rank, symbol))
    if seen_candidate_symbols.intersection(candidate_symbol_set) != candidate_symbol_set:
        raise ValueError("candidate ranking does not cover spread_probe_symbols")
    ranked.sort(key=lambda item: (item[0], item[1]))
    selected = tuple(
        symbol for _rank, symbol in ranked[: policy.target_count]
    )

    pre_materialization_ready = (
        delayed.ready_for_simulation_reference
        and raw_policy_canonical
        and simulation_quote_policy_canonical
        and inventory_server_matches
        and inventory_age <= policy.maximum_inventory_age_seconds
        and inventory_age >= -policy.maximum_inventory_future_skew_seconds
    )

    materialization: EngineeringUniverseMaterialization | None = None
    if pre_materialization_ready and selected:
        materialization = materialize_engineering_universe_from_mt5_probe(
            mt5_inventory_document,
            mapping_pairs=tuple((symbol, symbol) for symbol in selected),
            accepted_research_symbols=(
                frozenset(selected) if operator_attested else frozenset()
            ),
            generated_at=assessed_at,
        )

    return USSimulationUniverseFinalizationReport(
        policy=policy,
        candidate_selection_id=candidate_id,
        candidate_mt5_probe_id=candidate_probe_id,
        raw_quote_probe_report_id=raw.report_id,
        raw_quote_policy_id=raw.policy.policy_id,
        delayed_reference_report_id=delayed.report_id,
        simulation_quote_policy_id=delayed.policy.policy_id,
        broker_clock_evidence_id=raw.broker_clock_evidence.evidence_id,
        inventory_probe_id=inventory_probe_id,
        broker_server=raw.broker_server,
        inventory_probed_at=inventory_probed_at,
        inventory_age_seconds=inventory_age,
        required_seed_symbols=seeds,
        delayed_reference_symbols=tuple(
            symbol for symbol in candidate_symbols if symbol in delayed_valid
        ),
        selected_symbols=selected,
        excluded_by_delayed_quality=tuple(
            sorted(dict.fromkeys(excluded_quality))
        ),
        excluded_by_reference_spread=tuple(
            sorted(dict.fromkeys(excluded_spread))
        ),
        operator_attested=operator_attested,
        delayed_reference_ready=delayed.ready_for_simulation_reference,
        delayed_reference_blockers=delayed.blockers,
        raw_quote_policy_canonical=raw_policy_canonical,
        simulation_quote_policy_canonical=simulation_quote_policy_canonical,
        inventory_server_matches=inventory_server_matches,
        materialization=materialization,
        generated_at=assessed_at,
    )
