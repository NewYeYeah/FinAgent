from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.data.us_minute.simulation_certification import (
    USSimulationD3Review,
    USSimulationD3ReviewDecision,
    build_us_simulation_d3_certification,
    validate_canonical_us_simulation_d3_certification_policy,
    validate_us_simulation_universe_document,
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


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _aware(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _code_sha(value: object) -> str:
    sha = _text(value, "code_fence_sha").lower()
    if len(sha) != 40 or any(character not in "0123456789abcdef" for character in sha):
        raise ValueError("code_fence_sha must be a 40-character hexadecimal Git SHA")
    return sha


@dataclass(frozen=True, slots=True)
class USSimulationD3CompletionBundle:
    code_fence_sha: str
    simulation_universe_report_id: str
    simulation_universe_id: str
    simulation_universe_count: int
    broker_server: str
    reconciliation_report_id: str
    certification_policy_id: str
    certification_report_id: str
    review_id: str
    reviewer_id: str
    assembled_at: datetime
    schema_version: str = "finagent.us-simulation-d3-completion-bundle.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "code_fence_sha", _code_sha(self.code_fence_sha))
        if self.simulation_universe_count < 20 or self.simulation_universe_count > 30:
            raise ValueError("completion requires simulation universe count within 20..30")
        for field_name in (
            "simulation_universe_report_id",
            "simulation_universe_id",
            "broker_server",
            "reconciliation_report_id",
            "certification_policy_id",
            "certification_report_id",
            "review_id",
            "reviewer_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if self.assembled_at.tzinfo is None or self.assembled_at.utcoffset() is None:
            raise ValueError("assembled_at must be timezone-aware")
        object.__setattr__(self, "assembled_at", self.assembled_at.astimezone(UTC))

    @property
    def bundle_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-simulation-d3-completion",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "code_fence_sha": self.code_fence_sha,
            "simulation_universe_report_id": self.simulation_universe_report_id,
            "simulation_universe_id": self.simulation_universe_id,
            "simulation_universe_count": self.simulation_universe_count,
            "broker_server": self.broker_server,
            "reconciliation_report_id": self.reconciliation_report_id,
            "certification_policy_id": self.certification_policy_id,
            "certification_report_id": self.certification_report_id,
            "review_id": self.review_id,
            "reviewer_id": self.reviewer_id,
            "assembled_at": self.assembled_at.isoformat(),
            "governance_ready": True,
            "supports_us_b0_progression": True,
            "simulation_engineering_research_authority": True,
            "live_market_data_authority": False,
            "live_executable_spread_authority": False,
            "execution_authority": False,
            "order_authority": False,
            "live_capital_authority": False,
            "status_authority": False,
            "stage_exit_authority": False,
        }
        if include_id:
            payload["bundle_id"] = self.bundle_id
        return payload


def validate_us_simulation_d3_completion_bundle(
    document: Mapping[str, object],
) -> USSimulationD3CompletionBundle:
    if _text(document.get("schema_version"), "completion.schema_version") != (
        "finagent.us-simulation-d3-completion-bundle.v1"
    ):
        raise ValueError("unsupported US-D3 completion bundle schema")
    for field_name in (
        "governance_ready",
        "supports_us_b0_progression",
        "simulation_engineering_research_authority",
    ):
        if not _boolean(document.get(field_name), f"completion.{field_name}"):
            raise ValueError(f"completion bundle does not assert {field_name}")
    for field_name in (
        "live_market_data_authority",
        "live_executable_spread_authority",
        "execution_authority",
        "order_authority",
        "live_capital_authority",
        "status_authority",
        "stage_exit_authority",
    ):
        if _boolean(document.get(field_name), f"completion.{field_name}"):
            raise ValueError(f"completion bundle unexpectedly asserts {field_name}")
    bundle = USSimulationD3CompletionBundle(
        code_fence_sha=_code_sha(document.get("code_fence_sha")),
        simulation_universe_report_id=_text(
            document.get("simulation_universe_report_id"),
            "completion.simulation_universe_report_id",
        ),
        simulation_universe_id=_text(
            document.get("simulation_universe_id"), "completion.simulation_universe_id"
        ),
        simulation_universe_count=int(document.get("simulation_universe_count", 0)),
        broker_server=_text(document.get("broker_server"), "completion.broker_server"),
        reconciliation_report_id=_text(
            document.get("reconciliation_report_id"), "completion.reconciliation_report_id"
        ),
        certification_policy_id=_text(
            document.get("certification_policy_id"), "completion.certification_policy_id"
        ),
        certification_report_id=_text(
            document.get("certification_report_id"), "completion.certification_report_id"
        ),
        review_id=_text(document.get("review_id"), "completion.review_id"),
        reviewer_id=_text(document.get("reviewer_id"), "completion.reviewer_id"),
        assembled_at=_aware(document.get("assembled_at"), "completion.assembled_at"),
    )
    if _text(document.get("bundle_id"), "completion.bundle_id") != bundle.bundle_id:
        raise ValueError("US-D3 completion bundle identity mismatch")
    return bundle


def build_us_simulation_d3_completion_bundle(
    *,
    source_document: Mapping[str, object],
    d1_document: Mapping[str, object],
    d2_document: Mapping[str, object],
    simulation_universe_document: Mapping[str, object],
    reconciliation_document: Mapping[str, object],
    policy_document: Mapping[str, object],
    certification_document: Mapping[str, object],
    review_document: Mapping[str, object],
    code_fence_sha: str,
    assembled_at: datetime,
    point_in_time_security_master_available: bool = False,
) -> USSimulationD3CompletionBundle:
    policy = validate_canonical_us_simulation_d3_certification_policy(policy_document)
    rebuilt = build_us_simulation_d3_certification(
        source_document=source_document,
        d1_document=d1_document,
        d2_document=d2_document,
        simulation_universe_document=simulation_universe_document,
        reconciliation_document=reconciliation_document,
        point_in_time_security_master_available=point_in_time_security_master_available,
        policy=policy,
    )
    if certification_document != rebuilt.to_dict():
        raise ValueError("stored simulation D3 certification differs from reconstruction")
    if not rebuilt.certified or not rebuilt.supports_us_b0_progression:
        raise ValueError("US-D3 completion requires a passing machine certification")

    review = USSimulationD3Review(
        certification=rebuilt,
        reviewer_id=_text(review_document.get("reviewer_id"), "review.reviewer_id"),
        reviewed_at=_aware(review_document.get("reviewed_at"), "review.reviewed_at"),
        decision=USSimulationD3ReviewDecision(
            _text(review_document.get("decision"), "review.decision")
        ),
        notes=str(review_document.get("notes", "")),
    )
    if review_document != review.to_dict():
        raise ValueError("stored simulation D3 review differs from reconstruction")
    if not review.accepted:
        raise ValueError("US-D3 completion requires an accepted independent review")

    universe = validate_us_simulation_universe_document(simulation_universe_document)
    if rebuilt.simulation_universe.report_id != universe.report_id:
        raise ValueError("certification/simulation universe report identity mismatch")
    if rebuilt.simulation_universe.simulation_universe_id != universe.simulation_universe_id:
        raise ValueError("certification/simulation universe identity mismatch")

    return USSimulationD3CompletionBundle(
        code_fence_sha=code_fence_sha,
        simulation_universe_report_id=universe.report_id,
        simulation_universe_id=universe.simulation_universe_id,
        simulation_universe_count=universe.accepted_mapping_count,
        broker_server=universe.broker_server,
        reconciliation_report_id=rebuilt.reconciliation_report_id,
        certification_policy_id=policy.policy_id,
        certification_report_id=rebuilt.report_id,
        review_id=review.review_id,
        reviewer_id=review.reviewer_id,
        assembled_at=assembled_at,
    )
