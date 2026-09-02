from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.domain.trading_calendar import TradingCalendarEvidence
from finagent.research.us_agent_value_protocol import canonical_us_a0_primitive_vocabulary
from finagent.research.us_baseline_walkforward import canonical_us_b0_pilot_walk_forward
from finagent.research.us_r1_protocol import (
    USR1CandidateDenominator,
    canonical_us_r1_research_protocol,
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


def _aware_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class USR1WalkForwardFold:
    ordinal: int
    train_start: datetime
    train_end: datetime
    gap_start: datetime
    gap_end: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    purge_trading_minutes: int = 60
    embargo_trading_minutes: int = 60
    schema_version: str = "finagent.us-r1-walk-forward-fold.v1"

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("US-R1 fold ordinal must be >= 1")
        for field_name in (
            "train_start",
            "train_end",
            "gap_start",
            "gap_end",
            "evaluation_start",
            "evaluation_end",
        ):
            object.__setattr__(
                self,
                field_name,
                _aware_utc(getattr(self, field_name), field_name),
            )
        if not self.train_start < self.train_end:
            raise ValueError("US-R1 train window must be positive")
        if self.gap_start != self.train_end:
            raise ValueError("US-R1 excluded gap must start exactly at train_end")
        if not self.gap_start < self.gap_end:
            raise ValueError("US-R1 purge/embargo gap must be positive")
        if self.gap_end != self.evaluation_start:
            raise ValueError("US-R1 excluded gap must end exactly at evaluation_start")
        if not self.evaluation_start < self.evaluation_end:
            raise ValueError("US-R1 evaluation window must be positive")
        if self.purge_trading_minutes != 60 or self.embargo_trading_minutes != 60:
            raise ValueError("US-R1 v1 requires exact 60m purge and 60m embargo")

    @property
    def required_gap_trading_minutes(self) -> int:
        return self.purge_trading_minutes + self.embargo_trading_minutes

    @property
    def fold_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-fold")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "ordinal": self.ordinal,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "gap_start": self.gap_start.isoformat(),
            "gap_end": self.gap_end.isoformat(),
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "purge_trading_minutes": self.purge_trading_minutes,
            "embargo_trading_minutes": self.embargo_trading_minutes,
            "required_gap_trading_minutes": self.required_gap_trading_minutes,
            "gap_semantics": (
                "entire_pre_evaluation_validation_window_excluded; "
                "formal runner verifies XNYS regular-session minutes >= purge+embargo"
            ),
        }
        if include_id:
            payload["fold_id"] = self.fold_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1WalkForwardProtocol:
    research_protocol_id: str
    calendar_id: str
    source_revision: str
    folds: tuple[USR1WalkForwardFold, ...]
    market_id: str = "XNYS"
    schema_version: str = "finagent.us-r1-walk-forward-protocol.v1"

    def __post_init__(self) -> None:
        canonical = canonical_us_r1_research_protocol()
        if self.research_protocol_id != canonical.protocol_id:
            raise ValueError("US-R1 walk-forward/research protocol identity mismatch")
        for field_name in ("calendar_id", "source_revision", "market_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.market_id != "XNYS":
            raise ValueError("US-R1 v1 walk-forward market must be XNYS")
        if len(self.folds) != 3:
            raise ValueError("US-R1 v1 requires exactly three walk-forward folds")
        if tuple(fold.ordinal for fold in self.folds) != (1, 2, 3):
            raise ValueError("US-R1 fold ordinals must be exactly 1,2,3")
        if len({fold.fold_id for fold in self.folds}) != 3:
            raise ValueError("US-R1 fold identities must be unique")
        first_train_start = self.folds[0].train_start
        previous = self.folds[0]
        for fold in self.folds:
            if fold.train_start != first_train_start:
                raise ValueError("US-R1 uses one expanding train start")
        for fold in self.folds[1:]:
            if fold.train_end <= previous.train_end:
                raise ValueError("US-R1 training windows must expand")
            if fold.evaluation_start != previous.evaluation_end:
                raise ValueError("US-R1 OOS evaluation windows must be contiguous")
            previous = fold

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-walk-forward")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "research_protocol_id": self.research_protocol_id,
            "calendar_id": self.calendar_id,
            "source_revision": self.source_revision,
            "market_id": self.market_id,
            "fold_count": len(self.folds),
            "folds": [fold.to_dict() for fold in self.folds],
            "direction_selection": "train_15m_60m_rank_ic_sign_only",
            "evaluation_semantics": "oos_only_after_entire_excluded_gap",
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload


@dataclass(frozen=True, slots=True)
class USR1FoldExecutionSpec:
    walk_forward_protocol_id: str
    research_protocol_id: str
    denominator_id: str
    fold_id: str
    fold_ordinal: int
    train_start: datetime
    train_end: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    schema_version: str = "finagent.us-r1-fold-execution-spec.v1"

    def __post_init__(self) -> None:
        for field_name in (
            "walk_forward_protocol_id",
            "research_protocol_id",
            "denominator_id",
            "fold_id",
        ):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.fold_ordinal not in {1, 2, 3}:
            raise ValueError("US-R1 fold_ordinal must be 1,2,3")
        for field_name in ("train_start", "train_end", "evaluation_start", "evaluation_end"):
            object.__setattr__(
                self,
                field_name,
                _aware_utc(getattr(self, field_name), field_name),
            )
        if not self.train_start < self.train_end < self.evaluation_start < self.evaluation_end:
            raise ValueError("US-R1 fold execution windows must be strictly ordered")

    @property
    def execution_spec_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-r1-fold-execution")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "walk_forward_protocol_id": self.walk_forward_protocol_id,
            "research_protocol_id": self.research_protocol_id,
            "denominator_id": self.denominator_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "purpose": "us_r1_dependence_aware_robust_intraday_oos_materialization",
            "status_authority": False,
            "stage_exit_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["execution_spec_id"] = self.execution_spec_id
        return payload


def canonical_us_r1_walk_forward() -> USR1WalkForwardProtocol:
    base = canonical_us_b0_pilot_walk_forward()
    research = canonical_us_r1_research_protocol()
    return USR1WalkForwardProtocol(
        research_protocol_id=research.protocol_id,
        calendar_id=base.calendar_id,
        source_revision=base.source_revision,
        folds=tuple(
            USR1WalkForwardFold(
                ordinal=fold.ordinal,
                train_start=fold.train_start,
                train_end=fold.train_end,
                gap_start=fold.train_end,
                gap_end=fold.evaluation_start,
                evaluation_start=fold.evaluation_start,
                evaluation_end=fold.evaluation_end,
                purge_trading_minutes=research.purge_trading_minutes,
                embargo_trading_minutes=research.embargo_trading_minutes,
            )
            for fold in base.folds
        ),
    )


def validate_us_r1_walk_forward_document(document: dict[str, object]) -> USR1WalkForwardProtocol:
    canonical = canonical_us_r1_walk_forward()
    if document != canonical.to_dict():
        raise ValueError("US-R1 walk-forward document differs from the canonical preregistration")
    return canonical


def verify_us_r1_fold_gap(
    fold: USR1WalkForwardFold,
    calendar: TradingCalendarEvidence,
) -> int:
    if calendar.calendar_id != canonical_us_r1_walk_forward().calendar_id:
        raise ValueError("US-R1 fold gap verification requires the frozen XNYS calendar")
    regular_minutes = sum(
        session.regular_minutes
        for session in calendar.sessions
        if session.open_at >= fold.gap_start and session.close_at <= fold.gap_end
    )
    if regular_minutes < fold.required_gap_trading_minutes:
        raise ValueError(
            "US-R1 excluded fold gap does not contain the preregistered purge+embargo trading minutes"
        )
    return regular_minutes


def bind_us_r1_fold_execution_specs(
    walk_forward: USR1WalkForwardProtocol,
    denominator: USR1CandidateDenominator,
) -> tuple[USR1FoldExecutionSpec, ...]:
    research = canonical_us_r1_research_protocol()
    if walk_forward.research_protocol_id != research.protocol_id:
        raise ValueError("US-R1 walk-forward protocol drift")
    if denominator.protocol_id != research.protocol_id:
        raise ValueError("US-R1 denominator/research protocol identity mismatch")
    vocabulary = canonical_us_a0_primitive_vocabulary()
    for provenance in denominator.candidates:
        candidate = provenance.candidate
        expected = vocabulary.candidate(candidate.kind, candidate.window_bars)
        if candidate != expected:
            raise ValueError("US-R1 denominator contains candidate outside frozen A0 vocabulary")
    return tuple(
        USR1FoldExecutionSpec(
            walk_forward_protocol_id=walk_forward.protocol_id,
            research_protocol_id=research.protocol_id,
            denominator_id=denominator.denominator_id,
            fold_id=fold.fold_id,
            fold_ordinal=fold.ordinal,
            train_start=fold.train_start,
            train_end=fold.train_end,
            evaluation_start=fold.evaluation_start,
            evaluation_end=fold.evaluation_end,
        )
        for fold in walk_forward.folds
    )
