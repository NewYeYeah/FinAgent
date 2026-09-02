from __future__ import annotations

import argparse
import json
import tomllib
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import cast

from finagent.research.us_r1_authority import require_us_r1_stage_authority
from finagent.research.us_r1_contracts import (
    validate_us_r1_alpha_gate_policy,
    validate_us_r1_protocol_document,
)
from finagent.research.us_r1_evaluation_policy import (
    validate_us_r1_statistical_evaluation_policy,
)
from finagent.research.us_r1_final import build_us_r1_reviewed_evidence_manifest
from finagent.research.us_r1_final_validation import (
    validate_persisted_us_r1_final_evidence,
)
from finagent.research.us_r1_handoff import (
    parse_us_r1_candidate_denominator,
    validate_terminal_a0_review_document,
)
from finagent.research.us_r1_materialization import canonical_us_r1_feature_formation_policy
from finagent.research.us_r1_protocol import USR1Terminal
from finagent.research.us_r1_review import finalize_us_r1_alpha_gate_review
from finagent.research.us_r1_walkforward import validate_us_r1_walk_forward_document


def _read_mapping(path: Path) -> Mapping[str, object]:
    loaded = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise TypeError(f"JSON root must be an object: {path}")
    return cast(Mapping[str, object], loaded)


def _read_status(path: Path) -> Mapping[str, object]:
    with path.expanduser().resolve().open("rb") as handle:
        return cast(Mapping[str, object], tomllib.load(handle))


def _write_or_validate(path: Path, document: Mapping[str, object] | dict[str, object]) -> None:
    target = path.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    expected = dict(document)
    if target.exists():
        actual = json.loads(target.read_text(encoding="utf-8"))
        if actual != expected:
            raise SystemExit(f"existing immutable US-R1 review evidence differs: {target}")
        return
    target.write_text(
        json.dumps(expected, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay US-R1 materialized observations and deterministic inference, then create "
            "one immutable independent Alpha Gate review. The reviewer may accept the machine "
            "terminal or downgrade to SYSTEM_FAILURE only."
        )
    )
    parser.add_argument("--reviewer-id", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--reviewed-at", required=True, help="Timezone-aware ISO-8601 timestamp.")
    parser.add_argument(
        "--terminal",
        choices=tuple(item.value for item in USR1Terminal),
        help="Optional reviewer terminal; must equal assessment or SYSTEM_FAILURE.",
    )
    parser.add_argument("--attest-thresholds-unchanged", action="store_true")
    parser.add_argument("--attest-evidence-lineage", action="store_true")
    parser.add_argument("--attest-agent-value-separation", action="store_true")
    parser.add_argument("--attest-execution-gate-separation", action="store_true")
    parser.add_argument("--attest-live-capital-separation", action="store_true")
    parser.add_argument("--status", type=Path, default=Path("docs/status.toml"))
    parser.add_argument("--a0-gate-review", type=Path, required=True)
    parser.add_argument(
        "--research-protocol",
        type=Path,
        default=Path("reports/us_r1/us_r1_research_protocol.json"),
    )
    parser.add_argument(
        "--walk-forward",
        type=Path,
        default=Path("reports/us_r1/us_r1_walk_forward.json"),
    )
    parser.add_argument(
        "--formation-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_feature_formation_policy.json"),
    )
    parser.add_argument(
        "--evaluation-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_statistical_evaluation_policy.json"),
    )
    parser.add_argument(
        "--alpha-gate-policy",
        type=Path,
        default=Path("reports/us_r1/us_r1_alpha_gate_policy.json"),
    )
    parser.add_argument(
        "--candidate-denominator",
        type=Path,
        default=Path("reports/us_r1/us_r1_candidate_denominator.json"),
    )
    parser.add_argument("--fold-report-root", type=Path, default=Path("reports/us_r1/folds"))
    parser.add_argument("--fold-data-root", type=Path, default=Path("data/us_r1/folds"))
    parser.add_argument("--final-report-root", type=Path, default=Path("reports/us_r1/final"))
    parser.add_argument("--final-metric-root", type=Path, default=Path("data/us_r1/final"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    status = _read_status(args.status)
    authority = require_us_r1_stage_authority(status)
    review_id, review_phase, review_decision, review_experiment_id = (
        validate_terminal_a0_review_document(
            _read_mapping(args.a0_gate_review),
            authority=authority,
        )
    )
    research_protocol = validate_us_r1_protocol_document(dict(_read_mapping(args.research_protocol)))
    walk_forward = validate_us_r1_walk_forward_document(dict(_read_mapping(args.walk_forward)))
    formation = canonical_us_r1_feature_formation_policy()
    if dict(_read_mapping(args.formation_policy)) != formation.to_dict():
        raise SystemExit("US-R1 feature-formation policy differs from canonical preregistration")
    evaluation_policy = validate_us_r1_statistical_evaluation_policy(
        dict(_read_mapping(args.evaluation_policy))
    )
    alpha_gate_policy = validate_us_r1_alpha_gate_policy(
        dict(_read_mapping(args.alpha_gate_policy))
    )
    denominator = parse_us_r1_candidate_denominator(_read_mapping(args.candidate_denominator))
    if denominator.a0_gate_review_id != review_id or denominator.a0_experiment_id != review_experiment_id:
        raise SystemExit("US-R1 denominator differs from accepted A0 terminal authority")
    if denominator.a0_phase is not review_phase or denominator.a0_gate_decision is not review_decision:
        raise SystemExit("US-R1 denominator/A0 terminal phase or decision mismatch")

    artifacts = validate_persisted_us_r1_final_evidence(
        denominator,
        research_protocol_id=research_protocol.protocol_id,
        walk_forward_protocol_id=walk_forward.protocol_id,
        evaluation_policy=evaluation_policy,
        alpha_gate_policy=alpha_gate_policy,
        fold_report_root=args.fold_report_root,
        fold_data_root=args.fold_data_root,
        final_report_root=args.final_report_root,
        final_metric_root=args.final_metric_root,
    )
    reviewed_at = datetime.fromisoformat(args.reviewed_at)
    terminal = None if args.terminal is None else USR1Terminal(args.terminal)
    review = finalize_us_r1_alpha_gate_review(
        artifacts.assessment,
        reviewer_id=args.reviewer_id,
        reviewed_at=reviewed_at,
        review_notes=args.review_notes,
        terminal=terminal,
        thresholds_unchanged_attested=args.attest_thresholds_unchanged,
        evidence_lineage_attested=args.attest_evidence_lineage,
        agent_value_gate_separation_attested=args.attest_agent_value_separation,
        execution_gate_separation_attested=args.attest_execution_gate_separation,
        live_capital_separation_attested=args.attest_live_capital_separation,
    )
    reviewed_manifest = build_us_r1_reviewed_evidence_manifest(artifacts, review)
    final_root = args.final_report_root.expanduser().resolve()
    _write_or_validate(final_root / "us_r1_alpha_gate_review.json", review.to_dict())
    _write_or_validate(
        final_root / "us_r1_reviewed_evidence_manifest.json",
        reviewed_manifest.to_dict(),
    )

    print(
        json.dumps(
            {
                "review_id": review.review_id,
                "reviewed_evidence_manifest_id": reviewed_manifest.manifest_id,
                "terminal": review.terminal.value,
                "alpha_gate_authority": review.alpha_gate_authority,
                "alpha_authority": review.alpha_authority,
                "supports_us_x0_progression": review.supports_us_x0_progression,
                "robust_candidate_ids": list(reviewed_manifest.robust_candidate_ids),
                "status_authority": False,
                "stage_exit_authority": False,
                "order_authority": False,
                "live_capital_authority": False,
            },
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
    )
    return 2 if review.terminal is USR1Terminal.SYSTEM_FAILURE else 0


if __name__ == "__main__":
    raise SystemExit(main())
