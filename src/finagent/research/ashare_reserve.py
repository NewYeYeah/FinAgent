from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from finagent.domain._validation import require_aware_datetime, require_non_empty


A2P6_SCHEMA = "finagent.ashare-robust-research-program.v1"
A4_SCHEMA = "finagent.ashare-portfolio-validation.v1"
V2_REVIEW_BUNDLE_SCHEMA = "finagent.workspace.review-bundle.v2"
V2_REVIEW_ATTESTATION_SCHEMA = "finagent.v2-reserve-review-attestation.v1"
RESERVE_ELIGIBILITY_SCHEMA = "finagent.ashare-reserve-eligibility-seal.v1"
AUTHORITY_POLICY_ID = "a5-one-shot-reserve-authority-v1"

REQUIRED_V2_ACCEPTANCE_CHECKS = (
    "python_api",
    "typescript",
    "vitest",
    "vite_build",
    "playwright",
    "quality",
    "windows",
    "ubuntu",
    "legacy_streamlit",
    "read_only_authority",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _identity(prefix: str, value: object, length: int = 24) -> str:
    return f"{prefix}-{_sha256_json(value)[:length]}"


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a JSON object")
    return value


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a JSON array")
    return value


def _string(value: object, name: str) -> str:
    return require_non_empty(str(value), name)


def _semantic_replay_payload(payload: Mapping[str, Any]) -> dict[str, object]:
    result = dict(payload)
    result.pop("mode", None)
    return result


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _deep_freeze(item) for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_deep_freeze(item) for item in value)
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_thaw_json(item) for item in value]
    return value


def _ledger_rows(data: bytes) -> tuple[Mapping[str, Any], ...]:
    rows: list[Mapping[str, Any]] = []
    for number, raw_line in enumerate(data.decode("utf-8-sig").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"execution ledger line {number} is invalid JSON") from exc
        rows.append(_mapping(value, f"execution ledger line {number}"))
    return tuple(rows)


def execution_ledger_digest(data: bytes) -> str:
    """Return the exact A4 core ledger identity for JSONL bytes."""

    rows = _ledger_rows(data)
    digest = _sha256_json(rows)
    return f"a4-execution-ledger-{digest}"


def _load_report(path: str | Path, name: str) -> Mapping[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return _mapping(raw, name)


@dataclass(frozen=True, slots=True)
class ReserveAuthorityBoundary:
    """Frozen A5 authority boundary.

    This object deliberately has no permissive production mode. A5-1 may only seal a
    protocol whose Agent/UI feedback and post-outcome tuning paths are all disabled.
    The later A5-2 runner receives one narrowly-scoped human-authorized execution path;
    it must not widen this boundary.
    """

    agent_feedback_allowed: bool = False
    factor_replacement_allowed: bool = False
    weight_refit_allowed: bool = False
    threshold_mutation_allowed: bool = False
    risk_optimizer_mutation_allowed: bool = False
    fee_slippage_mutation_allowed: bool = False
    rebalance_mutation_allowed: bool = False
    ui_interactive_tuning_allowed: bool = False
    agent_reserve_authority: bool = False
    ui_reserve_authority: bool = False

    def __post_init__(self) -> None:
        if any(self.to_dict().values()):
            raise ValueError("A5 reserve authority boundary must remain fully fail-closed")

    def to_dict(self) -> dict[str, bool]:
        return {
            "agent_feedback_allowed": self.agent_feedback_allowed,
            "factor_replacement_allowed": self.factor_replacement_allowed,
            "weight_refit_allowed": self.weight_refit_allowed,
            "threshold_mutation_allowed": self.threshold_mutation_allowed,
            "risk_optimizer_mutation_allowed": self.risk_optimizer_mutation_allowed,
            "fee_slippage_mutation_allowed": self.fee_slippage_mutation_allowed,
            "rebalance_mutation_allowed": self.rebalance_mutation_allowed,
            "ui_interactive_tuning_allowed": self.ui_interactive_tuning_allowed,
            "agent_reserve_authority": self.agent_reserve_authority,
            "ui_reserve_authority": self.ui_reserve_authority,
        }

    @property
    def policy_digest(self) -> str:
        return _sha256_json({"policy_id": AUTHORITY_POLICY_ID, **self.to_dict()})


@dataclass(frozen=True, slots=True)
class V2ReserveReviewAttestation:
    program_result_id: str
    portfolio_validation_id: str
    review_bundle_sha256: str
    workspace_commit_sha: str
    reviewed_by: str
    reviewed_at: datetime
    checks: Mapping[str, bool]
    protocol_identity_reviewed: bool
    execution_ledger_reviewed: bool
    reserve_untouched_confirmed: bool
    no_post_a4_mutation_confirmed: bool
    no_agent_feedback_path_confirmed: bool

    def __post_init__(self) -> None:
        for name in (
            "program_result_id",
            "portfolio_validation_id",
            "review_bundle_sha256",
            "workspace_commit_sha",
            "reviewed_by",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if len(self.review_bundle_sha256) != 64:
            raise ValueError("review_bundle_sha256 must be a full SHA-256 digest")
        object.__setattr__(self, "reviewed_at", require_aware_datetime(self.reviewed_at, "reviewed_at"))
        if any(not isinstance(value, bool) for value in self.checks.values()):
            raise TypeError("V2 acceptance check values must be JSON booleans")
        normalized = {str(key): value for key, value in self.checks.items()}
        missing = [name for name in REQUIRED_V2_ACCEPTANCE_CHECKS if not normalized.get(name, False)]
        if missing:
            raise PermissionError("V2 acceptance checks are incomplete: " + ", ".join(missing))
        if not all(
            (
                self.protocol_identity_reviewed,
                self.execution_ledger_reviewed,
                self.reserve_untouched_confirmed,
                self.no_post_a4_mutation_confirmed,
                self.no_agent_feedback_path_confirmed,
            )
        ):
            raise PermissionError("human reserve review confirmations are incomplete")
        object.__setattr__(self, "checks", MappingProxyType(dict(sorted(normalized.items()))))

    @property
    def attestation_id(self) -> str:
        return _identity("v2-reserve-review", self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": V2_REVIEW_ATTESTATION_SCHEMA,
            "program_result_id": self.program_result_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "review_bundle_sha256": self.review_bundle_sha256,
            "workspace_commit_sha": self.workspace_commit_sha,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat(),
            "checks": dict(self.checks),
            "confirmations": {
                "protocol_identity_reviewed": self.protocol_identity_reviewed,
                "execution_ledger_reviewed": self.execution_ledger_reviewed,
                "reserve_untouched_confirmed": self.reserve_untouched_confirmed,
                "no_post_a4_mutation_confirmed": self.no_post_a4_mutation_confirmed,
                "no_agent_feedback_path_confirmed": self.no_agent_feedback_path_confirmed,
            },
        }
        if include_id:
            payload["attestation_id"] = self.attestation_id
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "V2ReserveReviewAttestation":
        if raw.get("schema_version") != V2_REVIEW_ATTESTATION_SCHEMA:
            raise ValueError("unsupported V2 reserve review attestation schema")
        confirmations = _mapping(raw.get("confirmations"), "confirmations")
        confirmation_names = (
            "protocol_identity_reviewed",
            "execution_ledger_reviewed",
            "reserve_untouched_confirmed",
            "no_post_a4_mutation_confirmed",
            "no_agent_feedback_path_confirmed",
        )
        if any(not isinstance(confirmations.get(name), bool) for name in confirmation_names):
            raise TypeError("human review confirmation values must be JSON booleans")
        result = cls(
            program_result_id=_string(raw.get("program_result_id"), "program_result_id"),
            portfolio_validation_id=_string(
                raw.get("portfolio_validation_id"), "portfolio_validation_id"
            ),
            review_bundle_sha256=_string(raw.get("review_bundle_sha256"), "review_bundle_sha256"),
            workspace_commit_sha=_string(raw.get("workspace_commit_sha"), "workspace_commit_sha"),
            reviewed_by=_string(raw.get("reviewed_by"), "reviewed_by"),
            reviewed_at=datetime.fromisoformat(_string(raw.get("reviewed_at"), "reviewed_at")),
            checks=_mapping(raw.get("checks"), "checks"),
            protocol_identity_reviewed=confirmations["protocol_identity_reviewed"],
            execution_ledger_reviewed=confirmations["execution_ledger_reviewed"],
            reserve_untouched_confirmed=confirmations["reserve_untouched_confirmed"],
            no_post_a4_mutation_confirmed=confirmations["no_post_a4_mutation_confirmed"],
            no_agent_feedback_path_confirmed=confirmations["no_agent_feedback_path_confirmed"],
        )
        provided = str(raw.get("attestation_id", "")).strip()
        if provided and provided != result.attestation_id:
            raise ValueError("V2 reserve review attestation identity does not match payload")
        return result

    @classmethod
    def read_json(cls, path: str | Path) -> "V2ReserveReviewAttestation":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(_mapping(raw, "V2 reserve review attestation"))

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return target


@dataclass(frozen=True, slots=True)
class ExactReplayProof:
    program_result_id: str
    portfolio_validation_id: str
    a26_reference_sha256: str
    a26_replay_sha256: str
    a4_reference_sha256: str
    a4_replay_sha256: str
    ledger_digest: str
    ledger_file_sha256: str

    @property
    def proof_id(self) -> str:
        return _identity("a5-exact-replay-proof", self.to_dict(include_id=False))

    def to_dict(self, *, include_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "program_result_id": self.program_result_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "a26_reference_sha256": self.a26_reference_sha256,
            "a26_replay_sha256": self.a26_replay_sha256,
            "a4_reference_sha256": self.a4_reference_sha256,
            "a4_replay_sha256": self.a4_replay_sha256,
            "ledger_digest": self.ledger_digest,
            "ledger_file_sha256": self.ledger_file_sha256,
        }
        if include_id:
            payload["proof_id"] = self.proof_id
        return payload


@dataclass(frozen=True, slots=True)
class ReserveEligibilitySeal:
    program_result_id: str
    program_report_sha256: str
    program_spec_id: str
    selection_id: str
    portfolio_validation_id: str
    portfolio_report_sha256: str
    a4_spec_id: str
    ledger_digest: str
    ledger_file_sha256: str
    reserve_id: str
    reserve_start: str
    reserve_end: str
    data_version: str
    selected_feature_digests: tuple[str, ...]
    selected_weights: tuple[float, ...]
    selected_directions: tuple[int, ...]
    protocol_snapshot: Mapping[str, object]
    protocol_digest: str
    exact_replay_proof: ExactReplayProof
    v2_review_attestation_id: str
    v2_review_bundle_sha256: str
    workspace_commit_sha: str
    code_git_sha: str
    authority_policy_id: str
    authority_policy_digest: str
    created_at: datetime

    def __post_init__(self) -> None:
        for name in (
            "program_result_id",
            "program_report_sha256",
            "program_spec_id",
            "selection_id",
            "portfolio_validation_id",
            "portfolio_report_sha256",
            "a4_spec_id",
            "ledger_digest",
            "ledger_file_sha256",
            "reserve_id",
            "reserve_start",
            "reserve_end",
            "data_version",
            "protocol_digest",
            "v2_review_attestation_id",
            "v2_review_bundle_sha256",
            "workspace_commit_sha",
            "code_git_sha",
            "authority_policy_id",
            "authority_policy_digest",
        ):
            object.__setattr__(self, name, require_non_empty(getattr(self, name), name))
        if self.authority_policy_id != AUTHORITY_POLICY_ID:
            raise ValueError("unknown reserve authority policy")
        thawed_snapshot = _thaw_json(self.protocol_snapshot)
        if self.protocol_digest != _sha256_json(thawed_snapshot):
            raise ValueError("reserve protocol digest does not match protocol snapshot")
        if not (
            len(self.selected_feature_digests)
            == len(self.selected_weights)
            == len(self.selected_directions)
            and self.selected_feature_digests
        ):
            raise ValueError("reserve seal requires a non-empty aligned frozen factor family")
        if len(set(self.selected_feature_digests)) != len(self.selected_feature_digests):
            raise ValueError("reserve factor digests must be unique")
        if any(direction not in {-1, 1} for direction in self.selected_directions):
            raise ValueError("reserve directions must be +/-1")
        if any(not math.isfinite(weight) or weight < 0.0 for weight in self.selected_weights):
            raise ValueError("reserve weights must be finite and non-negative")
        if abs(sum(self.selected_weights) - 1.0) > 1e-9:
            raise ValueError("reserve weights must sum to one")
        if self.exact_replay_proof.program_result_id != self.program_result_id:
            raise ValueError("replay proof A2.6 identity does not match reserve seal")
        if self.exact_replay_proof.portfolio_validation_id != self.portfolio_validation_id:
            raise ValueError("replay proof A4 identity does not match reserve seal")
        if self.exact_replay_proof.ledger_digest != self.ledger_digest:
            raise ValueError("replay proof ledger identity does not match reserve seal")
        if self.exact_replay_proof.ledger_file_sha256 != self.ledger_file_sha256:
            raise ValueError("replay proof ledger artifact does not match reserve seal")
        if self.authority_policy_digest != ReserveAuthorityBoundary().policy_digest:
            raise ValueError("reserve authority policy digest drifted")
        frozen_snapshot = _deep_freeze(thawed_snapshot)
        if not isinstance(frozen_snapshot, Mapping):
            raise TypeError("reserve protocol snapshot must remain a JSON object")
        object.__setattr__(self, "protocol_snapshot", frozen_snapshot)
        object.__setattr__(self, "created_at", require_aware_datetime(self.created_at, "created_at"))

    def identity_dict(self) -> dict[str, object]:
        return {
            "schema_version": RESERVE_ELIGIBILITY_SCHEMA,
            "program_result_id": self.program_result_id,
            "program_report_sha256": self.program_report_sha256,
            "program_spec_id": self.program_spec_id,
            "selection_id": self.selection_id,
            "portfolio_validation_id": self.portfolio_validation_id,
            "portfolio_report_sha256": self.portfolio_report_sha256,
            "a4_spec_id": self.a4_spec_id,
            "ledger_digest": self.ledger_digest,
            "ledger_file_sha256": self.ledger_file_sha256,
            "reserve": {
                "reserve_id": self.reserve_id,
                "start": self.reserve_start,
                "end": self.reserve_end,
                "status": "untouched",
            },
            "data_version": self.data_version,
            "selected_feature_digests": list(self.selected_feature_digests),
            "selected_weights": list(self.selected_weights),
            "selected_directions": list(self.selected_directions),
            "protocol_snapshot": _thaw_json(self.protocol_snapshot),
            "protocol_digest": self.protocol_digest,
            "exact_replay_proof": self.exact_replay_proof.to_dict(),
            "v2_review_attestation_id": self.v2_review_attestation_id,
            "v2_review_bundle_sha256": self.v2_review_bundle_sha256,
            "workspace_commit_sha": self.workspace_commit_sha,
            "code_git_sha": self.code_git_sha,
            "authority_policy_id": self.authority_policy_id,
            "authority_policy_digest": self.authority_policy_digest,
            "eligibility_status": "ELIGIBLE_SEALED",
            "reserve_consumed": False,
        }

    @property
    def seal_id(self) -> str:
        return _identity("ashare-reserve-eligibility", self.identity_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            **self.identity_dict(),
            "seal_id": self.seal_id,
            "created_at": self.created_at.isoformat(),
        }

    def write_json(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if target.exists() and target.read_text(encoding="utf-8") != encoded:
            raise ValueError("reserve eligibility seal output is immutable")
        target.write_text(encoded, encoding="utf-8")
        return target


@dataclass(frozen=True, slots=True)
class V2ReviewBundleProof:
    bundle_sha256: str
    program_result_id: str
    portfolio_validation_id: str
    ledger_digest: str


def verify_v2_review_bundle(
    *,
    bundle_bytes: bytes,
    a26_report: Mapping[str, Any],
    a4_report: Mapping[str, Any],
    ledger_bytes: bytes,
) -> V2ReviewBundleProof:
    required = {
        "manifest.json",
        "lineage.json",
        "protocol_diff.json",
        "report_a26.json",
        "report_a4.json",
        "execution_ledger.jsonl",
    }
    try:
        archive = zipfile.ZipFile(BytesIO(bundle_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("V2 review bundle is not a valid ZIP archive") from exc
    with archive:
        names = set(archive.namelist())
        missing = sorted(required - names)
        if missing:
            raise ValueError("V2 review bundle is incomplete: " + ", ".join(missing))
        manifest = _mapping(json.loads(archive.read("manifest.json")), "review bundle manifest")
        if manifest.get("schema_version") != V2_REVIEW_BUNDLE_SCHEMA:
            raise ValueError("unsupported V2 review bundle schema")
        if manifest.get("review_only") is not True or manifest.get("signed") is not False:
            raise PermissionError("A5-1 requires the read-only unsigned V2 human-review bundle")
        if str(manifest.get("reserve_status")) != "untouched":
            raise PermissionError("V2 review bundle reserve is not untouched")
        if bool(manifest.get("promotion_eligible")):
            raise PermissionError("V2 review bundle cannot already be promotion eligible")
        protocol_diff = _mapping(json.loads(archive.read("protocol_diff.json")), "protocol diff")
        if protocol_diff.get("read_only") is not True or "warning" in protocol_diff:
            raise PermissionError("V2 protocol diff is incomplete or not read-only")
        included_a26 = _mapping(json.loads(archive.read("report_a26.json")), "review A2.6 report")
        included_a4 = _mapping(json.loads(archive.read("report_a4.json")), "review A4 report")
        if _canonical_json(included_a26) != _canonical_json(a26_report):
            raise ValueError("V2 review bundle contains a different A2.6 report")
        if _canonical_json(included_a4) != _canonical_json(a4_report):
            raise ValueError("V2 review bundle contains a different A4 report")
        included_ledger = archive.read("execution_ledger.jsonl")
        expected_ledger_digest = execution_ledger_digest(ledger_bytes)
        if execution_ledger_digest(included_ledger) != expected_ledger_digest:
            raise ValueError("V2 review bundle contains a different execution ledger")
        program_result_id = _string(a26_report.get("program_result_id"), "program_result_id")
        portfolio_validation_id = _string(
            a4_report.get("portfolio_validation_id"), "portfolio_validation_id"
        )
        ids = {str(value) for value in _sequence(manifest.get("source_evidence_ids"), "source_evidence_ids")}
        if not {program_result_id, portfolio_validation_id}.issubset(ids):
            raise ValueError("V2 review bundle source evidence identities are incomplete")
        if str(manifest.get("ledger_digest")) != expected_ledger_digest:
            raise ValueError("V2 review bundle manifest ledger digest drifted")
    return V2ReviewBundleProof(
        bundle_sha256=_sha256_bytes(bundle_bytes),
        program_result_id=program_result_id,
        portfolio_validation_id=portfolio_validation_id,
        ledger_digest=expected_ledger_digest,
    )


class ReserveEligibilitySealer:
    """Build the immutable A5-1 seal without accessing or consuming reserve data."""

    def __init__(self, authority: ReserveAuthorityBoundary | None = None) -> None:
        self.authority = authority or ReserveAuthorityBoundary()

    def _validate_a26(self, raw: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        if raw.get("schema_version") != A2P6_SCHEMA:
            raise ValueError("A5-1 requires an A2.6 robust ResearchProgram report")
        if _mapping(raw.get("system_acceptance"), "A2.6 system_acceptance").get("passed") is not True:
            raise PermissionError("A2.6 system acceptance did not pass")
        if str(raw.get("program_status")) != "frozen":
            raise PermissionError("A2.6 ResearchProgram is not frozen")
        outcome = _mapping(raw.get("research_outcome"), "A2.6 research_outcome")
        if str(outcome.get("status")) != "ROBUST_FACTOR_FAMILY_FROZEN":
            raise PermissionError("A5 reserve requires a frozen robust factor family")
        if bool(outcome.get("promotion_eligible")):
            raise PermissionError("pre-reserve A2.6 evidence cannot already be promotion eligible")
        selection = _mapping(raw.get("frozen_selection"), "A2.6 frozen_selection")
        if str(selection.get("status")) != "ROBUST_FACTOR_FAMILY_FROZEN":
            raise PermissionError("A2.6 frozen selection is not reserve eligible")
        components = _sequence(selection.get("components"), "A2.6 frozen components")
        if not components:
            raise PermissionError("A5 reserve cannot run without a frozen factor family")
        reserve = _mapping(raw.get("reserve"), "A2.6 reserve")
        if str(reserve.get("status")) != "untouched":
            raise PermissionError("A2.6 reserve is not untouched")
        program_spec = _mapping(raw.get("program_spec"), "program_spec")
        plan = _mapping(program_spec.get("walk_forward_plan"), "walk_forward_plan")
        if str(plan.get("reserve_status")) != "untouched":
            raise PermissionError("A2.6 frozen plan no longer marks reserve untouched")
        if str(program_spec.get("reserve_id")) != str(reserve.get("reserve_id")):
            raise ValueError("A2.6 program_spec reserve_id differs from report reserve")
        if str(program_spec.get("data_version")) != str(raw.get("data_version")):
            raise ValueError("A2.6 program_spec data_version differs from report")
        plan_reserve = list(_sequence(plan.get("reserve"), "walk-forward reserve"))
        if plan_reserve != [reserve.get("start"), reserve.get("end")]:
            raise ValueError("A2.6 walk-forward reserve interval differs from report reserve")
        return selection, reserve

    def _validate_a4(
        self,
        raw: Mapping[str, Any],
        *,
        a26: Mapping[str, Any],
        selection: Mapping[str, Any],
        reserve: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if raw.get("schema_version") != A4_SCHEMA:
            raise ValueError("A5-1 requires an A4 portfolio-validation report")
        if _mapping(raw.get("system_acceptance"), "A4 system_acceptance").get("passed") is not True:
            raise PermissionError("A4 system acceptance did not pass")
        outcome = _mapping(raw.get("research_outcome"), "A4 research_outcome")
        if outcome.get("execution_validation_passed") is not True:
            raise PermissionError("A4 execution/economic validation did not pass")
        if str(raw.get("source_research_status")) != "ROBUST_FACTOR_FAMILY_FROZEN":
            raise PermissionError("A4 source research status is not frozen robust-factor evidence")
        if bool(outcome.get("promotion_eligible")):
            raise PermissionError("pre-reserve A4 evidence cannot already be promotion eligible")
        a4_reserve = _mapping(raw.get("reserve"), "A4 reserve")
        if str(a4_reserve.get("status")) != "untouched":
            raise PermissionError("A4 reserve is not untouched")
        for name in ("reserve_id", "start", "end"):
            if str(a4_reserve.get(name)) != str(reserve.get(name)):
                raise ValueError(f"A2.6/A4 reserve {name} identity drifted")
        spec = _mapping(raw.get("validation_spec"), "A4 validation_spec")
        program_spec = _mapping(a26.get("program_spec"), "A2.6 program_spec")
        expected_pairs = (
            ("source_program_result_id", a26.get("program_result_id")),
            ("source_program_spec_id", program_spec.get("spec_id")),
            ("source_selection_id", selection.get("selection_id")),
            ("data_version", a26.get("data_version")),
            ("candidate_selection_id", program_spec.get("candidate_selection_id")),
            ("universe_policy_version", program_spec.get("universe_policy_version")),
            ("plan_id", _mapping(program_spec.get("walk_forward_plan"), "walk_forward_plan").get("plan_id")),
            ("reserve_id", reserve.get("reserve_id")),
        )
        for field, expected in expected_pairs:
            if str(spec.get(field)) != str(expected):
                raise ValueError(f"A4 {field} drifted from frozen A2.6 identity")
        if str(spec.get("source_report_digest")) != _sha256_json(a26):
            raise ValueError("A4 source_report_digest does not bind the exact A2.6 report")
        components = [_mapping(value, "A2.6 factor component") for value in _sequence(selection.get("components"), "components")]
        expected_digests = [str(value.get("feature_digest")) for value in components]
        expected_weights = [float(value.get("weight", 0.0)) for value in components]
        expected_directions = [int(value.get("direction", 0)) for value in components]
        if list(_sequence(spec.get("selected_feature_digests"), "A4 selected_feature_digests")) != expected_digests:
            raise ValueError("A4 selected feature family drifted from A2.6")
        if [float(value) for value in _sequence(spec.get("selected_weights"), "A4 selected_weights")] != expected_weights:
            raise ValueError("A4 selected weights drifted from A2.6")
        if [int(value) for value in _sequence(spec.get("selected_directions"), "A4 selected_directions")] != expected_directions:
            raise ValueError("A4 selected directions drifted from A2.6")
        return spec

    def _replay_proof(
        self,
        *,
        a26: Mapping[str, Any],
        a26_replay: Mapping[str, Any],
        a4: Mapping[str, Any],
        a4_replay: Mapping[str, Any],
        ledger_bytes: bytes,
    ) -> ExactReplayProof:
        if str(a26_replay.get("mode")) != "replay":
            raise PermissionError("A2.6 replay proof must come from replay mode")
        if str(a4_replay.get("mode")) != "replay":
            raise PermissionError("A4 replay proof must come from replay mode")
        if _semantic_replay_payload(a26_replay) != _semantic_replay_payload(a26):
            raise ValueError("A2.6 exact replay differs from frozen reference")
        if _semantic_replay_payload(a4_replay) != _semantic_replay_payload(a4):
            raise ValueError("A4 exact replay differs from frozen reference")
        ledger_digest = execution_ledger_digest(ledger_bytes)
        if str(a4.get("ledger_digest")) != ledger_digest:
            raise ValueError("A4 report ledger_digest does not match immutable JSONL ledger")
        if str(a4_replay.get("ledger_digest")) != ledger_digest:
            raise ValueError("A4 replay ledger_digest does not match immutable JSONL ledger")
        return ExactReplayProof(
            program_result_id=_string(a26.get("program_result_id"), "program_result_id"),
            portfolio_validation_id=_string(
                a4.get("portfolio_validation_id"), "portfolio_validation_id"
            ),
            a26_reference_sha256=_sha256_json(a26),
            a26_replay_sha256=_sha256_json(a26_replay),
            a4_reference_sha256=_sha256_json(a4),
            a4_replay_sha256=_sha256_json(a4_replay),
            ledger_digest=ledger_digest,
            ledger_file_sha256=_sha256_bytes(ledger_bytes),
        )

    def seal(
        self,
        *,
        a26_report: Mapping[str, Any],
        a26_replay_report: Mapping[str, Any],
        a4_report: Mapping[str, Any],
        a4_replay_report: Mapping[str, Any],
        ledger_bytes: bytes,
        review_bundle_bytes: bytes,
        review_attestation: V2ReserveReviewAttestation,
        code_git_sha: str,
        created_at: datetime,
    ) -> ReserveEligibilitySeal:
        selection, reserve = self._validate_a26(a26_report)
        spec = self._validate_a4(
            a4_report,
            a26=a26_report,
            selection=selection,
            reserve=reserve,
        )
        replay = self._replay_proof(
            a26=a26_report,
            a26_replay=a26_replay_report,
            a4=a4_report,
            a4_replay=a4_replay_report,
            ledger_bytes=ledger_bytes,
        )
        review = verify_v2_review_bundle(
            bundle_bytes=review_bundle_bytes,
            a26_report=a26_report,
            a4_report=a4_report,
            ledger_bytes=ledger_bytes,
        )
        if review_attestation.review_bundle_sha256 != review.bundle_sha256:
            raise ValueError("human review attestation points to a different V2 review bundle")
        if review_attestation.program_result_id != replay.program_result_id:
            raise ValueError("human review attestation points to a different A2.6 result")
        if review_attestation.portfolio_validation_id != replay.portfolio_validation_id:
            raise ValueError("human review attestation points to a different A4 result")

        program_spec = _mapping(a26_report.get("program_spec"), "program_spec")
        components = tuple(
            _mapping(value, "frozen factor component")
            for value in _sequence(selection.get("components"), "components")
        )
        protocol_snapshot: dict[str, object] = {
            "a2p6_program_spec": dict(program_spec),
            "a2p6_frozen_selection": dict(selection),
            "a4_validation_spec": dict(spec),
            "reserve": {
                "reserve_id": str(reserve.get("reserve_id")),
                "start": str(reserve.get("start")),
                "end": str(reserve.get("end")),
            },
        }
        protocol_digest = _sha256_json(protocol_snapshot)
        authority_digest = self.authority.policy_digest
        return ReserveEligibilitySeal(
            program_result_id=replay.program_result_id,
            program_report_sha256=_sha256_json(a26_report),
            program_spec_id=_string(program_spec.get("spec_id"), "program_spec_id"),
            selection_id=_string(selection.get("selection_id"), "selection_id"),
            portfolio_validation_id=replay.portfolio_validation_id,
            portfolio_report_sha256=_sha256_json(a4_report),
            a4_spec_id=_string(spec.get("spec_id"), "a4_spec_id"),
            ledger_digest=replay.ledger_digest,
            ledger_file_sha256=replay.ledger_file_sha256,
            reserve_id=_string(reserve.get("reserve_id"), "reserve_id"),
            reserve_start=_string(reserve.get("start"), "reserve_start"),
            reserve_end=_string(reserve.get("end"), "reserve_end"),
            data_version=_string(a26_report.get("data_version"), "data_version"),
            selected_feature_digests=tuple(str(value.get("feature_digest")) for value in components),
            selected_weights=tuple(float(value.get("weight", 0.0)) for value in components),
            selected_directions=tuple(int(value.get("direction", 0)) for value in components),
            protocol_snapshot=protocol_snapshot,
            protocol_digest=protocol_digest,
            exact_replay_proof=replay,
            v2_review_attestation_id=review_attestation.attestation_id,
            v2_review_bundle_sha256=review.bundle_sha256,
            workspace_commit_sha=review_attestation.workspace_commit_sha,
            code_git_sha=require_non_empty(code_git_sha, "code_git_sha"),
            authority_policy_id=AUTHORITY_POLICY_ID,
            authority_policy_digest=authority_digest,
            created_at=created_at,
        )

    def seal_from_paths(
        self,
        *,
        a26_report_path: str | Path,
        a26_replay_path: str | Path,
        a4_report_path: str | Path,
        a4_replay_path: str | Path,
        ledger_path: str | Path,
        review_bundle_path: str | Path,
        review_attestation_path: str | Path,
        code_git_sha: str,
        created_at: datetime,
    ) -> ReserveEligibilitySeal:
        return self.seal(
            a26_report=_load_report(a26_report_path, "A2.6 report"),
            a26_replay_report=_load_report(a26_replay_path, "A2.6 replay report"),
            a4_report=_load_report(a4_report_path, "A4 report"),
            a4_replay_report=_load_report(a4_replay_path, "A4 replay report"),
            ledger_bytes=Path(ledger_path).read_bytes(),
            review_bundle_bytes=Path(review_bundle_path).read_bytes(),
            review_attestation=V2ReserveReviewAttestation.read_json(review_attestation_path),
            code_git_sha=code_git_sha,
            created_at=created_at,
        )


class SQLiteReserveEligibilityStore:
    """Append-only A5-1 seal store.

    This store records eligibility only. It intentionally has no consumed-state column
    and no mutation method; A5-3 owns reserve consumption state.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reserve_eligibility_seals (
                    seal_id TEXT PRIMARY KEY,
                    reserve_id TEXT NOT NULL UNIQUE,
                    program_result_id TEXT NOT NULL UNIQUE,
                    portfolio_validation_id TEXT NOT NULL UNIQUE,
                    protocol_digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, seal: ReserveEligibilitySeal) -> None:
        encoded = _canonical_json(seal.to_dict())
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT seal_id, reserve_id, program_result_id, portfolio_validation_id,
                       protocol_digest, payload_json
                FROM reserve_eligibility_seals
                WHERE seal_id=? OR reserve_id=? OR program_result_id=? OR portfolio_validation_id=?
                """,
                (
                    seal.seal_id,
                    seal.reserve_id,
                    seal.program_result_id,
                    seal.portfolio_validation_id,
                ),
            ).fetchall()
            if rows:
                if len(rows) == 1 and rows[0][0] == seal.seal_id:
                    return
                raise ValueError("reserve/program/A4 identity already has a different eligibility seal")
            connection.execute(
                "INSERT INTO reserve_eligibility_seals VALUES (?, ?, ?, ?, ?, ?)",
                (
                    seal.seal_id,
                    seal.reserve_id,
                    seal.program_result_id,
                    seal.portfolio_validation_id,
                    seal.protocol_digest,
                    encoded,
                ),
            )

    def get(self, seal_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_eligibility_seals WHERE seal_id=?",
                (seal_id,),
            ).fetchone()
        if row is None:
            raise KeyError(seal_id)
        return MappingProxyType(json.loads(row[0]))

    def get_for_reserve(self, reserve_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM reserve_eligibility_seals WHERE reserve_id=?",
                (reserve_id,),
            ).fetchone()
        if row is None:
            raise KeyError(reserve_id)
        return MappingProxyType(json.loads(row[0]))
