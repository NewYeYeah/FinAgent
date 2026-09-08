from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.strip() + "\n", encoding="utf-8")


write(
    "src/finagent/visualization/market_factor_intelligence.py",
    r'''
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
''',
)

write(
    "src/finagent/visualization/market_factor_intelligence_routes.py",
    r'''
from __future__ import annotations

import sqlite3

from fastapi import FastAPI, HTTPException

from .market_factor_intelligence import MarketFactorIntelligenceProjection
from .semantic import EvidenceContractError


def attach_market_factor_intelligence_routes(
    app: FastAPI,
    projection: MarketFactorIntelligenceProjection,
) -> None:
    @app.get("/api/v3/market-factor/status")
    def get_market_factor_status() -> dict[str, object]:
        return projection.status()

    @app.get("/api/v3/market-state")
    def get_market_state_index() -> dict[str, object]:
        try:
            return projection.markets()
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/market-state/{model_id}")
    def get_market_state_detail(model_id: str) -> dict[str, object]:
        try:
            return projection.market(model_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="market state model not found") from exc
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/factor-intelligence")
    def get_factor_intelligence_index() -> dict[str, object]:
        try:
            return projection.factors()
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/api/v3/factor-intelligence/{factor_id}")
    def get_factor_intelligence_detail(factor_id: str) -> dict[str, object]:
        try:
            return projection.factor(factor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="factor intelligence not found") from exc
        except (OSError, sqlite3.Error, EvidenceContractError) as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
''',
)

write(
    "workspace/src/workbench/marketFactorApi.ts",
    r'''
export interface MarketStateItem {
  model_id: string;
  model: Record<string, unknown>;
  model_artifact_id: string;
  result_artifact_id?: string | null;
  historical_states: Array<Record<string, unknown>>;
  current_snapshot: Record<string, unknown> | null;
  transitions: Array<Record<string, unknown>>;
  unavailable_snapshot_count: number;
  available_snapshot_count: number;
  run_id?: string | null;
  evaluation_data_status?: string | null;
  interpretation?: string | null;
  feature_definitions: string[];
  feature_identities: null;
  feature_identity_status: string;
  causal: Record<string, unknown>;
  factor_state_evidence: Array<{
    factor_id: string;
    status: string;
    evaluations: Array<Record<string, unknown>>;
    allocator_weight_observations: Array<Record<string, unknown>>;
  }>;
  linked_experiment_ids: string[];
  unavailable: Record<string, string | null>;
}

export interface MarketStateIndexResponse {
  schema_version: string;
  items: MarketStateItem[];
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  causal_projection: true;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface MarketStateDetailResponse extends Omit<MarketStateIndexResponse, "items"> {
  item: MarketStateItem;
}

export interface FactorIntelligenceSummary {
  factor_id: string;
  status: string;
  status_reason: string;
  family?: string | null;
  mechanism?: string | null;
  hypothesis?: string | null;
  origin?: string | null;
  provenance: Record<string, string>;
  created_at?: string | null;
  definition_conflict: boolean;
  library_ids: string[];
  lifecycle: Array<Record<string, unknown>>;
  evaluation_count: number;
  latest_model_id?: string | null;
  evaluation_selection_reason: string;
}

export interface FactorIntelligenceDetail extends Omit<FactorIntelligenceSummary, "evaluation_count"> {
  evaluations: Array<Record<string, unknown>>;
  latest_evaluation: Record<string, unknown> | null;
  global_metrics: Record<string, unknown> | null;
  state_metrics: Record<string, unknown> | null;
  cost_sensitive_economics: Record<string, unknown> | null;
  similarity: unknown;
  novelty: null;
  novelty_status: string;
  allocator_weights: Array<Record<string, unknown>>;
  allocator_weight_status: string;
  linked_market_state_model_ids: string[];
  linked_experiments: Array<Record<string, unknown>>;
  agent_decision_history: Array<Record<string, unknown>>;
  evidence_identities: string[];
  unavailable: Record<string, string | null>;
}

export interface FactorIntelligenceIndexResponse {
  schema_version: string;
  items: FactorIntelligenceSummary[];
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

export interface FactorIntelligenceDetailResponse {
  schema_version: string;
  item: FactorIntelligenceDetail;
  warnings: string[];
  read_only: true;
  browser_recomputation: false;
  hidden_reasoning: "not_persisted_not_projected";
}

async function json<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export const marketFactorQueryKeys = {
  root: ["workbench2", "market-factor"] as const,
  markets: () => [...marketFactorQueryKeys.root, "markets"] as const,
  market: (modelId: string) => [...marketFactorQueryKeys.root, "market", modelId] as const,
  factors: () => [...marketFactorQueryKeys.root, "factors"] as const,
  factor: (factorId: string) => [...marketFactorQueryKeys.root, "factor", factorId] as const,
};

export const marketFactorApi = {
  markets() {
    return json<MarketStateIndexResponse>("/api/v3/market-state");
  },
  market(modelId: string) {
    return json<MarketStateDetailResponse>(`/api/v3/market-state/${encodeURIComponent(modelId)}`);
  },
  factors() {
    return json<FactorIntelligenceIndexResponse>("/api/v3/factor-intelligence");
  },
  factor(factorId: string) {
    return json<FactorIntelligenceDetailResponse>(`/api/v3/factor-intelligence/${encodeURIComponent(factorId)}`);
  },
};
''',
)

write(
    "workspace/src/workbench/market.tsx",
    r'''
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { Activity, Link2, LockKeyhole } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { EmptyState, ErrorState, LoadingState, PageHeader, Panel, StatusBadge } from "../components";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import { marketFactorApi, marketFactorQueryKeys } from "./marketFactorApi";
import { researchQueryKeys, researchWorkspaceApi } from "./researchWorkspaceApi";
import "./marketFactor.css";

function json(value: unknown) {
  return value == null ? "unavailable" : JSON.stringify(value, null, 2);
}

function MarketContent() {
  const { context, select } = useWorkbenchContext();
  const indexQuery = useQuery({ queryKey: marketFactorQueryKeys.markets(), queryFn: marketFactorApi.markets, retry: false });
  const cyclesQuery = useQuery({ queryKey: researchQueryKeys.cycles(), queryFn: researchWorkspaceApi.cycles, retry: false });
  const selectedModel = context.market_state_model_id;
  const modelId = selectedModel && indexQuery.data?.items.some((item) => item.model_id === selectedModel)
    ? selectedModel
    : indexQuery.data?.items[0]?.model_id;
  const detailQuery = useQuery({
    queryKey: marketFactorQueryKeys.market(modelId ?? ""),
    queryFn: () => marketFactorApi.market(modelId ?? ""),
    enabled: Boolean(modelId),
    retry: false,
  });

  useEffect(() => {
    if (modelId && context.market_state_model_id !== modelId) {
      select({ market_state_model_id: modelId }, "market_state_selected", { replace: true });
    }
  }, [context.market_state_model_id, modelId, select]);

  if (indexQuery.isPending || cyclesQuery.isPending) return <LoadingState label="Loading persisted MarketState evidence" />;
  if (indexQuery.error || cyclesQuery.error) return <ErrorState error={indexQuery.error ?? cyclesQuery.error} />;

  const accepted = cyclesQuery.data?.items.find((cycle) => cycle.accepted === true);
  const items = indexQuery.data?.items ?? [];
  if (!items.length) {
    return <div className="page market-state-page">
      <PageHeader eyebrow="Workbench-2 · causal state evidence" title="Market State" description="No persisted MarketState model/result is available under the configured Evidence Plane report roots." />
      {accepted ? <div className="market-r4-carry"><strong>{accepted.terminal}</strong><span>AgentValue {accepted.agent_value}</span><span>This accepted completeness/reliability result does not imply MarketState is invalid.</span></div> : null}
      <EmptyState title="MarketState unavailable" detail="The UI does not fit a GMM, cluster, smooth, infer missing states, or fill current state from future observations." />
    </div>;
  }
  if (detailQuery.isPending) return <LoadingState label="Loading MarketState model detail" />;
  if (detailQuery.error) return <ErrorState error={detailQuery.error} />;
  const item = detailQuery.data?.item;
  if (!item) return <EmptyState title="MarketState unavailable" detail="No canonical MarketState model is selected." />;
  const model = item.model as Record<string, unknown>;
  const current = item.current_snapshot;
  const search = workbenchContextSearch(context);

  return <div className="page market-state-page">
    <PageHeader eyebrow="Workbench-2 · causal state evidence" title="Market State" description="Persisted model parameters, causal state probabilities and exact linked research identities. No browser refit or smoothing." />
    {accepted ? <div className="market-r4-carry"><strong>{accepted.terminal}</strong><span>AgentValue {accepted.agent_value}</span><span>{String((accepted.economic_evidence as Record<string, unknown>).complete_deterministic_strategy_count ?? "?")}/{String((accepted.economic_evidence as Record<string, unknown>).deterministic_strategy_count ?? "?")} complete deterministic strategies</span><span>{String((accepted.agent_reliability as Record<string, unknown>).rejected_action_attempts ?? "?")} rejected actions</span></div> : null}
    <div className="market-toolbar"><label><span>Model</span><select value={item.model_id} onChange={(event) => select({ market_state_model_id: event.target.value }, "market_state_selected")}>{items.map((value) => <option value={value.model_id} key={value.model_id}>{value.model_id}</option>)}</select></label><StatusBadge value="causal persisted" tone="positive" /></div>

    <div className="market-factor-grid">
      <Panel title="Model identity & fit window" subtitle="Validated inert JSON parameters; model identity is content-derived in the core.">
        <dl className="market-factor-kv">
          <div><dt>Model</dt><dd className="mono">{item.model_id}</dd></div>
          <div><dt>Version</dt><dd>{String(model.version ?? "unavailable")}</dd></div>
          <div><dt>Estimator</dt><dd>{String(model.estimator ?? "unavailable")}</dd></div>
          <div><dt>Available at</dt><dd>{String(model.available_at ?? "unavailable")}</dd></div>
          <div><dt>Fit / training window</dt><dd><code>{json(model.fit_window)}</code></dd></div>
          <div><dt>Implementation</dt><dd className="mono">{String(model.implementation_id ?? "unavailable")}</dd></div>
        </dl>
      </Panel>
      <Panel title="Latest persisted snapshot" subtitle="Latest by persisted event/availability timestamps; not a realtime or future-filled state.">
        {current ? <dl className="market-factor-kv">
          <div><dt>Event</dt><dd>{String(current.event_time ?? "unavailable")}</dd></div>
          <div><dt>Available at</dt><dd>{String(current.available_at ?? "unavailable")}</dd></div>
          <div><dt>State</dt><dd>{String(current.state ?? "unavailable")}</dd></div>
          <div><dt>Probabilities</dt><dd><code data-testid="market-probabilities">{json(current.probabilities)}</code></dd></div>
          <div><dt>Unavailable reason</dt><dd>{String(current.unavailable_reason ?? "none")}</dd></div>
        </dl> : <div className="market-factor-unavailable">Persisted state history unavailable. No state is inferred.</div>}
      </Panel>
    </div>

    <Panel title="Causal feature/model contract" subtitle="Definitions are persisted; feature identities are unavailable because the artifact does not persist separate canonical feature IDs.">
      <div className="market-feature-list">{item.feature_definitions.length ? item.feature_definitions.map((definition) => <code key={definition}>{definition}</code>) : <span>unavailable</span>}</div>
      <pre className="json-view">{json(item.causal)}</pre>
      <p className="subtle">feature identities: {item.feature_identity_status} · browser_refit=false · smoothing=false · future_fill=false</p>
    </Panel>

    <div className="two-column">
      <Panel title="Historical state probabilities" subtitle="Persisted snapshots only, including unavailable rows and their explicit reasons.">
        <div className="market-history-list">{item.historical_states.length ? item.historical_states.map((row, index) => <article key={`${String(row.event_time)}-${index}`}><time>{String(row.available_at ?? row.event_time)}</time><strong>state {String(row.state ?? "unavailable")}</strong><code>{json(row.probabilities)}</code>{row.unavailable_reason ? <span>{String(row.unavailable_reason)}</span> : null}</article>) : <span className="market-factor-unavailable">unavailable</span>}</div>
      </Panel>
      <Panel title="Observed state transitions" subtitle="Server presentation projection over adjacent available persisted snapshots; gaps reset the chain and no smoothing/rate inference is performed.">
        {item.transitions.length ? <div className="market-transition-list">{item.transitions.map((row, index) => <article key={`${String(row.event_time)}-${index}`}><strong>{String(row.from_state)} → {String(row.to_state)}</strong><time>{String(row.available_at)}</time><small>{String(row.semantics)}</small></article>)}</div> : <div className="market-factor-unavailable">No adjacent persisted state changes are available.</div>}
      </Panel>
    </div>

    <Panel title="Factor performance / allocation by MarketState" subtitle="Factor metrics and allocator weights are copied from persisted FactorLibrary/adaptive portfolio artifacts. Missing bindings remain unavailable.">
      {item.factor_state_evidence.length ? <div className="market-factor-evidence">{item.factor_state_evidence.map((factor) => <article key={factor.factor_id}><header><Link to={`/factors${search}`} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}><Link2 size={12} /> {factor.factor_id}</Link><StatusBadge value={factor.status} tone={factor.status === "REJECTED" || factor.status === "RETIRED" ? "negative" : "neutral"} /></header><pre className="json-view">{json(factor.evaluations.map((value) => ({ evaluation_id: value.evaluation_id, by_market_state: value.by_market_state, conditioning: value.conditioning })))}</pre><small>{factor.allocator_weight_observations.length} persisted allocator weight observations</small></article>)}</div> : <div className="market-factor-unavailable">No FactorLibrary evaluation explicitly binds this model identity.</div>}
    </Panel>

    <div className="market-linked-actions">
      <Link to={`/research-graph${search}`}><Activity size={13} /> Research Graph</Link>
      {item.linked_experiment_ids.map((experimentId) => <Link key={experimentId} to={`/experiments?experiment=${encodeURIComponent(experimentId)}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> experiment:{experimentId}</Link>)}
    </div>
    <p className="market-authority-note"><LockKeyhole size={12} /> Hidden chain-of-thought is not persisted or projected. Browser financial/statistical recomputation = false.</p>
  </div>;
}

export function MarketStatePage() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } } }));
  return <QueryClientProvider client={client}><MarketContent /></QueryClientProvider>;
}
''',
)

write(
    "workspace/src/workbench/factorIntelligence.tsx",
    r'''
import { useQuery } from "@tanstack/react-query";
import { GitBranch, Link2, LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState, StatusBadge } from "../components";
import { useWorkbenchContext, workbenchContextSearch } from "./context";
import { marketFactorApi, marketFactorQueryKeys } from "./marketFactorApi";
import "./marketFactor.css";

function json(value: unknown) {
  return value == null ? "unavailable" : JSON.stringify(value, null, 2);
}

export function FactorIntelligencePanel() {
  const { context, select } = useWorkbenchContext();
  const indexQuery = useQuery({ queryKey: marketFactorQueryKeys.factors(), queryFn: marketFactorApi.factors, retry: false });
  const factorId = context.factor_id && indexQuery.data?.items.some((item) => item.factor_id === context.factor_id)
    ? context.factor_id
    : undefined;
  const detailQuery = useQuery({
    queryKey: marketFactorQueryKeys.factor(factorId ?? ""),
    queryFn: () => marketFactorApi.factor(factorId ?? ""),
    enabled: Boolean(factorId),
    retry: false,
  });

  if (indexQuery.isPending) return <section className="factor-intelligence-shell"><LoadingState label="Loading FactorLibrary intelligence" /></section>;
  if (indexQuery.error) return <section className="factor-intelligence-shell"><ErrorState error={indexQuery.error} /></section>;
  const factors = indexQuery.data?.items ?? [];
  if (!factors.length) return <section className="factor-intelligence-shell"><header><div><span className="eyebrow">Workbench-2 · FactorLibrary</span><h2>Factor Intelligence</h2></div><span className="experiment-contract">no browser recomputation</span></header><div className="market-factor-unavailable">No persisted FactorLibrary is available under the configured report roots. Existing Tear Sheet evidence remains below.</div></section>;

  const detail = detailQuery.data?.item;
  const search = workbenchContextSearch(context);
  return <section className="factor-intelligence-shell" aria-label="Factor Intelligence">
    <header><div><span className="eyebrow">Workbench-2 · FactorLibrary</span><h2>Factor Intelligence</h2><p>Lifecycle, causal state-conditioned development evidence, persisted allocator weights and research lineage.</p></div><span className="experiment-contract">GET-only · server authoritative</span></header>
    <div className="factor-intelligence-selector">{factors.map((factor) => <button type="button" className={factor.factor_id === factorId ? "selected" : ""} key={factor.factor_id} onClick={() => select({ factor_id: factor.factor_id }, "factor_selected")}><strong>{factor.factor_id}</strong><span>{factor.family ?? "family unavailable"}</span><StatusBadge value={factor.status} tone={factor.status === "REJECTED" || factor.status === "RETIRED" ? "negative" : factor.status === "DORMANT" ? "neutral" : "positive"} /></button>)}</div>
    {context.factor_id && !factorId ? <div className="market-factor-unavailable">The selected Tear Sheet factor identity is not present in a persisted FactorLibrary. Intelligence fields remain unavailable rather than inferred.</div> : null}
    {factorId && detailQuery.isPending ? <LoadingState label="Loading persisted factor intelligence" /> : null}
    {detailQuery.error ? <ErrorState error={detailQuery.error} /> : null}
    {detail ? <div className="factor-intelligence-detail">
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><header><h3>Lifecycle / hypothesis</h3><StatusBadge value={detail.status} tone={detail.status === "REJECTED" || detail.status === "RETIRED" ? "negative" : "neutral"} /></header><dl className="market-factor-kv"><div><dt>Family</dt><dd>{detail.family ?? "unavailable"}</dd></div><div><dt>Mechanism</dt><dd>{detail.mechanism ?? "unavailable"}</dd></div><div><dt>Hypothesis</dt><dd>{detail.hypothesis ?? "unavailable"}</dd></div><div><dt>Origin</dt><dd>{detail.origin ?? "unavailable"}</dd></div></dl><pre className="json-view" data-testid="factor-lifecycle">{json(detail.lifecycle)}</pre></article>
        <article className="factor-intelligence-card"><h3>Provenance / Agent decisions</h3><pre className="json-view" data-testid="factor-provenance">{json(detail.provenance)}</pre>{detail.agent_decision_history.length ? <pre className="json-view">{json(detail.agent_decision_history)}</pre> : <div className="market-factor-unavailable">Agent decision history unavailable for this exact factor identity.</div>}</article>
      </div>
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><h3>Global development metrics</h3>{detail.global_metrics ? <pre className="json-view" data-testid="factor-global-metrics">{json(detail.global_metrics)}</pre> : <div className="market-factor-unavailable">unavailable · {detail.evaluation_selection_reason}</div>}</article>
        <article className="factor-intelligence-card"><h3>MarketState-conditioned metrics</h3>{detail.state_metrics ? <pre className="json-view" data-testid="factor-state-metrics">{json(detail.state_metrics)}</pre> : <div className="market-factor-unavailable">unavailable</div>}</article>
      </div>
      <div className="market-factor-grid">
        <article className="factor-intelligence-card"><h3>Cost-sensitive economics</h3>{detail.cost_sensitive_economics ? <pre className="json-view">{json(detail.cost_sensitive_economics)}</pre> : <div className="market-factor-unavailable">unavailable</div>}</article>
        <article className="factor-intelligence-card"><h3>Similarity / novelty</h3>{detail.similarity ? <pre className="json-view">{json(detail.similarity)}</pre> : <div className="market-factor-unavailable">similarity unavailable</div>}<p>novelty: {detail.novelty_status}</p></article>
      </div>
      <article className="factor-intelligence-card"><h3>Persisted allocator weight history</h3>{detail.allocator_weights.length ? <div className="factor-weight-list" data-testid="factor-weights">{detail.allocator_weights.map((row, index) => <div key={`${String(row.as_of)}-${String(row.allocator)}-${index}`}><time>{String(row.as_of)}</time><strong>{String(row.allocator)}</strong><code>weight={String(row.weight)}</code><span>{String(row.state_link_status)}</span></div>)}</div> : <div className="market-factor-unavailable">unavailable · no persisted allocator snapshot binds this factor.</div>}</article>
      <article className="factor-intelligence-card"><h3>Canonical linked research</h3><div className="market-linked-actions">{detail.linked_market_state_model_ids.map((modelId) => <Link key={modelId} to={`/market?market_model=${encodeURIComponent(modelId)}${search ? `&${search.slice(1)}` : ""}`} onClick={() => select({ market_state_model_id: modelId }, "market_state_selected")}><Link2 size={12} /> MarketState:{modelId}</Link>)}{detail.linked_experiments.map((experiment) => <Link key={String(experiment.identity)} to={`/experiments?experiment=${encodeURIComponent(String(experiment.identity))}${search ? `&${search.slice(1)}` : ""}`}><Link2 size={12} /> experiment:{String(experiment.identity)}</Link>)}<Link to={`/research-graph${search}`}><GitBranch size={12} /> Research Graph</Link>{detail.agent_decision_history.map((decision) => decision.run_id ? <Link key={String(decision.node_id)} to={`/agent?run=${encodeURIComponent(String(decision.run_id))}${search ? `&${search.slice(1)}` : ""}`}>Agent run:{String(decision.run_id)}</Link> : null)}</div><pre className="json-view">{json(detail.evidence_identities)}</pre></article>
    </div> : null}
    <p className="market-authority-note"><LockKeyhole size={12} /> Existing Tear Sheet IC/decay/heatmap/bootstrap/multiplicity/correlation/provenance remains authoritative below. Hidden chain-of-thought is not persisted or projected.</p>
  </section>;
}
''',
)

write(
    "workspace/src/workbench/marketFactor.css",
    r'''
.market-state-page,.factor-intelligence-shell{display:flex;flex-direction:column;gap:14px}.market-r4-carry{display:flex;gap:12px;flex-wrap:wrap;padding:10px 12px;border:1px solid var(--border);border-radius:10px}.market-r4-carry strong{font-family:var(--mono)}.market-toolbar{display:flex;align-items:end;gap:12px}.market-toolbar label{display:flex;flex-direction:column;gap:4px;min-width:320px}.market-toolbar select{max-width:100%;padding:7px}.market-factor-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.market-factor-kv{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.market-factor-kv div{min-width:0}.market-factor-kv dt{font-size:11px;color:var(--muted)}.market-factor-kv dd{margin:2px 0 0;word-break:break-word}.market-feature-list{display:flex;gap:7px;flex-wrap:wrap}.market-history-list,.market-transition-list,.market-factor-evidence,.factor-weight-list{display:flex;flex-direction:column;gap:7px;max-height:430px;overflow:auto}.market-history-list article,.market-transition-list article,.market-factor-evidence article,.factor-weight-list div{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px;border:1px solid var(--border);border-radius:8px}.market-history-list code{max-width:100%;overflow:auto}.market-factor-evidence article{align-items:stretch;flex-direction:column}.market-factor-evidence header{display:flex;gap:8px;justify-content:space-between}.market-factor-unavailable{padding:12px;border:1px dashed var(--border);border-radius:8px;color:var(--muted)}.market-linked-actions{display:flex;gap:8px;flex-wrap:wrap}.market-linked-actions a{display:inline-flex;align-items:center;gap:5px}.market-authority-note{color:var(--muted);display:flex;align-items:center;gap:5px}.factor-intelligence-shell{padding:14px;border:1px solid var(--border);border-radius:12px;background:var(--surface)}.factor-intelligence-shell>header{display:flex;justify-content:space-between;gap:16px}.factor-intelligence-shell h2,.factor-intelligence-shell h3,.factor-intelligence-shell p{margin-top:0}.factor-intelligence-selector{display:flex;gap:7px;overflow:auto;padding-bottom:4px}.factor-intelligence-selector button{display:grid;grid-template-columns:auto auto;gap:4px;min-width:220px;text-align:left;border:1px solid var(--border);background:transparent;color:inherit;border-radius:8px;padding:8px;cursor:pointer}.factor-intelligence-selector button.selected{outline:1px solid currentColor}.factor-intelligence-selector button span:not(.badge){grid-column:1/-1;color:var(--muted)}.factor-intelligence-detail{display:flex;flex-direction:column;gap:12px}.factor-intelligence-card{padding:12px;border:1px solid var(--border);border-radius:10px;min-width:0}.factor-intelligence-card>header{display:flex;justify-content:space-between;gap:8px}.factor-intelligence-card .json-view{max-height:320px;overflow:auto}@media(max-width:1000px){.market-factor-grid{grid-template-columns:1fr}.market-toolbar label{min-width:0;flex:1}}''',
)

# --- Existing backend integration -------------------------------------------------
workspace_api = ROOT / "src/finagent/visualization/workspace_api.py"
text = workspace_api.read_text(encoding="utf-8")
text = text.replace(
    "from .agent_projection import load_agent_run_projection\n",
    "from .agent_projection import load_agent_run_projection\nfrom .market_factor_intelligence import MarketFactorIntelligenceProjection\nfrom .market_factor_intelligence_routes import attach_market_factor_intelligence_routes\n",
)
text = text.replace(
    "    research_workspace = ResearchWorkspaceProjection(agent_path)\n",
    "    research_workspace = ResearchWorkspaceProjection(agent_path)\n    market_factor_intelligence = MarketFactorIntelligenceProjection(\n        report_paths, research_workspace=research_workspace\n    )\n",
)
text = text.replace(
    "    app.state.research_workspace = research_workspace\n",
    "    app.state.research_workspace = research_workspace\n    app.state.market_factor_intelligence = market_factor_intelligence\n",
)
text = text.replace(
    "    attach_research_workspace_routes(app, research_workspace)\n",
    "    attach_research_workspace_routes(app, research_workspace)\n    attach_market_factor_intelligence_routes(app, market_factor_intelligence)\n",
)
text = text.replace(
    '            "research_workspace": research_workspace.status(),\n',
    '            "research_workspace": research_workspace.status(),\n            "market_factor_intelligence": market_factor_intelligence.status(),\n',
)
workspace_api.write_text(text, encoding="utf-8")

# --- Carry-forward hardening + graph MarketState node ------------------------------
research = ROOT / "src/finagent/visualization/research_workspace.py"
text = research.read_text(encoding="utf-8")
text = text.replace(
    '                "SELECT r.run_id,r.payload_json,r.decision_json,t.sequence,t.call_id,"\n',
    '                "SELECT r.rowid,r.run_id,r.payload_json,r.decision_json,t.sequence,t.call_id,"\n',
)
text = text.replace(
    "        for run_id, payload_raw, decision_raw, sequence, call_id, request_raw, result_raw in rows:\n",
    "        for run_ordinal, run_id, payload_raw, decision_raw, sequence, call_id, request_raw, result_raw in rows:\n",
)
text = text.replace(
    '                    "run_id": str(run_id),\n                    "sequence": int(sequence),\n',
    '                    "run_id": str(run_id),\n                    "run_ordinal": int(run_ordinal),\n                    "run_started_at": str(context.get("started_at", "")),\n                    "sequence": int(sequence),\n',
)
text = text.replace(
    '                "identity_kind": "experiment_id" if experiment_id else "attempt_call_id",\n',
    '                "identity_kind": "experiment_id" if experiment_id else "attempt_call_id",\n                "attempt_order": {\n                    "run_ordinal": record["run_ordinal"],\n                    "tool_sequence": record["sequence"],\n                    "run_started_at": record["run_started_at"],\n                },\n',
)
old = '''        if len(matches) > 1:\n            # Duplicate experiment attempts are separate persisted trials; selecting\n            # the canonical experiment id returns the latest attempt deterministically.\n            matches.sort(key=lambda item: (item["run_id"], item["attempt_id"]))\n        return {\n            "schema_version": "finagent.workspace.research-experiment-detail.v1",\n            "item": matches[-1],\n            "read_only": True,\n            "browser_recomputation": False,\n            "hidden_reasoning": "not_persisted_not_projected",\n        }'''
new = '''        matches.sort(\n            key=lambda item: (\n                int(_object(item.get("attempt_order")).get("run_ordinal", -1)),\n                int(_object(item.get("attempt_order")).get("tool_sequence", -1)),\n            )\n        )\n        return {\n            "schema_version": "finagent.workspace.research-experiment-detail.v1",\n            "item": matches[-1],\n            "attempts": matches,\n            "attempt_count": len(matches),\n            "selection_semantics": "persisted_agent_audit_run_ordinal_then_tool_sequence",\n            "read_only": True,\n            "browser_recomputation": False,\n            "hidden_reasoning": "not_persisted_not_projected",\n        }'''
if old not in text:
    raise RuntimeError("research experiment hardening target not found")
text = text.replace(old, new)
# cycles: add accepted/review status and fail-closed unresolved collection.
text = text.replace(
    "        items: list[dict[str, Any]] = []\n        seen: set[str] = set()\n",
    "        items: list[dict[str, Any]] = []\n        unresolved: list[dict[str, Any]] = []\n        seen: set[str] = set()\n",
    1,
)
text = text.replace(
    '                items.append(\n                    {\n                        "cycle_id": cycle_id,\n',
    '                accepted = value.get("review_disposition") == "R4_RESULT_ACCEPTED"\n                if not accepted:\n                    unresolved.append(\n                        {\n                            "cycle_id": cycle_id,\n                            "relation": "review_disposition",\n                            "reason": "accepted_review_disposition_missing_or_unrecognized",\n                        }\n                    )\n                items.append(\n                    {\n                        "cycle_id": cycle_id,\n                        "accepted": accepted,\n                        "review_status": "accepted" if accepted else "not_accepted",\n',
)
text = text.replace(
    '            "items": items,\n            "read_only": True,\n            "browser_recomputation": False,\n        }\n\n    def graph(',
    '            "items": items,\n            "unresolved": unresolved,\n            "read_only": True,\n            "browser_recomputation": False,\n        }\n\n    def graph(',
)
# graph MarketState node before literature branch.
needle = '            if tool == "read_literature" and result.get("outcome") == "LITERATURE_READ":\n'
market_branch = '''            if tool == "inspect_market_state" and result.get("outcome") == "MARKET_STATE_INSPECTED":\n                market_state = _object(result.get("market_state"))\n                model_id = str(market_state.get("model_id", ""))\n                if model_id:\n                    node(\n                        "market_state",\n                        model_id,\n                        label=f"MarketState · {model_id}",\n                        href=f"/market?market_model={quote(model_id, safe='')}",\n                        context={**run_context, "market_state_model_id": model_id},\n                        details=market_state,\n                    )\n                else:\n                    unresolved.append(\n                        {\n                            "run_id": record["run_id"],\n                            "call_id": record["call_id"],\n                            "relation": "market_state_model_identity",\n                            "reason": "persisted_market_state_model_id_unavailable",\n                        }\n                    )\n            elif tool == "read_literature" and result.get("outcome") == "LITERATURE_READ":\n'''
if needle not in text:
    raise RuntimeError("research graph MarketState target not found")
text = text.replace(needle, market_branch)
# cycle graph fail closed: do not default to accepted.
text = text.replace(
    '        for cycle in self.cycles()["items"]:\n            cycle_id = str(cycle["cycle_id"])\n            cycle_node = node(\n',
    '        for cycle in self.cycles()["items"]:\n            cycle_id = str(cycle["cycle_id"])\n            if cycle.get("accepted") is not True:\n                unresolved.append(\n                    {\n                        "cycle_id": cycle_id,\n                        "relation": "accepted_cycle_lineage",\n                        "reason": "cycle_not_explicitly_accepted",\n                    }\n                )\n                continue\n            cycle_node = node(\n',
)
text = text.replace(
    '                status=str(cycle.get("review_disposition") or "accepted").lower(),\n',
    '                status="accepted",\n',
)
research.write_text(text, encoding="utf-8")

# --- WorkbenchContext ---------------------------------------------------------------
context = ROOT / "workspace/src/workbench/context.tsx"
text = context.read_text(encoding="utf-8")
text = text.replace("  graph_node_id?: string;\n", "  graph_node_id?: string;\n  market_state_model_id?: string;\n")
text = text.replace('  | "graph_node_selected"\n', '  | "graph_node_selected"\n  | "market_state_selected"\n')
text = text.replace('  graph_node_id: "graph_node",\n', '  graph_node_id: "graph_node",\n  market_state_model_id: "market_model",\n')
context.write_text(text, encoding="utf-8")

# --- Panels / shell -----------------------------------------------------------------
panels = ROOT / "workspace/src/workbench/panels.ts"
text = panels.read_text(encoding="utf-8")
text = text.replace('  | "research-graph"\n', '  | "research-graph"\n  | "market"\n')
text = text.replace(
    '  { panel_id: "research-graph", module: "research-graph", title: "Research Graph", route: "/research-graph", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "factor_id", "research_cycle_id", "graph_node_id"], slot: "chart" },\n',
    '  { panel_id: "research-graph", module: "research-graph", title: "Research Graph", route: "/research-graph", status: "available", context_keys: ["project_id", "thread_id", "run_id", "experiment_id", "factor_id", "research_cycle_id", "graph_node_id", "market_state_model_id"], slot: "chart" },\n  { panel_id: "market", module: "market", title: "Market", route: "/market", status: "available", context_keys: ["market_state_model_id", "factor_id", "experiment_id", "run_id"], slot: "chart" },\n',
)
text = text.replace(
    '  { panel_id: "factors", module: "factors", title: "Factors", route: "/factors", status: "available", context_keys: ["program_id", "factor_id", "date_range", "fold_id"], slot: "chart" },\n',
    '  { panel_id: "factors", module: "factors", title: "Factors", route: "/factors", status: "available", context_keys: ["program_id", "factor_id", "market_state_model_id", "experiment_id", "date_range", "fold_id"], slot: "chart" },\n',
)
panels.write_text(text, encoding="utf-8")

shell = ROOT / "workspace/src/workbench/shell.tsx"
text = shell.read_text(encoding="utf-8")
text = text.replace('  "research-graph": <GitBranch size={17} />,\n', '  "research-graph": <GitBranch size={17} />,\n  market: <CircleGauge size={17} />,\n')
text = text.replace('  graph_node_id: "Graph node",\n', '  graph_node_id: "Graph node",\n  market_state_model_id: "Market model",\n')
shell.write_text(text, encoding="utf-8")

# --- Research Graph frontend canonical context --------------------------------------
graph = ROOT / "workspace/src/workbench/researchGraph.tsx"
text = graph.read_text(encoding="utf-8")
text = text.replace('  research_cycle: 0,\n', '  research_cycle: 0,\n  market_state: 1,\n')
text = text.replace('    "research_cycle_id",\n', '    "research_cycle_id",\n    "market_state_model_id",\n')
graph.write_text(text, encoding="utf-8")

# --- Research API types for fail-closed cycles/attempt chronology ------------------
rwa = ROOT / "workspace/src/workbench/researchWorkspaceApi.ts"
text = rwa.read_text(encoding="utf-8")
text = text.replace(
    '  identity_kind: "experiment_id" | "attempt_call_id";\n',
    '  identity_kind: "experiment_id" | "attempt_call_id";\n  attempt_order?: { run_ordinal: number; tool_sequence: number; run_started_at: string };\n',
)
text = text.replace(
    'export interface ResearchExperimentDetailResponse {\n  schema_version: string;\n  item: ResearchExperiment;\n',
    'export interface ResearchExperimentDetailResponse {\n  schema_version: string;\n  item: ResearchExperiment;\n  attempts?: ResearchExperiment[];\n  attempt_count?: number;\n  selection_semantics?: string;\n',
)
text = text.replace(
    '  cycle_id: string;\n',
    '  cycle_id: string;\n  accepted: boolean;\n  review_status: string;\n',
    1,
)
text = text.replace(
    '  items: ResearchCycle[];\n',
    '  items: ResearchCycle[];\n  unresolved?: Array<Record<string, unknown>>;\n',
)
rwa.write_text(text, encoding="utf-8")

# --- Factor Tear Sheet: migrate touched queries + add intelligence ------------------
factor = ROOT / "workspace/src/workbench/factor.tsx"
text = factor.read_text(encoding="utf-8")
text = text.replace(
    'import { useEffect, useMemo, useState } from "react";\n',
    'import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";\nimport { useEffect, useMemo, useState, type ReactNode } from "react";\n',
)
text = text.replace('import { factorTearSheetApi } from "./factorApi";\n', 'import { factorTearSheetApi } from "./factorApi";\nimport { FactorIntelligencePanel } from "./factorIntelligence";\n')
text = text.replace('import { useWorkbenchQuery } from "./query";\n', '')
text = re.sub(r'useWorkbenchQuery\(\{\s*key:', 'useQuery({ queryKey:', text)
text = text.replace('export function FactorTearSheetIndexPage() {', 'function FactorTearSheetIndexContent() {')
text = text.replace('export function FactorTearSheetPage() {', 'function FactorTearSheetContent() {')
text += r'''

function FactorQueryBoundary({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 1_500 } },
  }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export function FactorTearSheetIndexPage() {
  return <FactorQueryBoundary><FactorIntelligencePanel /><FactorTearSheetIndexContent /></FactorQueryBoundary>;
}

export function FactorTearSheetPage() {
  return <FactorQueryBoundary><FactorIntelligencePanel /><FactorTearSheetContent /></FactorQueryBoundary>;
}
'''
factor.write_text(text, encoding="utf-8")

# --- App route ----------------------------------------------------------------------
app = ROOT / "workspace/src/App.tsx"
text = app.read_text(encoding="utf-8")
text = text.replace(
    'import { FactorTearSheetIndexPage, FactorTearSheetPage } from "./workbench/factor";\n',
    'import { FactorTearSheetIndexPage, FactorTearSheetPage } from "./workbench/factor";\nimport { MarketStatePage } from "./workbench/market";\n',
)
text = text.replace(
    '            <Route path="/factors" element={<FactorTearSheetIndexPage />} />\n',
    '            <Route path="/market" element={<MarketStatePage />} />\n            <Route path="/factors" element={<FactorTearSheetIndexPage />} />\n',
)
app.write_text(text, encoding="utf-8")

# --- Governance ---------------------------------------------------------------------
status = ROOT / "docs/status.toml"
text = status.read_text(encoding="utf-8")
text = text.replace(
    'current_stage_status = "development_in_progress_experiments_graph_slice"',
    'current_stage_status = "development_in_progress_market_factor_intelligence_slice"',
)
text = text.replace(
    'workbench2_experiments_graph = "second_vertical_slice_in_development"\n',
    'workbench2_experiments_graph = "second_vertical_slice_in_development"\nworkbench2_market_factor_intelligence = "third_vertical_slice_in_development"\n',
)
status.write_text(text, encoding="utf-8")

stage = ROOT / "docs/development/stages/workbench-2.md"
text = stage.read_text(encoding="utf-8")
text = text.replace(
    "The second slice adds first-class Experiments and a canonical Research Graph",
    "The second slice adds first-class Experiments and a canonical Research Graph",
)
marker = "## Existing baseline to reuse\n"
insert = '''### Current third slice: Market State + Factor Intelligence\n\nThe third vertical slice extends the existing Factor Tear Sheet and adds a first-class Market State surface. It projects only persisted causal MarketState model/state rows, FactorLibrary lifecycle/evaluations, persisted adaptive allocator weight snapshots, Agent audit links and accepted research evidence. React does not fit GMMs, cluster, smooth, infer missing states, recompute factor/economic statistics or create research authority. Missing bindings remain explicitly unavailable/unresolved.\n\nTouched Factor server-state is migrated to `@tanstack/react-query`; untouched Workbench consumers may still use the legacy custom query client, so B-102 remains open. The accepted R4 terminal remains `NO_ADAPTIVE_CANDIDATE` with AgentValue `INCONCLUSIVE`, 0/20 complete deterministic strategies and 62 rejected Agent actions; these completeness/reliability facts do not imply all factors lose money, MarketState is invalid, or Agent value is proven negative. `r4-matched-v3` remains evidence-only and must not be rerun.\n\n'''
if marker not in text:
    raise RuntimeError("workbench stage marker missing")
text = text.replace(marker, insert + marker)
stage.write_text(text, encoding="utf-8")

backlog = ROOT / "docs/development/backlog.md"
text = backlog.read_text(encoding="utf-8")
text = text.replace(
    "The second slice adds first-class persisted Experiments/comparison and a canonical Research Graph with unresolved-lineage handling. These are implementation milestones only:",
    "The second slice adds first-class persisted Experiments/comparison and a canonical Research Graph with unresolved-lineage handling. The third slice adds persisted causal MarketState and FactorLibrary intelligence while retaining the existing Factor Tear Sheet. These are implementation milestones only:",
)
text = text.replace(
    "The Agent Workspace first slice migrated its touched Agent/Research reads, and the Experiments/Research Graph slice also uses `@tanstack/react-query` for list/detail/comparison/graph/cycle server-state plus SSE-driven graph invalidation. No new custom-query consumer is added. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.",
    "The Agent Workspace first slice migrated its touched Agent/Research reads, and the Experiments/Research Graph slice also uses `@tanstack/react-query` for list/detail/comparison/graph/cycle server-state plus SSE-driven graph invalidation. The Market State + Factor Intelligence slice uses TanStack Query for new Market/Factor intelligence reads and migrates the existing touched Factor Tear Sheet server-state calls from the custom query client. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.",
)
backlog.write_text(text, encoding="utf-8")

# --- Focused Python tests -----------------------------------------------------------
write(
    "tests/test_market_factor_intelligence_v3.py",
    r'''
from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.domain.research import TimeRange
from finagent.research.market_state import MarketFeatureConfig, MarketStateSource
from finagent.research.market_state_gmm import GMMConfig, MarketStateModel
from finagent.visualization.market_factor_intelligence import MarketFactorIntelligenceProjection
from finagent.visualization.research_workspace import ResearchWorkspaceProjection
from finagent.visualization.workspace_api import create_workspace_app


class _ResearchLinks:
    def experiments(self):
        return {"items": [{"identity": "exp-a", "experiment_id": "exp-a", "attempt_id": "call-a", "run_id": "run-a", "status": "completed", "factor_ids": ["factor-a"]}]}

    def graph(self):
        return {"nodes": [{"node_id": "agent_decision:decision-a", "kind": "agent_decision", "status": "recorded", "context": {"run_id": "run-a"}, "details": {"factor_id": "factor-a", "reason": "persisted decision"}}]}


def _model() -> MarketStateModel:
    source = MarketStateSource("source-a", "rev-a", "data-a", "admission-a", "calendar-a")
    return MarketStateModel(
        source,
        MarketFeatureConfig("IWM", 4),
        GMMConfig(n_components=2, min_train_rows=2),
        TimeRange(datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 3, tzinfo=UTC)),
        datetime(2026, 1, 3, tzinfo=UTC),
        "train-digest",
        4,
        "implementation-a",
        (("numpy", "1"),),
        (0.0, 0.0),
        (1.0, 1.0),
        (0.5, 0.5),
        ((-1.0, 0.5), (1.0, 1.5)),
        ((1.0, 1.0), (1.0, 1.0)),
        3,
    )


def _library(path: Path, model_id: str) -> None:
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE factors (factor_id TEXT PRIMARY KEY, definition TEXT NOT NULL);
        CREATE TABLE lifecycle (factor_id TEXT NOT NULL, sequence INTEGER NOT NULL, status TEXT NOT NULL, available_at TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, evaluation_id TEXT, PRIMARY KEY (factor_id, sequence));
        CREATE TABLE evaluations (evaluation_id TEXT PRIMARY KEY, factor_id TEXT NOT NULL, model_id TEXT NOT NULL, available_at TEXT NOT NULL, payload TEXT NOT NULL);
    """)
    for factor_id, status, origin in (("factor-a", "ACTIVE", "agent"), ("factor-b", "DORMANT", "programmatic"), ("factor-c", "REJECTED", "manual")):
        definition = {"version": "finagent.factor-registration.v1", "factor_id": factor_id, "graph": {}, "family": "flow", "mechanism": "causal mechanism", "hypothesis": f"hypothesis {factor_id}", "origin": origin, "provenance": {"source": "fixture"}, "created_at": "2026-01-01T00:00:00+00:00", "activation_scope": "research_only_no_alpha_paper_or_live_authority"}
        connection.execute("INSERT INTO factors VALUES (?, ?)", (factor_id, json.dumps(definition, sort_keys=True, separators=(",", ":"))))
        connection.execute("INSERT INTO lifecycle VALUES (?, 0, 'PROPOSED', '2026-01-01T00:00:00+00:00', ?, 'registered hypothesis', NULL)", (factor_id, origin))
        connection.execute("INSERT INTO lifecycle VALUES (?, 1, ?, '2026-01-05T00:00:00+00:00', 'deterministic_core', 'fixture lifecycle', ?)", (factor_id, status, "eval-" + factor_id if status != "REJECTED" else None))
        if status != "REJECTED":
            report = {"version": "finagent.factor-evaluation.v1", "evaluation_id": "eval-" + factor_id, "factor_id": factor_id, "model_id": model_id, "source_id": "source-a", "implementation_id": "impl-eval", "window": {"start": "2026-01-03T00:00:00+00:00", "end": "2026-01-05T00:00:00+00:00"}, "available_at": "2026-01-05T00:00:00+00:00", "compiled_batch_id": "batch-a", "global": {"coverage": 0.8, "turnover": 0.2, "decay_rank_ic": {"15": 0.03}, "rank_similarity": {"factor-c": 0.1}, "economic_scenarios": {"5.0": {"compounded_return": 0.01}}}, "by_market_state": {"state_0": {"coverage": 0.9, "turnover": 0.1, "decay_rank_ic": {"15": 0.04}}, "state_1": {"coverage": 0.7, "turnover": 0.3, "decay_rank_ic": {"15": -0.01}}}, "conditioning": "soft_probability_weighted_IC_coverage_decay_similarity", "alpha_authority": False, "paper_authority": False, "live_authority": False}
            connection.execute("INSERT INTO evaluations VALUES (?, ?, ?, ?, ?)", (report["evaluation_id"], factor_id, model_id, report["available_at"], json.dumps(report, sort_keys=True, separators=(",", ":"))))
    connection.commit()
    connection.close()


def _artifacts(root: Path) -> tuple[Path, str]:
    target = root / "adaptive"
    target.mkdir(parents=True)
    model = _model()
    (target / "market_state_model.json").write_text(json.dumps(model.to_dict()), encoding="utf-8")
    states = [
        {"model_id": model.model_id, "event_time": "2026-01-03T10:00:00+00:00", "available_at": "2026-01-03T10:15:00+00:00", "session_id": "s1", "probabilities": [0.8, 0.2], "state": 0, "unavailable_reason": None},
        {"model_id": model.model_id, "event_time": "2026-01-03T10:15:00+00:00", "available_at": "2026-01-03T10:30:00+00:00", "session_id": "s1", "probabilities": [0.2, 0.8], "state": 1, "unavailable_reason": None},
        {"model_id": model.model_id, "event_time": "2026-01-03T10:30:00+00:00", "available_at": "2026-01-03T10:45:00+00:00", "session_id": "s1", "probabilities": None, "state": None, "unavailable_reason": "OBSERVATION_NOT_AVAILABLE"},
    ]
    (target / "result.json").write_text(json.dumps({"run_id": "slice-a", "terminal": "DEVELOPMENT_SLICE_COMPLETE", "evaluation_data_status": "EVALUABLE", "model_id": model.model_id, "states": states, "interpretation": "development diagnostics", "alpha_authority": False, "paper_authority": False, "live_authority": False}), encoding="utf-8")
    _library(target / "factor_library.sqlite", model.model_id)
    portfolio = root / "portfolio"
    portfolio.mkdir()
    (portfolio / "result.json").write_text(json.dumps({"version": "finagent.deterministic-adaptive-result.v1", "run_id": "portfolio-a", "folds": [{"fold": {"name": "fold-a"}, "factor_ids": ["factor-a", "factor-b"], "state_model": {"model_id": model.model_id}, "arms": {"regime_conditional": {"factor_weight_series": [{"allocator_id": "allocator-a", "as_of": "2026-01-04T10:15:00+00:00", "session_id": "s2", "weights": {"factor-a": 0.7, "factor-b": 0.3}, "market_state_model_id": model.model_id, "state_probabilities": [0.75, 0.25], "fallback_reason": None, "history_id": "history-a"}]}}}], "overall": {}, "alpha_authority": False, "paper_authority": False, "live_authority": False}), encoding="utf-8")
    return root, model.model_id


def test_market_state_projection_is_persisted_causal_and_unavailable_explicit(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    projection = MarketFactorIntelligenceProjection((root,), research_workspace=_ResearchLinks())  # type: ignore[arg-type]
    market = projection.market(model_id)["item"]
    assert market["current_snapshot"]["unavailable_reason"] == "OBSERVATION_NOT_AVAILABLE"
    assert market["historical_states"][0]["probabilities"] == [0.8, 0.2]
    assert market["transitions"][0]["from_state"] == 0
    assert market["transitions"][0]["to_state"] == 1
    assert market["transitions"][0]["semantics"] == "adjacent_persisted_available_snapshots_no_smoothing"
    assert market["causal"]["browser_refit"] is False
    assert market["causal"]["future_fill"] is False
    assert market["feature_identity_status"] == "unavailable_not_persisted"
    assert market["factor_state_evidence"][0]["factor_id"] == "factor-a"
    assert market["linked_experiment_ids"] == ["exp-a"]


def test_factor_intelligence_lifecycle_state_metrics_provenance_and_weights(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    projection = MarketFactorIntelligenceProjection((root,), research_workspace=_ResearchLinks())  # type: ignore[arg-type]
    index = {item["factor_id"]: item for item in projection.factors()["items"]}
    assert index["factor-a"]["status"] == "ACTIVE"
    assert index["factor-b"]["status"] == "DORMANT"
    assert index["factor-c"]["status"] == "REJECTED"
    factor = projection.factor("factor-a")["item"]
    assert factor["origin"] == "agent"
    assert factor["provenance"] == {"source": "fixture"}
    assert factor["global_metrics"]["coverage"] == 0.8
    assert factor["state_metrics"]["state_0"]["coverage"] == 0.9
    assert factor["cost_sensitive_economics"]["5.0"]["compounded_return"] == 0.01
    assert factor["similarity"]["factor-c"] == 0.1
    assert factor["novelty"] is None
    assert factor["novelty_status"] == "unavailable_not_persisted"
    assert factor["allocator_weights"][0]["weight"] == 0.7
    assert factor["allocator_weights"][0]["market_state_model_id"] == model_id
    assert factor["linked_experiments"][0]["experiment_id"] == "exp-a"
    assert factor["agent_decision_history"][0]["run_id"] == "run-a"


def test_market_factor_routes_are_get_only_and_never_grant_browser_authority(tmp_path: Path) -> None:
    root, model_id = _artifacts(tmp_path)
    app = create_workspace_app(report_paths=(root,), frontend_dir=None)
    with TestClient(app) as client:
        market = client.get(f"/api/v3/market-state/{model_id}")
        assert market.status_code == 200
        assert market.json()["browser_recomputation"] is False
        assert market.json()["causal_projection"] is True
        factor = client.get("/api/v3/factor-intelligence/factor-a")
        assert factor.status_code == 200
        assert factor.json()["browser_recomputation"] is False
        assert factor.json()["hidden_reasoning"] == "not_persisted_not_projected"
        assert client.post("/api/v3/market-state", json={}).status_code == 405
        assert client.post("/api/v3/factor-intelligence", json={}).status_code == 405


def test_cycle_projection_fails_closed_without_explicit_accepted_disposition(tmp_path: Path) -> None:
    root = tmp_path / "cycles"
    target = root / "cycle"
    target.mkdir(parents=True)
    (target / "campaign_result_attestation.json").write_text(json.dumps({"schema_version": "finagent.r4-campaign-result-attestation.v1", "campaign_result_id": "cycle-unreviewed", "candidate_decision": "NO_ADAPTIVE_CANDIDATE", "agent_value": "INCONCLUSIVE", "economic_evidence": {}, "agent_reliability": {}, "development_only": True, "alpha_authority": False, "paper_authority": False, "live_authority": False, "r5_eligible": False}), encoding="utf-8")
    projection = ResearchWorkspaceProjection(None, cycle_paths=(root,))
    cycle = projection.cycles()["items"][0]
    assert cycle["accepted"] is False
    assert cycle["review_status"] == "not_accepted"
    assert projection.cycles()["unresolved"][0]["reason"] == "accepted_review_disposition_missing_or_unrecognized"
    graph = projection.graph()
    assert not any(node["node_id"] == "terminal:cycle-unreviewed" for node in graph["nodes"])
    assert any(item["reason"] == "cycle_not_explicitly_accepted" for item in graph["unresolved"])
''',
)

# --- Frontend Vitest ---------------------------------------------------------------
write(
    "workspace/src/workbench/marketFactor.test.tsx",
    r'''
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="echarts" /> }));

import App from "../App";

function response(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }));
}

const marketItem = {
  model_id: "market-model-a", model_artifact_id: "model-artifact-a", result_artifact_id: "result-artifact-a",
  model: { version: "finagent.market-state-gmm.v1", estimator: "sklearn.mixture.GaussianMixture", available_at: "2026-01-03T00:00:00+00:00", fit_window: { start: "2026-01-01", end: "2026-01-03" }, implementation_id: "impl-a" },
  historical_states: [
    { event_time: "2026-01-03T10:00:00+00:00", available_at: "2026-01-03T10:15:00+00:00", state: 0, probabilities: [0.8, 0.2], unavailable_reason: null },
    { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null },
    { event_time: "2026-01-03T10:30:00+00:00", available_at: "2026-01-03T10:45:00+00:00", state: null, probabilities: null, unavailable_reason: "OBSERVATION_NOT_AVAILABLE" },
  ], current_snapshot: { event_time: "2026-01-03T10:30:00+00:00", available_at: "2026-01-03T10:45:00+00:00", state: null, probabilities: null, unavailable_reason: "OBSERVATION_NOT_AVAILABLE" },
  transitions: [{ from_state: 0, to_state: 1, event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", semantics: "adjacent_persisted_available_snapshots_no_smoothing" }],
  unavailable_snapshot_count: 1, available_snapshot_count: 2, run_id: "slice-a", evaluation_data_status: "EVALUABLE", interpretation: "development diagnostics",
  feature_definitions: ["proxy_close[t]/proxy_close[t-lookback_returns]-1", "sqrt(mean(square(adjacent_proxy_simple_returns)))"], feature_identities: null, feature_identity_status: "unavailable_not_persisted",
  causal: { inference: "P(S_t|X_<=t); frozen_train_parameters; no_sequence_smoothing", browser_refit: false, future_fill: false, smoothing: false },
  factor_state_evidence: [{ factor_id: "factor-a", status: "ACTIVE", evaluations: [{ evaluation_id: "eval-a", by_market_state: { state_0: { coverage: 0.9 } }, conditioning: "soft_probability_weighted_IC_coverage_decay_similarity" }], allocator_weight_observations: [{ as_of: "2026-01-04T10:15:00+00:00", allocator: "regime_conditional", weight: 0.7 }] }], linked_experiment_ids: ["exp-a"], unavailable: { feature_identities: "not_persisted" },
};
const markets = { schema_version: "market", items: [marketItem], warnings: [], read_only: true, browser_recomputation: false, causal_projection: true, hidden_reasoning: "not_persisted_not_projected" };
const cycles = { schema_version: "cycles", items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", review_disposition: "R4_RESULT_ACCEPTED", terminal: "NO_ADAPTIVE_CANDIDATE", agent_value: "INCONCLUSIVE", economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0 }, agent_reliability: { rejected_action_attempts: 62 }, provider_usage: {}, resource_summary: {}, authority: {}, evidence: {} }], read_only: true, browser_recomputation: false };
const factorSummary = { factor_id: "factor-a", status: "ACTIVE", status_reason: "latest_persisted_lifecycle_event", family: "flow", mechanism: "causal mechanism", hypothesis: "state-aware hypothesis", origin: "agent", provenance: { source: "fixture" }, created_at: "2026-01-01", definition_conflict: false, library_ids: ["library-a"], lifecycle: [{ status: "PROPOSED" }, { status: "ACTIVE" }], evaluation_count: 1, latest_model_id: "market-model-a", evaluation_selection_reason: "latest_by_persisted_available_at" };
const factorDormant = { ...factorSummary, factor_id: "factor-b", status: "DORMANT", origin: "programmatic" };
const factorRejected = { ...factorSummary, factor_id: "factor-c", status: "REJECTED", origin: "manual", evaluation_count: 0, latest_model_id: null };
const factorDetail = { ...factorSummary, evaluations: [{ evaluation_id: "eval-a" }], latest_evaluation: { evaluation_id: "eval-a" }, global_metrics: { coverage: 0.8, turnover: 0.2, decay_rank_ic: { "15": 0.03 } }, state_metrics: { state_0: { coverage: 0.9, turnover: 0.1 } }, cost_sensitive_economics: { "5.0": { compounded_return: 0.01 } }, similarity: { "factor-c": 0.1 }, novelty: null, novelty_status: "unavailable_not_persisted", allocator_weights: [{ as_of: "2026-01-04T10:15:00+00:00", allocator: "regime_conditional", weight: 0.7, state_link_status: "persisted" }], allocator_weight_status: "persisted", linked_market_state_model_ids: ["market-model-a"], linked_experiments: [{ identity: "exp-a", experiment_id: "exp-a", run_id: "run-a" }], agent_decision_history: [{ node_id: "decision-a", run_id: "run-a", status: "recorded" }], evidence_identities: ["eval-a"], unavailable: { novelty: "not_persisted" } };

class EventSourceStub { close() {}; addEventListener() {}; removeEventListener() {}; onerror = null; onopen = null; constructor(_url: string) {} }

describe("Workbench-2 Market State + Factor Intelligence", () => {
  beforeEach(() => {
    vi.stubGlobal("EventSource", EventSourceStub);
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("127.0.0.1:8766/api/v3/control/")) return Promise.reject(new TypeError("control unavailable"));
      if (url === "/api/v3/market-state") return response(markets);
      if (url === "/api/v3/market-state/market-model-a") return response({ ...markets, item: marketItem });
      if (url === "/api/v3/research-cycles") return response(cycles);
      if (url === "/api/v3/factor-intelligence") return response({ schema_version: "factors", items: [factorSummary, factorDormant, factorRejected], warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url === "/api/v3/factor-intelligence/factor-a") return response({ schema_version: "factor", item: factorDetail, warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" });
      if (url === "/api/v4/factor-series") return response({ schema_version: "catalog", items: [], read_only: true });
      throw new Error(`unexpected URL: ${url}`);
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it("renders persisted MarketState probabilities/transitions/unavailable state without refit", async () => {
    window.history.pushState({}, "", "/market?market_model=market-model-a");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Market State" })).toBeInTheDocument();
    expect(screen.getByText("NO_ADAPTIVE_CANDIDATE")).toBeInTheDocument();
    expect(screen.getByText("AgentValue INCONCLUSIVE")).toBeInTheDocument();
    expect(screen.getByText("0/20 complete deterministic strategies")).toBeInTheDocument();
    expect(screen.getByText("62 rejected actions")).toBeInTheDocument();
    expect(screen.getByText("OBSERVATION_NOT_AVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("0 → 1")).toBeInTheDocument();
    expect(screen.getByText(/browser_refit=false/)).toBeInTheDocument();
    expect(screen.getByText(/feature identities: unavailable_not_persisted/)).toBeInTheDocument();
    expect(screen.getByTestId("workbench-context-bar")).toHaveTextContent("market-model-a");
  });

  it("extends the Factor Tear Sheet with lifecycle/state metrics/provenance/weights and canonical links", async () => {
    window.history.pushState({}, "", "/factors?factor=factor-a&market_model=market-model-a");
    render(<App />);
    expect(await screen.findByRole("region", { name: "Factor Intelligence" })).toBeInTheDocument();
    expect(screen.getByText("DORMANT")).toBeInTheDocument();
    expect(screen.getByText("REJECTED")).toBeInTheDocument();
    expect(await screen.findByTestId("factor-state-metrics")).toHaveTextContent('"coverage": 0.9');
    expect(screen.getByTestId("factor-global-metrics")).toHaveTextContent('"turnover": 0.2');
    expect(screen.getByTestId("factor-provenance")).toHaveTextContent('"source": "fixture"');
    expect(screen.getByTestId("factor-weights")).toHaveTextContent("weight=0.7");
    const marketLink = screen.getByRole("link", { name: /MarketState:market-model-a/ });
    await userEvent.click(marketLink);
    await waitFor(() => expect(window.location.pathname).toBe("/market"));
    expect(window.location.search).toContain("market_model=market-model-a");
    expect(window.location.search).toContain("factor=factor-a");
  });
});
''',
)

# --- Browser acceptance ------------------------------------------------------------
write(
    "workspace/e2e/market-factor-intelligence.spec.ts",
    r'''
import { expect, test } from "@playwright/test";

const cycles = { schema_version: "cycles", items: [{ cycle_id: "cycle-a", accepted: true, review_status: "accepted", review_disposition: "R4_RESULT_ACCEPTED", terminal: "NO_ADAPTIVE_CANDIDATE", agent_value: "INCONCLUSIVE", economic_evidence: { deterministic_strategy_count: 20, complete_deterministic_strategy_count: 0 }, agent_reliability: { rejected_action_attempts: 62 }, provider_usage: {}, resource_summary: {}, authority: {}, evidence: {} }], read_only: true, browser_recomputation: false };
const market = { model_id: "market-model-a", model_artifact_id: "model-a", result_artifact_id: "result-a", model: { version: "finagent.market-state-gmm.v1", estimator: "GaussianMixture", available_at: "2026-01-03T00:00:00+00:00", fit_window: { start: "2026-01-01", end: "2026-01-03" }, implementation_id: "impl-a" }, historical_states: [{ event_time: "2026-01-03T10:00:00+00:00", available_at: "2026-01-03T10:15:00+00:00", state: 0, probabilities: [0.8, 0.2], unavailable_reason: null }, { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null }], current_snapshot: { event_time: "2026-01-03T10:15:00+00:00", available_at: "2026-01-03T10:30:00+00:00", state: 1, probabilities: [0.2, 0.8], unavailable_reason: null }, transitions: [{ from_state: 0, to_state: 1, available_at: "2026-01-03T10:30:00+00:00", semantics: "adjacent_persisted_available_snapshots_no_smoothing" }], unavailable_snapshot_count: 0, available_snapshot_count: 2, feature_definitions: ["persisted feature"], feature_identities: null, feature_identity_status: "unavailable_not_persisted", causal: { browser_refit: false, smoothing: false, future_fill: false }, factor_state_evidence: [{ factor_id: "factor-a", status: "ACTIVE", evaluations: [{ evaluation_id: "eval-a", by_market_state: { state_1: { coverage: 0.9 } } }], allocator_weight_observations: [] }], linked_experiment_ids: ["exp-a"], unavailable: {} };
const markets = { schema_version: "market", items: [market], warnings: [], read_only: true, browser_recomputation: false, causal_projection: true, hidden_reasoning: "not_persisted_not_projected" };
const factorSummary = { factor_id: "factor-a", status: "ACTIVE", status_reason: "latest_persisted_lifecycle_event", family: "flow", mechanism: "causal", hypothesis: "hypothesis", origin: "agent", provenance: { source: "fixture" }, definition_conflict: false, library_ids: ["library-a"], lifecycle: [{ status: "ACTIVE" }], evaluation_count: 1, latest_model_id: "market-model-a", evaluation_selection_reason: "latest_by_persisted_available_at" };
const factor = { ...factorSummary, evaluations: [], latest_evaluation: {}, global_metrics: { coverage: 0.8 }, state_metrics: { state_1: { coverage: 0.9 } }, cost_sensitive_economics: null, similarity: null, novelty: null, novelty_status: "unavailable_not_persisted", allocator_weights: [], allocator_weight_status: "unavailable_not_persisted", linked_market_state_model_ids: ["market-model-a"], linked_experiments: [{ identity: "exp-a", experiment_id: "exp-a", run_id: "run-a" }], agent_decision_history: [{ node_id: "decision-a", run_id: "run-a", status: "recorded" }], evidence_identities: ["eval-a"], unavailable: { allocator_weights: "not_persisted" } };

 test("Market State and Factor Intelligence retain canonical deep links without browser authority", async ({ page }) => {
  await page.route("**/api/v3/market-state", (route) => route.fulfill({ json: markets }));
  await page.route("**/api/v3/market-state/market-model-a", (route) => route.fulfill({ json: { ...markets, item: market } }));
  await page.route("**/api/v3/research-cycles", (route) => route.fulfill({ json: cycles }));
  await page.route("**/api/v3/factor-intelligence", (route) => route.fulfill({ json: { schema_version: "factors", items: [factorSummary], warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v3/factor-intelligence/factor-a", (route) => route.fulfill({ json: { schema_version: "factor", item: factor, warnings: [], read_only: true, browser_recomputation: false, hidden_reasoning: "not_persisted_not_projected" } }));
  await page.route("**/api/v4/factor-series", (route) => route.fulfill({ json: { schema_version: "catalog", items: [], read_only: true } }));
  await page.goto("/market?market_model=market-model-a");
  await expect(page.getByRole("heading", { name: "Market State" })).toBeVisible();
  await expect(page.getByText("NO_ADAPTIVE_CANDIDATE")).toBeVisible();
  await page.getByRole("link", { name: /factor-a/ }).click();
  await expect(page).toHaveURL(/factor=factor-a/);
  await page.goto("/factors?factor=factor-a&market_model=market-model-a");
  await expect(page.getByRole("region", { name: "Factor Intelligence" })).toBeVisible();
  await expect(page.getByText(/Hidden chain-of-thought is not persisted or projected/)).toBeVisible();
  await page.getByRole("link", { name: /experiment:exp-a/ }).click();
  await expect(page).toHaveURL(/experiment=exp-a/);
});
''',
)
