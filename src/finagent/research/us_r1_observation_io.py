from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from finagent.domain.market_bars import BarInterval
from finagent.research.us_r1_materialization import (
    USR1CandidateObservation,
    USR1ObservationArtifact,
    USR1ObservationRole,
    compile_us_r1_feature_spec,
)
from finagent.research.us_r1_protocol import USR1CandidateDenominator


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _text(value: object, field_name: str) -> str:
    rendered = str(value).strip() if value is not None else ""
    if not rendered:
        raise ValueError(f"{field_name} must be non-empty")
    return rendered


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    result = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field_name} must be integer-like")
    return result


def _datetime(value: object, field_name: str) -> datetime:
    parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _optional_float(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric or null")
    rendered = float(value)
    if not math.isfinite(rendered):
        raise ValueError(f"{field_name} must be finite")
    return rendered


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _text(value, field_name)


def parse_us_r1_candidate_observation(
    document: Mapping[str, object],
) -> USR1CandidateObservation:
    observation = USR1CandidateObservation(
        candidate_id=_text(document.get("candidate_id"), "observation.candidate_id"),
        feature_spec_id=_text(document.get("feature_spec_id"), "observation.feature_spec_id"),
        role=USR1ObservationRole(_text(document.get("role"), "observation.role")),
        signal_interval=BarInterval(
            _text(document.get("signal_interval"), "observation.signal_interval")
        ),
        label_horizon_trading_minutes=_integer(
            document.get("label_horizon_trading_minutes"),
            "observation.label_horizon_trading_minutes",
        ),
        asset=_text(document.get("asset"), "observation.asset"),
        session_id=_text(document.get("session_id"), "observation.session_id"),
        event_time=_datetime(document.get("event_time"), "observation.event_time"),
        feature_available_at=_datetime(
            document.get("feature_available_at"),
            "observation.feature_available_at",
        ),
        feature_value=_optional_float(document.get("feature_value"), "observation.feature_value"),
        feature_unavailable_reason=_optional_text(
            document.get("feature_unavailable_reason"),
            "observation.feature_unavailable_reason",
        ),
        realized_label=_optional_float(
            document.get("realized_label"),
            "observation.realized_label",
        ),
        label_available_at=(
            None
            if document.get("label_available_at") is None
            else _datetime(document.get("label_available_at"), "observation.label_available_at")
        ),
        label_unavailable_reason=_optional_text(
            document.get("label_unavailable_reason"),
            "observation.label_unavailable_reason",
        ),
    )
    if dict(document) != observation.to_dict():
        raise ValueError("US-R1 persisted observation content mismatch")
    if observation.label_available_at is not None and (
        observation.label_available_at <= observation.feature_available_at
    ):
        raise ValueError("US-R1 realized label must mature after feature formation")
    return observation


def read_us_r1_observation_file(
    path: str | Path,
    artifact: USR1ObservationArtifact,
    denominator: USR1CandidateDenominator,
) -> tuple[USR1CandidateObservation, ...]:
    target = Path(path).expanduser().resolve()
    payload = target.read_bytes()
    if hashlib.sha256(payload).hexdigest() != artifact.content_sha256:
        raise ValueError("US-R1 observation file SHA-256 differs from artifact evidence")
    lines = payload.splitlines()
    if len(lines) != artifact.row_count:
        raise ValueError("US-R1 observation file row count differs from artifact evidence")
    expected = {
        provenance.candidate.candidate_id: compile_us_r1_feature_spec(
            provenance.candidate,
            artifact.signal_interval,
        ).spec_id
        for provenance in denominator.candidates
    }
    rows: list[USR1CandidateObservation] = []
    previous_key: tuple[str, datetime, str] | None = None
    for index, raw_line in enumerate(lines):
        if not raw_line.strip():
            raise ValueError("US-R1 observation artifact cannot contain blank records")
        loaded = json.loads(raw_line)
        document = _mapping(loaded, f"observation_file[{index}]")
        row = parse_us_r1_candidate_observation(document)
        expected_spec_id = expected.get(row.candidate_id)
        if expected_spec_id is None:
            raise ValueError("US-R1 observation contains candidate outside frozen denominator")
        if row.feature_spec_id != expected_spec_id:
            raise ValueError("US-R1 observation compiled feature identity differs from denominator")
        if row.role is not artifact.role:
            raise ValueError("US-R1 observation/artifact role mismatch")
        if row.signal_interval is not artifact.signal_interval:
            raise ValueError("US-R1 observation/artifact signal interval mismatch")
        if row.label_horizon_trading_minutes != artifact.label_horizon_trading_minutes:
            raise ValueError("US-R1 observation/artifact label horizon mismatch")
        key = (row.candidate_id, row.feature_available_at, row.asset)
        if previous_key is not None and key <= previous_key:
            raise ValueError("US-R1 observation file must preserve canonical strict row ordering")
        previous_key = key
        rows.append(row)
    return tuple(rows)
