#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

from finagent.research.ashare_reserve import (
    REQUIRED_V2_ACCEPTANCE_CHECKS,
    V2ReserveReviewAttestation,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create the explicit human V2 pre-reserve review attestation required by A5-1. "
            "This command does not access or consume reserve data."
        )
    )
    parser.add_argument("--program-result-id", required=True)
    parser.add_argument("--portfolio-validation-id", required=True)
    parser.add_argument("--review-bundle", type=Path, required=True)
    parser.add_argument("--workspace-commit-sha", required=True)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument(
        "--passed-check",
        action="append",
        choices=REQUIRED_V2_ACCEPTANCE_CHECKS,
        default=[],
        help="Repeat for every required V2 acceptance check that was reviewed as PASS.",
    )
    parser.add_argument("--confirm-protocol-identity-reviewed", action="store_true")
    parser.add_argument("--confirm-execution-ledger-reviewed", action="store_true")
    parser.add_argument("--confirm-reserve-untouched", action="store_true")
    parser.add_argument("--confirm-no-post-a4-mutation", action="store_true")
    parser.add_argument("--confirm-no-agent-feedback-path", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    import hashlib

    checks = {name: name in set(args.passed_check) for name in REQUIRED_V2_ACCEPTANCE_CHECKS}
    attestation = V2ReserveReviewAttestation(
        program_result_id=args.program_result_id,
        portfolio_validation_id=args.portfolio_validation_id,
        review_bundle_sha256=hashlib.sha256(args.review_bundle.read_bytes()).hexdigest(),
        workspace_commit_sha=args.workspace_commit_sha,
        reviewed_by=args.reviewed_by,
        reviewed_at=datetime.now(tz=UTC),
        checks=checks,
        protocol_identity_reviewed=args.confirm_protocol_identity_reviewed,
        execution_ledger_reviewed=args.confirm_execution_ledger_reviewed,
        reserve_untouched_confirmed=args.confirm_reserve_untouched,
        no_post_a4_mutation_confirmed=args.confirm_no_post_a4_mutation,
        no_agent_feedback_path_confirmed=args.confirm_no_agent_feedback_path,
    )
    attestation.write_json(args.output)
    print(attestation.attestation_id)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
