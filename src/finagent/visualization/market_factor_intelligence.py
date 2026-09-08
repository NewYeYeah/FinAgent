"""GET-only MarketState and FactorLibrary intelligence projections for Workbench-2.

All financial/statistical facts are copied from persisted authoritative artifacts.
This module performs presentation-only indexing/linkage. It never fits MarketState,
recomputes factor metrics, reruns an allocator, or invents missing lineage.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from finagent.research.factor_library import FactorLibrary
from finagent.research.market_state_gmm import MarketStateModel

from .research_workspace import ResearchWorkspaceProjection
from .semantic import EvidenceContractError


def _object(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceContractError(f"invalid persisted JSON artifact {path.name}") from exc
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"persisted artifact {path.name} must be an object")
    return value


def _artifact_id(path: Path, prefix: str) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _candidates(roots: Sequence[Path], name: str) -> tuple[Path, ...]:
    values: set[Path] = set()
    for root in roots:
        if root.is_file() and root.name == name:
            values.add(root.resolve())
        elif root.is_dir():
            values.update(path.resolve() for path in root.rglob(name) if path.is_file())
    return tuple(sorted(values, key=lambda value: value.as_posix()))


def _valid_state_rows(
    result: Mapping[str, Any], model_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    rows = result.get("states", ())
    warnings: list[str] = []
    output: list[dict[str, Any]] = []
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return output, ["persisted_state_history_unavailable"]
    for index, raw in enumerate(rows):
        row = _object(raw)
        if str(row.get("model_id", "")) != model_id:
            warnings.append(f"state_row_{index}_model_identity_mismatch")
            continue
        try:
            event_time = datetime.fromisoformat(str(row["event_time"]))
            available_at = datetime.fromisoformat(str(row["available_at"]))
        except (KeyError, ValueError):
            warnings.append(f"state_row_{index}_invalid_time")
            continue
        if event_time.tzinfo is None or available_at.tzinfo is None or available_at < event_time:
            warnings.append(f"state_row_{index}_invalid_causal_clock")
            continue
        probabilities = row.get("probabilities")
        unavailable = row.get("unavailable_reason")
        if probabilities is None:
            if not str(unavailable or "").strip():
                warnings.append(f"state_row_{index}_missing_unavailable_reason")
                continue
        elif (
            not isinstance(probabilities, Sequence)
            or isinstance(probabilities, (str, bytes))
            or not probabilities
        ):
            warnings.append(f"state_row_{index}_invalid_probabilities")
            continue
        else:
            try:
                values = [float(value) for value in probabilities]
            except (TypeError, ValueError):
                warnings.append(f"state_row_{index}_invalid_probabilities")
                continue
            if (
                any(not math.isfinite(value) or not 0 <= value <= 1 for value in values)
                or not math.isclose(math.fsum(values), 1.0, abs_tol=1e-12)
            ):
                warnings.append(f"state_row_{index}_invalid_probability_mass")
                continue
        output.append(dict(row))
    output.sort(key=lambda row: (str(row["event_time"]), str(row["available_at"])))
    return output, warnings


def _transitions(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    previous: Mapping[str, Any] | None = None
    for row in rows:
        state = row.get("state")
        if state is None:
            previous = None
            continue
        if previous is not None and previous.get("state") != state:
            output.append(
                {
                    "from_state": previous.get("state"),
                    "to_state": state,
                    "event_time": row.get("event_time"),
                    "available_at": row.get("available_at"),
                    "session_id": row.get("session_id"),
                    "semantics": "adjacent_persisted_available_snapshots_no_smoothing",
                }
            )
        previous = row
    return output


class MarketFactorIntelligenceProjection:
    """Disposable read model over persisted MarketState/FactorLibrary artifacts."""

    def __init__(
        self,
        report_paths: Sequence[str | Path],
        *,
        research_workspace: ResearchWorkspaceProjection | None = None,
    ) -> None:
        self.report_paths = tuple(Path(value).expanduser() for value in report_paths)
        self.research_workspace = research_workspace

    def _market_slices(self) -> tuple[list[dict[str, Any]], list[str]]:
        items: list[dict[str, Any]] = []
        warnings: list[str] = []
        for model_path in _candidates(self.report_paths, "market_state_model.json"):
            try:
                payload = _load_json(model_path)
                model = MarketStateModel.from_dict(payload)
            except (EvidenceContractError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f"{model_path.name}: {type(exc).__name__}: {exc}")
                continue
            result_path = model_path.with_name("result.json")
            result: Mapping[str, Any] = {}
            if result_path.is_file():
                try:
                    candidate = _load_json(result_path)
                    if str(candidate.get("model_id", "")) == model.model_id:
                        result = candidate
                    else:
                        warnings.append(
                            f"{model.model_id}: sibling result model identity mismatch"
                        )
                except EvidenceContractError as exc:
                    warnings.append(f"{model.model_id}: {exc}")
            states, state_warnings = _valid_state_rows(result, model.model_id)
            warnings.extend(f"{model.model_id}: {value}" for value in state_warnings)
            current = states[-1] if states else None
            items.append(
                {
                    "model_id": model.model_id,
                    "model": model.to_dict(),
                    "model_artifact_id": _artifact_id(model_path, "market-state-model"),
                    "result_artifact_id": (
                        _artifact_id(result_path, "market-state-result")
                        if result_path.is_file() and result
                        else None
                    ),
                    "historical_states": states,
                    "current_snapshot": current,
                    "transitions": _transitions(states),
                    "unavailable_snapshot_count": sum(
                        row.get("probabilities") is None for row in states
                    ),
                    "available_snapshot_count": sum(
                        row.get("probabilities") is not None for row in states
                    ),
                    "run_id": result.get("run_id"),
                    "evaluation_data_status": result.get("evaluation_data_status"),
                    "interpretation": result.get("interpretation"),
                }
            )
        items.sort(key=lambda item: str(item["model_id"]))
        return items, warnings

    def _portfolio_results(self) -> tuple[list[Mapping[str, Any]], list[str]]:
        output: list[Mapping[str, Any]] = []
        warnings: list[str] = []
        for path in _candidates(self.report_paths, "result.json"):
            try:
                payload = _load_json(path)
            except EvidenceContractError as exc:
                warnings.append(str(exc))
                continue
            if payload.get("version") != "finagent.deterministic-adaptive-result.v1":
                continue
            folds = payload.get("folds")
            if not isinstance(folds, Sequence) or isinstance(folds, (str, bytes)):
                warnings.append("deterministic adaptive result lacks fold sequence")
                continue
            output.append(payload)
        return output, warnings

    def _factor_items(self) -> tuple[list[dict[str, Any]], list[str]]:
        merged: dict[str, dict[str, Any]] = {}
        warnings: list[str] = []
        for path in _candidates(self.report_paths, "factor_library.sqlite"):
            library_id = _artifact_id(path, "factor-library")
            try:
                library = FactorLibrary(path, read_only=True)
            except (OSError, sqlite3.Error) as exc:
                warnings.append(f"{library_id}: {exc}")
                continue
            try:
                for row in library.list_factors():
                    factor_id = str(row["factor_id"])
                    definition = {
                        key: row.get(key)
                        for key in (
                            "factor_id",
                            "graph",
                            "family",
                            "mechanism",
                            "hypothesis",
                            "origin",
                            "provenance",
                            "created_at",
                            "activation_scope",
                        )
                    }
                    item = merged.setdefault(
                        factor_id,
                        {
                            "factor_id": factor_id,
                            "definition": definition,
                            "definition_conflict": False,
                            "library_ids": [],
                            "lifecycle": [],
                            "evaluations": {},
                        },
                    )
                    if item["definition"] != definition:
                        item["definition_conflict"] = True
                        warnings.append(f"{factor_id}: conflicting FactorLibrary definitions")
                    if library_id not in item["library_ids"]:
                        item["library_ids"].append(library_id)
                    for event in row.get("lifecycle", ()):
                        value = {**dict(event), "library_id": library_id}
                        key = json.dumps(value, sort_keys=True, separators=(",", ":"))
                        if all(
                            json.dumps(existing, sort_keys=True, separators=(",", ":")) != key
                            for existing in item["lifecycle"]
                        ):
                            item["lifecycle"].append(value)
                    for report in library.evaluations(factor_id):
                        evaluation_id = str(report.get("evaluation_id", ""))
                        if not evaluation_id:
                            warnings.append(f"{factor_id}: evaluation without canonical identity")
                            continue
                        existing = item["evaluations"].get(evaluation_id)
                        if existing is not None and existing != report:
                            warnings.append(f"{factor_id}: conflicting evaluation {evaluation_id}")
                            continue
                        item["evaluations"][evaluation_id] = dict(report)
            except (KeyError, ValueError, sqlite3.Error, json.JSONDecodeError) as exc:
                warnings.append(f"{library_id}: {type(exc).__name__}: {exc}")
            finally:
                library.close()

        output: list[dict[str, Any]] = []
        for factor_id, raw in merged.items():
            lifecycle = list(raw["lifecycle"])
            lifecycle.sort(
                key=lambda event: (
                    str(event.get("available_at", "")),
                    int(event.get("sequence", 0)),
                    str(event.get("library_id", "")),
                )
            )
            status = "UNAVAILABLE"
            status_reason = "lifecycle_unavailable"
            if lifecycle:
                latest_at = str(lifecycle[-1].get("available_at", ""))
                latest = [
                    event for event in lifecycle if str(event.get("available_at", "")) == latest_at
                ]
                statuses = {str(event.get("status", "")) for event in latest}
                if len(statuses) == 1:
                    status = statuses.pop()
                    status_reason = "latest_persisted_lifecycle_event"
                else:
                    status = "UNRESOLVED"
                    status_reason = "conflicting_lifecycle_at_same_availability"
            evaluations = list(raw["evaluations"].values())
            evaluations.sort(
                key=lambda value: (
                    str(value.get("available_at", "")),
                    str(value.get("evaluation_id", "")),
                )
            )
            latest_evaluation: Mapping[str, Any] | None = None
            evaluation_reason = "evaluation_unavailable"
            if evaluations:
                latest_at = str(evaluations[-1].get("available_at", ""))
                candidates = [
                    value
                    for value in evaluations
                    if str(value.get("available_at", "")) == latest_at
                ]
                if len(candidates) == 1:
                    latest_evaluation = candidates[0]
                    evaluation_reason = "latest_by_persisted_available_at"
                else:
                    evaluation_reason = "ambiguous_multiple_evaluations_same_available_at"
            definition = dict(raw["definition"])
            output.append(
                {
                    "factor_id": factor_id,
                    "status": status,
                    "status_reason": status_reason,
                    "family": definition.get("family"),
                    "mechanism": definition.get("mechanism"),
                    "hypothesis": definition.get("hypothesis"),
                    "origin": definition.get("origin"),
                    "provenance": definition.get("provenance") or {},
                    "created_at": definition.get("created_at"),
                    "definition_conflict": raw["definition_conflict"],
                    "library_ids": sorted(raw["library_ids"]),
                    "lifecycle": lifecycle,
                    "evaluations": evaluations,
                    "latest_evaluation": dict(latest_evaluation) if latest_evaluation else None,
                    "evaluation_selection_reason": evaluation_reason,
                }
            )
        output.sort(key=lambda item: str(item["factor_id"]))
        return output, warnings

    def _research_links(self, factor_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if self.research_workspace is None:
            return [], []
        experiments = []
        try:
            for item in self.research_workspace.experiments()["items"]:
                if factor_id in item.get("factor_ids", ()):
                    experiments.append(
                        {
                            "identity": item.get("identity"),
                            "experiment_id": item.get("experiment_id"),
                            "attempt_id": item.get("attempt_id"),
                            "run_id": item.get("run_id"),
                            "status": item.get("status"),
                        }
                    )
        except (FileNotFoundError, sqlite3.Error, EvidenceContractError):
            experiments = []
        decisions = []
        try:
            graph = self.research_workspace.graph()
            for node in graph["nodes"]:
                if node.get("kind") != "agent_decision":
                    continue
                details = _object(node.get("details"))
                if str(details.get("factor_id", "")) == factor_id:
                    decisions.append(
                        {
                            "node_id": node.get("node_id"),
                            "run_id": _object(node.get("context")).get("run_id"),
                            "status": node.get("status"),
                            "details": dict(details),
                        }
                    )
        except (FileNotFoundError, sqlite3.Error, EvidenceContractError):
            decisions = []
        return experiments, decisions

    def _allocator_weights(
        self,
        factor_id: str,
        *,
        model_id: str | None = None,
    ) -> list[dict[str, Any]]:
        reports, _ = self._portfolio_results()
        output: list[dict[str, Any]] = []
        for report in reports:
            for fold_raw in report.get("folds", ()):
                fold = _object(fold_raw)
                state_model = _object(fold.get("state_model"))
                fold_model_id = str(state_model.get("model_id", ""))
                if model_id and fold_model_id != model_id:
                    continue
                if factor_id not in {str(value) for value in fold.get("factor_ids", ())}:
                    continue
                fold_name = str(_object(fold.get("fold")).get("name", ""))
                for arm_name, arm_raw in _object(fold.get("arms")).items():
                    arm = _object(arm_raw)
                    for row_raw in arm.get("factor_weight_series", ()):
                        row = _object(row_raw)
                        weights = _object(row.get("weights"))
                        if factor_id not in weights:
                            continue
                        snapshot_model = row.get("market_state_model_id")
                        output.append(
                            {
                                "portfolio_run_id": report.get("run_id"),
                                "fold": fold_name,
                                "fold_market_state_model_id": fold_model_id or None,
                                "allocator": arm_name,
                                "allocator_id": row.get("allocator_id"),
                                "as_of": row.get("as_of"),
                                "session_id": row.get("session_id"),
                                "weight": weights.get(factor_id),
                                "market_state_model_id": snapshot_model,
                                "state_probabilities": row.get("state_probabilities"),
                                "fallback_reason": row.get("fallback_reason"),
                                "history_id": row.get("history_id"),
                                "state_link_status": (
                                    "persisted"
                                    if snapshot_model and row.get("state_probabilities") is not None
                                    else "unavailable_allocator_snapshot_has_no_market_state"
                                ),
                            }
                        )
        output.sort(key=lambda row: (str(row.get("as_of", "")), str(row.get("allocator", ""))))
        return output

    def factors(self) -> dict[str, object]:
        factors, warnings = self._factor_items()
        items = [
            {
                **{key: value for key, value in factor.items() if key not in {"evaluations", "latest_evaluation"}},
                "evaluation_count": len(factor["evaluations"]),
                "latest_model_id": _object(factor.get("latest_evaluation")).get("model_id")
                if factor.get("latest_evaluation")
                else None,
            }
            for factor in factors
        ]
        return {
            "schema_version": "finagent.workspace.factor-intelligence-index.v1",
            "items": items,
            "warnings": warnings,
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def factor(self, factor_id: str) -> dict[str, object]:
        factors, warnings = self._factor_items()
        match = next((item for item in factors if item["factor_id"] == factor_id), None)
        if match is None:
            raise KeyError(factor_id)
        latest = _object(match.get("latest_evaluation"))
        experiments, decisions = self._research_links(factor_id)
        weights = self._allocator_weights(factor_id)
        evidence_ids: list[str] = []
        for evaluation in match["evaluations"]:
            for key in ("evaluation_id", "source_id", "compiled_batch_id", "implementation_id"):
                value = str(evaluation.get(key, "") or "")
                if value and value not in evidence_ids:
                    evidence_ids.append(value)
        model_ids = sorted(
            {
                str(value.get("model_id"))
                for value in match["evaluations"]
                if value.get("model_id")
            }
        )
        similarity = _object(latest.get("global")).get("rank_similarity") if latest else None
        return {
            "schema_version": "finagent.workspace.factor-intelligence-detail.v1",
            "item": {
                **match,
                "global_metrics": dict(_object(latest.get("global"))) if latest else None,
                "state_metrics": dict(_object(latest.get("by_market_state"))) if latest else None,
                "cost_sensitive_economics": (
                    dict(_object(_object(latest.get("global")).get("economic_scenarios")))
                    if latest
                    else None
                ),
                "similarity": similarity,
                "novelty": None,
                "novelty_status": "unavailable_not_persisted",
                "allocator_weights": weights,
                "allocator_weight_status": "persisted" if weights else "unavailable_not_persisted",
                "linked_market_state_model_ids": model_ids,
                "linked_experiments": experiments,
                "agent_decision_history": decisions,
                "evidence_identities": evidence_ids,
                "unavailable": {
                    "latest_evaluation": match["evaluation_selection_reason"]
                    if not latest
                    else None,
                    "novelty": "not_persisted",
                    "allocator_weights": None if weights else "not_persisted",
                },
            },
            "warnings": warnings,
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def markets(self) -> dict[str, object]:
        slices, warnings = self._market_slices()
        factors, factor_warnings = self._factor_items()
        warnings.extend(factor_warnings)
        items: list[dict[str, Any]] = []
        for item in slices:
            model_id = str(item["model_id"])
            factor_evidence: list[dict[str, Any]] = []
            experiment_ids: set[str] = set()
            for factor in factors:
                evaluations = [
                    value
                    for value in factor["evaluations"]
                    if str(value.get("model_id", "")) == model_id
                ]
                if not evaluations:
                    continue
                experiments, _ = self._research_links(str(factor["factor_id"]))
                for experiment in experiments:
                    if experiment.get("experiment_id"):
                        experiment_ids.add(str(experiment["experiment_id"]))
                factor_evidence.append(
                    {
                        "factor_id": factor["factor_id"],
                        "status": factor["status"],
                        "evaluations": [
                            {
                                "evaluation_id": value.get("evaluation_id"),
                                "available_at": value.get("available_at"),
                                "global": value.get("global"),
                                "by_market_state": value.get("by_market_state"),
                                "conditioning": value.get("conditioning"),
                            }
                            for value in evaluations
                        ],
                        "allocator_weight_observations": self._allocator_weights(
                            str(factor["factor_id"]), model_id=model_id
                        ),
                    }
                )
            model = _object(item["model"])
            features = _object(model.get("features"))
            items.append(
                {
                    **item,
                    "feature_definitions": features.get("features") or [],
                    "feature_identities": None,
                    "feature_identity_status": "unavailable_not_persisted",
                    "causal": {
                        "inference": model.get("inference"),
                        "fit_window": model.get("fit_window"),
                        "model_available_at": model.get("available_at"),
                        "state_mapping": model.get("state_mapping"),
                        "missing": features.get("missing"),
                        "future_fill": False,
                        "smoothing": False,
                        "browser_refit": False,
                    },
                    "factor_state_evidence": factor_evidence,
                    "linked_experiment_ids": sorted(experiment_ids),
                    "unavailable": {
                        "historical_states": None
                        if item["historical_states"]
                        else "persisted_state_history_unavailable",
                        "feature_identities": "not_persisted",
                    },
                }
            )
        return {
            "schema_version": "finagent.workspace.market-state-index.v1",
            "items": items,
            "warnings": warnings,
            "read_only": True,
            "browser_recomputation": False,
            "causal_projection": True,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def market(self, model_id: str) -> dict[str, object]:
        payload = self.markets()
        item = next((value for value in payload["items"] if value["model_id"] == model_id), None)
        if item is None:
            raise KeyError(model_id)
        return {
            "schema_version": "finagent.workspace.market-state-detail.v1",
            "item": item,
            "warnings": payload["warnings"],
            "read_only": True,
            "browser_recomputation": False,
            "causal_projection": True,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def status(self) -> dict[str, object]:
        markets = self.markets()
        factors = self.factors()
        return {
            "schema_version": "finagent.workspace.market-factor-status.v1",
            "market_model_count": len(markets["items"]),
            "factor_count": len(factors["items"]),
            "read_only": True,
            "browser_recomputation": False,
            "causal_projection": True,
            "hidden_reasoning": "not_persisted_not_projected",
        }
