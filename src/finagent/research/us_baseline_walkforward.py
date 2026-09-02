from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from finagent.research.us_baseline_evaluation import USBaselineRunSpec


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
class USBaselineWalkForwardFold:
    ordinal: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    evaluation_start: datetime
    evaluation_end: datetime
    schema_version: str = "finagent.us-baseline-walk-forward-fold.v1"

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("fold ordinal must be >= 1")
        for field_name in (
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
            "evaluation_start",
            "evaluation_end",
        ):
            object.__setattr__(
                self,
                field_name,
                _aware_utc(getattr(self, field_name), field_name),
            )
        if not self.train_start < self.train_end:
            raise ValueError("train window must be positive")
        if self.train_end != self.validation_start:
            raise ValueError("pilot fold requires contiguous train->validation boundary")
        if not self.validation_start < self.validation_end:
            raise ValueError("validation window must be positive")
        if self.validation_end != self.evaluation_start:
            raise ValueError("pilot fold requires contiguous validation->evaluation boundary")
        if not self.evaluation_start < self.evaluation_end:
            raise ValueError("evaluation window must be positive")

    @property
    def fold_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-fold")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "ordinal": self.ordinal,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "validation_start": self.validation_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
        }
        if include_id:
            payload["fold_id"] = self.fold_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineWalkForwardProtocol:
    calendar_id: str
    source_revision: str
    folds: tuple[USBaselineWalkForwardFold, ...]
    market_id: str = "XNYS"
    signal_interval: str = "15m"
    label_name: str = "us_same_session_60m_simple_return_raw"
    split_basis: str = "utc_day_boundaries_filtered_by_xnys_regular_sessions"
    schema_version: str = "finagent.us-baseline-walk-forward-protocol.v1"

    def __post_init__(self) -> None:
        for field_name in ("calendar_id", "source_revision", "market_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.signal_interval != "15m":
            raise ValueError("US-B0 pilot walk-forward uses the canonical 15m signal interval")
        if self.label_name != "us_same_session_60m_simple_return_raw":
            raise ValueError("US-B0 pilot walk-forward uses the frozen same-session 60m RAW label")
        if len(self.folds) < 3:
            raise ValueError("pilot walk-forward requires at least three folds")
        ordinals = tuple(item.ordinal for item in self.folds)
        if ordinals != tuple(range(1, len(self.folds) + 1)):
            raise ValueError("fold ordinals must be consecutive starting at one")
        fold_ids = tuple(item.fold_id for item in self.folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("walk-forward fold identities must be unique")
        first_train_start = self.folds[0].train_start
        previous = self.folds[0]
        for current in self.folds:
            if current.train_start != first_train_start:
                raise ValueError("pilot walk-forward uses one expanding train start")
        for current in self.folds[1:]:
            if current.train_end != previous.validation_end:
                raise ValueError(
                    "next expanding train end must equal the previous validation end"
                )
            if current.validation_start != previous.evaluation_start:
                raise ValueError(
                    "next validation window must start at the previous evaluation start"
                )
            if current.evaluation_start != previous.evaluation_end:
                raise ValueError("evaluation windows must be contiguous and non-overlapping")
            previous = current

    @property
    def protocol_id(self) -> str:
        return _canonical_hash(self.to_dict(include_id=False), prefix="us-baseline-walk-forward")

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "calendar_id": self.calendar_id,
            "source_revision": self.source_revision,
            "market_id": self.market_id,
            "signal_interval": self.signal_interval,
            "label_name": self.label_name,
            "split_basis": self.split_basis,
            "fold_count": len(self.folds),
            "folds": [item.to_dict() for item in self.folds],
            "selection_authority": False,
            "alpha_authority": False,
        }
        if include_id:
            payload["protocol_id"] = self.protocol_id
        return payload


@dataclass(frozen=True, slots=True)
class USBaselineFoldExecutionSpec:
    protocol_id: str
    fold_id: str
    fold_ordinal: int
    run_spec_id: str
    evaluation_start: datetime
    evaluation_end: datetime
    schema_version: str = "finagent.us-baseline-fold-execution-spec.v1"

    def __post_init__(self) -> None:
        for field_name in ("protocol_id", "fold_id", "run_spec_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)
        if self.fold_ordinal < 1:
            raise ValueError("fold_ordinal must be >= 1")
        object.__setattr__(
            self,
            "evaluation_start",
            _aware_utc(self.evaluation_start, "evaluation_start"),
        )
        object.__setattr__(
            self,
            "evaluation_end",
            _aware_utc(self.evaluation_end, "evaluation_end"),
        )
        if self.evaluation_end <= self.evaluation_start:
            raise ValueError("evaluation_end must be later than evaluation_start")

    @property
    def execution_spec_id(self) -> str:
        return _canonical_hash(
            self.to_dict(include_id=False),
            prefix="us-baseline-fold-execution",
        )

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol_id": self.protocol_id,
            "fold_id": self.fold_id,
            "fold_ordinal": self.fold_ordinal,
            "run_spec_id": self.run_spec_id,
            "evaluation_start": self.evaluation_start.isoformat(),
            "evaluation_end": self.evaluation_end.isoformat(),
            "purpose": "cost_free_manual_baseline_evaluation",
            "stage_exit_authority": False,
        }
        if include_id:
            payload["execution_spec_id"] = self.execution_spec_id
        return payload


def canonical_us_b0_pilot_walk_forward() -> USBaselineWalkForwardProtocol:
    utc = UTC
    return USBaselineWalkForwardProtocol(
        calendar_id="trading-calendar-03a9c29f566d6634aedbbbdc",
        source_revision="776328445b7ac6e7815ef3a483e9c8ded1eb6d56",
        folds=(
            USBaselineWalkForwardFold(
                ordinal=1,
                train_start=datetime(2026, 1, 2, tzinfo=utc),
                train_end=datetime(2026, 2, 2, tzinfo=utc),
                validation_start=datetime(2026, 2, 2, tzinfo=utc),
                validation_end=datetime(2026, 2, 17, tzinfo=utc),
                evaluation_start=datetime(2026, 2, 17, tzinfo=utc),
                evaluation_end=datetime(2026, 3, 2, tzinfo=utc),
            ),
            USBaselineWalkForwardFold(
                ordinal=2,
                train_start=datetime(2026, 1, 2, tzinfo=utc),
                train_end=datetime(2026, 2, 17, tzinfo=utc),
                validation_start=datetime(2026, 2, 17, tzinfo=utc),
                validation_end=datetime(2026, 3, 2, tzinfo=utc),
                evaluation_start=datetime(2026, 3, 2, tzinfo=utc),
                evaluation_end=datetime(2026, 3, 16, tzinfo=utc),
            ),
            USBaselineWalkForwardFold(
                ordinal=3,
                train_start=datetime(2026, 1, 2, tzinfo=utc),
                train_end=datetime(2026, 3, 2, tzinfo=utc),
                validation_start=datetime(2026, 3, 2, tzinfo=utc),
                validation_end=datetime(2026, 3, 16, tzinfo=utc),
                evaluation_start=datetime(2026, 3, 16, tzinfo=utc),
                evaluation_end=datetime(2026, 3, 30, tzinfo=utc),
            ),
        ),
    )


def bind_us_b0_fold_execution_specs(
    protocol: USBaselineWalkForwardProtocol,
    run_spec: USBaselineRunSpec,
) -> tuple[USBaselineFoldExecutionSpec, ...]:
    if run_spec.signal_interval != protocol.signal_interval:
        raise ValueError("walk-forward/run-spec signal interval mismatch")
    if run_spec.label_name != protocol.label_name:
        raise ValueError("walk-forward/run-spec label identity mismatch")
    return tuple(
        USBaselineFoldExecutionSpec(
            protocol_id=protocol.protocol_id,
            fold_id=fold.fold_id,
            fold_ordinal=fold.ordinal,
            run_spec_id=run_spec.spec_id,
            evaluation_start=fold.evaluation_start,
            evaluation_end=fold.evaluation_end,
        )
        for fold in protocol.folds
    )
