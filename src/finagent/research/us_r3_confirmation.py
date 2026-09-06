"""Blind final-return admission using an independently supplied receipt digest.

The trusted receipt digest is a host/operator trust root, never a model field.
Its attestation must be obtained from an independent reviewer. This module does
not authenticate a reviewer by accepting a self-declared name inside data.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from finagent.research.us_r3_economic_campaign import _sealed, digest, file_digest
from finagent.research.us_r3_inference import (
    EvidenceDesign,
    confirmation_terminal,
    describe_returns,
)
from finagent.research.us_r3_usability import write_immutable_json


def confirm_returns(
    *,
    model_path: Path,
    protocol_path: Path,
    receipt_path: Path,
    trusted_receipt_sha256: str,
    returns_path: Path,
    output: Path,
) -> dict[str, Any]:
    # Final data is not opened until the externally bound attestation is checked.
    if len(trusted_receipt_sha256) != 64 or file_digest(receipt_path) != trusted_receipt_sha256:
        raise ValueError("independent receipt trust root mismatch")
    receipt = json.loads(receipt_path.read_text())
    model = _sealed(model_path, "evidence_id", "r3-frozen-model-")
    protocol = _sealed(protocol_path, "evidence_id", "us-r3-completion-protocol-")
    if (
        receipt.get("model_id") != model["evidence_id"]
        or receipt.get("protocol_id") != protocol["evidence_id"]
        or model["protocol_id"] != protocol["evidence_id"]
        or not receipt.get("independent_reviewer_id")
        or receipt.get("not_previously_exposed") is not True
        or receipt.get("point_in_time_universe_admitted") is not True
        or receipt.get("cost_and_execution_evidence_admitted") is not True
    ):
        raise ValueError("independent source/model/economic admission missing")
    frozen = datetime.fromisoformat(model["frozen_at_utc"])
    admitted_at = datetime.fromisoformat(receipt["preregistered_at_utc"])
    start = datetime.fromisoformat(receipt["observations_start_utc"])
    end = datetime.fromisoformat(receipt["observations_end_utc"])
    if (
        any(d.tzinfo is None for d in (frozen, admitted_at, start, end))
        or not frozen <= admitted_at < start <= end
    ):
        raise ValueError("prospective chronology not established")
    required = {f"{m['method']}-{m['run']}" for m in model["members"]}
    design = EvidenceDesign(
        **{k: protocol["design"][k] for k in EvidenceDesign.__dataclass_fields__}
    )
    if design.family_size < 2 * len(required):
        raise ValueError("confirmation multiplicity denominator is too small")
    scheduled = receipt.get("scheduled_sessions", [])
    if (
        not scheduled
        or scheduled != sorted(set(scheduled))
        or scheduled[0] < start.date().isoformat()
        or scheduled[-1] > end.date().isoformat()
        or receipt.get("cost_bps") != 5.0
        or len(scheduled) != design.to_dict()["planning_calendar_sessions"]
    ):
        raise ValueError("final calendar/cost/fixed endpoint admission missing")
    if file_digest(returns_path) != receipt.get("returns_sha256"):
        raise ValueError("independent return evidence digest mismatch")
    data = json.loads(returns_path.read_text())
    if data.get("model_id") != model["evidence_id"] or set(data.get("series", {})) != required:
        raise ValueError("final membership must exactly match frozen model")
    days = data.get("sessions", [])
    if (
        not days
        or days != sorted(set(days))
        or days[0] < start.date().isoformat()
        or days[-1] > end.date().isoformat()
    ):
        raise ValueError("invalid final calendar denominator")
    if days != receipt.get("scheduled_sessions") or receipt.get("cost_bps") != 5.0:
        raise ValueError("final calendar/cost policy was not independently admitted")
    control = data.get("equal_weight_net_returns", [])
    if len(control) != len(days):
        raise ValueError("final control denominator mismatch")
    describe_returns(control, design)  # Validate the actual control path's solvency too.
    findings = {}
    for name, values in data["series"].items():
        if len(values) != len(days):
            raise ValueError("final candidate denominator mismatch")
        stats = describe_returns(values, design)
        excess = [
            a - b if a is not None and b is not None else None
            for a, b in zip(values, control, strict=True)
        ]
        relative = describe_returns(excess, design, paired=True)
        effective = (
            min(
                cast(float, stats["effective_sessions_diagnostic"]),
                cast(float, relative["effective_sessions_diagnostic"]),
            )
            if stats.get("effective_sessions_diagnostic") is not None
            and relative.get("effective_sessions_diagnostic") is not None
            else None
        )
        economic_pass = bool(
            stats.get("compounded_return", -1) is not None
            and cast(float, stats.get("compounded_return", -1)) > 0
            and cast(float, relative.get("mean_bps", -1)) >= design.effect_bps
        )
        statistical_pass = all(
            s.get("hac_family_lower_mean_bps") is not None
            and cast(float, s["hac_family_lower_mean_bps"]) > 0
            for s in (stats, relative)
        )
        findings[name] = {
            "statistics": stats,
            "relative_statistics": relative,
            "terminal": confirmation_terminal(
                admitted=True,
                independent_review_id=receipt["independent_reviewer_id"],
                effective_sessions=effective,
                minimum_sessions=cast(int, design.to_dict()["minimum_effective_sessions"]),
                statistical_pass=statistical_pass,
                economic_pass=economic_pass,
            ),
        }
    report = {
        "schema_version": "finagent.us-r3-independent-confirmation.v1",
        "model_id": model["evidence_id"],
        "protocol_id": protocol["evidence_id"],
        "confirmation_implementation_sha256": file_digest(Path(__file__)),
        "trusted_receipt_sha256": trusted_receipt_sha256,
        "findings": findings,
        "authority_scope": "independently attested final return artifact; broker authority remains false",
        "broker_authority": False,
        "alpha_authority": False,
        "independent_statistical_review_required": True,
    }
    report["evidence_id"] = "us-r3-confirmation-" + digest(report)
    write_immutable_json(output, report)
    return report
