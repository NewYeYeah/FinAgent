from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median


def _canonical_hash(payload: dict[str, object], *, prefix: str) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:24]}"


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class ReferenceMinuteBar:
    timestamp: datetime
    close: float
    volume: float | None = None
    tick_volume: float | None = None
    real_volume: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _aware(self.timestamp, "timestamp"))
        if self.close <= 0:
            raise ValueError("reference close must be positive")


@dataclass(frozen=True, slots=True)
class MinuteReferenceReconciliationPolicy:
    start: datetime
    end: datetime
    required_symbol_count: int = 4
    minimum_rows_per_symbol: int = 100
    minimum_aligned_overlap_ratio: float = 0.80
    maximum_abs_offset_minutes: int = 360
    schema_version: str = "finagent.minute-reference-reconciliation-policy.v1"

    def __post_init__(self) -> None:
        start = _aware(self.start, "start")
        end = _aware(self.end, "end")
        if end <= start:
            raise ValueError("end must be later than start")
        if self.required_symbol_count < 1:
            raise ValueError("required_symbol_count must be >= 1")
        if self.minimum_rows_per_symbol < 1:
            raise ValueError("minimum_rows_per_symbol must be >= 1")
        if not 0 < self.minimum_aligned_overlap_ratio <= 1:
            raise ValueError("minimum_aligned_overlap_ratio must be in (0, 1]")
        if self.maximum_abs_offset_minutes < 0:
            raise ValueError("maximum_abs_offset_minutes must be >= 0")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)

    @property
    def policy_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="minute-reference-policy")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "required_symbol_count": self.required_symbol_count,
            "minimum_rows_per_symbol": self.minimum_rows_per_symbol,
            "minimum_aligned_overlap_ratio": self.minimum_aligned_overlap_ratio,
            "maximum_abs_offset_minutes": self.maximum_abs_offset_minutes,
        }
        if include_id:
            payload["policy_id"] = self.policy_id
        return payload


@dataclass(frozen=True, slots=True)
class MinuteReferenceSymbolCheck:
    research_symbol: str
    broker_symbol: str
    research_row_count: int
    broker_row_count: int
    exact_overlap_count: int
    best_broker_to_research_offset_minutes: int
    aligned_overlap_count: int
    aligned_overlap_ratio: float
    median_close_relative_difference: float | None
    maximum_close_relative_difference: float | None
    research_volume_sum: float | None
    broker_tick_volume_sum: float | None
    broker_real_volume_sum: float | None
    schema_version: str = "finagent.minute-reference-symbol-check.v1"

    @property
    def passed(self) -> bool:
        return self.aligned_overlap_count > 0 and self.aligned_overlap_ratio > 0

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "research_symbol": self.research_symbol,
            "broker_symbol": self.broker_symbol,
            "research_row_count": self.research_row_count,
            "broker_row_count": self.broker_row_count,
            "exact_overlap_count": self.exact_overlap_count,
            "best_broker_to_research_offset_minutes": (
                self.best_broker_to_research_offset_minutes
            ),
            "aligned_overlap_count": self.aligned_overlap_count,
            "aligned_overlap_ratio": self.aligned_overlap_ratio,
            "median_close_relative_difference": self.median_close_relative_difference,
            "maximum_close_relative_difference": self.maximum_close_relative_difference,
            "research_volume_sum": self.research_volume_sum,
            "broker_tick_volume_sum": self.broker_tick_volume_sum,
            "broker_real_volume_sum": self.broker_real_volume_sum,
        }


def reconcile_reference_symbol(
    research_symbol: str,
    broker_symbol: str,
    research_bars: tuple[ReferenceMinuteBar, ...],
    broker_bars: tuple[ReferenceMinuteBar, ...],
    *,
    policy: MinuteReferenceReconciliationPolicy,
) -> MinuteReferenceSymbolCheck:
    research_by_time = {item.timestamp: item for item in research_bars}
    broker_by_time = {item.timestamp: item for item in broker_bars}
    exact_overlap = len(set(research_by_time) & set(broker_by_time))

    best_offset = 0
    best_overlap = -1
    for offset_minutes in range(
        -policy.maximum_abs_offset_minutes,
        policy.maximum_abs_offset_minutes + 1,
    ):
        delta = timedelta(minutes=offset_minutes)
        overlap = sum(
            (timestamp + delta) in research_by_time for timestamp in broker_by_time
        )
        if overlap > best_overlap or (
            overlap == best_overlap
            and (abs(offset_minutes), offset_minutes) < (abs(best_offset), best_offset)
        ):
            best_overlap = overlap
            best_offset = offset_minutes

    denominator = min(len(research_by_time), len(broker_by_time))
    overlap_ratio = best_overlap / denominator if denominator else 0.0
    aligned_differences: list[float] = []
    delta = timedelta(minutes=best_offset)
    for broker_time, broker_bar in broker_by_time.items():
        research_bar = research_by_time.get(broker_time + delta)
        if research_bar is None:
            continue
        aligned_differences.append(
            abs(broker_bar.close - research_bar.close) / research_bar.close
        )

    def _sum(values: tuple[float | None, ...]) -> float | None:
        present = [value for value in values if value is not None]
        return sum(present) if present else None

    return MinuteReferenceSymbolCheck(
        research_symbol=research_symbol,
        broker_symbol=broker_symbol,
        research_row_count=len(research_by_time),
        broker_row_count=len(broker_by_time),
        exact_overlap_count=exact_overlap,
        best_broker_to_research_offset_minutes=best_offset,
        aligned_overlap_count=max(best_overlap, 0),
        aligned_overlap_ratio=overlap_ratio,
        median_close_relative_difference=(
            median(aligned_differences) if aligned_differences else None
        ),
        maximum_close_relative_difference=(
            max(aligned_differences) if aligned_differences else None
        ),
        research_volume_sum=_sum(tuple(item.volume for item in research_bars)),
        broker_tick_volume_sum=_sum(tuple(item.tick_volume for item in broker_bars)),
        broker_real_volume_sum=_sum(tuple(item.real_volume for item in broker_bars)),
    )


@dataclass(frozen=True, slots=True)
class MinuteReferenceReconciliationReport:
    policy: MinuteReferenceReconciliationPolicy
    source_revision: str
    source_data_version: str
    calendar_id: str
    mt5_probe_id: str
    broker_server: str
    symbol_checks: tuple[MinuteReferenceSymbolCheck, ...]
    retrieved_at: datetime
    schema_version: str = "finagent.minute-reference-reconciliation-report.v1"

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if len(self.symbol_checks) < self.policy.required_symbol_count:
            blockers.append(
                f"reconciliation:insufficient_symbols:{len(self.symbol_checks)}"
                f"<{self.policy.required_symbol_count}"
            )
        for check in self.symbol_checks:
            if check.research_row_count < self.policy.minimum_rows_per_symbol:
                blockers.append(f"symbol:{check.research_symbol}:research_rows_insufficient")
            if check.broker_row_count < self.policy.minimum_rows_per_symbol:
                blockers.append(f"symbol:{check.research_symbol}:broker_rows_insufficient")
            if check.aligned_overlap_ratio < self.policy.minimum_aligned_overlap_ratio:
                blockers.append(f"symbol:{check.research_symbol}:aligned_overlap_below_minimum")
        return tuple(blockers)

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "policy_id": self.policy.policy_id,
                "source_revision": self.source_revision,
                "source_data_version": self.source_data_version,
                "calendar_id": self.calendar_id,
                "mt5_probe_id": self.mt5_probe_id,
                "broker_server": self.broker_server,
                "symbol_checks": [item.to_dict() for item in self.symbol_checks],
            },
            prefix="minute-reference-reconciliation",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "policy": self.policy.to_dict(),
            "source_revision": self.source_revision,
            "source_data_version": self.source_data_version,
            "calendar_id": self.calendar_id,
            "mt5_probe_id": self.mt5_probe_id,
            "broker_server": self.broker_server,
            "reference_symbol_count": len(self.symbol_checks),
            "passed": self.passed,
            "blockers": list(self.blockers),
            "limitations": [
                "reference:broker_cfd_is_not_authoritative_source_replacement",
                "timestamp_offset:evidence_only_no_source_clock_rewrite",
                "price_difference:diagnostic_not_adjustment_authority",
                "volume:broker_tick_real_volume_not_assumed_equivalent_to_source_volume",
            ],
            "symbol_checks": [item.to_dict() for item in self.symbol_checks],
            "retrieved_at": self.retrieved_at.astimezone(UTC).isoformat(),
        }
