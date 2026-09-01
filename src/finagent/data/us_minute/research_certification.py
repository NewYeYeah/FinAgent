from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


def _canonical_hash(payload: Mapping[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _optional_mapping(value: object, field_name: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _mapping(value, field_name)


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be integer-like, not boolean")
    if isinstance(value, (int, float, str)):
        return int(value)
    raise TypeError(f"{field_name} must be integer-like")


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field_name}[]") for item in _sequence(value, field_name))


class USMinuteCertificationOutcome(str, Enum):
    CERTIFIED_FOR_ENGINEERING_RESEARCH = "CERTIFIED_FOR_ENGINEERING_RESEARCH"
    CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS = (
        "CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS"
    )
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class USMinuteCertificationPolicy:
    expected_source_revision: str = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"
    expected_inventory_id: str = "us-minute-inventory-c2cbf682b456f97eb613ed65"
    expected_calendar_id: str = "trading-calendar-03a9c29f566d6634aedbbbdc"
    minimum_engineering_universe_size: int = 20
    maximum_engineering_universe_size: int = 30
    required_scenarios: tuple[str, ...] = ("half_day", "pre_dst", "post_dst")
    require_reconciliation: bool = True
    require_d1_replay_match: bool = True
    require_action_authority_boundary: bool = True
    require_no_unknown_label_unavailability: bool = True
    schema_version: str = "finagent.us-minute-certification-policy.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "expected_source_revision",
            "expected_inventory_id",
            "expected_calendar_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.minimum_engineering_universe_size <= 0:
            raise ValueError("minimum_engineering_universe_size must be positive")
        if self.maximum_engineering_universe_size < self.minimum_engineering_universe_size:
            raise ValueError(
                "maximum_engineering_universe_size must be >= minimum_engineering_universe_size"
            )
        scenarios = tuple(dict.fromkeys(item.strip() for item in self.required_scenarios))
        if not scenarios or any(not item for item in scenarios):
            raise ValueError("required_scenarios must contain non-empty unique values")
        object.__setattr__(self, "required_scenarios", scenarios)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-minute-cert-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "expected_source_revision": self.expected_source_revision,
            "expected_inventory_id": self.expected_inventory_id,
            "expected_calendar_id": self.expected_calendar_id,
            "minimum_engineering_universe_size": self.minimum_engineering_universe_size,
            "maximum_engineering_universe_size": self.maximum_engineering_universe_size,
            "required_scenarios": list(self.required_scenarios),
            "require_reconciliation": self.require_reconciliation,
            "require_d1_replay_match": self.require_d1_replay_match,
            "require_action_authority_boundary": self.require_action_authority_boundary,
            "require_no_unknown_label_unavailability": (
                self.require_no_unknown_label_unavailability
            ),
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_US_MINUTE_CERTIFICATION_POLICY = USMinuteCertificationPolicy()


@dataclass(frozen=True, slots=True)
class USMinuteCertificationInputs:
    source_admission_id: str
    source_revision: str
    source_authority_status: str
    local_research_admitted: bool
    source_certification_passed: bool
    inventory_id: str
    d1_smoke_report_id: str
    d1_passed: bool
    d1_blockers: tuple[str, ...]
    d1_replay_match: bool
    d1_asset_count: int
    d1_partition_count: int
    d2_smoke_report_id: str | None
    d2_passed: bool
    d2_blockers: tuple[str, ...]
    d2_calendar_id: str | None
    d2_scenario_names: tuple[str, ...]
    d2_unknown_label_unavailability_count: int
    d2_action_authority_passed: bool
    engineering_universe_id: str | None
    engineering_universe_accepted: bool
    engineering_universe_count: int
    point_in_time_security_master_available: bool
    reconciliation_report_id: str | None
    reconciliation_passed: bool
    reconciliation_blockers: tuple[str, ...]
    schema_version: str = "finagent.us-minute-certification-inputs.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_admission_id",
            "source_revision",
            "source_authority_status",
            "inventory_id",
            "d1_smoke_report_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "d1_asset_count",
            "d1_partition_count",
            "d2_unknown_label_unavailability_count",
            "engineering_universe_count",
        ):
            if int(getattr(self, field_name)) < 0:
                raise ValueError(f"{field_name} must be >= 0")
        object.__setattr__(self, "d1_blockers", tuple(dict.fromkeys(self.d1_blockers)))
        object.__setattr__(self, "d2_blockers", tuple(dict.fromkeys(self.d2_blockers)))
        object.__setattr__(
            self,
            "d2_scenario_names",
            tuple(dict.fromkeys(self.d2_scenario_names)),
        )
        object.__setattr__(
            self,
            "reconciliation_blockers",
            tuple(dict.fromkeys(self.reconciliation_blockers)),
        )

    @property
    def inputs_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-minute-cert-inputs")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "source_admission_id": self.source_admission_id,
            "source_revision": self.source_revision,
            "source_authority_status": self.source_authority_status,
            "local_research_admitted": self.local_research_admitted,
            "source_certification_passed": self.source_certification_passed,
            "inventory_id": self.inventory_id,
            "d1_smoke_report_id": self.d1_smoke_report_id,
            "d1_passed": self.d1_passed,
            "d1_blockers": list(self.d1_blockers),
            "d1_replay_match": self.d1_replay_match,
            "d1_asset_count": self.d1_asset_count,
            "d1_partition_count": self.d1_partition_count,
            "d2_smoke_report_id": self.d2_smoke_report_id,
            "d2_passed": self.d2_passed,
            "d2_blockers": list(self.d2_blockers),
            "d2_calendar_id": self.d2_calendar_id,
            "d2_scenario_names": list(self.d2_scenario_names),
            "d2_unknown_label_unavailability_count": (
                self.d2_unknown_label_unavailability_count
            ),
            "d2_action_authority_passed": self.d2_action_authority_passed,
            "engineering_universe_id": self.engineering_universe_id,
            "engineering_universe_accepted": self.engineering_universe_accepted,
            "engineering_universe_count": self.engineering_universe_count,
            "point_in_time_security_master_available": (
                self.point_in_time_security_master_available
            ),
            "reconciliation_report_id": self.reconciliation_report_id,
            "reconciliation_passed": self.reconciliation_passed,
            "reconciliation_blockers": list(self.reconciliation_blockers),
        }
        if include_id:
            payload["inputs_id"] = self.inputs_id
        return payload


@dataclass(frozen=True, slots=True)
class USMinuteCertificationReport:
    policy: USMinuteCertificationPolicy
    inputs: USMinuteCertificationInputs
    outcome: USMinuteCertificationOutcome
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "finagent.us-minute-certification-report.v1"

    @property
    def certified(self) -> bool:
        return self.outcome is not USMinuteCertificationOutcome.REJECTED

    @property
    def report_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-minute-research-cert")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy": self.policy.to_dict(),
            "inputs": self.inputs.to_dict(),
            "outcome": self.outcome.value,
            "certified": self.certified,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["report_id"] = self.report_id
        return payload


def _d2_action_authority_passed(action: Mapping[str, object] | None) -> bool:
    if action is None:
        return False
    required = (
        "same_session_raw_allowed",
        "cross_session_raw_denied",
        "split_adjusted_denied",
        "total_return_adjusted_denied",
    )
    return all(action.get(field_name) is True for field_name in required)


def _d2_unknown_label_count(scenarios: Sequence[object]) -> int:
    total = 0
    for item in scenarios:
        scenario = _mapping(item, "d2.scenarios[]")
        labels = _mapping(scenario.get("labels"), "d2.scenarios[].labels")
        total += _integer(
            labels.get("other_unavailable_count", 0),
            "d2.scenarios[].labels.other_unavailable_count",
        )
    return total


def load_us_minute_certification_inputs(
    *,
    source_document: Mapping[str, object],
    d1_document: Mapping[str, object],
    d2_document: Mapping[str, object] | None,
    universe_document: Mapping[str, object] | None,
    reconciliation_document: Mapping[str, object] | None,
    point_in_time_security_master_available: bool = False,
) -> USMinuteCertificationInputs:
    admission = _mapping(source_document.get("admission"), "source.admission")
    source_identity = _mapping(
        admission.get("source_identity"),
        "source.admission.source_identity",
    )
    source_certification = _mapping(
        source_document.get("certification"),
        "source.certification",
    )

    d2_scenarios_raw: Sequence[object] = ()
    d2_action: Mapping[str, object] | None = None
    if d2_document is not None:
        d2_scenarios_raw = _sequence(d2_document.get("scenarios", ()), "d2.scenarios")
        d2_action = _optional_mapping(
            d2_document.get("action_authority"),
            "d2.action_authority",
        )

    reconciliation_blockers: tuple[str, ...] = ()
    if reconciliation_document is not None:
        reconciliation_blockers = _strings(
            reconciliation_document.get("blockers", ()),
            "reconciliation.blockers",
        )

    return USMinuteCertificationInputs(
        source_admission_id=_text(
            admission.get("admission_id"),
            "source.admission.admission_id",
        ),
        source_revision=_text(
            source_identity.get("revision"),
            "source.admission.source_identity.revision",
        ),
        source_authority_status=_text(
            admission.get("source_authority_status"),
            "source.admission.source_authority_status",
        ),
        local_research_admitted=_boolean(
            source_document.get("local_research_admitted"),
            "source.local_research_admitted",
        ),
        source_certification_passed=_boolean(
            source_certification.get("passed"),
            "source.certification.passed",
        ),
        inventory_id=_text(admission.get("inventory_id"), "source.admission.inventory_id"),
        d1_smoke_report_id=_text(d1_document.get("report_id"), "d1.report_id"),
        d1_passed=_boolean(d1_document.get("passed"), "d1.passed"),
        d1_blockers=_strings(d1_document.get("blockers", ()), "d1.blockers"),
        d1_replay_match=_boolean(d1_document.get("replay_match"), "d1.replay_match"),
        d1_asset_count=_integer(d1_document.get("asset_count"), "d1.asset_count"),
        d1_partition_count=_integer(
            d1_document.get("partition_count"),
            "d1.partition_count",
        ),
        d2_smoke_report_id=(
            _text(d2_document.get("report_id"), "d2.report_id")
            if d2_document is not None
            else None
        ),
        d2_passed=(
            _boolean(d2_document.get("passed"), "d2.passed")
            if d2_document is not None
            else False
        ),
        d2_blockers=(
            _strings(d2_document.get("blockers", ()), "d2.blockers")
            if d2_document is not None
            else ()
        ),
        d2_calendar_id=(
            _text(d2_document.get("calendar_id"), "d2.calendar_id")
            if d2_document is not None
            else None
        ),
        d2_scenario_names=tuple(
            _text(
                _mapping(item, "d2.scenarios[]").get("name"),
                "d2.scenarios[].name",
            )
            for item in d2_scenarios_raw
        ),
        d2_unknown_label_unavailability_count=_d2_unknown_label_count(d2_scenarios_raw),
        d2_action_authority_passed=_d2_action_authority_passed(d2_action),
        engineering_universe_id=(
            _optional_text(universe_document.get("universe_id"))
            if universe_document is not None
            else None
        ),
        engineering_universe_accepted=(
            _boolean(universe_document.get("accepted"), "universe.accepted")
            if universe_document is not None
            else False
        ),
        engineering_universe_count=(
            _integer(
                universe_document.get("accepted_mapping_count", 0),
                "universe.accepted_mapping_count",
            )
            if universe_document is not None
            else 0
        ),
        point_in_time_security_master_available=point_in_time_security_master_available,
        reconciliation_report_id=(
            _optional_text(reconciliation_document.get("report_id"))
            if reconciliation_document is not None
            else None
        ),
        reconciliation_passed=(
            _boolean(reconciliation_document.get("passed"), "reconciliation.passed")
            if reconciliation_document is not None
            else False
        ),
        reconciliation_blockers=reconciliation_blockers,
    )


def evaluate_us_minute_certification(
    inputs: USMinuteCertificationInputs,
    *,
    policy: USMinuteCertificationPolicy = DEFAULT_US_MINUTE_CERTIFICATION_POLICY,
) -> USMinuteCertificationReport:
    blockers: list[str] = []
    if inputs.source_revision != policy.expected_source_revision:
        blockers.append("source:revision_mismatch")
    if inputs.inventory_id != policy.expected_inventory_id:
        blockers.append("source:inventory_mismatch")
    if not inputs.local_research_admitted:
        blockers.append("source:local_research_not_admitted")
    if not inputs.source_certification_passed:
        blockers.append("source:certification_failed")

    if not inputs.d1_passed:
        blockers.append("us_d1:smoke_failed")
    blockers.extend(f"us_d1:{item}" for item in inputs.d1_blockers)
    if policy.require_d1_replay_match and not inputs.d1_replay_match:
        blockers.append("us_d1:replay_mismatch")
    if inputs.d1_asset_count <= 0 or inputs.d1_partition_count <= 0:
        blockers.append("us_d1:empty_bounded_scan")

    if inputs.d2_smoke_report_id is None:
        blockers.append("us_d2:smoke_missing")
    elif not inputs.d2_passed:
        blockers.append("us_d2:smoke_failed")
    blockers.extend(f"us_d2:{item}" for item in inputs.d2_blockers)
    if inputs.d2_calendar_id != policy.expected_calendar_id:
        blockers.append("us_d2:calendar_identity_mismatch")
    missing_scenarios = sorted(
        set(policy.required_scenarios).difference(inputs.d2_scenario_names)
    )
    blockers.extend(f"us_d2:scenario_missing:{item}" for item in missing_scenarios)
    if (
        policy.require_no_unknown_label_unavailability
        and inputs.d2_unknown_label_unavailability_count != 0
    ):
        blockers.append("us_d2:unknown_label_unavailability")
    if policy.require_action_authority_boundary and not inputs.d2_action_authority_passed:
        blockers.append("us_d2:corporate_action_authority_failed")

    if inputs.engineering_universe_id is None:
        blockers.append("us_i0:engineering_universe_missing")
    if not inputs.engineering_universe_accepted:
        blockers.append("us_i0:engineering_universe_not_accepted")
    if inputs.engineering_universe_count < policy.minimum_engineering_universe_size:
        blockers.append("us_i0:engineering_universe_below_minimum")
    if inputs.engineering_universe_count > policy.maximum_engineering_universe_size:
        blockers.append("us_i0:engineering_universe_above_maximum")

    if policy.require_reconciliation:
        if inputs.reconciliation_report_id is None:
            blockers.append("reconciliation:report_missing")
        elif not inputs.reconciliation_passed:
            blockers.append("reconciliation:failed")
        blockers.extend(
            f"reconciliation:{item}" for item in inputs.reconciliation_blockers
        )

    limitations: list[str] = [
        "scope:local_non_redistributed_research_only",
        "prices:intraday_raw_split_unadjusted",
        "corporate_actions:adjusted_transform_unavailable",
        "universe:engineering_integration_universe",
    ]
    if inputs.source_authority_status != "accepted_for_research":
        limitations.append(f"source_authority:{inputs.source_authority_status}")
    if not inputs.point_in_time_security_master_available:
        limitations.extend(
            (
                "identity:no_point_in_time_security_master",
                "claim:no_survivorship_unbiased_market_wide_alpha",
            )
        )

    unique_blockers = tuple(dict.fromkeys(blockers))
    unique_limitations = tuple(dict.fromkeys(limitations))
    if unique_blockers:
        outcome = USMinuteCertificationOutcome.REJECTED
    elif (
        inputs.point_in_time_security_master_available
        and inputs.source_authority_status == "accepted_for_research"
    ):
        outcome = USMinuteCertificationOutcome.CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS
    else:
        outcome = USMinuteCertificationOutcome.CERTIFIED_FOR_ENGINEERING_RESEARCH

    return USMinuteCertificationReport(
        policy=policy,
        inputs=inputs,
        outcome=outcome,
        blockers=unique_blockers,
        limitations=unique_limitations,
    )
