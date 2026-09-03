from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from finagent.data.us_minute.reconciliation import (
    MinuteReferenceReconciliationPolicy,
    MinuteReferenceReconciliationReport,
    MinuteReferenceSymbolCheck,
)
from finagent.data.us_minute.research_certification import (
    USMinuteCertificationPolicy,
    USMinuteCertificationReport,
    evaluate_us_minute_certification,
    load_us_minute_certification_inputs,
)
from finagent.data.us_simulation_universe import (
    CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY,
    validate_canonical_us_simulation_universe_policy,
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


def _aware(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field_name}[]") for item in _sequence(value, field_name))


def _document_hash(
    document: Mapping[str, object],
    *,
    id_field: str,
    prefix: str,
) -> str:
    payload = dict(document)
    payload.pop(id_field, None)
    return _canonical_hash(payload, prefix=prefix)


@dataclass(frozen=True, slots=True)
class USSimulationD3CertificationPolicy:
    core_policy: USMinuteCertificationPolicy = USMinuteCertificationPolicy()
    expected_simulation_universe_policy_id: str = (
        CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY.policy_id
    )
    require_simulation_universe_acceptance: bool = True
    require_delayed_reference_limitation: bool = True
    require_no_live_authority: bool = True
    schema_version: str = "finagent.us-simulation-d3-certification-policy.v1"

    def __post_init__(self) -> None:
        expected = self.expected_simulation_universe_policy_id.strip()
        if not expected:
            raise ValueError("expected_simulation_universe_policy_id must be non-empty")
        object.__setattr__(self, "expected_simulation_universe_policy_id", expected)
        if not (
            self.require_simulation_universe_acceptance
            and self.require_delayed_reference_limitation
            and self.require_no_live_authority
        ):
            raise ValueError("simulation D3 v1 requires all authority-boundary checks")

    @property
    def policy_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-d3-cert-policy",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "core_policy": self.core_policy.to_dict(),
            "expected_simulation_universe_policy_id": (
                self.expected_simulation_universe_policy_id
            ),
            "require_simulation_universe_acceptance": (
                self.require_simulation_universe_acceptance
            ),
            "require_delayed_reference_limitation": (
                self.require_delayed_reference_limitation
            ),
            "require_no_live_authority": self.require_no_live_authority,
            "all_day_preflight_in_certification_denominator": False,
            "live_broker_re_admission_required": True,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY = USSimulationD3CertificationPolicy()


def validate_canonical_us_simulation_d3_certification_policy(
    document: Mapping[str, object],
) -> USSimulationD3CertificationPolicy:
    schema = _text(document.get("schema_version"), "policy.schema_version")
    if schema != "finagent.us-simulation-d3-certification-policy.v1":
        raise ValueError(f"unsupported simulation D3 policy schema: {schema}")
    core_raw = _mapping(document.get("core_policy"), "policy.core_policy")
    core = USMinuteCertificationPolicy(
        expected_source_revision=_text(
            core_raw.get("expected_source_revision"),
            "policy.core_policy.expected_source_revision",
        ),
        expected_inventory_id=_text(
            core_raw.get("expected_inventory_id"),
            "policy.core_policy.expected_inventory_id",
        ),
        expected_calendar_id=_text(
            core_raw.get("expected_calendar_id"),
            "policy.core_policy.expected_calendar_id",
        ),
        minimum_engineering_universe_size=_integer(
            core_raw.get("minimum_engineering_universe_size"),
            "policy.core_policy.minimum_engineering_universe_size",
        ),
        maximum_engineering_universe_size=_integer(
            core_raw.get("maximum_engineering_universe_size"),
            "policy.core_policy.maximum_engineering_universe_size",
        ),
        required_scenarios=_strings(
            core_raw.get("required_scenarios"),
            "policy.core_policy.required_scenarios",
        ),
        require_reconciliation=_boolean(
            core_raw.get("require_reconciliation"),
            "policy.core_policy.require_reconciliation",
        ),
        require_d1_replay_match=_boolean(
            core_raw.get("require_d1_replay_match"),
            "policy.core_policy.require_d1_replay_match",
        ),
        require_action_authority_boundary=_boolean(
            core_raw.get("require_action_authority_boundary"),
            "policy.core_policy.require_action_authority_boundary",
        ),
        require_no_unknown_label_unavailability=_boolean(
            core_raw.get("require_no_unknown_label_unavailability"),
            "policy.core_policy.require_no_unknown_label_unavailability",
        ),
    )
    stored_core_id = _text(core_raw.get("policy_id"), "policy.core_policy.policy_id")
    if stored_core_id != core.policy_id:
        raise ValueError("stored core certification policy identity mismatch")
    policy = USSimulationD3CertificationPolicy(
        core_policy=core,
        expected_simulation_universe_policy_id=_text(
            document.get("expected_simulation_universe_policy_id"),
            "policy.expected_simulation_universe_policy_id",
        ),
        require_simulation_universe_acceptance=_boolean(
            document.get("require_simulation_universe_acceptance"),
            "policy.require_simulation_universe_acceptance",
        ),
        require_delayed_reference_limitation=_boolean(
            document.get("require_delayed_reference_limitation"),
            "policy.require_delayed_reference_limitation",
        ),
        require_no_live_authority=_boolean(
            document.get("require_no_live_authority"),
            "policy.require_no_live_authority",
        ),
    )
    stored_id = _text(document.get("policy_id"), "policy.policy_id")
    if stored_id != policy.policy_id:
        raise ValueError("stored simulation D3 policy identity mismatch")
    if policy != CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY:
        raise ValueError("simulation D3 certification policy differs from canonical v1")
    return policy


@dataclass(frozen=True, slots=True)
class USSimulationUniverseBinding:
    report_id: str
    simulation_universe_id: str
    accepted_mapping_count: int
    candidate_mt5_probe_id: str
    broker_server: str
    selected_pairs: tuple[tuple[str, str], ...]
    limitations: tuple[str, ...]
    accepted: bool


_REQUIRED_SIMULATION_LIMITATIONS = (
    "market_data:metaquotes_demo_delayed_reference_without_broker_account",
    "spread:delayed_reference_diagnostic_only",
    "spread:not_live_executable_spread_authority",
    "live_broker:requires_separate_re_admission",
)


def validate_us_simulation_universe_document(
    document: Mapping[str, object],
) -> USSimulationUniverseBinding:
    schema = _text(document.get("schema_version"), "simulation_universe.schema_version")
    if schema != "finagent.us-simulation-engineering-universe-finalization-report.v1":
        raise ValueError(f"unsupported simulation universe report schema: {schema}")
    policy = validate_canonical_us_simulation_universe_policy(
        _mapping(document.get("policy"), "simulation_universe.policy")
    )
    if policy.policy_id != CANONICAL_US_SIMULATION_UNIVERSE_FINALIZATION_POLICY.policy_id:
        raise ValueError("simulation universe is not bound to canonical policy")

    materialization = _mapping(
        document.get("materialization"),
        "simulation_universe.materialization",
    )
    stored_materialization_id = _text(
        materialization.get("materialization_id"),
        "simulation_universe.materialization.materialization_id",
    )
    if stored_materialization_id != _document_hash(
        materialization,
        id_field="materialization_id",
        prefix="engineering-universe-materialization",
    ):
        raise ValueError("simulation universe materialization identity mismatch")

    universe = _mapping(
        materialization.get("universe"),
        "simulation_universe.materialization.universe",
    )
    stored_universe_id = _text(universe.get("universe_id"), "materialization.universe.universe_id")
    if stored_universe_id != _document_hash(
        universe,
        id_field="universe_id",
        prefix="engineering-universe",
    ):
        raise ValueError("embedded engineering universe identity mismatch")
    if _text(
        document.get("simulation_universe_id"),
        "simulation_universe.simulation_universe_id",
    ) != stored_universe_id:
        raise ValueError("top-level simulation universe identity mismatch")

    mappings = _sequence(materialization.get("mappings"), "materialization.mappings")
    selected_pairs: list[tuple[str, str]] = []
    for raw in mappings:
        row = _mapping(raw, "materialization.mappings[]")
        if _text(row.get("status"), "mapping.status") != "accepted_for_engineering":
            raise ValueError("accepted simulation materialization contains non-accepted mapping")
        research = _mapping(row.get("research"), "mapping.research")
        broker = _mapping(row.get("broker"), "mapping.broker")
        selected_pairs.append(
            (
                _text(research.get("source_symbol"), "mapping.research.source_symbol"),
                _text(broker.get("broker_symbol"), "mapping.broker.broker_symbol"),
            )
        )
    selected_symbols = _strings(
        document.get("selected_symbols"),
        "simulation_universe.selected_symbols",
    )
    if tuple(pair[0] for pair in selected_pairs) != selected_symbols:
        raise ValueError("simulation selected symbols do not match materialized mappings")
    count = _integer(
        document.get("simulation_accepted_mapping_count"),
        "simulation_universe.simulation_accepted_mapping_count",
    )
    if count != len(selected_pairs):
        raise ValueError("simulation accepted mapping count mismatch")

    limitations = _strings(document.get("limitations", ()), "simulation_universe.limitations")
    missing_limitations = set(_REQUIRED_SIMULATION_LIMITATIONS).difference(limitations)
    if missing_limitations:
        raise ValueError(
            "simulation universe missing authority limitations: "
            + ",".join(sorted(missing_limitations))
        )
    false_authority_fields = (
        "broker_account_authority",
        "live_market_data_authority",
        "live_executable_spread_authority",
        "execution_authority",
        "order_authority",
        "live_capital_authority",
        "alpha_authority",
        "status_authority",
        "stage_exit_authority",
    )
    for field_name in false_authority_fields:
        if _boolean(document.get(field_name), f"simulation_universe.{field_name}"):
            raise ValueError(f"simulation universe unexpectedly asserts {field_name}")

    report_payload = {
        "schema_version": schema,
        "policy_id": policy.policy_id,
        "candidate_selection_id": document.get("candidate_selection_id"),
        "candidate_mt5_probe_id": document.get("candidate_mt5_probe_id"),
        "raw_quote_probe_report_id": document.get("raw_quote_probe_report_id"),
        "raw_quote_policy_id": document.get("raw_quote_policy_id"),
        "delayed_reference_report_id": document.get("delayed_reference_report_id"),
        "simulation_quote_policy_id": document.get("simulation_quote_policy_id"),
        "broker_clock_evidence_id": document.get("broker_clock_evidence_id"),
        "inventory_probe_id": document.get("inventory_probe_id"),
        "broker_server": document.get("broker_server"),
        "inventory_probed_at": document.get("inventory_probed_at"),
        "inventory_age_seconds": document.get("inventory_age_seconds"),
        "required_seed_symbols": document.get("required_seed_symbols"),
        "delayed_reference_symbols": document.get("delayed_reference_symbols"),
        "selected_symbols": document.get("selected_symbols"),
        "excluded_by_delayed_quality": document.get("excluded_by_delayed_quality"),
        "excluded_by_reference_spread": document.get("excluded_by_reference_spread"),
        "operator_attested": document.get("operator_attested"),
        "delayed_reference_ready": document.get("delayed_reference_ready"),
        "delayed_reference_blockers": document.get("delayed_reference_blockers"),
        "raw_quote_policy_canonical": document.get("raw_quote_policy_canonical"),
        "simulation_quote_policy_canonical": document.get("simulation_quote_policy_canonical"),
        "inventory_server_matches": document.get("inventory_server_matches"),
        "materialization_id": stored_materialization_id,
        "generated_at": document.get("generated_at"),
    }
    stored_report_id = _text(document.get("report_id"), "simulation_universe.report_id")
    if stored_report_id != _canonical_hash(
        report_payload,
        prefix="us-simulation-engineering-universe-finalization",
    ):
        raise ValueError("simulation universe finalization report identity mismatch")

    accepted = _boolean(
        document.get("accepted_for_simulation_engineering"),
        "simulation_universe.accepted_for_simulation_engineering",
    )
    return USSimulationUniverseBinding(
        report_id=stored_report_id,
        simulation_universe_id=stored_universe_id,
        accepted_mapping_count=count,
        candidate_mt5_probe_id=_text(
            document.get("candidate_mt5_probe_id"),
            "simulation_universe.candidate_mt5_probe_id",
        ),
        broker_server=_text(document.get("broker_server"), "simulation_universe.broker_server"),
        selected_pairs=tuple(selected_pairs),
        limitations=limitations,
        accepted=accepted,
    )


def _parse_reconciliation(
    document: Mapping[str, object],
) -> MinuteReferenceReconciliationReport:
    schema = _text(document.get("schema_version"), "reconciliation.schema_version")
    if schema != "finagent.minute-reference-reconciliation-report.v1":
        raise ValueError(f"unsupported reconciliation schema: {schema}")
    policy_raw = _mapping(document.get("policy"), "reconciliation.policy")
    policy = MinuteReferenceReconciliationPolicy(
        start=_aware(policy_raw.get("start_inclusive"), "reconciliation.policy.start_inclusive"),
        end=_aware(policy_raw.get("end_exclusive"), "reconciliation.policy.end_exclusive"),
        required_symbol_count=_integer(
            policy_raw.get("required_symbol_count"), "reconciliation.policy.required_symbol_count"
        ),
        minimum_rows_per_symbol=_integer(
            policy_raw.get("minimum_rows_per_symbol"), "reconciliation.policy.minimum_rows_per_symbol"
        ),
        minimum_aligned_overlap_ratio=_number(
            policy_raw.get("minimum_aligned_overlap_ratio"),
            "reconciliation.policy.minimum_aligned_overlap_ratio",
        ),
        maximum_abs_offset_minutes=_integer(
            policy_raw.get("maximum_abs_offset_minutes"),
            "reconciliation.policy.maximum_abs_offset_minutes",
        ),
    )
    if _text(policy_raw.get("policy_id"), "reconciliation.policy.policy_id") != policy.policy_id:
        raise ValueError("reconciliation policy identity mismatch")
    checks = tuple(
        MinuteReferenceSymbolCheck(
            research_symbol=_text(row.get("research_symbol"), "check.research_symbol"),
            broker_symbol=_text(row.get("broker_symbol"), "check.broker_symbol"),
            research_row_count=_integer(row.get("research_row_count"), "check.research_row_count"),
            broker_row_count=_integer(row.get("broker_row_count"), "check.broker_row_count"),
            exact_overlap_count=_integer(row.get("exact_overlap_count"), "check.exact_overlap_count"),
            best_broker_to_research_offset_minutes=_integer(
                row.get("best_broker_to_research_offset_minutes"),
                "check.best_broker_to_research_offset_minutes",
            ),
            aligned_overlap_count=_integer(row.get("aligned_overlap_count"), "check.aligned_overlap_count"),
            aligned_overlap_ratio=_number(row.get("aligned_overlap_ratio"), "check.aligned_overlap_ratio"),
            median_close_relative_difference=(
                None
                if row.get("median_close_relative_difference") is None
                else _number(row.get("median_close_relative_difference"), "check.median_close_relative_difference")
            ),
            maximum_close_relative_difference=(
                None
                if row.get("maximum_close_relative_difference") is None
                else _number(row.get("maximum_close_relative_difference"), "check.maximum_close_relative_difference")
            ),
            research_volume_sum=(
                None if row.get("research_volume_sum") is None else _number(row.get("research_volume_sum"), "check.research_volume_sum")
            ),
            broker_tick_volume_sum=(
                None if row.get("broker_tick_volume_sum") is None else _number(row.get("broker_tick_volume_sum"), "check.broker_tick_volume_sum")
            ),
            broker_real_volume_sum=(
                None if row.get("broker_real_volume_sum") is None else _number(row.get("broker_real_volume_sum"), "check.broker_real_volume_sum")
            ),
        )
        for row in (
            _mapping(item, "reconciliation.symbol_checks[]")
            for item in _sequence(document.get("symbol_checks"), "reconciliation.symbol_checks")
        )
    )
    report = MinuteReferenceReconciliationReport(
        policy=policy,
        source_revision=_text(document.get("source_revision"), "reconciliation.source_revision"),
        source_data_version=_text(
            document.get("source_data_version"), "reconciliation.source_data_version"
        ),
        calendar_id=_text(document.get("calendar_id"), "reconciliation.calendar_id"),
        mt5_probe_id=_text(document.get("mt5_probe_id"), "reconciliation.mt5_probe_id"),
        broker_server=_text(document.get("broker_server"), "reconciliation.broker_server"),
        symbol_checks=checks,
        retrieved_at=_aware(document.get("retrieved_at"), "reconciliation.retrieved_at"),
    )
    if _text(document.get("report_id"), "reconciliation.report_id") != report.report_id:
        raise ValueError("reconciliation report identity mismatch")
    stored_passed = _boolean(document.get("passed"), "reconciliation.passed")
    if stored_passed is not report.passed:
        raise ValueError("reconciliation passed flag does not match content")
    return report


class USSimulationD3CertificationOutcome(StrEnum):
    CERTIFIED_FOR_SIMULATION_ENGINEERING_RESEARCH = (
        "CERTIFIED_FOR_SIMULATION_ENGINEERING_RESEARCH"
    )
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class USSimulationD3CertificationReport:
    policy: USSimulationD3CertificationPolicy
    simulation_universe: USSimulationUniverseBinding
    reconciliation_report_id: str
    core_report: USMinuteCertificationReport
    outcome: USSimulationD3CertificationOutcome
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "finagent.us-simulation-d3-certification-report.v1"

    @property
    def certified(self) -> bool:
        return self.outcome is USSimulationD3CertificationOutcome.CERTIFIED_FOR_SIMULATION_ENGINEERING_RESEARCH

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-d3-certification",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy": self.policy.to_dict(),
            "simulation_universe_report_id": self.simulation_universe.report_id,
            "simulation_universe_id": self.simulation_universe.simulation_universe_id,
            "simulation_universe_count": self.simulation_universe.accepted_mapping_count,
            "reconciliation_report_id": self.reconciliation_report_id,
            "core_report": self.core_report.to_dict(),
            "outcome": self.outcome.value,
            "certified": self.certified,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "simulation_engineering_research_authority": self.certified,
            "supports_us_b0_progression": self.certified,
            "all_day_preflight_in_certification_denominator": False,
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
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def build_us_simulation_d3_certification(
    *,
    source_document: Mapping[str, object],
    d1_document: Mapping[str, object],
    d2_document: Mapping[str, object],
    simulation_universe_document: Mapping[str, object],
    reconciliation_document: Mapping[str, object],
    point_in_time_security_master_available: bool = False,
    policy: USSimulationD3CertificationPolicy = CANONICAL_US_SIMULATION_D3_CERTIFICATION_POLICY,
) -> USSimulationD3CertificationReport:
    universe = validate_us_simulation_universe_document(simulation_universe_document)
    reconciliation = _parse_reconciliation(reconciliation_document)
    bridge_blockers: list[str] = []
    if policy.require_simulation_universe_acceptance and not universe.accepted:
        bridge_blockers.append("simulation_us_i0:universe_not_accepted")
    if not (
        policy.core_policy.minimum_engineering_universe_size
        <= universe.accepted_mapping_count
        <= policy.core_policy.maximum_engineering_universe_size
    ):
        bridge_blockers.append("simulation_us_i0:universe_count_out_of_bounds")
    if reconciliation.mt5_probe_id != universe.candidate_mt5_probe_id:
        bridge_blockers.append("reconciliation:mt5_probe_identity_mismatch")
    if reconciliation.broker_server != universe.broker_server:
        bridge_blockers.append("reconciliation:broker_server_mismatch")
    allowed_pairs = set(universe.selected_pairs)
    observed_pairs = tuple(
        (item.research_symbol, item.broker_symbol) for item in reconciliation.symbol_checks
    )
    if any(pair not in allowed_pairs for pair in observed_pairs):
        bridge_blockers.append("reconciliation:symbol_outside_simulation_universe")

    compatibility_universe = {
        "universe_id": universe.simulation_universe_id,
        "accepted": universe.accepted,
        "accepted_mapping_count": universe.accepted_mapping_count,
    }
    inputs = load_us_minute_certification_inputs(
        source_document=source_document,
        d1_document=d1_document,
        d2_document=d2_document,
        universe_document=compatibility_universe,
        reconciliation_document=reconciliation.to_dict(),
        point_in_time_security_master_available=point_in_time_security_master_available,
    )
    core = evaluate_us_minute_certification(inputs, policy=policy.core_policy)
    blockers = tuple(dict.fromkeys([*bridge_blockers, *core.blockers]))
    limitations = tuple(
        dict.fromkeys(
            [
                *core.limitations,
                "market_data:metaquotes_demo_delayed_reference_without_broker_account",
                "spread:delayed_reference_diagnostic_only",
                "spread:not_live_executable_spread_authority",
                "broker_account:simulation_without_target_broker_account",
                "live_broker:requires_separate_re_admission",
                "universe:simulation_engineering_integration_only",
                "all_day_products:engineering_preflight_only_not_us_research_evidence",
            ]
        )
    )
    outcome = (
        USSimulationD3CertificationOutcome.REJECTED
        if blockers
        else USSimulationD3CertificationOutcome.CERTIFIED_FOR_SIMULATION_ENGINEERING_RESEARCH
    )
    return USSimulationD3CertificationReport(
        policy=policy,
        simulation_universe=universe,
        reconciliation_report_id=reconciliation.report_id,
        core_report=core,
        outcome=outcome,
        blockers=blockers,
        limitations=limitations,
    )


class USSimulationD3ReviewDecision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class USSimulationD3Review:
    certification: USSimulationD3CertificationReport
    reviewer_id: str
    reviewed_at: datetime
    decision: USSimulationD3ReviewDecision
    notes: str
    schema_version: str = "finagent.us-simulation-d3-review.v1"

    def __post_init__(self) -> None:
        reviewer = self.reviewer_id.strip()
        notes = self.notes.strip()
        if not reviewer:
            raise ValueError("reviewer_id must be non-empty")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("reviewed_at must be timezone-aware")
        if self.decision is USSimulationD3ReviewDecision.ACCEPT and not self.certification.certified:
            raise ValueError("review cannot upgrade a rejected certification")
        object.__setattr__(self, "reviewer_id", reviewer)
        object.__setattr__(self, "notes", notes)
        object.__setattr__(self, "reviewed_at", self.reviewed_at.astimezone(UTC))

    @property
    def accepted(self) -> bool:
        return self.decision is USSimulationD3ReviewDecision.ACCEPT and self.certification.certified

    @property
    def review_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-d3-review",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "certification_report_id": self.certification.report_id,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at.isoformat(),
            "decision": self.decision.value,
            "notes": self.notes,
            "accepted": self.accepted,
            "supports_us_b0_progression": self.accepted,
            "simulation_engineering_research_authority": self.accepted,
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
        if include_id:
            payload["review_id"] = self.review_id
        return payload
