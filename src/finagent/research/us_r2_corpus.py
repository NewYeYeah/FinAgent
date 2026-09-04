from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime


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


@dataclass(frozen=True, slots=True)
class USRegimeCorpusInventoryPlan:
    manifest_id: str
    data_version: str
    calendar_id: str
    assets: tuple[str, ...]
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    sql: str
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-corpus-inventory-plan.v1"

    def __post_init__(self) -> None:
        for field_name in ("manifest_id", "data_version", "calendar_id", "sql"):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        assets = tuple(sorted(dict.fromkeys(_text(item, "assets[]") for item in self.assets)))
        months = tuple(
            sorted(dict.fromkeys(_text(item, "partition_months[]") for item in self.partition_months))
        )
        if not assets:
            raise ValueError("US-R2 corpus inventory requires at least one asset")
        if not months:
            raise ValueError("US-R2 corpus inventory requires at least one partition")
        if self.selected_size_bytes < 0:
            raise ValueError("selected_size_bytes must be >= 0")
        if not self.output_columns:
            raise ValueError("output_columns cannot be empty")
        object.__setattr__(self, "assets", assets)
        object.__setattr__(self, "partition_months", months)

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "manifest_id": self.manifest_id,
                "data_version": self.data_version,
                "calendar_id": self.calendar_id,
                "assets": list(self.assets),
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
                "scan_strategy": (
                    "single_read_parquet_relation_asset_pushdown_regular_session_preaggregation"
                ),
            },
            prefix="us-r2-corpus-inventory-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "manifest_id": self.manifest_id,
            "data_version": self.data_version,
            "calendar_id": self.calendar_id,
            "assets": list(self.assets),
            "asset_count": len(self.assets),
            "partition_months": list(self.partition_months),
            "partition_count": len(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
            "scan_strategy": (
                "single_read_parquet_relation_asset_pushdown_regular_session_preaggregation"
            ),
            "candidate_dependent_scan": False,
            "source_rows_emitted": False,
        }


@dataclass(frozen=True, slots=True)
class USRegimeMonthCoverage:
    asset: str
    month: str
    expected_session_count: int
    observed_session_count: int
    complete_session_count: int
    expected_regular_minute_count: int
    observed_regular_minute_count: int
    missing_session_count: int
    conflicting_key_count: int
    invalid_key_count: int
    exact_duplicate_extra_row_count: int
    session_membership_sha256: str
    complete_session_membership_sha256: str
    first_session_date: date | None = None
    last_session_date: date | None = None
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None
    schema_version: str = "finagent.us-r2-regime-month-coverage.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, "asset"))
        month = _text(self.month, "month")
        if len(month) != 7 or month[4] != "-":
            raise ValueError("month must be YYYY-MM")
        object.__setattr__(self, "month", month)
        counts = (
            self.expected_session_count,
            self.observed_session_count,
            self.complete_session_count,
            self.expected_regular_minute_count,
            self.observed_regular_minute_count,
            self.missing_session_count,
            self.conflicting_key_count,
            self.invalid_key_count,
            self.exact_duplicate_extra_row_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("US-R2 month coverage counts must be >= 0")
        if self.observed_session_count > self.expected_session_count:
            raise ValueError("observed sessions cannot exceed admitted calendar sessions")
        if self.complete_session_count > self.observed_session_count:
            raise ValueError("complete sessions cannot exceed observed sessions")
        if self.missing_session_count != self.expected_session_count - self.observed_session_count:
            raise ValueError("missing_session_count must equal expected minus observed sessions")
        for field_name in ("session_membership_sha256", "complete_session_membership_sha256"):
            digest = str(getattr(self, field_name)).strip().lower()
            if len(digest) != 64 or any(item not in "0123456789abcdef" for item in digest):
                raise ValueError(f"{field_name} must be a SHA-256 hex digest")
            object.__setattr__(self, field_name, digest)

    @property
    def regular_minute_coverage_ratio(self) -> float | None:
        if self.expected_regular_minute_count == 0:
            return None
        return self.observed_regular_minute_count / self.expected_regular_minute_count

    @property
    def complete_session_ratio(self) -> float | None:
        if self.expected_session_count == 0:
            return None
        return self.complete_session_count / self.expected_session_count

    @property
    def coverage_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-month-coverage")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "asset": self.asset,
            "month": self.month,
            "expected_session_count": self.expected_session_count,
            "observed_session_count": self.observed_session_count,
            "complete_session_count": self.complete_session_count,
            "expected_regular_minute_count": self.expected_regular_minute_count,
            "observed_regular_minute_count": self.observed_regular_minute_count,
            "missing_session_count": self.missing_session_count,
            "regular_minute_coverage_ratio": self.regular_minute_coverage_ratio,
            "complete_session_ratio": self.complete_session_ratio,
            "conflicting_key_count": self.conflicting_key_count,
            "invalid_key_count": self.invalid_key_count,
            "exact_duplicate_extra_row_count": self.exact_duplicate_extra_row_count,
            "session_membership_sha256": self.session_membership_sha256,
            "complete_session_membership_sha256": self.complete_session_membership_sha256,
            "first_session_date": self.first_session_date.isoformat() if self.first_session_date else None,
            "last_session_date": self.last_session_date.isoformat() if self.last_session_date else None,
            "first_event_time": self.first_event_time.isoformat() if self.first_event_time else None,
            "last_event_time": self.last_event_time.isoformat() if self.last_event_time else None,
        }
        if include_id:
            payload["coverage_id"] = self.coverage_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeAssetCoverage:
    asset: str
    first_observed_session: date | None
    last_observed_session: date | None
    observed_month_count: int
    active_span_expected_session_count: int
    active_span_observed_session_count: int
    active_span_complete_session_count: int
    active_span_expected_regular_minute_count: int
    active_span_observed_regular_minute_count: int
    month_coverage_ids: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-asset-coverage.v1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "asset", _text(self.asset, "asset"))
        if (self.first_observed_session is None) != (self.last_observed_session is None):
            raise ValueError("asset history boundaries must both be present or both be absent")
        if (
            self.first_observed_session is not None
            and self.last_observed_session is not None
            and self.last_observed_session < self.first_observed_session
        ):
            raise ValueError("asset history end cannot precede start")
        counts = (
            self.observed_month_count,
            self.active_span_expected_session_count,
            self.active_span_observed_session_count,
            self.active_span_complete_session_count,
            self.active_span_expected_regular_minute_count,
            self.active_span_observed_regular_minute_count,
        )
        if any(value < 0 for value in counts):
            raise ValueError("US-R2 asset coverage counts must be >= 0")
        if self.active_span_observed_session_count > self.active_span_expected_session_count:
            raise ValueError("asset observed sessions cannot exceed active-span calendar sessions")
        if self.active_span_complete_session_count > self.active_span_observed_session_count:
            raise ValueError("asset complete sessions cannot exceed observed sessions")
        if len(self.month_coverage_ids) != len(set(self.month_coverage_ids)):
            raise ValueError("asset month coverage IDs must be unique")

    @property
    def active_span_missing_session_count(self) -> int:
        return self.active_span_expected_session_count - self.active_span_observed_session_count

    @property
    def active_span_regular_minute_coverage_ratio(self) -> float | None:
        if self.active_span_expected_regular_minute_count == 0:
            return None
        return (
            self.active_span_observed_regular_minute_count
            / self.active_span_expected_regular_minute_count
        )

    @property
    def coverage_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-asset-coverage")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "asset": self.asset,
            "first_observed_session": (
                self.first_observed_session.isoformat() if self.first_observed_session else None
            ),
            "last_observed_session": (
                self.last_observed_session.isoformat() if self.last_observed_session else None
            ),
            "observed_month_count": self.observed_month_count,
            "active_span_expected_session_count": self.active_span_expected_session_count,
            "active_span_observed_session_count": self.active_span_observed_session_count,
            "active_span_complete_session_count": self.active_span_complete_session_count,
            "active_span_missing_session_count": self.active_span_missing_session_count,
            "active_span_expected_regular_minute_count": self.active_span_expected_regular_minute_count,
            "active_span_observed_regular_minute_count": self.active_span_observed_regular_minute_count,
            "active_span_regular_minute_coverage_ratio": self.active_span_regular_minute_coverage_ratio,
            "month_coverage_ids": list(self.month_coverage_ids),
            "history_boundary_semantics": (
                "first_last_observed_regular_session_not_listing_or_delisting_authority"
            ),
        }
        if include_id:
            payload["coverage_id"] = self.coverage_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeYearBreadth:
    year: int
    expected_session_count: int
    observed_asset_count_histogram: tuple[int, ...]
    complete_asset_count_histogram: tuple[int, ...]
    minimum_observed_asset_count: int
    median_observed_asset_count: float
    maximum_observed_asset_count: int
    minimum_complete_asset_count: int
    median_complete_asset_count: float
    maximum_complete_asset_count: int
    schema_version: str = "finagent.us-r2-regime-year-breadth.v1"

    def __post_init__(self) -> None:
        if self.year < 1900 or self.expected_session_count < 0:
            raise ValueError("invalid US-R2 year breadth identity/count")
        if not self.observed_asset_count_histogram or not self.complete_asset_count_histogram:
            raise ValueError("year breadth histograms cannot be empty")
        if len(self.observed_asset_count_histogram) != len(self.complete_asset_count_histogram):
            raise ValueError("observed/complete breadth histograms must have the same bins")
        if sum(self.observed_asset_count_histogram) != self.expected_session_count:
            raise ValueError("observed breadth histogram must cover every expected session")
        if sum(self.complete_asset_count_histogram) != self.expected_session_count:
            raise ValueError("complete breadth histogram must cover every expected session")

    @property
    def full_universe_observed_session_count(self) -> int:
        return self.observed_asset_count_histogram[-1]

    @property
    def full_universe_complete_session_count(self) -> int:
        return self.complete_asset_count_histogram[-1]

    @property
    def breadth_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-year-breadth")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "year": self.year,
            "expected_session_count": self.expected_session_count,
            "observed_asset_count_histogram": list(self.observed_asset_count_histogram),
            "complete_asset_count_histogram": list(self.complete_asset_count_histogram),
            "minimum_observed_asset_count": self.minimum_observed_asset_count,
            "median_observed_asset_count": self.median_observed_asset_count,
            "maximum_observed_asset_count": self.maximum_observed_asset_count,
            "minimum_complete_asset_count": self.minimum_complete_asset_count,
            "median_complete_asset_count": self.median_complete_asset_count,
            "maximum_complete_asset_count": self.maximum_complete_asset_count,
            "full_universe_observed_session_count": self.full_universe_observed_session_count,
            "full_universe_complete_session_count": self.full_universe_complete_session_count,
        }
        if include_id:
            payload["breadth_id"] = self.breadth_id
        return payload


@dataclass(frozen=True, slots=True)
class USRegimeResearchCorpus:
    plan: USRegimeCorpusInventoryPlan
    source_id: str
    source_revision: str
    cleaning_identity: str
    engineering_universe_id: str
    candidate_denominator_id: str
    month_coverages: tuple[USRegimeMonthCoverage, ...]
    asset_coverages: tuple[USRegimeAssetCoverage, ...]
    year_breadth: tuple[USRegimeYearBreadth, ...]
    common_all_asset_start: date | None
    common_all_asset_end: date | None
    common_all_asset_session_count: int
    blockers: tuple[str, ...]
    limitations: tuple[str, ...]
    schema_version: str = "finagent.us-r2-regime-research-corpus.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "source_id",
            "source_revision",
            "cleaning_identity",
            "engineering_universe_id",
            "candidate_denominator_id",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        if (self.common_all_asset_start is None) != (self.common_all_asset_end is None):
            raise ValueError("common all-asset window boundaries must both exist or both be absent")
        if (
            self.common_all_asset_start is not None
            and self.common_all_asset_end is not None
            and self.common_all_asset_end < self.common_all_asset_start
        ):
            raise ValueError("common all-asset window end cannot precede start")
        if self.common_all_asset_session_count < 0:
            raise ValueError("common_all_asset_session_count must be >= 0")
        if tuple(item.asset for item in self.asset_coverages) != tuple(sorted(self.plan.assets)):
            raise ValueError("asset coverages must match the complete inventory-plan assets")
        if len(self.month_coverages) != len(self.plan.assets) * len(self.plan.partition_months):
            raise ValueError("month coverage matrix must retain every asset x partition cell")

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def corpus_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r2-regime-corpus")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "plan": self.plan.to_dict(),
            "source_id": self.source_id,
            "source_revision": self.source_revision,
            "cleaning_identity": self.cleaning_identity,
            "engineering_universe_id": self.engineering_universe_id,
            "candidate_denominator_id": self.candidate_denominator_id,
            "candidate_performance_read": False,
            "performance_filter_applied": False,
            "point_in_time_security_master_available": False,
            "survivorship_safe_market_claim": False,
            "month_coverage_count": len(self.month_coverages),
            "month_coverages": [item.to_dict() for item in self.month_coverages],
            "asset_coverages": [item.to_dict() for item in self.asset_coverages],
            "year_breadth": [item.to_dict() for item in self.year_breadth],
            "common_all_asset_start": (
                self.common_all_asset_start.isoformat() if self.common_all_asset_start else None
            ),
            "common_all_asset_end": (
                self.common_all_asset_end.isoformat() if self.common_all_asset_end else None
            ),
            "common_all_asset_session_count": self.common_all_asset_session_count,
            "blockers": list(self.blockers),
            "limitations": list(self.limitations),
            "research_scope": "multi_regime_engineering_evidence_inventory_only",
            "stage_exit_authority": False,
            "alpha_authority": False,
            "execution_authority": False,
            "order_authority": False,
        }
        if include_id:
            payload["corpus_id"] = self.corpus_id
        return payload
