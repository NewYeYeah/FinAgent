from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from finagent.domain.corporate_actions import CorporateActionEvent, CorporateActionEventType
from finagent.domain.labels import ResearchPriceBasis

US_MINUTE_SOURCE_ID = "hf-mito0o852-ohlcv-1m"
US_MINUTE_SOURCE_REVISION = "776328445b7ac6e7815ef3a483e9c8ded1eb6d56"


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


class CorporateActionCoverageStatus(str, Enum):
    UNAVAILABLE = "unavailable"
    COMPLETE_FOR_DECLARED_TYPES = "complete_for_declared_types"


@dataclass(frozen=True, slots=True)
class CorporateActionCoverageEvidence:
    market_id: str
    assets: tuple[str, ...]
    coverage_start: datetime
    coverage_end: datetime
    source: str
    source_revision: str
    status: CorporateActionCoverageStatus
    covered_types: frozenset[CorporateActionEventType] = frozenset()
    events: tuple[CorporateActionEvent, ...] = ()
    limitations: tuple[str, ...] = ()
    schema_version: str = "finagent.corporate-action-coverage-evidence.v1"

    def __post_init__(self) -> None:
        market_id = self.market_id.strip()
        source = self.source.strip()
        source_revision = self.source_revision.strip()
        assets = tuple(sorted({asset.strip() for asset in self.assets if asset.strip()}))
        coverage_start = _aware_utc(self.coverage_start, "coverage_start")
        coverage_end = _aware_utc(self.coverage_end, "coverage_end")
        limitations = tuple(dict.fromkeys(item.strip() for item in self.limitations if item.strip()))
        events = tuple(
            sorted(
                self.events,
                key=lambda event: (event.effective_at, event.asset, event.event_id),
            )
        )
        if not market_id or not source or not source_revision:
            raise ValueError("market_id/source/source_revision must be non-empty")
        if not assets:
            raise ValueError("corporate-action coverage requires at least one asset")
        if coverage_end <= coverage_start:
            raise ValueError("coverage_end must be later than coverage_start")
        if self.status is CorporateActionCoverageStatus.UNAVAILABLE:
            if self.covered_types or events:
                raise ValueError("unavailable corporate-action coverage cannot declare types/events")
        elif not self.covered_types:
            raise ValueError("complete coverage must declare at least one covered action type")
        for event in events:
            effective = _aware_utc(event.effective_at, "event.effective_at")
            if event.asset not in assets:
                raise ValueError(f"corporate-action event asset is outside coverage: {event.asset}")
            if event.action_type not in self.covered_types:
                raise ValueError(
                    f"event type {event.action_type.value} is not declared covered"
                )
            if not coverage_start < effective <= coverage_end:
                raise ValueError("corporate-action event falls outside coverage interval")
        object.__setattr__(self, "market_id", market_id)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "source_revision", source_revision)
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "coverage_start", coverage_start)
        object.__setattr__(self, "coverage_end", coverage_end)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "limitations", limitations)
        object.__setattr__(self, "covered_types", frozenset(self.covered_types))

    @property
    def coverage_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="corporate-action-coverage")

    def covers_interval(self, start: datetime, end: datetime) -> bool:
        start_utc = _aware_utc(start, "start")
        end_utc = _aware_utc(end, "end")
        if end_utc <= start_utc:
            raise ValueError("end must be later than start")
        return self.coverage_start <= start_utc and end_utc <= self.coverage_end

    def events_between(
        self,
        asset: str,
        start: datetime,
        end: datetime,
    ) -> tuple[CorporateActionEvent, ...]:
        asset_key = asset.strip()
        if asset_key not in self.assets:
            raise ValueError(f"asset is outside corporate-action coverage: {asset_key}")
        start_utc = _aware_utc(start, "start")
        end_utc = _aware_utc(end, "end")
        if end_utc <= start_utc:
            raise ValueError("end must be later than start")
        return tuple(
            event
            for event in self.events
            if event.asset == asset_key and start_utc < event.effective_at.astimezone(UTC) <= end_utc
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "market_id": self.market_id,
            "assets": list(self.assets),
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "source": self.source,
            "source_revision": self.source_revision,
            "status": self.status.value,
            "covered_types": sorted(item.value for item in self.covered_types),
            "events": [event.to_dict() for event in self.events],
            "limitations": list(self.limitations),
        }
        if include_id:
            payload["coverage_id"] = self.coverage_id
        return payload


@dataclass(frozen=True, slots=True)
class CorporateActionResearchPolicy:
    same_session_raw_without_action_coverage: bool = True
    raw_cross_session_required_types: frozenset[CorporateActionEventType] = frozenset(
        {
            CorporateActionEventType.SPLIT,
            CorporateActionEventType.CASH_DIVIDEND,
            CorporateActionEventType.CASH_EVENT,
        }
    )
    split_adjusted_transform_implemented: bool = False
    total_return_adjusted_transform_implemented: bool = False
    schema_version: str = "finagent.corporate-action-research-policy.v1"

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="corporate-action-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "same_session_raw_without_action_coverage": (
                self.same_session_raw_without_action_coverage
            ),
            "raw_cross_session_required_types": sorted(
                item.value for item in self.raw_cross_session_required_types
            ),
            "split_adjusted_transform_implemented": self.split_adjusted_transform_implemented,
            "total_return_adjusted_transform_implemented": (
                self.total_return_adjusted_transform_implemented
            ),
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


DEFAULT_CORPORATE_ACTION_RESEARCH_POLICY = CorporateActionResearchPolicy()


@dataclass(frozen=True, slots=True)
class ResearchPriceAuthorityDecision:
    policy_id: str
    coverage_id: str
    asset: str
    start: datetime
    end: datetime
    price_basis: ResearchPriceBasis
    allow_cross_session: bool
    allowed: bool
    blockers: tuple[str, ...]
    observed_event_ids: tuple[str, ...]
    schema_version: str = "finagent.research-price-authority-decision.v1"

    @property
    def decision_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="research-price-authority")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "coverage_id": self.coverage_id,
            "asset": self.asset,
            "start": self.start.astimezone(UTC).isoformat(),
            "end": self.end.astimezone(UTC).isoformat(),
            "price_basis": self.price_basis.value,
            "allow_cross_session": self.allow_cross_session,
            "allowed": self.allowed,
            "blockers": list(self.blockers),
            "observed_event_ids": list(self.observed_event_ids),
        }
        if include_id:
            payload["decision_id"] = self.decision_id
        return payload


def assess_research_price_authority(
    coverage: CorporateActionCoverageEvidence,
    *,
    asset: str,
    start: datetime,
    end: datetime,
    price_basis: ResearchPriceBasis,
    allow_cross_session: bool,
    policy: CorporateActionResearchPolicy = DEFAULT_CORPORATE_ACTION_RESEARCH_POLICY,
) -> ResearchPriceAuthorityDecision:
    asset_key = asset.strip()
    start_utc = _aware_utc(start, "start")
    end_utc = _aware_utc(end, "end")
    if end_utc <= start_utc:
        raise ValueError("end must be later than start")
    if asset_key not in coverage.assets:
        raise ValueError(f"asset is outside corporate-action coverage: {asset_key}")

    blockers: list[str] = []
    events: tuple[CorporateActionEvent, ...] = ()

    if price_basis is ResearchPriceBasis.RAW and not allow_cross_session:
        if not policy.same_session_raw_without_action_coverage:
            blockers.append("policy:same_session_raw_disabled")
    elif price_basis is ResearchPriceBasis.RAW:
        if coverage.status is CorporateActionCoverageStatus.UNAVAILABLE:
            blockers.append("corporate_actions:coverage_unavailable")
        elif not coverage.covers_interval(start_utc, end_utc):
            blockers.append("corporate_actions:interval_not_covered")
        else:
            missing = policy.raw_cross_session_required_types.difference(coverage.covered_types)
            if missing:
                blockers.append(
                    "corporate_actions:required_types_not_covered:"
                    + ",".join(sorted(item.value for item in missing))
                )
            else:
                events = coverage.events_between(asset_key, start_utc, end_utc)
                if events:
                    blockers.append("corporate_actions:raw_price_discontinuity_observed")
    elif price_basis is ResearchPriceBasis.SPLIT_ADJUSTED:
        if coverage.status is CorporateActionCoverageStatus.UNAVAILABLE:
            blockers.append("corporate_actions:coverage_unavailable")
        elif CorporateActionEventType.SPLIT not in coverage.covered_types:
            blockers.append("corporate_actions:split_coverage_unavailable")
        if not policy.split_adjusted_transform_implemented:
            blockers.append("transform:split_adjusted_not_implemented")
    elif price_basis is ResearchPriceBasis.TOTAL_RETURN_ADJUSTED:
        required = policy.raw_cross_session_required_types
        if coverage.status is CorporateActionCoverageStatus.UNAVAILABLE:
            blockers.append("corporate_actions:coverage_unavailable")
        else:
            missing = required.difference(coverage.covered_types)
            if missing:
                blockers.append(
                    "corporate_actions:total_return_types_not_covered:"
                    + ",".join(sorted(item.value for item in missing))
                )
        if not policy.total_return_adjusted_transform_implemented:
            blockers.append("transform:total_return_adjusted_not_implemented")
    else:  # pragma: no cover - exhaustive enum boundary
        blockers.append(f"price_basis:unsupported:{price_basis.value}")

    blockers_tuple = tuple(dict.fromkeys(blockers))
    return ResearchPriceAuthorityDecision(
        policy_id=policy.policy_id,
        coverage_id=coverage.coverage_id,
        asset=asset_key,
        start=start_utc,
        end=end_utc,
        price_basis=price_basis,
        allow_cross_session=allow_cross_session,
        allowed=not blockers_tuple,
        blockers=blockers_tuple,
        observed_event_ids=tuple(event.event_id for event in events),
    )


def unavailable_us_minute_corporate_action_coverage(
    assets: tuple[str, ...],
) -> CorporateActionCoverageEvidence:
    return CorporateActionCoverageEvidence(
        market_id="XNYS",
        assets=assets,
        coverage_start=datetime(1992, 1, 1, tzinfo=UTC),
        coverage_end=datetime(2026, 4, 1, tzinfo=UTC),
        source=f"{US_MINUTE_SOURCE_ID}:no_embedded_corporate_actions",
        source_revision=US_MINUTE_SOURCE_REVISION,
        status=CorporateActionCoverageStatus.UNAVAILABLE,
        limitations=(
            "corporate_actions:not_embedded_in_ohlcv",
            "adjusted_prices:not_authoritative",
            "cross_session_raw_continuity:not_authoritative_without_action_coverage",
        ),
    )
