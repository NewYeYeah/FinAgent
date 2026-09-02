from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from finagent.research.us_agent_value_experiment import (
    USAgentValuePredecessorBinding,
    bind_us_a0_predecessor,
)
from finagent.research.us_agent_value_protocol import USAgentValueExperimentProtocol


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def _sequence(value: object, field_name: str) -> Sequence[object]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be a sequence")
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


def _ids(value: object, field_name: str) -> tuple[str, ...]:
    return tuple(_text(item, f"{field_name}[]") for item in _sequence(value, field_name))


@dataclass(frozen=True, slots=True)
class USAgentValueStageAuthority:
    us_b0_evidence_graph_id: str
    us_b0_aggregate_report_id: str
    schema_version: str = "finagent.us-agent-value-stage-authority.v1"

    def __post_init__(self) -> None:
        for field_name in ("us_b0_evidence_graph_id", "us_b0_aggregate_report_id"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must be non-empty")
            object.__setattr__(self, field_name, value)


def require_us_a0_stage_authority(
    status_document: Mapping[str, object],
) -> USAgentValueStageAuthority:
    """Require the sole project-stage authority to have explicitly accepted US-B0.

    A content hash proves identity, not acceptance. Formal A0 execution must therefore bind
    the B0 graph/report IDs recorded in docs/status.toml after human review.
    """

    if _text(status_document.get("current_stage"), "status.current_stage") != "US-A0":
        raise ValueError("formal US-A0 execution requires docs/status.toml current_stage=US-A0")
    stages = _mapping(status_document.get("stage"), "status.stage")
    us_b0 = _mapping(stages.get("us_b0"), "status.stage.us_b0")
    if _text(us_b0.get("status"), "status.stage.us_b0.status") != "accepted":
        raise ValueError("formal US-A0 execution requires accepted US-B0 stage authority")
    if us_b0.get("stage_exit_gate_passed") is not True:
        raise ValueError("formal US-A0 execution requires US-B0 stage_exit_gate_passed=true")
    return USAgentValueStageAuthority(
        us_b0_evidence_graph_id=_text(
            us_b0.get("walk_forward_evidence_graph_id"),
            "status.stage.us_b0.walk_forward_evidence_graph_id",
        ),
        us_b0_aggregate_report_id=_text(
            us_b0.get("walk_forward_aggregate_report_id"),
            "status.stage.us_b0.walk_forward_aggregate_report_id",
        ),
    )


def _validate_full_b0_graph_shape(document: Mapping[str, object]) -> None:
    if _integer(document.get("fold_count"), "us_b0.fold_count") != 3:
        raise ValueError("formal US-A0 predecessor requires all three frozen US-B0 folds")
    if _text(document.get("scope"), "us_b0.scope") != "split_bound_manual_baseline_evidence_graph":
        raise ValueError("formal US-A0 predecessor has unexpected US-B0 evidence scope")

    manifest_ids = _ids(document.get("fold_manifest_ids"), "us_b0.fold_manifest_ids")
    execution_ids = _ids(
        document.get("fold_execution_spec_ids"),
        "us_b0.fold_execution_spec_ids",
    )
    materialization_ids = _ids(
        document.get("fold_materialization_report_ids"),
        "us_b0.fold_materialization_report_ids",
    )
    evaluation_ids = _ids(
        document.get("fold_evaluation_report_ids"),
        "us_b0.fold_evaluation_report_ids",
    )
    for field_name, values in (
        ("fold_manifest_ids", manifest_ids),
        ("fold_execution_spec_ids", execution_ids),
        ("fold_materialization_report_ids", materialization_ids),
        ("fold_evaluation_report_ids", evaluation_ids),
    ):
        if len(values) != 3 or len(set(values)) != 3:
            raise ValueError(f"formal US-A0 predecessor requires three unique {field_name}")

    raw_manifests = _sequence(document.get("fold_manifests"), "us_b0.fold_manifests")
    if len(raw_manifests) != 3:
        raise ValueError("formal US-A0 predecessor requires three embedded fold manifests")
    for index, raw in enumerate(raw_manifests):
        manifest = _mapping(raw, f"us_b0.fold_manifests[{index}]")
        if _text(manifest.get("manifest_id"), f"us_b0.fold_manifests[{index}].manifest_id") != (
            manifest_ids[index]
        ):
            raise ValueError("US-B0 embedded fold manifest identity/order mismatch")
        execution = _mapping(
            manifest.get("execution_spec"),
            f"us_b0.fold_manifests[{index}].execution_spec",
        )
        if _text(
            execution.get("execution_spec_id"),
            f"us_b0.fold_manifests[{index}].execution_spec.execution_spec_id",
        ) != execution_ids[index]:
            raise ValueError("US-B0 embedded fold execution identity/order mismatch")
        if _text(
            manifest.get("materialization_report_id"),
            f"us_b0.fold_manifests[{index}].materialization_report_id",
        ) != materialization_ids[index]:
            raise ValueError("US-B0 embedded fold materialization identity/order mismatch")
        if _text(
            manifest.get("evaluation_report_id"),
            f"us_b0.fold_manifests[{index}].evaluation_report_id",
        ) != evaluation_ids[index]:
            raise ValueError("US-B0 embedded fold evaluation identity/order mismatch")


def bind_authorized_us_a0_predecessor(
    status_document: Mapping[str, object],
    evidence_graph_document: Mapping[str, object],
    protocol: USAgentValueExperimentProtocol,
) -> USAgentValuePredecessorBinding:
    authority = require_us_a0_stage_authority(status_document)
    _validate_full_b0_graph_shape(evidence_graph_document)
    binding = bind_us_a0_predecessor(evidence_graph_document, protocol)
    if binding.us_b0_evidence_graph_id != authority.us_b0_evidence_graph_id:
        raise ValueError("US-B0 graph identity does not match project-stage authority")
    if binding.us_b0_aggregate_report_id != authority.us_b0_aggregate_report_id:
        raise ValueError("US-B0 aggregate identity does not match project-stage authority")
    return binding
