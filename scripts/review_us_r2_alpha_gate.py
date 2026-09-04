from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import cast

from finagent.research.us_r2_final import (
    build_us_r2_final_artifacts_from_documents,
    finalize_us_r2_alpha_gate_review,
)
from finagent.research.us_r2_protocol import USR2Terminal


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
            raise SystemExit(f"existing immutable US-R2 review evidence differs: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _require_exact(path: Path, expected: Mapping[str, object]) -> None:
    actual = _read_mapping(path)
    if dict(actual) != dict(expected):
        raise SystemExit(f"persisted US-R2 final evidence differs from independent replay: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reconstruct and review the terminal US-R2 Alpha Gate. The reviewer "
            "may accept the deterministic terminal or downgrade it to SYSTEM_FAILURE only."
        )
    )
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--reviewed-at", required=True, help="Timezone-aware ISO-8601 timestamp")
    parser.add_argument(
        "--terminal",
        choices=tuple(item.value for item in USR2Terminal),
        help="Optional reviewed terminal; defaults to the deterministic assessment.",
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
    parser.add_argument("--final-root", type=Path, default=Path("reports/us_r2/final"))
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
    root = args.final_root.expanduser().resolve()
    _require_exact(root / "us_r2_alpha_gate_policy.json", artifacts.policy.to_dict())
    _require_exact(root / "us_r2_final_family_evidence.json", artifacts.family.to_dict())
    _require_exact(root / "us_r2_alpha_gate_assessment.json", artifacts.assessment.to_dict())
    _require_exact(root / "us_r2_inference_evidence_graph.json", artifacts.graph.to_dict())
    chosen = None if args.terminal is None else USR2Terminal(args.terminal)
    review, manifest = finalize_us_r2_alpha_gate_review(
        artifacts,
        reviewer_id=args.reviewer_id,
        reviewed_at=datetime.fromisoformat(args.reviewed_at),
        review_notes=args.review_notes,
        terminal=chosen,
    )
    _write_or_validate(root / "us_r2_alpha_gate_review.json", review.to_dict())
    _write_or_validate(root / "us_r2_reviewed_evidence_manifest.json", manifest.to_dict())
    print(
        json.dumps(
            {
                "review_id": review.review_id,
                "reviewed_evidence_manifest_id": manifest.manifest_id,
                "terminal": review.terminal.value,
                "robust_candidate_ids": list(manifest.robust_candidate_ids),
                "alpha_gate_authority": review.alpha_gate_authority,
                "alpha_authority": review.alpha_authority,
                "supports_us_x0_progression": review.supports_us_x0_progression,
                "status_authority": False,
                "stage_exit_authority": False,
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
    return 2 if review.terminal is USR2Terminal.SYSTEM_FAILURE else 0


if __name__ == "__main__":
    raise SystemExit(main())
