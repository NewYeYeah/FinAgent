from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from finagent.research.us_r2_final import build_us_r2_final_artifacts_from_documents


def _read_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], loaded)


def _write_or_validate(path: Path, document: Mapping[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        actual = json.loads(target.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit(f"existing immutable US-R2 final evidence differs: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Assemble the deterministic US-R2 Alpha Gate from the frozen 37-candidate "
            "primary, pooled-inference and per-regime robustness evidence."
        )
    )
    parser.add_argument(
        "--frozen-protocol",
        type=Path,
        default=Path("reports/us_r2/us_r2_frozen_protocol.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument(
        "--primary-statistics",
        type=Path,
        default=Path("reports/us_r2/primary/us_r2_primary_statistics_report.json"),
    )
    parser.add_argument(
        "--pooled-inference",
        type=Path,
        default=Path("reports/us_r2/primary/us_r2_pooled_inference_report.json"),
    )
    parser.add_argument(
        "--candidate-robustness",
        type=Path,
        default=Path("reports/us_r2/robustness/candidate/us_r2_candidate_robustness_report.json"),
    )
    parser.add_argument("--output-root", type=Path, default=Path("reports/us_r2/final"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    artifacts = build_us_r2_final_artifacts_from_documents(
        frozen_protocol_document=_read_mapping(args.frozen_protocol),
        denominator_document=_read_mapping(args.candidate_denominator),
        primary_statistics_document=_read_mapping(args.primary_statistics),
        pooled_inference_document=_read_mapping(args.pooled_inference),
        candidate_robustness_document=_read_mapping(args.candidate_robustness),
    )
    output = args.output_root.expanduser().resolve()
    _write_or_validate(output / "us_r2_alpha_gate_policy.json", artifacts.policy.to_dict())
    _write_or_validate(output / "us_r2_final_family_evidence.json", artifacts.family.to_dict())
    _write_or_validate(output / "us_r2_alpha_gate_assessment.json", artifacts.assessment.to_dict())
    _write_or_validate(output / "us_r2_inference_evidence_graph.json", artifacts.graph.to_dict())
    print(
        json.dumps(
            {
                "alpha_gate_policy_id": artifacts.policy.policy_id,
                "family_evidence_id": artifacts.family.evidence_id,
                "alpha_gate_assessment_id": artifacts.assessment.assessment_id,
                "inference_graph_id": artifacts.graph.graph_id,
                "terminal": artifacts.assessment.terminal.value,
                "robust_candidate_ids": list(artifacts.assessment.robust_candidate_ids),
                "candidate_count": len(artifacts.assessment.candidates),
                "thresholds_relaxed": False,
                "performance_filter_applied": False,
                "alpha_gate_reviewed": False,
                "status_authority": False,
                "stage_exit_authority": False,
                "alpha_authority": False,
                "execution_authority": False,
                "order_authority": False,
                "paper_authority": False,
                "live_capital_authority": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 2 if artifacts.assessment.terminal.value == "SYSTEM_FAILURE" else 0


if __name__ == "__main__":
    raise SystemExit(main())
