from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from finagent.data.minute_store import MinuteMaterialization
from finagent.research.us_r1_materialization import (
    USR1MaterializationSlice,
    USR1ObservationArtifact,
    USR1ObservationDiagnostics,
)
from finagent.research.us_r1_materialization_evidence import (
    parse_minute_materialization,
    parse_us_r1_materialization_slice,
    parse_us_r1_observation_artifact,
    parse_us_r1_observation_diagnostics,
    validate_us_r1_input_plan_document,
)


@dataclass(frozen=True, slots=True)
class ParsedUSR1MaterializationSliceEvidence:
    input_plan_id: str
    input_materialization: MinuteMaterialization
    observation_artifact: USR1ObservationArtifact
    diagnostics: USR1ObservationDiagnostics
    materialization_slice: USR1MaterializationSlice


def parse_us_r1_materialization_slice_bundle(
    *,
    input_plan_document: Mapping[str, object],
    input_materialization_document: Mapping[str, object],
    observation_artifact_document: Mapping[str, object],
    diagnostics_document: Mapping[str, object],
    slice_document: Mapping[str, object],
) -> ParsedUSR1MaterializationSliceEvidence:
    input_plan_id = validate_us_r1_input_plan_document(input_plan_document)
    materialization = parse_minute_materialization(input_materialization_document)
    artifact = parse_us_r1_observation_artifact(observation_artifact_document)
    diagnostics = parse_us_r1_observation_diagnostics(diagnostics_document)
    materialization_slice = parse_us_r1_materialization_slice(slice_document)

    if materialization.plan_id != input_plan_id:
        raise ValueError("US-R1 persisted input materialization/input-plan identity mismatch")
    if artifact.input_plan_id != input_plan_id:
        raise ValueError("US-R1 persisted observation artifact/input-plan identity mismatch")
    if materialization_slice.input_plan_id != input_plan_id:
        raise ValueError("US-R1 persisted slice/input-plan identity mismatch")
    if materialization_slice.input_materialization_id != materialization.materialization_id:
        raise ValueError("US-R1 persisted slice/input-materialization identity mismatch")
    if materialization_slice.observation_artifact_id != artifact.artifact_id:
        raise ValueError("US-R1 persisted slice/observation-artifact identity mismatch")
    if materialization_slice.diagnostics_id != diagnostics.diagnostics_id:
        raise ValueError("US-R1 persisted slice/diagnostics identity mismatch")
    if materialization_slice.input_row_count != materialization.row_count:
        raise ValueError("US-R1 persisted slice input row count mismatch")
    if materialization_slice.observation_row_count != artifact.row_count:
        raise ValueError("US-R1 persisted slice observation row count mismatch")
    if materialization_slice.passed is not diagnostics.passed:
        raise ValueError("US-R1 persisted slice passed flag differs from diagnostics")
    if materialization_slice.blockers != diagnostics.blockers:
        raise ValueError("US-R1 persisted slice blockers differ from diagnostics")
    if materialization_slice.role is not artifact.role:
        raise ValueError("US-R1 persisted slice/artifact role mismatch")
    if materialization_slice.signal_interval is not artifact.signal_interval:
        raise ValueError("US-R1 persisted slice/artifact frequency mismatch")
    if materialization_slice.label_horizon_trading_minutes != (
        artifact.label_horizon_trading_minutes
    ):
        raise ValueError("US-R1 persisted slice/artifact label horizon mismatch")
    return ParsedUSR1MaterializationSliceEvidence(
        input_plan_id=input_plan_id,
        input_materialization=materialization,
        observation_artifact=artifact,
        diagnostics=diagnostics,
        materialization_slice=materialization_slice,
    )
