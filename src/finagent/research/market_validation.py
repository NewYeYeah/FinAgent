from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from finagent.agents.generated_features import GeneratedFeatureArtifact, SQLiteGeneratedFeatureStore
from finagent.data.ingestion.diff import ProviderDiffReport

from .agent_market import (
    AgentMarketCandidate,
    AgentMarketFoldResult,
    AgentMarketResearchResult,
)


class AgentMarketValidationMode(str, Enum):
    REPLAY = "replay"
    CROSS_PROVIDER = "cross_provider"


def _float_value(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be numeric")
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _int_value(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, float) and value != parsed:
        raise ValueError(f"{name} must be an integer")
    return parsed


@dataclass(frozen=True, slots=True)
class AgentMarketValidationPolicy:
    """Pre-registered validation contract for Agent market-study comparison.

    Replay is intentionally exact. Cross-provider comparison is structural by default:
    it requires the same frozen research family and calendar, while financial metric
    tolerances remain opt-in evidence thresholds rather than hidden defaults.
    """

    mode: AgentMarketValidationMode
    require_same_provider: bool
    require_same_data_version: bool
    require_exact_payload: bool
    require_provider_calendar_match: bool
    min_selection_agreement: float = 0.0
    min_acceptance_agreement: float = 0.0
    aggregate_abs_limits: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("min_selection_agreement", "min_acceptance_agreement"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, value)
        limits = {str(name): float(value) for name, value in self.aggregate_abs_limits.items()}
        if any(value < 0.0 for value in limits.values()):
            raise ValueError("aggregate_abs_limits must be non-negative")
        object.__setattr__(self, "aggregate_abs_limits", MappingProxyType(limits))

    @classmethod
    def replay(cls) -> AgentMarketValidationPolicy:
        return cls(
            mode=AgentMarketValidationMode.REPLAY,
            require_same_provider=True,
            require_same_data_version=True,
            require_exact_payload=True,
            require_provider_calendar_match=False,
            min_selection_agreement=1.0,
            min_acceptance_agreement=1.0,
        )

    @classmethod
    def cross_provider(
        cls,
        *,
        min_selection_agreement: float = 0.0,
        min_acceptance_agreement: float = 0.0,
        aggregate_abs_limits: Mapping[str, float] | None = None,
    ) -> AgentMarketValidationPolicy:
        return cls(
            mode=AgentMarketValidationMode.CROSS_PROVIDER,
            require_same_provider=False,
            require_same_data_version=False,
            require_exact_payload=False,
            require_provider_calendar_match=True,
            min_selection_agreement=min_selection_agreement,
            min_acceptance_agreement=min_acceptance_agreement,
            aggregate_abs_limits=aggregate_abs_limits or {},
        )


@dataclass(frozen=True, slots=True)
class AgentMarketValidationReport:
    validation_id: str
    mode: AgentMarketValidationMode
    left_study_id: str
    right_study_id: str
    left_provider: str
    right_provider: str
    left_data_version: str
    right_data_version: str
    task_match: bool
    program_match: bool
    family_match: bool
    candidate_family_match: bool
    universe_match: bool
    fold_boundary_match: bool
    provider_calendar_match: bool | None
    exact_payload_match: bool
    common_folds: int
    selection_agreement: float
    acceptance_agreement: float
    aggregate_abs_differences: Mapping[str, float]
    policy_violations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.common_folds < 0:
            raise ValueError("common_folds must be non-negative")
        for name in ("selection_agreement", "acceptance_agreement"):
            value = float(getattr(self, name))
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "aggregate_abs_differences",
            MappingProxyType(
                {str(name): float(value) for name, value in self.aggregate_abs_differences.items()}
            ),
        )
        object.__setattr__(self, "policy_violations", tuple(str(v) for v in self.policy_violations))

    @property
    def passed(self) -> bool:
        return not self.policy_violations

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "finagent.agent-market-validation.v1",
            "validation_id": self.validation_id,
            "mode": self.mode.value,
            "passed": self.passed,
            "left_study_id": self.left_study_id,
            "right_study_id": self.right_study_id,
            "left_provider": self.left_provider,
            "right_provider": self.right_provider,
            "left_data_version": self.left_data_version,
            "right_data_version": self.right_data_version,
            "task_match": self.task_match,
            "program_match": self.program_match,
            "family_match": self.family_match,
            "candidate_family_match": self.candidate_family_match,
            "universe_match": self.universe_match,
            "fold_boundary_match": self.fold_boundary_match,
            "provider_calendar_match": self.provider_calendar_match,
            "exact_payload_match": self.exact_payload_match,
            "common_folds": self.common_folds,
            "selection_agreement": self.selection_agreement,
            "acceptance_agreement": self.acceptance_agreement,
            "aggregate_abs_differences": dict(self.aggregate_abs_differences),
            "policy_violations": list(self.policy_violations),
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path


def _candidate_from_dict(payload: Mapping[str, object]) -> AgentMarketCandidate:
    raw_fields = payload.get("input_fields", ())
    if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes, bytearray)):
        raise TypeError("candidate.input_fields must be an array")
    return AgentMarketCandidate(
        feature_id=str(payload["feature_id"]),
        feature_digest=str(payload["feature_digest"]),
        hypothesis=str(payload["hypothesis"]),
        description=str(payload["description"]),
        lookback=_int_value(payload["lookback"], "candidate.lookback"),
        input_fields=tuple(str(value) for value in raw_fields),
    )


def _float_mapping(value: object, name: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return {str(key): _float_value(item, f"{name}.{key}") for key, item in value.items()}


def _fold_from_dict(payload: Mapping[str, object]) -> AgentMarketFoldResult:
    return AgentMarketFoldResult(
        outer_fold_index=_int_value(payload["outer_fold_index"], "outer_fold_index"),
        selected_feature_id=str(payload["selected_feature_id"]),
        selected_feature_digest=str(payload["selected_feature_digest"]),
        statistically_accepted=bool(payload["statistically_accepted"]),
        inner_mean_scores=_float_mapping(payload["inner_mean_scores"], "inner_mean_scores"),
        inner_raw_pvalues=_float_mapping(payload["inner_raw_pvalues"], "inner_raw_pvalues"),
        inner_adjusted_pvalues=_float_mapping(
            payload["inner_adjusted_pvalues"], "inner_adjusted_pvalues"
        ),
        signal_outer_metrics=_float_mapping(payload["signal_outer_metrics"], "signal_outer_metrics"),
        portfolio_outer_metrics=_float_mapping(
            payload["portfolio_outer_metrics"], "portfolio_outer_metrics"
        ),
        outer_start=str(payload["outer_start"]),
        outer_end=str(payload["outer_end"]),
    )


def agent_market_result_from_dict(payload: Mapping[str, object]) -> AgentMarketResearchResult:
    schema = str(payload.get("schema_version", ""))
    if schema and schema != "finagent.agent-market-research.v1":
        raise ValueError(f"unsupported Agent market result schema {schema!r}")
    raw_candidates = payload.get("candidates")
    raw_folds = payload.get("folds")
    raw_universe = payload.get("universe")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes, bytearray)):
        raise TypeError("candidates must be an array")
    if not isinstance(raw_folds, Sequence) or isinstance(raw_folds, (str, bytes, bytearray)):
        raise TypeError("folds must be an array")
    if not isinstance(raw_universe, Sequence) or isinstance(raw_universe, (str, bytes, bytearray)):
        raise TypeError("universe must be an array")
    candidates = []
    for item in raw_candidates:
        if not isinstance(item, Mapping):
            raise TypeError("candidate entries must be objects")
        candidates.append(_candidate_from_dict(item))
    folds = []
    for item in raw_folds:
        if not isinstance(item, Mapping):
            raise TypeError("fold entries must be objects")
        folds.append(_fold_from_dict(item))
    return AgentMarketResearchResult(
        study_id=str(payload["study_id"]),
        task_id=str(payload["task_id"]),
        program_id=str(payload["program_id"]),
        family_id=str(payload["family_id"]),
        provider=str(payload["provider"]),
        data_version=str(payload["data_version"]),
        universe=tuple(str(value) for value in raw_universe),
        candidates=tuple(candidates),
        folds=tuple(folds),
        aggregate_portfolio_metrics=_float_mapping(
            payload["aggregate_portfolio_metrics"], "aggregate_portfolio_metrics"
        ),
        promotion_eligible_folds=_int_value(
            payload["promotion_eligible_folds"], "promotion_eligible_folds"
        ),
    )


def read_agent_market_result(path: str | Path) -> AgentMarketResearchResult:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("Agent market result JSON must contain an object")
    return agent_market_result_from_dict(payload)


def frozen_feature_family(
    store: SQLiteGeneratedFeatureStore,
    reference: AgentMarketResearchResult,
    *,
    approved_input_fields: Sequence[str],
) -> tuple[GeneratedFeatureArtifact, ...]:
    """Reconstruct the exact immutable candidate family from a prior result."""

    approved = {str(value) for value in approved_input_fields}
    if not approved:
        raise ValueError("approved_input_fields cannot be empty")
    artifacts: list[GeneratedFeatureArtifact] = []
    for expected in reference.candidates:
        artifact = store.get(expected.feature_digest)
        actual = AgentMarketCandidate.from_artifact(artifact)
        if actual != expected:
            raise ValueError(
                f"stored generated feature {expected.feature_digest!r} does not match frozen evidence"
            )
        unexpected = set(artifact.spec.input_fields) - approved
        if unexpected:
            raise PermissionError(
                f"frozen feature {artifact.spec.feature_id!r} requires unapproved fields: "
                f"{sorted(unexpected)}"
            )
        artifacts.append(artifact)
    return tuple(artifacts)


def _candidate_identity(result: AgentMarketResearchResult) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            item.feature_id,
            item.feature_digest,
            item.hypothesis,
            item.description,
            item.lookback,
            item.input_fields,
        )
        for item in result.candidates
    )


def _fold_boundaries(result: AgentMarketResearchResult) -> tuple[tuple[int, str, str], ...]:
    return tuple((fold.outer_fold_index, fold.outer_start, fold.outer_end) for fold in result.folds)


def _fold_map(result: AgentMarketResearchResult) -> dict[int, AgentMarketFoldResult]:
    output = {fold.outer_fold_index: fold for fold in result.folds}
    if len(output) != len(result.folds):
        raise ValueError("Agent market result contains duplicate outer_fold_index values")
    return output


def _aggregate_differences(
    left: AgentMarketResearchResult,
    right: AgentMarketResearchResult,
) -> tuple[dict[str, float], bool]:
    left_names = set(left.aggregate_portfolio_metrics)
    right_names = set(right.aggregate_portfolio_metrics)
    same_names = left_names == right_names
    common = sorted(left_names & right_names)
    return (
        {
            name: abs(
                float(left.aggregate_portfolio_metrics[name])
                - float(right.aggregate_portfolio_metrics[name])
            )
            for name in common
        },
        same_names,
    )


def validate_agent_market_results(
    left: AgentMarketResearchResult,
    right: AgentMarketResearchResult,
    *,
    policy: AgentMarketValidationPolicy,
    provider_diff: ProviderDiffReport | None = None,
) -> AgentMarketValidationReport:
    task_match = left.task_id == right.task_id
    program_match = left.program_id == right.program_id
    family_match = left.family_id == right.family_id
    candidate_match = _candidate_identity(left) == _candidate_identity(right)
    universe_match = left.universe == right.universe
    boundary_match = _fold_boundaries(left) == _fold_boundaries(right)
    left_folds = _fold_map(left)
    right_folds = _fold_map(right)
    common_indices = sorted(set(left_folds) & set(right_folds))
    common_count = len(common_indices)
    if common_count:
        selection_agreement = sum(
            left_folds[index].selected_feature_digest
            == right_folds[index].selected_feature_digest
            for index in common_indices
        ) / common_count
        acceptance_agreement = sum(
            left_folds[index].statistically_accepted
            == right_folds[index].statistically_accepted
            for index in common_indices
        ) / common_count
    else:
        selection_agreement = 0.0
        acceptance_agreement = 0.0

    differences, metric_names_match = _aggregate_differences(left, right)
    exact_payload = left.to_dict() == right.to_dict()
    calendar_match = provider_diff.exact_calendar_match if provider_diff is not None else None

    violations: list[str] = []
    structural = (
        (task_match, "task_id differs"),
        (program_match, "program_id differs"),
        (family_match, "family_id differs"),
        (candidate_match, "frozen candidate family differs"),
        (universe_match, "canonical universe differs"),
        (boundary_match, "outer-fold boundaries differ"),
        (metric_names_match, "aggregate metric names differ"),
    )
    violations.extend(message for passed, message in structural if not passed)
    if policy.require_same_provider and left.provider != right.provider:
        violations.append("provider differs under replay policy")
    if policy.require_same_data_version and left.data_version != right.data_version:
        violations.append("data_version differs under replay policy")
    if policy.require_exact_payload and not exact_payload:
        violations.append("canonical result payload differs under exact replay policy")
    if policy.require_provider_calendar_match:
        if provider_diff is None:
            violations.append("cross-provider validation requires ProviderDiffReport evidence")
        elif not provider_diff.exact_calendar_match:
            violations.append("provider calendars differ")
    if selection_agreement + 1e-12 < policy.min_selection_agreement:
        violations.append(
            f"selection agreement {selection_agreement:.6f} is below "
            f"{policy.min_selection_agreement:.6f}"
        )
    if acceptance_agreement + 1e-12 < policy.min_acceptance_agreement:
        violations.append(
            f"statistical-acceptance agreement {acceptance_agreement:.6f} is below "
            f"{policy.min_acceptance_agreement:.6f}"
        )
    for name, limit in policy.aggregate_abs_limits.items():
        if name not in differences:
            violations.append(f"aggregate metric {name!r} is unavailable for threshold validation")
        elif differences[name] > limit + 1e-12:
            violations.append(
                f"aggregate metric {name!r} absolute difference {differences[name]:.12g} "
                f"exceeds {limit:.12g}"
            )

    identity = {
        "mode": policy.mode.value,
        "left_study_id": left.study_id,
        "right_study_id": right.study_id,
        "left_provider": left.provider,
        "right_provider": right.provider,
        "left_data_version": left.data_version,
        "right_data_version": right.data_version,
        "policy": {
            "require_same_provider": policy.require_same_provider,
            "require_same_data_version": policy.require_same_data_version,
            "require_exact_payload": policy.require_exact_payload,
            "require_provider_calendar_match": policy.require_provider_calendar_match,
            "min_selection_agreement": policy.min_selection_agreement,
            "min_acceptance_agreement": policy.min_acceptance_agreement,
            "aggregate_abs_limits": dict(sorted(policy.aggregate_abs_limits.items())),
        },
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return AgentMarketValidationReport(
        validation_id=f"agent-market-validation-{hashlib.sha256(encoded).hexdigest()[:16]}",
        mode=policy.mode,
        left_study_id=left.study_id,
        right_study_id=right.study_id,
        left_provider=left.provider,
        right_provider=right.provider,
        left_data_version=left.data_version,
        right_data_version=right.data_version,
        task_match=task_match,
        program_match=program_match,
        family_match=family_match,
        candidate_family_match=candidate_match,
        universe_match=universe_match,
        fold_boundary_match=boundary_match,
        provider_calendar_match=calendar_match,
        exact_payload_match=exact_payload,
        common_folds=common_count,
        selection_agreement=selection_agreement,
        acceptance_agreement=acceptance_agreement,
        aggregate_abs_differences=differences,
        policy_violations=tuple(violations),
    )


class SQLiteAgentMarketValidationStore:
    """Append-only/idempotent evidence store for replay/cross-provider validation."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_market_validation (
                    validation_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    left_study_id TEXT NOT NULL,
                    right_study_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    def register(self, report: AgentMarketValidationReport) -> None:
        payload = json.dumps(
            report.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        row = (
            report.validation_id,
            report.mode.value,
            report.left_study_id,
            report.right_study_id,
            payload,
        )
        with sqlite3.connect(self.path) as con:
            existing = con.execute(
                "SELECT mode, left_study_id, right_study_id, payload_json "
                "FROM agent_market_validation WHERE validation_id=?",
                (report.validation_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != row[1:]:
                    raise ValueError(f"agent market validation {report.validation_id!r} is immutable")
                return
            con.execute("INSERT INTO agent_market_validation VALUES (?, ?, ?, ?, ?)", row)

    def get(self, validation_id: str) -> Mapping[str, object]:
        with sqlite3.connect(self.path) as con:
            row = con.execute(
                "SELECT payload_json FROM agent_market_validation WHERE validation_id=?",
                (validation_id,),
            ).fetchone()
        if row is None:
            raise KeyError(validation_id)
        return MappingProxyType(json.loads(row[0]))
