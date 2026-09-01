from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.domain.market_bars import BarInterval


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


@dataclass(frozen=True, slots=True)
class D2ResampleSmokeCheck:
    interval: BarInterval
    row_count: int
    complete_row_count: int
    incomplete_row_count: int
    minimum_coverage_ratio: float | None
    materialization_id: str
    content_sha256: str
    schema_version: str = "finagent.us-d2-resample-smoke-check.v1"

    def __post_init__(self) -> None:
        if self.interval not in {
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_15,
            BarInterval.MINUTE_30,
        }:
            raise ValueError("D2 resample smoke supports only 5m/15m/30m")
        if min(self.row_count, self.complete_row_count, self.incomplete_row_count) < 0:
            raise ValueError("resample smoke counts must be >= 0")
        if self.complete_row_count + self.incomplete_row_count != self.row_count:
            raise ValueError("complete + incomplete rows must equal resample row_count")
        if self.minimum_coverage_ratio is not None and not 0 < self.minimum_coverage_ratio <= 1:
            raise ValueError("minimum_coverage_ratio must be in (0, 1]")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def passed(self) -> bool:
        return self.row_count > 0 and self.minimum_coverage_ratio is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "interval": self.interval.value,
            "row_count": self.row_count,
            "complete_row_count": self.complete_row_count,
            "incomplete_row_count": self.incomplete_row_count,
            "minimum_coverage_ratio": self.minimum_coverage_ratio,
            "materialization_id": self.materialization_id,
            "content_sha256": self.content_sha256,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class D2LabelSmokeCheck:
    row_count: int
    available_row_count: int
    target_crosses_session_count: int
    target_minute_missing_count: int
    other_unavailable_count: int
    materialization_id: str
    content_sha256: str
    label_plan_id: str
    label_data_version: str
    schema_version: str = "finagent.us-d2-label-smoke-check.v1"

    def __post_init__(self) -> None:
        counts = (
            self.row_count,
            self.available_row_count,
            self.target_crosses_session_count,
            self.target_minute_missing_count,
            self.other_unavailable_count,
        )
        if min(counts) < 0:
            raise ValueError("label smoke counts must be >= 0")
        unavailable = (
            self.target_crosses_session_count
            + self.target_minute_missing_count
            + self.other_unavailable_count
        )
        if self.available_row_count + unavailable != self.row_count:
            raise ValueError("available + unavailable label rows must equal row_count")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def passed(self) -> bool:
        return (
            self.row_count > 0
            and self.available_row_count > 0
            and self.target_crosses_session_count > 0
            and self.other_unavailable_count == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_count": self.row_count,
            "available_row_count": self.available_row_count,
            "target_crosses_session_count": self.target_crosses_session_count,
            "target_minute_missing_count": self.target_minute_missing_count,
            "other_unavailable_count": self.other_unavailable_count,
            "materialization_id": self.materialization_id,
            "content_sha256": self.content_sha256,
            "label_plan_id": self.label_plan_id,
            "label_data_version": self.label_data_version,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class D2ScenarioSmokeCheck:
    name: str
    start: datetime
    end: datetime
    expected_regular_minutes_per_asset: int
    asset_count: int
    regular_1m_row_count: int
    resamples: tuple[D2ResampleSmokeCheck, ...]
    labels: D2LabelSmokeCheck
    schema_version: str = "finagent.us-d2-scenario-smoke-check.v1"

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("scenario name must be non-empty")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("scenario timestamps must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("scenario end must be later than start")
        if self.expected_regular_minutes_per_asset <= 0 or self.asset_count <= 0:
            raise ValueError("scenario expected minutes/assets must be positive")
        if self.regular_1m_row_count < 0:
            raise ValueError("regular_1m_row_count must be >= 0")
        intervals = tuple(item.interval for item in self.resamples)
        if intervals != (
            BarInterval.MINUTE_5,
            BarInterval.MINUTE_15,
            BarInterval.MINUTE_30,
        ):
            raise ValueError("scenario resamples must be exactly 5m, 15m, 30m")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "start", self.start.astimezone(UTC))
        object.__setattr__(self, "end", self.end.astimezone(UTC))

    @property
    def expected_regular_row_count(self) -> int:
        return self.expected_regular_minutes_per_asset * self.asset_count

    @property
    def regular_row_coverage_ratio(self) -> float:
        return self.regular_1m_row_count / self.expected_regular_row_count

    @property
    def passed(self) -> bool:
        return (
            self.regular_1m_row_count > 0
            and all(item.passed for item in self.resamples)
            and self.labels.passed
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "expected_regular_minutes_per_asset": self.expected_regular_minutes_per_asset,
            "asset_count": self.asset_count,
            "expected_regular_row_count": self.expected_regular_row_count,
            "regular_1m_row_count": self.regular_1m_row_count,
            "regular_row_coverage_ratio": self.regular_row_coverage_ratio,
            "resamples": [item.to_dict() for item in self.resamples],
            "labels": self.labels.to_dict(),
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class D2ActionAuthoritySmokeCheck:
    coverage_id: str
    same_session_raw_allowed: bool
    cross_session_raw_denied: bool
    split_adjusted_denied: bool
    total_return_adjusted_denied: bool
    schema_version: str = "finagent.us-d2-action-authority-smoke-check.v1"

    @property
    def passed(self) -> bool:
        return (
            self.same_session_raw_allowed
            and self.cross_session_raw_denied
            and self.split_adjusted_denied
            and self.total_return_adjusted_denied
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "coverage_id": self.coverage_id,
            "same_session_raw_allowed": self.same_session_raw_allowed,
            "cross_session_raw_denied": self.cross_session_raw_denied,
            "split_adjusted_denied": self.split_adjusted_denied,
            "total_return_adjusted_denied": self.total_return_adjusted_denied,
            "passed": self.passed,
        }


@dataclass(frozen=True, slots=True)
class D2TransformSmokePolicy:
    calendar_id: str
    minimum_assets: int = 4
    required_scenarios: tuple[str, ...] = ("half_day", "pre_dst", "post_dst")
    schema_version: str = "finagent.us-d2-transform-smoke-policy.v1"

    def __post_init__(self) -> None:
        calendar_id = self.calendar_id.strip()
        scenarios = tuple(dict.fromkeys(item.strip() for item in self.required_scenarios if item.strip()))
        if not calendar_id or self.minimum_assets < 1 or not scenarios:
            raise ValueError("D2 smoke policy requires calendar, assets and scenarios")
        object.__setattr__(self, "calendar_id", calendar_id)
        object.__setattr__(self, "required_scenarios", scenarios)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-d2-transform-smoke-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calendar_id": self.calendar_id,
            "minimum_assets": self.minimum_assets,
            "required_scenarios": list(self.required_scenarios),
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class D2TransformSmokeReport:
    policy: D2TransformSmokePolicy
    calendar_id: str
    manifest_id: str
    source_data_version: str
    assets: tuple[str, ...]
    scenarios: tuple[D2ScenarioSmokeCheck, ...]
    action_authority: D2ActionAuthoritySmokeCheck
    ran_at: datetime
    schema_version: str = "finagent.us-d2-transform-smoke-report.v1"

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self.calendar_id != self.policy.calendar_id:
            blockers.append("calendar:identity_mismatch")
        if len(self.assets) < self.policy.minimum_assets:
            blockers.append("assets:insufficient")
        observed = {item.name for item in self.scenarios}
        for name in self.policy.required_scenarios:
            if name not in observed:
                blockers.append(f"scenario:{name}:missing")
        for scenario in self.scenarios:
            if not scenario.passed:
                blockers.append(f"scenario:{scenario.name}:failed")
        if not self.action_authority.passed:
            blockers.append("corporate_action_authority:failed")
        return tuple(blockers)

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy.policy_id,
            "calendar_id": self.calendar_id,
            "manifest_id": self.manifest_id,
            "source_data_version": self.source_data_version,
            "assets": list(self.assets),
            "scenarios": [item.to_dict() for item in self.scenarios],
            "action_authority": self.action_authority.to_dict(),
            "passed": self.passed,
            "blockers": list(self.blockers),
        }
        return _canonical_hash(payload, prefix="us-d2-transform-smoke")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "ran_at": self.ran_at.astimezone(UTC).isoformat(),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "policy": self.policy.to_dict(),
            "calendar_id": self.calendar_id,
            "manifest_id": self.manifest_id,
            "source_data_version": self.source_data_version,
            "assets": list(self.assets),
            "scenarios": [item.to_dict() for item in self.scenarios],
            "action_authority": self.action_authority.to_dict(),
        }
