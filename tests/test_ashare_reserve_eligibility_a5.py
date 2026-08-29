from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from finagent.research.ashare_reserve import (
    REQUIRED_V2_ACCEPTANCE_CHECKS,
    ReserveAuthorityBoundary,
    ReserveEligibilitySealer,
    SQLiteReserveEligibilityStore,
    V2ReserveReviewAttestation,
    execution_ledger_digest,
)
from finagent.visualization.workspace_api import WorkspaceEvidenceCatalog
from finagent.visualization.workspace_v2 import WorkspaceV2Projection

from tests.test_workspace_api_v2 import _fixture


NOW = datetime(2026, 8, 29, 2, 30, tzinfo=UTC)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _prepared(tmp_path: Path):
    a26, a4, _ = _fixture(tmp_path)
    a26_replay = copy.deepcopy(a26)
    a26_replay["mode"] = "replay"
    a4_replay = copy.deepcopy(a4)
    a4_replay["mode"] = "replay"
    _write_json(tmp_path / "a26_replay.json", a26_replay)
    _write_json(tmp_path / "a4_replay.json", a4_replay)

    catalog = WorkspaceEvidenceCatalog((tmp_path,), git_sha="workspace-v2-pass-sha")
    projection = WorkspaceV2Projection(
        catalog.bundles(), report_paths=(tmp_path,), git_sha="workspace-v2-pass-sha"
    )
    bundle = projection.review_bundle(str(a4["portfolio_validation_id"]))
    bundle_path = tmp_path / "review.zip"
    bundle_path.write_bytes(bundle)
    attestation = V2ReserveReviewAttestation(
        program_result_id=str(a26["program_result_id"]),
        portfolio_validation_id=str(a4["portfolio_validation_id"]),
        review_bundle_sha256=hashlib.sha256(bundle).hexdigest(),
        workspace_commit_sha="workspace-v2-pass-sha",
        reviewed_by="human-reviewer",
        reviewed_at=NOW,
        checks={name: True for name in REQUIRED_V2_ACCEPTANCE_CHECKS},
        protocol_identity_reviewed=True,
        execution_ledger_reviewed=True,
        reserve_untouched_confirmed=True,
        no_post_a4_mutation_confirmed=True,
        no_agent_feedback_path_confirmed=True,
    )
    attestation_path = tmp_path / "review_attestation.json"
    attestation.write_json(attestation_path)
    return a26, a4, a26_replay, a4_replay, bundle, attestation


def _seal(tmp_path: Path, *, code_git_sha: str = "a5-code-sha"):
    _prepared(tmp_path)
    return ReserveEligibilitySealer().seal_from_paths(
        a26_report_path=tmp_path / "a26.json",
        a26_replay_path=tmp_path / "a26_replay.json",
        a4_report_path=tmp_path / "a4.json",
        a4_replay_path=tmp_path / "a4_replay.json",
        ledger_path=tmp_path / "a4_ledger.jsonl",
        review_bundle_path=tmp_path / "review.zip",
        review_attestation_path=tmp_path / "review_attestation.json",
        code_git_sha=code_git_sha,
        created_at=NOW,
    )


def test_a5p1_seals_exact_frozen_protocol_without_consuming_reserve(tmp_path: Path) -> None:
    _prepared(tmp_path)
    sources = {
        path.name: path.read_bytes()
        for path in (
            tmp_path / "a26.json",
            tmp_path / "a4.json",
            tmp_path / "a4_ledger.jsonl",
            tmp_path / "review.zip",
        )
    }
    seal = ReserveEligibilitySealer().seal_from_paths(
        a26_report_path=tmp_path / "a26.json",
        a26_replay_path=tmp_path / "a26_replay.json",
        a4_report_path=tmp_path / "a4.json",
        a4_replay_path=tmp_path / "a4_replay.json",
        ledger_path=tmp_path / "a4_ledger.jsonl",
        review_bundle_path=tmp_path / "review.zip",
        review_attestation_path=tmp_path / "review_attestation.json",
        code_git_sha="a5-code-sha",
        created_at=NOW,
    )
    assert seal.reserve_id == "reserve-v1"
    assert seal.reserve_start == "2025-01-01T00:00:00+00:00"
    assert seal.reserve_end == "2026-01-01T00:00:00+00:00"
    assert seal.selected_feature_digests == ("a" * 64,)
    assert seal.selected_weights == (1.0,)
    assert seal.selected_directions == (1,)
    assert seal.to_dict()["eligibility_status"] == "ELIGIBLE_SEALED"
    assert seal.to_dict()["reserve_consumed"] is False
    assert seal.to_dict()["reserve"]["status"] == "untouched"  # type: ignore[index]
    assert all(path.read_bytes() == sources[path.name] for path in map(tmp_path.__truediv__, sources))


def test_a5p1_seal_identity_is_deterministic_and_store_is_append_only(tmp_path: Path) -> None:
    seal = _seal(tmp_path)
    repeated = ReserveEligibilitySealer().seal_from_paths(
        a26_report_path=tmp_path / "a26.json",
        a26_replay_path=tmp_path / "a26_replay.json",
        a4_report_path=tmp_path / "a4.json",
        a4_replay_path=tmp_path / "a4_replay.json",
        ledger_path=tmp_path / "a4_ledger.jsonl",
        review_bundle_path=tmp_path / "review.zip",
        review_attestation_path=tmp_path / "review_attestation.json",
        code_git_sha="a5-code-sha",
        created_at=datetime(2026, 8, 29, 3, 0, tzinfo=UTC),
    )
    assert repeated.seal_id == seal.seal_id

    store = SQLiteReserveEligibilityStore(tmp_path / "eligibility.sqlite")
    store.register(seal)
    store.register(seal)
    store.register(repeated)
    assert store.get(seal.seal_id)["reserve_consumed"] is False
    assert store.get_for_reserve("reserve-v1")["seal_id"] == seal.seal_id

    different_code = ReserveEligibilitySealer().seal_from_paths(
        a26_report_path=tmp_path / "a26.json",
        a26_replay_path=tmp_path / "a26_replay.json",
        a4_report_path=tmp_path / "a4.json",
        a4_replay_path=tmp_path / "a4_replay.json",
        ledger_path=tmp_path / "a4_ledger.jsonl",
        review_bundle_path=tmp_path / "review.zip",
        review_attestation_path=tmp_path / "review_attestation.json",
        code_git_sha="different-a5-code-sha",
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="different eligibility seal"):
        store.register(different_code)


def test_a5p1_rejects_non_untouched_reserve(tmp_path: Path) -> None:
    a26, _, _, _, _, _ = _prepared(tmp_path)
    changed = copy.deepcopy(a26)
    changed["reserve"]["status"] = "consumed"  # type: ignore[index]
    _write_json(tmp_path / "a26.json", changed)
    with pytest.raises(PermissionError, match="reserve is not untouched"):
        ReserveEligibilitySealer().seal_from_paths(
            a26_report_path=tmp_path / "a26.json",
            a26_replay_path=tmp_path / "a26_replay.json",
            a4_report_path=tmp_path / "a4.json",
            a4_replay_path=tmp_path / "a4_replay.json",
            ledger_path=tmp_path / "a4_ledger.jsonl",
            review_bundle_path=tmp_path / "review.zip",
            review_attestation_path=tmp_path / "review_attestation.json",
            code_git_sha="a5-code-sha",
            created_at=NOW,
        )


def test_a5p1_rejects_a2p6_a4_identity_or_factor_mutation(tmp_path: Path) -> None:
    _, a4, _, _, _, _ = _prepared(tmp_path)
    changed = copy.deepcopy(a4)
    changed["validation_spec"]["selected_weights"] = [0.9]  # type: ignore[index]
    _write_json(tmp_path / "a4.json", changed)
    with pytest.raises(ValueError, match="selected weights drifted"):
        ReserveEligibilitySealer().seal_from_paths(
            a26_report_path=tmp_path / "a26.json",
            a26_replay_path=tmp_path / "a26_replay.json",
            a4_report_path=tmp_path / "a4.json",
            a4_replay_path=tmp_path / "a4_replay.json",
            ledger_path=tmp_path / "a4_ledger.jsonl",
            review_bundle_path=tmp_path / "review.zip",
            review_attestation_path=tmp_path / "review_attestation.json",
            code_git_sha="a5-code-sha",
            created_at=NOW,
        )


def test_a5p1_rejects_non_exact_replay(tmp_path: Path) -> None:
    _, _, a26_replay, _, _, _ = _prepared(tmp_path)
    changed = copy.deepcopy(a26_replay)
    changed["gate_report"]["candidates"][0]["robust_score"] = 999.0  # type: ignore[index]
    _write_json(tmp_path / "a26_replay.json", changed)
    with pytest.raises(ValueError, match="A2.6 exact replay differs"):
        ReserveEligibilitySealer().seal_from_paths(
            a26_report_path=tmp_path / "a26.json",
            a26_replay_path=tmp_path / "a26_replay.json",
            a4_report_path=tmp_path / "a4.json",
            a4_replay_path=tmp_path / "a4_replay.json",
            ledger_path=tmp_path / "a4_ledger.jsonl",
            review_bundle_path=tmp_path / "review.zip",
            review_attestation_path=tmp_path / "review_attestation.json",
            code_git_sha="a5-code-sha",
            created_at=NOW,
        )


def test_a5p1_rejects_ledger_drift(tmp_path: Path) -> None:
    _prepared(tmp_path)
    with (tmp_path / "a4_ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(_canonical_json({"unexpected": True}) + "\n")
    with pytest.raises(ValueError, match="ledger_digest does not match"):
        ReserveEligibilitySealer().seal_from_paths(
            a26_report_path=tmp_path / "a26.json",
            a26_replay_path=tmp_path / "a26_replay.json",
            a4_report_path=tmp_path / "a4.json",
            a4_replay_path=tmp_path / "a4_replay.json",
            ledger_path=tmp_path / "a4_ledger.jsonl",
            review_bundle_path=tmp_path / "review.zip",
            review_attestation_path=tmp_path / "review_attestation.json",
            code_git_sha="a5-code-sha",
            created_at=NOW,
        )


def test_a5p1_requires_complete_v2_acceptance_and_review_attestation(tmp_path: Path) -> None:
    a26, a4, _, _, bundle, _ = _prepared(tmp_path)
    checks = {name: True for name in REQUIRED_V2_ACCEPTANCE_CHECKS}
    checks["playwright"] = False
    with pytest.raises(PermissionError, match="V2 acceptance checks are incomplete"):
        V2ReserveReviewAttestation(
            program_result_id=str(a26["program_result_id"]),
            portfolio_validation_id=str(a4["portfolio_validation_id"]),
            review_bundle_sha256=hashlib.sha256(bundle).hexdigest(),
            workspace_commit_sha="workspace-v2-pass-sha",
            reviewed_by="human-reviewer",
            reviewed_at=NOW,
            checks=checks,
            protocol_identity_reviewed=True,
            execution_ledger_reviewed=True,
            reserve_untouched_confirmed=True,
            no_post_a4_mutation_confirmed=True,
            no_agent_feedback_path_confirmed=True,
        )


def test_a5p1_rejects_review_bundle_or_attestation_identity_drift(tmp_path: Path) -> None:
    _prepared(tmp_path)
    attestation_raw = json.loads((tmp_path / "review_attestation.json").read_text(encoding="utf-8"))
    attestation_raw["review_bundle_sha256"] = "0" * 64
    attestation_raw.pop("attestation_id", None)
    _write_json(tmp_path / "review_attestation.json", attestation_raw)
    with pytest.raises(ValueError, match="different V2 review bundle"):
        ReserveEligibilitySealer().seal_from_paths(
            a26_report_path=tmp_path / "a26.json",
            a26_replay_path=tmp_path / "a26_replay.json",
            a4_report_path=tmp_path / "a4.json",
            a4_replay_path=tmp_path / "a4_replay.json",
            ledger_path=tmp_path / "a4_ledger.jsonl",
            review_bundle_path=tmp_path / "review.zip",
            review_attestation_path=tmp_path / "review_attestation.json",
            code_git_sha="a5-code-sha",
            created_at=NOW,
        )


def test_a5p1_authority_boundary_cannot_enable_feedback_or_tuning() -> None:
    with pytest.raises(ValueError, match="fail-closed"):
        ReserveAuthorityBoundary(agent_feedback_allowed=True)
    with pytest.raises(ValueError, match="fail-closed"):
        ReserveAuthorityBoundary(threshold_mutation_allowed=True)
    with pytest.raises(ValueError, match="fail-closed"):
        ReserveAuthorityBoundary(ui_reserve_authority=True)


def test_a5_execution_ledger_digest_matches_a4_core_format(tmp_path: Path) -> None:
    _, a4, _ = _fixture(tmp_path)
    assert execution_ledger_digest((tmp_path / "a4_ledger.jsonl").read_bytes()) == a4["ledger_digest"]
