from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from finagent.data.minute_store import MinuteMaterialization, MinuteQueryPlan
from finagent.data.minute_transform import (
    LabelQueryPlan,
    LabelSeriesEvidence,
    ResamplingEvidence,
)
from finagent.data.query import MarketDataField, SessionPolicy
from finagent.domain.labels import AvailabilityPolicy, ResearchPriceBasis
from finagent.domain.market_bars import BarInterval
from finagent.research.us_baseline_evaluation import (
    USBaselineEvaluationReport,
    USBaselineObservation,
    USBaselineRunSpec,
    evaluate_us_baseline_denominator,
)
from finagent.research.us_baselines import (
    USBaselineBar,
    USBaselineCandidateDenominator,
    evaluate_us_baseline_feature,
)

_CERTIFIED_OUTCOMES = frozenset(
    {
        "CERTIFIED_FOR_ENGINEERING_RESEARCH",
        "CERTIFIED_FOR_RESEARCH_UNDER_LIMITATIONS",
    }
)
_ALLOWED_LABEL_UNAVAILABLE = frozenset(
    {
        "target_crosses_session",
        "target_minute_missing",
    }
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


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be integer-like")
    return int(value)


def _boolean(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name} must be boolean")
    return value


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
    return value


def _aware_datetime(value: object, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(_text(value, field_name))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return parsed


def _float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    return result


@dataclass(frozen=True, slots=True)
class USBaselineInputPlan:
    run_spec_id: str
    resampled_plan_id: str
    label_plan_id: str
    resampling_evidence_id: str
    label_evidence_id: str
    source_data_version: str
    data_version: str
    sql: str
    partition_months: tuple[str, ...]
    selected_size_bytes: int
    output_columns: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-input-plan.v1"

    @property
    def plan_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "run_spec_id": self.run_spec_id,
                "resampled_plan_id": self.resampled_plan_id,
                "label_plan_id": self.label_plan_id,
                "resampling_evidence_id": self.resampling_evidence_id,
                "label_evidence_id": self.label_evidence_id,
                "source_data_version": self.source_data_version,
                "data_version": self.data_version,
                "partition_months": list(self.partition_months),
                "output_columns": list(self.output_columns),
            },
            prefix="us-baseline-input-plan",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_id": self.plan_id,
            "run_spec_id": self.run_spec_id,
            "resampled_plan_id": self.resampled_plan_id,
            "label_plan_id": self.label_plan_id,
            "resampling_evidence_id": self.resampling_evidence_id,
            "label_evidence_id": self.label_evidence_id,
            "source_data_version": self.source_data_version,
            "data_version": self.data_version,
            "partition_months": list(self.partition_months),
            "selected_size_bytes": self.selected_size_bytes,
            "output_columns": list(self.output_columns),
        }


@dataclass(frozen=True, slots=True)
class USBaselineCandidateMaterializationCheck:
    feature_id: str
    feature_spec_id: str
    observation_count: int
    available_feature_count: int
    unavailable_reason_counts: tuple[tuple[str, int], ...]
    schema_version: str = "finagent.us-baseline-candidate-materialization-check.v1"

    def __post_init__(self) -> None:
        if self.observation_count < 0 or self.available_feature_count < 0:
            raise ValueError("candidate materialization counts must be >= 0")
        if self.available_feature_count > self.observation_count:
            raise ValueError("available_feature_count cannot exceed observation_count")

    @property
    def feature_coverage(self) -> float:
        if self.observation_count == 0:
            return 0.0
        return self.available_feature_count / self.observation_count

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "feature_id": self.feature_id,
            "feature_spec_id": self.feature_spec_id,
            "observation_count": self.observation_count,
            "available_feature_count": self.available_feature_count,
            "feature_coverage": self.feature_coverage,
            "unavailable_reason_counts": {
                key: value for key, value in self.unavailable_reason_counts
            },
        }


@dataclass(frozen=True, slots=True)
class USBaselineObservationArtifact:
    run_spec_id: str
    denominator_id: str
    row_count: int
    content_sha256: str
    output_filename: str
    schema_version: str = "finagent.us-baseline-observation-artifact.v1"

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError("observation artifact row_count must be >= 0")
        digest = self.content_sha256.strip().lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("content_sha256 must be a 64-character hexadecimal SHA-256")
        object.__setattr__(self, "content_sha256", digest)

    @property
    def artifact_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "run_spec_id": self.run_spec_id,
                "denominator_id": self.denominator_id,
                "row_count": self.row_count,
                "content_sha256": self.content_sha256,
            },
            prefix="us-baseline-observations",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_id": self.artifact_id,
            "run_spec_id": self.run_spec_id,
            "denominator_id": self.denominator_id,
            "row_count": self.row_count,
            "content_sha256": self.content_sha256,
            "output_filename": self.output_filename,
        }


@dataclass(frozen=True, slots=True)
class USBaselineMaterializationDiagnostics:
    input_row_count: int
    expected_asset_count: int
    observed_asset_count: int
    missing_assets: tuple[str, ...]
    assets_without_complete_bar: tuple[str, ...]
    complete_bar_count: int
    incomplete_bar_count: int
    label_anchor_missing_count: int
    close_anchor_mismatch_count: int
    label_available_count: int
    target_crosses_session_count: int
    target_minute_missing_count: int
    candidate_checks: tuple[USBaselineCandidateMaterializationCheck, ...]
    blockers: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-materialization-diagnostics.v1"

    @property
    def passed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "passed": self.passed,
            "input_row_count": self.input_row_count,
            "expected_asset_count": self.expected_asset_count,
            "observed_asset_count": self.observed_asset_count,
            "missing_assets": list(self.missing_assets),
            "assets_without_complete_bar": list(self.assets_without_complete_bar),
            "complete_bar_count": self.complete_bar_count,
            "incomplete_bar_count": self.incomplete_bar_count,
            "label_anchor_missing_count": self.label_anchor_missing_count,
            "close_anchor_mismatch_count": self.close_anchor_mismatch_count,
            "label_available_count": self.label_available_count,
            "target_crosses_session_count": self.target_crosses_session_count,
            "target_minute_missing_count": self.target_minute_missing_count,
            "candidate_checks": [item.to_dict() for item in self.candidate_checks],
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True, slots=True)
class USBaselineMaterializationReport:
    run_spec: USBaselineRunSpec
    input_plan: USBaselineInputPlan
    input_materialization: MinuteMaterialization
    observation_artifact: USBaselineObservationArtifact
    diagnostics: USBaselineMaterializationDiagnostics
    evaluation_report_id: str
    engineering_assets: tuple[str, ...]
    schema_version: str = "finagent.us-baseline-materialization-report.v1"

    def __post_init__(self) -> None:
        if self.input_plan.run_spec_id != self.run_spec.spec_id:
            raise ValueError("input plan/run-spec identity mismatch")
        if self.observation_artifact.run_spec_id != self.run_spec.spec_id:
            raise ValueError("observation artifact/run-spec identity mismatch")
        if self.observation_artifact.denominator_id != self.run_spec.denominator_id:
            raise ValueError("observation artifact denominator identity mismatch")
        if self.input_materialization.plan_id != self.input_plan.plan_id:
            raise ValueError("input materialization/plan identity mismatch")
        if not self.engineering_assets:
            raise ValueError("materialization report requires engineering assets")

    @property
    def blockers(self) -> tuple[str, ...]:
        return self.diagnostics.blockers

    @property
    def passed(self) -> bool:
        return not self.blockers

    @property
    def report_id(self) -> str:
        return _canonical_hash(
            {
                "schema_version": self.schema_version,
                "run_spec_id": self.run_spec.spec_id,
                "input_plan_id": self.input_plan.plan_id,
                "input_materialization_id": self.input_materialization.materialization_id,
                "observation_artifact_id": self.observation_artifact.artifact_id,
                "diagnostics": self.diagnostics.to_dict(),
                "evaluation_report_id": self.evaluation_report_id,
                "engineering_assets": list(self.engineering_assets),
            },
            prefix="us-baseline-materialization",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "passed": self.passed,
            "blockers": list(self.blockers),
            "run_spec": self.run_spec.to_dict(),
            "input_plan": self.input_plan.to_dict(),
            "input_materialization": self.input_materialization.to_dict(),
            "observation_artifact": self.observation_artifact.to_dict(),
            "diagnostics": self.diagnostics.to_dict(),
            "evaluation_report_id": self.evaluation_report_id,
            "engineering_assets": list(self.engineering_assets),
            "engineering_asset_count": len(self.engineering_assets),
            "scope": "cost_free_diagnostic_pre_agent_baseline_materialization",
            "stage_exit_authority": False,
            "factor_selection_authority": False,
            "alpha_authority": False,
            "limitations": [
                "universe:engineering_integration_only_not_pit_research_universe",
                "performance:cost_free_diagnostic_only",
                "split:formal_walk_forward_protocol_must_be_frozen_before_result_interpretation",
                "selection:no_factor_selection_authority",
            ],
        }


def bind_us_b0_run_spec(
    certification_document: Mapping[str, object],
    universe_document: Mapping[str, object],
    *,
    denominator: USBaselineCandidateDenominator,
    minimum_cross_section: int = 10,
    minimum_evaluated_periods: int = 20,
    minimum_ic_periods: int = 20,
    fail_on_partial_realized_label: bool = True,
) -> tuple[USBaselineRunSpec, tuple[str, ...]]:
    if _text(certification_document.get("schema_version"), "certification.schema_version") != (
        "finagent.us-minute-certification-report.v1"
    ):
        raise ValueError("US-B0 requires the frozen US-D3 certification report schema")
    certification_blockers = _sequence(
        certification_document.get("blockers", ()),
        "certification.blockers",
    )
    if certification_blockers:
        raise ValueError("US-B0 requires blocker-free US-D3 certification evidence")
    if not _boolean(certification_document.get("certified"), "certification.certified"):
        raise ValueError("US-B0 requires certified US-D3 evidence")
    outcome = _text(certification_document.get("outcome"), "certification.outcome")
    if outcome not in _CERTIFIED_OUTCOMES:
        raise ValueError("US-B0 requires an accepted US-D3 certification outcome")
    certification_report_id = _text(
        certification_document.get("report_id"),
        "certification.report_id",
    )
    inputs = _mapping(certification_document.get("inputs"), "certification.inputs")
    certified_universe_id = _text(
        inputs.get("engineering_universe_id"),
        "certification.inputs.engineering_universe_id",
    )
    certified_universe_count = _integer(
        inputs.get("engineering_universe_count"),
        "certification.inputs.engineering_universe_count",
    )
    if not _boolean(
        inputs.get("engineering_universe_accepted"),
        "certification.inputs.engineering_universe_accepted",
    ):
        raise ValueError("US-D3 certification did not accept its EngineeringUniverse")
    if not _boolean(
        inputs.get("reconciliation_passed"),
        "certification.inputs.reconciliation_passed",
    ):
        raise ValueError("US-D3 certification did not bind a passing reconciliation")

    if _text(universe_document.get("schema_version"), "universe.schema_version") != (
        "finagent.us-engineering-universe-finalization-report.v2"
    ):
        raise ValueError("US-B0 requires the final US-I0 v2 EngineeringUniverse report")
    universe_blockers = _sequence(universe_document.get("blockers", ()), "universe.blockers")
    if universe_blockers:
        raise ValueError("US-B0 requires blocker-free final EngineeringUniverse evidence")
    quote_evidence = _mapping(universe_document.get("quote_evidence"), "universe.quote_evidence")
    if not _boolean(quote_evidence.get("passed"), "universe.quote_evidence.passed"):
        raise ValueError("US-B0 requires passing final-universe quote evidence")
    if not _boolean(universe_document.get("accepted"), "universe.accepted"):
        raise ValueError("final EngineeringUniverse is not accepted")
    universe_id = _text(universe_document.get("universe_id"), "universe.universe_id")
    universe_count = _integer(
        universe_document.get("accepted_mapping_count"),
        "universe.accepted_mapping_count",
    )
    if universe_id != certified_universe_id:
        raise ValueError("US-D3 certification/universe identity mismatch")
    if universe_count != certified_universe_count:
        raise ValueError("US-D3 certification/universe count mismatch")
    if not 20 <= universe_count <= 30:
        raise ValueError("formal US-B0 EngineeringUniverse size must be in 20..30")

    materialization = _mapping(
        universe_document.get("materialization"),
        "universe.materialization",
    )
    mappings = _sequence(materialization.get("mappings"), "universe.materialization.mappings")
    assets: list[str] = []
    for raw in mappings:
        row = _mapping(raw, "universe.materialization.mappings[]")
        if _text(row.get("status"), "universe.mapping.status") != "accepted_for_engineering":
            continue
        research = _mapping(row.get("research"), "universe.mapping.research")
        assets.append(
            _text(
                research.get("source_symbol"),
                "universe.mapping.research.source_symbol",
            )
        )
    ordered_assets = tuple(dict.fromkeys(assets))
    if len(ordered_assets) != universe_count:
        raise ValueError("final EngineeringUniverse mapping count does not match accepted count")

    selected_raw = universe_document.get("selected_symbols")
    if selected_raw is not None:
        selected = tuple(
            _text(item, "universe.selected_symbols[]")
            for item in _sequence(selected_raw, "universe.selected_symbols")
        )
        if set(selected) != set(ordered_assets):
            raise ValueError("final EngineeringUniverse selected-symbol/mapping mismatch")

    run_spec = USBaselineRunSpec(
        certification_report_id=certification_report_id,
        certification_outcome=outcome,
        engineering_universe_id=universe_id,
        denominator_id=denominator.denominator_id,
        minimum_cross_section=minimum_cross_section,
        minimum_evaluated_periods=minimum_evaluated_periods,
        minimum_ic_periods=minimum_ic_periods,
        fail_on_partial_realized_label=fail_on_partial_realized_label,
    )
    return run_spec, ordered_assets


def build_us_baseline_input_plan(
    resampled_plan: MinuteQueryPlan,
    label_plan: LabelQueryPlan,
    resampling_evidence: ResamplingEvidence,
    label_evidence: LabelSeriesEvidence,
    *,
    run_spec: USBaselineRunSpec,
) -> USBaselineInputPlan:
    query = resampled_plan.query
    label_query = label_plan.source_query
    if query.interval is not BarInterval.MINUTE_15:
        raise ValueError("US-B0 input plan requires canonical 15m bars")
    if query.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
        raise ValueError("US-B0 15m bars must use available_at")
    if query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-B0 input plan requires RAW research prices")
    if query.session_policy is not SessionPolicy.REGULAR:
        raise ValueError("US-B0 15m bars must use the regular session")
    if set(query.fields) != set(MarketDataField):
        raise ValueError("US-B0 input plan requires OHLCV fields")
    if label_query.interval is not BarInterval.MINUTE_1:
        raise ValueError("US-B0 label source must remain canonical 1m")
    if label_query.availability_policy is not AvailabilityPolicy.AVAILABLE_AT:
        raise ValueError("US-B0 label plan must use available_at")
    if label_query.adjustment_policy is not ResearchPriceBasis.RAW:
        raise ValueError("US-B0 labels must use RAW research prices")
    if label_query.session_policy is not SessionPolicy.REGULAR:
        raise ValueError("US-B0 labels must use the regular session")
    if label_query.fields != (MarketDataField.CLOSE,):
        raise ValueError("US-B0 label source fields must be exactly close")
    if query.assets != label_query.assets:
        raise ValueError("US-B0 resampled/label asset sets must match")
    if query.start != label_query.start or query.end != label_query.end:
        raise ValueError("US-B0 resampled/label query windows must match")
    if resampling_evidence.resampled_plan_id != resampled_plan.plan_id:
        raise ValueError("resampling evidence does not bind supplied 15m plan")
    if label_evidence.label_plan_id != label_plan.plan_id:
        raise ValueError("label evidence does not bind supplied label plan")
    if resampling_evidence.calendar_id != label_evidence.calendar_id:
        raise ValueError("US-B0 resampling/label calendar identity mismatch")
    if resampling_evidence.source_data_version != label_evidence.source_data_version:
        raise ValueError("US-B0 resampling/label source data identity mismatch")

    data_version = _canonical_hash(
        {
            "run_spec_id": run_spec.spec_id,
            "resampled_data_version": resampled_plan.data_version,
            "label_data_version": label_plan.data_version,
            "resampling_evidence_id": resampling_evidence.evidence_id,
            "label_evidence_id": label_evidence.evidence_id,
            "join_clock": "bar.available_at=label.source_available_at",
        },
        prefix="us-baseline-input-data-version",
    )
    output_columns = (
        "research_asset_id",
        "session_date",
        "session_id",
        "event_time",
        "available_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bar_index",
        "observed_minute_count",
        "expected_minute_count",
        "coverage_ratio",
        "is_complete",
        "source_event_time",
        "source_available_at",
        "source_price",
        "target_event_time",
        "target_available_at",
        "label_value",
        "label_available",
        "unavailable_reason",
        "label_row_present",
        "close_anchor_difference",
    )
    sql = f"""
        WITH bars AS (
            {resampled_plan.sql}
        ),
        labels AS (
            {label_plan.sql}
        )
        SELECT
            b.research_asset_id,
            b.session_date,
            b.session_id,
            b.event_time,
            b.available_at,
            CAST(b.open AS DOUBLE) AS open,
            CAST(b.high AS DOUBLE) AS high,
            CAST(b.low AS DOUBLE) AS low,
            CAST(b.close AS DOUBLE) AS close,
            CAST(b.volume AS DOUBLE) AS volume,
            b.bar_index,
            b.observed_minute_count,
            b.expected_minute_count,
            CAST(b.coverage_ratio AS DOUBLE) AS coverage_ratio,
            b.is_complete,
            l.source_event_time,
            l.source_available_at,
            CAST(l.source_price AS DOUBLE) AS source_price,
            l.target_event_time,
            l.target_available_at,
            CAST(l.label_value AS DOUBLE) AS label_value,
            l.label_available,
            l.unavailable_reason,
            l.source_available_at IS NOT NULL AS label_row_present,
            CASE
                WHEN l.source_price IS NULL THEN NULL
                ELSE abs(CAST(b.close AS DOUBLE) - CAST(l.source_price AS DOUBLE))
            END AS close_anchor_difference
        FROM bars AS b
        LEFT JOIN labels AS l
          ON l.research_asset_id = b.research_asset_id
         AND l.session_date = b.session_date
         AND l.source_available_at = b.available_at
        ORDER BY b.available_at, b.research_asset_id
    """.strip()
    partitions = tuple(
        sorted(set(resampled_plan.partition_months).union(label_plan.partition_months))
    )
    return USBaselineInputPlan(
        run_spec_id=run_spec.spec_id,
        resampled_plan_id=resampled_plan.plan_id,
        label_plan_id=label_plan.plan_id,
        resampling_evidence_id=resampling_evidence.evidence_id,
        label_evidence_id=label_evidence.evidence_id,
        source_data_version=resampling_evidence.source_data_version,
        data_version=data_version,
        sql=sql,
        partition_months=partitions,
        selected_size_bytes=max(
            resampled_plan.selected_size_bytes,
            label_plan.selected_size_bytes,
        ),
        output_columns=output_columns,
    )


def materialize_us_baseline_observations(
    rows: Sequence[Mapping[str, object]],
    denominator: USBaselineCandidateDenominator,
    *,
    expected_assets: Sequence[str],
) -> tuple[
    dict[str, tuple[USBaselineObservation, ...]],
    USBaselineMaterializationDiagnostics,
]:
    expected = tuple(dict.fromkeys(item.strip() for item in expected_assets if item.strip()))
    if not expected or len(expected) != len(tuple(expected_assets)):
        raise ValueError("expected_assets must be non-empty and unique")
    expected_set = set(expected)
    observed_assets: set[str] = set()
    complete_assets: set[str] = set()
    histories: dict[str, list[USBaselineBar]] = defaultdict(list)
    observations: dict[str, list[USBaselineObservation]] = {
        item.feature_id: [] for item in denominator.candidates
    }
    unavailable: dict[str, dict[str, int]] = {
        item.feature_id: defaultdict(int) for item in denominator.candidates
    }
    available_counts = {item.feature_id: 0 for item in denominator.candidates}
    complete_count = 0
    incomplete_count = 0
    anchor_missing = 0
    close_mismatch = 0
    label_available_count = 0
    crosses_count = 0
    target_missing_count = 0
    blockers: list[str] = []

    for raw in rows:
        asset = _text(raw.get("research_asset_id"), "row.research_asset_id")
        if asset not in expected_set:
            raise ValueError(f"US-B0 input contains asset outside EngineeringUniverse: {asset!r}")
        observed_assets.add(asset)
        event_time = _aware_datetime(raw.get("event_time"), "row.event_time")
        available_at = _aware_datetime(raw.get("available_at"), "row.available_at")
        session_id = _text(raw.get("session_id"), "row.session_id")
        bar = USBaselineBar(
            event_time=event_time,
            available_at=available_at,
            session_id=session_id,
            open=_float(raw.get("open"), "row.open"),
            high=_float(raw.get("high"), "row.high"),
            low=_float(raw.get("low"), "row.low"),
            close=_float(raw.get("close"), "row.close"),
            volume=_float(raw.get("volume"), "row.volume"),
            is_complete=_boolean(raw.get("is_complete"), "row.is_complete"),
        )
        history = histories[asset]
        if history and available_at <= history[-1].available_at:
            raise ValueError(f"non-increasing baseline formation clock for asset {asset!r}")
        history.append(bar)

        if not bar.is_complete:
            incomplete_count += 1
            continue
        complete_count += 1
        complete_assets.add(asset)

        label_row_present = _boolean(raw.get("label_row_present"), "row.label_row_present")
        if not label_row_present:
            anchor_missing += 1
            blockers.append(f"label_anchor_missing:{asset}:{available_at.isoformat()}")
            continue
        source_available_at = _aware_datetime(
            raw.get("source_available_at"),
            "row.source_available_at",
        )
        if source_available_at != available_at:
            raise ValueError("label source availability must equal feature formation time")
        source_price = _float(raw.get("source_price"), "row.source_price")
        difference = abs(bar.close - source_price)
        if difference > max(1e-12, abs(bar.close) * 1e-12):
            close_mismatch += 1
            blockers.append(f"close_anchor_mismatch:{asset}:{available_at.isoformat()}")
            continue

        label_available = _boolean(raw.get("label_available"), "row.label_available")
        label_value: float | None
        label_available_at: datetime | None
        unavailable_reason: str | None
        if label_available:
            label_value = _float(raw.get("label_value"), "row.label_value")
            label_available_at = _aware_datetime(
                raw.get("target_available_at"),
                "row.target_available_at",
            )
            unavailable_reason = None
            label_available_count += 1
        else:
            if raw.get("label_value") is not None:
                raise ValueError("unavailable label cannot carry label_value")
            if raw.get("target_available_at") is not None:
                raise ValueError("unavailable label cannot carry target_available_at")
            unavailable_reason = _text(raw.get("unavailable_reason"), "row.unavailable_reason")
            if unavailable_reason not in _ALLOWED_LABEL_UNAVAILABLE:
                raise ValueError("US-B0 input contains unknown D2 label unavailability reason")
            label_value = None
            label_available_at = None
            if unavailable_reason == "target_crosses_session":
                crosses_count += 1
            elif unavailable_reason == "target_minute_missing":
                target_missing_count += 1

        for spec in denominator.candidates:
            feature = evaluate_us_baseline_feature(
                spec,
                tuple(history),
                protocol=denominator.protocol,
            )
            if feature.value is None:
                reason = feature.unavailable_reason
                if reason is None:  # pragma: no cover - dataclass invariant
                    raise RuntimeError("unavailable feature is missing its reason")
                unavailable[spec.feature_id][reason.value] += 1
            else:
                available_counts[spec.feature_id] += 1
            observations[spec.feature_id].append(
                USBaselineObservation(
                    feature_id=spec.feature_id,
                    feature_spec_id=spec.spec_id,
                    asset=asset,
                    event_time=feature.event_time,
                    feature_available_at=feature.available_at,
                    eligible_at_formation=True,
                    feature_value=feature.value,
                    realized_label=label_value,
                    label_available_at=label_available_at,
                    label_unavailable_reason=unavailable_reason,
                )
            )

    candidate_checks = tuple(
        USBaselineCandidateMaterializationCheck(
            feature_id=spec.feature_id,
            feature_spec_id=spec.spec_id,
            observation_count=len(observations[spec.feature_id]),
            available_feature_count=available_counts[spec.feature_id],
            unavailable_reason_counts=tuple(sorted(unavailable[spec.feature_id].items())),
        )
        for spec in denominator.candidates
    )
    missing_assets = tuple(sorted(expected_set.difference(observed_assets)))
    assets_without_complete = tuple(sorted(expected_set.difference(complete_assets)))
    if missing_assets:
        blockers.append("input:engineering_assets_missing:" + ",".join(missing_assets))
    if assets_without_complete:
        blockers.append(
            "input:engineering_assets_without_complete_bar:" + ",".join(assets_without_complete)
        )
    if complete_count == 0:
        blockers.append("input:no_complete_15m_bars")
    if anchor_missing:
        blockers.append(f"input:label_anchor_missing_count:{anchor_missing}")
    if close_mismatch:
        blockers.append(f"input:close_anchor_mismatch_count:{close_mismatch}")

    diagnostics = USBaselineMaterializationDiagnostics(
        input_row_count=len(rows),
        expected_asset_count=len(expected),
        observed_asset_count=len(observed_assets),
        missing_assets=missing_assets,
        assets_without_complete_bar=assets_without_complete,
        complete_bar_count=complete_count,
        incomplete_bar_count=incomplete_count,
        label_anchor_missing_count=anchor_missing,
        close_anchor_mismatch_count=close_mismatch,
        label_available_count=label_available_count,
        target_crosses_session_count=crosses_count,
        target_minute_missing_count=target_missing_count,
        candidate_checks=candidate_checks,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    frozen = {
        feature_id: tuple(feature_rows)
        for feature_id, feature_rows in observations.items()
    }
    return frozen, diagnostics


def evaluate_materialized_us_baselines(
    denominator: USBaselineCandidateDenominator,
    observations_by_feature: Mapping[str, Sequence[USBaselineObservation]],
    *,
    run_spec: USBaselineRunSpec,
) -> USBaselineEvaluationReport:
    return evaluate_us_baseline_denominator(
        denominator,
        observations_by_feature,
        run_spec=run_spec,
    )


def _observation_payload(row: USBaselineObservation) -> dict[str, object]:
    return {
        "schema_version": row.schema_version,
        "feature_id": row.feature_id,
        "feature_spec_id": row.feature_spec_id,
        "asset": row.asset,
        "event_time": row.event_time.isoformat(),
        "feature_available_at": row.feature_available_at.isoformat(),
        "eligible_at_formation": row.eligible_at_formation,
        "feature_value": row.feature_value,
        "realized_label": row.realized_label,
        "label_available_at": (
            row.label_available_at.isoformat() if row.label_available_at is not None else None
        ),
        "label_unavailable_reason": row.label_unavailable_reason,
    }


def write_us_baseline_observation_artifact(
    observations_by_feature: Mapping[str, Sequence[USBaselineObservation]],
    output: str | Path,
    *,
    run_spec: USBaselineRunSpec,
) -> USBaselineObservationArtifact:
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        (
            row
            for rows in observations_by_feature.values()
            for row in rows
        ),
        key=lambda item: (
            item.feature_id,
            item.feature_available_at,
            item.asset,
        ),
    )
    digest = hashlib.sha256()
    with target.open("wb") as handle:
        for row in ordered:
            payload = json.dumps(
                _observation_payload(row),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8") + b"\n"
            handle.write(payload)
            digest.update(payload)
    return USBaselineObservationArtifact(
        run_spec_id=run_spec.spec_id,
        denominator_id=run_spec.denominator_id,
        row_count=len(ordered),
        content_sha256=digest.hexdigest(),
        output_filename=target.name,
    )


def build_us_baseline_materialization_report(
    *,
    run_spec: USBaselineRunSpec,
    input_plan: USBaselineInputPlan,
    input_materialization: MinuteMaterialization,
    observation_artifact: USBaselineObservationArtifact,
    diagnostics: USBaselineMaterializationDiagnostics,
    evaluation_report: USBaselineEvaluationReport,
    engineering_assets: tuple[str, ...],
) -> USBaselineMaterializationReport:
    blockers = list(diagnostics.blockers)
    blockers.extend(f"evaluation:{item}" for item in evaluation_report.blockers)
    merged_diagnostics = USBaselineMaterializationDiagnostics(
        input_row_count=diagnostics.input_row_count,
        expected_asset_count=diagnostics.expected_asset_count,
        observed_asset_count=diagnostics.observed_asset_count,
        missing_assets=diagnostics.missing_assets,
        assets_without_complete_bar=diagnostics.assets_without_complete_bar,
        complete_bar_count=diagnostics.complete_bar_count,
        incomplete_bar_count=diagnostics.incomplete_bar_count,
        label_anchor_missing_count=diagnostics.label_anchor_missing_count,
        close_anchor_mismatch_count=diagnostics.close_anchor_mismatch_count,
        label_available_count=diagnostics.label_available_count,
        target_crosses_session_count=diagnostics.target_crosses_session_count,
        target_minute_missing_count=diagnostics.target_minute_missing_count,
        candidate_checks=diagnostics.candidate_checks,
        blockers=tuple(dict.fromkeys(blockers)),
    )
    return USBaselineMaterializationReport(
        run_spec=run_spec,
        input_plan=input_plan,
        input_materialization=input_materialization,
        observation_artifact=observation_artifact,
        diagnostics=merged_diagnostics,
        evaluation_report_id=evaluation_report.report_id,
        engineering_assets=engineering_assets,
    )
