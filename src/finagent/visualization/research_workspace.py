"""Read-only Workbench-2 Experiments and Research Graph projections.

The projection deliberately consumes only persisted Agent audit records and accepted
campaign attestations.  It never calls a provider, reruns an evaluator, recomputes
financial/statistical metrics, or invents missing research lineage.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from .semantic import EvidenceContractError


_EXPERIMENT_TOOLS = {"evaluate_factor", "evaluate_portfolio"}
_TERMINAL_OUTCOMES = {"DEVELOPMENT_CANDIDATE_PROPOSED", "NO_CANDIDATE_RECOMMENDED"}
_FAILED_OUTCOMES = {"TOOL_FAILED", "EVALUATOR_TIMEOUT", "AUDIT_FAILED"}


def _object(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _json_object(raw: object, *, label: str) -> Mapping[str, Any]:
    if raw is None:
        return {}
    try:
        value = json.loads(str(raw))
    except json.JSONDecodeError as exc:
        raise EvidenceContractError(f"{label} contains invalid JSON") from exc
    if not isinstance(value, Mapping):
        raise EvidenceContractError(f"{label} must decode to an object")
    return value


def _read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _unique(values: Iterable[object]) -> list[str]:
    output: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def _deep_ids(value: object) -> list[str]:
    keys = {
        "evidence_id",
        "artifact_id",
        "report_id",
        "acceptance_id",
        "program_result_id",
        "factor_id",
        "factor_set_id",
        "allocator_proposal_id",
        "experiment_id",
        "proposal_id",
        "record_id",
        "campaign_result_id",
    }
    output: list[str] = []

    def walk(item: object, key: str = "") -> None:
        if isinstance(item, Mapping):
            for child_key, child in item.items():
                walk(child, str(child_key))
        elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
            for child in item:
                walk(child, key)
        elif key in keys:
            text = str(item or "").strip()
            if text and text not in output:
                output.append(text)

    walk(value)
    return output


def _status(record_status: str, result: Mapping[str, Any]) -> str:
    outcome = str(result.get("outcome", ""))
    if outcome == "DUPLICATE_EXPERIMENT":
        return "duplicate"
    if result.get("repaired_attempt_id"):
        return "repaired"
    if record_status == "denied" or outcome in {"REJECTED", "DENIED"}:
        return "rejected"
    if record_status == "failed" or outcome in _FAILED_OUTCOMES:
        return "failed"
    if outcome.endswith("EVALUATED") and result.get("experiment_id"):
        return "completed"
    return "incomplete"


def _authoritative_metrics(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    summary = _object(result.get("summary"))
    allocator = str(result.get("preferred_allocator", ""))
    arms = _object(summary.get("arms"))
    selected = arms.get(allocator)
    if allocator and isinstance(selected, Mapping):
        return dict(selected)
    metrics = result.get("metrics")
    if isinstance(metrics, Mapping):
        return dict(metrics)
    feedback = result.get("feedback")
    if isinstance(feedback, Mapping):
        return dict(feedback)
    return None


class ResearchWorkspaceProjection:
    """Typed read model over canonical research audit and accepted cycle evidence."""

    def __init__(
        self,
        agent_audit_path: str | Path | None,
        *,
        cycle_paths: Sequence[str | Path] = ("configs/research",),
    ) -> None:
        self.agent_audit_path = (
            Path(agent_audit_path).expanduser() if agent_audit_path is not None else None
        )
        self.cycle_paths = tuple(Path(value).expanduser() for value in cycle_paths)

    @property
    def agent_configured(self) -> bool:
        return self.agent_audit_path is not None

    def _tool_records(self) -> list[dict[str, Any]]:
        if self.agent_audit_path is None:
            return []
        with _read_only(self.agent_audit_path) as connection:
            rows = connection.execute(
                "SELECT r.rowid,r.run_id,r.payload_json,r.decision_json,t.sequence,t.call_id,"
                "t.request_json,t.result_json FROM agent_runs r "
                "JOIN agent_tool_calls t ON t.run_id=r.run_id ORDER BY r.rowid,t.sequence"
            ).fetchall()
        output: list[dict[str, Any]] = []
        for run_ordinal, run_id, payload_raw, decision_raw, sequence, call_id, request_raw, result_raw in rows:
            payload = _json_object(payload_raw, label="agent run payload")
            context = _object(payload.get("context"))
            metadata = _object(context.get("metadata"))
            if metadata.get("controller") != "r4":
                continue
            task = _object(payload.get("task"))
            request = _json_object(request_raw, label="agent tool request")
            stored_result = _json_object(result_raw, label="agent tool result") if result_raw else {}
            stored_output = _object(stored_result.get("output"))
            research_result = _object(stored_output.get("research_result"))
            research_state = _object(stored_output.get("research_state"))
            output.append(
                {
                    "run_id": str(run_id),
                    "run_ordinal": int(run_ordinal),
                    "run_started_at": str(context.get("started_at", "")),
                    "sequence": int(sequence),
                    "call_id": str(call_id),
                    "objective": str(task.get("objective", "")),
                    "project_id": str(metadata.get("project_id", "")),
                    "thread_id": str(metadata.get("thread_id", "")),
                    "provider_id": str(metadata.get("provider_id", "unavailable")),
                    "model_id": str(metadata.get("model_id", "unavailable")),
                    "tool": str(request.get("tool_name", "")),
                    "arguments": dict(_object(request.get("arguments"))),
                    "status": str(stored_result.get("status", "pending")),
                    "error": str(stored_result.get("error", "") or ""),
                    "result": dict(research_result),
                    "state": dict(research_state),
                    "decision": dict(
                        _json_object(decision_raw, label="agent decision")
                        if decision_raw
                        else {}
                    ),
                }
            )
        return output

    def _decision_for(
        self, records: Sequence[Mapping[str, Any]], experiment_id: str
    ) -> Mapping[str, Any] | None:
        for record in reversed(records):
            result = _object(record.get("result"))
            outcome = str(result.get("outcome", ""))
            ids = result.get("experiment_ids")
            if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)):
                continue
            if experiment_id not in {str(value) for value in ids}:
                continue
            if outcome in _TERMINAL_OUTCOMES:
                return {
                    "action_id": record["call_id"],
                    "kind": "finalize_candidate",
                    "recommendation": "candidate"
                    if outcome == "DEVELOPMENT_CANDIDATE_PROPOSED"
                    else "reject",
                    "decision": result.get("decision"),
                    "terminal": outcome,
                }
            if outcome == "LIFECYCLE_DECIDED":
                return {
                    "action_id": record["call_id"],
                    "kind": "lifecycle_decision",
                    "recommendation": str(result.get("status", "modify")).lower(),
                    "decision": result.get("reason"),
                    "terminal": None,
                }
        return None

    def experiments(self, *, run_id: str | None = None) -> dict[str, object]:
        records = self._tool_records()
        by_run: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_run.setdefault(record["run_id"], []).append(record)
        items: list[dict[str, Any]] = []
        for record in records:
            if run_id and record["run_id"] != run_id:
                continue
            if record["tool"] not in _EXPERIMENT_TOOLS:
                continue
            result = _object(record["result"])
            args = _object(record["arguments"])
            experiment_id = str(result.get("experiment_id", "") or "")
            attempt_id = str(record["call_id"])
            factor_ids_raw = result.get("factor_ids", ())
            factor_ids = (
                _unique(factor_ids_raw)
                if isinstance(factor_ids_raw, Sequence)
                and not isinstance(factor_ids_raw, (str, bytes))
                else []
            )
            resources = _object(_object(record["state"]).get("resources"))
            evidence_ids = _unique(
                _deep_ids(result)
                + _deep_ids(args)
                + [value for value in factor_ids if value]
            )
            item = {
                "attempt_id": attempt_id,
                "experiment_id": experiment_id or None,
                "identity": experiment_id or attempt_id,
                "identity_kind": "experiment_id" if experiment_id else "attempt_call_id",
                "attempt_order": {
                    "run_ordinal": record["run_ordinal"],
                    "tool_sequence": record["sequence"],
                    "run_started_at": record["run_started_at"],
                },
                "canonical_experiment_identity_available": bool(experiment_id),
                "run_id": record["run_id"],
                "project_id": record["project_id"],
                "thread_id": record["thread_id"],
                "objective": record["objective"],
                "hypothesis_id": args.get("hypothesis_id"),
                "factor_set_id": result.get("factor_set_id") or args.get("factor_set_id"),
                "factor_ids": factor_ids,
                "allocator_proposal_id": result.get("allocator_proposal_id")
                or args.get("allocator_proposal_id"),
                "allocator": result.get("preferred_allocator"),
                "status": _status(str(record["status"]), result),
                "outcome": result.get("outcome"),
                "evaluation_scope": {
                    key: result[key]
                    for key in (
                        "evaluation_mode",
                        "compatibility_id",
                        "evidence_mode",
                        "evidence_semantics",
                        "research_scope_id",
                    )
                    if key in result
                },
                "authoritative_metrics": _authoritative_metrics(result),
                "metrics_source": "persisted_research_result",
                "provider_id": record["provider_id"],
                "model_id": record["model_id"],
                "resource_snapshot": dict(resources),
                "evaluation_budget": {
                    "used": resources.get("evaluations"),
                    "remaining": resources.get("remaining_evaluations"),
                },
                "tokens": resources.get("tokens"),
                "cost_microusd": resources.get("cost_microusd"),
                "agent_decision": self._decision_for(
                    by_run.get(record["run_id"], ()), experiment_id
                )
                if experiment_id
                else None,
                "related_identities": evidence_ids,
                "error": record["error"] or result.get("code") or None,
                "read_only": True,
                "browser_recomputation": False,
                "hidden_reasoning": "not_persisted_not_projected",
            }
            items.append(item)
        return {
            "schema_version": "finagent.workspace.research-experiments.v1",
            "configured": self.agent_configured,
            "items": items,
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def experiment(self, identity: str) -> dict[str, object]:
        payload = self.experiments()
        experiment_items = cast(list[dict[str, Any]], payload["items"])
        matches = [
            item
            for item in experiment_items
            if item["identity"] == identity
            or item["experiment_id"] == identity
            or item["attempt_id"] == identity
        ]
        if not matches:
            raise KeyError(identity)
        matches.sort(
            key=lambda item: (
                int(_object(item.get("attempt_order")).get("run_ordinal", -1)),
                int(_object(item.get("attempt_order")).get("tool_sequence", -1)),
            )
        )
        return {
            "schema_version": "finagent.workspace.research-experiment-detail.v1",
            "item": matches[-1],
            "attempts": matches,
            "attempt_count": len(matches),
            "selection_semantics": "persisted_agent_audit_run_ordinal_then_tool_sequence",
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def comparison(self, experiment_ids: Sequence[str]) -> dict[str, object]:
        selected = _unique(experiment_ids)
        if len(selected) < 2:
            raise ValueError("at least two distinct experiment ids are required")
        records = self._tool_records()
        persisted: Mapping[str, Any] | None = None
        comparison_call_id: str | None = None
        for record in records:
            if record["tool"] != "compare_experiments":
                continue
            args = _object(record["arguments"])
            ids = args.get("experiment_ids")
            if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)):
                continue
            if sorted(_unique(ids)) == sorted(selected):
                persisted = _object(record["result"])
                comparison_call_id = str(record["call_id"])
        outcome = str((persisted or {}).get("outcome", ""))
        compatible = bool(
            persisted
            and outcome == "EXPERIMENTS_COMPARED"
            and persisted.get("compatible_source_folds_cost_execution") is True
        )
        reason = None
        if not persisted:
            reason = "persisted_comparison_unavailable"
        elif not compatible:
            reason = "incompatible_source_folds_cost_execution"
        items = []
        for experiment_id in selected:
            try:
                items.append(self.experiment(experiment_id)["item"])
            except KeyError:
                items.append(
                    {
                        "identity": experiment_id,
                        "experiment_id": experiment_id,
                        "status": "incomplete",
                        "error": "experiment_identity_unresolved",
                    }
                )
        return {
            "schema_version": "finagent.workspace.research-experiment-comparison.v1",
            "experiment_ids": selected,
            "comparison_call_id": comparison_call_id,
            "comparable": compatible,
            "reason": reason,
            "persisted_comparison": dict(persisted) if persisted else None,
            "items": items,
            "ranking": None,
            "read_only": True,
            "browser_recomputation": False,
        }

    def cycles(self) -> dict[str, object]:
        items: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root in self.cycle_paths:
            candidates = (
                (root,) if root.is_file() else tuple(root.rglob("campaign_result_attestation.json"))
                if root.is_dir()
                else ()
            )
            for path in candidates:
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(value, Mapping) or not str(value.get("schema_version", "")).startswith(
                    "finagent.r4-campaign-result-attestation."
                ):
                    continue
                cycle_id = str(value.get("campaign_result_id", "")).strip()
                if not cycle_id or cycle_id in seen:
                    continue
                seen.add(cycle_id)
                resource_path = path.with_name("resource_summary.json")
                resources: Mapping[str, Any] = {}
                if resource_path.is_file():
                    try:
                        loaded = json.loads(resource_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        loaded = {}
                    resources = loaded if isinstance(loaded, Mapping) else {}
                accepted = value.get("review_disposition") == "R4_RESULT_ACCEPTED"
                if not accepted:
                    unresolved.append(
                        {
                            "cycle_id": cycle_id,
                            "relation": "review_disposition",
                            "reason": "accepted_review_disposition_missing_or_unrecognized",
                        }
                    )
                items.append(
                    {
                        "cycle_id": cycle_id,
                        "accepted": accepted,
                        "review_status": "accepted" if accepted else "not_accepted",
                        "protocol_id": value.get("protocol_id"),
                        "protocol_version": value.get("protocol_version"),
                        "review_disposition": value.get("review_disposition"),
                        "terminal": value.get("candidate_decision"),
                        "agent_value": value.get("agent_value"),
                        "candidate_id": value.get("candidate_id"),
                        "economic_evidence": dict(_object(value.get("economic_evidence"))),
                        "provider_usage": dict(_object(value.get("provider_usage"))),
                        "agent_reliability": dict(_object(value.get("agent_reliability"))),
                        "resource_summary": dict(resources),
                        "authority": {
                            "development_only": bool(value.get("development_only", True)),
                            "alpha_authority": bool(value.get("alpha_authority", False)),
                            "paper_authority": bool(value.get("paper_authority", False)),
                            "live_authority": bool(value.get("live_authority", False)),
                            "r5_eligible": bool(value.get("r5_eligible", False)),
                        },
                        "evidence": {
                            "attestation_path": path.as_posix(),
                            "resource_summary_path": resource_path.as_posix()
                            if resource_path.is_file()
                            else None,
                            "campaign_freeze_id": value.get("campaign_freeze_id"),
                            "provider_admission_id": value.get("provider_admission_id"),
                            "research_admission_id": value.get("research_admission_id"),
                        },
                    }
                )
        items.sort(key=lambda item: item["cycle_id"])
        return {
            "schema_version": "finagent.workspace.research-cycles.v1",
            "items": items,
            "unresolved": unresolved,
            "read_only": True,
            "browser_recomputation": False,
        }

    def graph(self, *, run_id: str | None = None) -> dict[str, object]:
        records = self._tool_records()
        if run_id:
            records = [record for record in records if record["run_id"] == run_id]
        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}
        unresolved: list[dict[str, Any]] = []

        def node(kind: str, identity: str, *, label: str | None = None, status: str = "persisted", href: str | None = None, context: Mapping[str, Any] | None = None, details: Mapping[str, Any] | None = None) -> str:
            identity = str(identity or "").strip()
            if not identity:
                raise ValueError("graph node identity is required")
            key = f"{kind}:{identity}"
            nodes.setdefault(
                key,
                {
                    "node_id": key,
                    "kind": kind,
                    "identity": identity,
                    "label": label or identity,
                    "status": status,
                    "href": href,
                    "context": dict(context or {}),
                    "details": dict(details or {}),
                },
            )
            return key

        def edge(source: str, target: str, relation: str) -> None:
            key = f"{source}->{relation}->{target}"
            edges.setdefault(
                key,
                {"edge_id": key, "source": source, "target": target, "relation": relation},
            )

        by_run: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            by_run.setdefault(record["run_id"], []).append(record)

        for record in records:
            tool = record["tool"]
            args = _object(record["arguments"])
            result = _object(record["result"])
            run_context = {
                "project_id": record["project_id"],
                "thread_id": record["thread_id"],
                "run_id": record["run_id"],
            }
            if tool == "inspect_market_state" and result.get("outcome") == "MARKET_STATE_INSPECTED":
                market_state = _object(result.get("market_state"))
                model_id = str(market_state.get("model_id", ""))
                if model_id:
                    node(
                        "market_state",
                        model_id,
                        label=f"MarketState · {model_id}",
                        href=f"/market?market_model={quote(model_id, safe='')}",
                        context={**run_context, "market_state_model_id": model_id},
                        details=market_state,
                    )
                else:
                    unresolved.append(
                        {
                            "run_id": record["run_id"],
                            "call_id": record["call_id"],
                            "relation": "market_state_model_identity",
                            "reason": "persisted_market_state_model_id_unavailable",
                        }
                    )
            elif tool == "read_literature" and result.get("outcome") == "LITERATURE_READ":
                literature = _object(result.get("record"))
                record_id = str(literature.get("record_id", "") or args.get("record_id", ""))
                if record_id:
                    node("literature", record_id, label=str(literature.get("title", record_id)), context=run_context, details=literature)
            elif tool in {"propose_factor", "validate_factor"}:
                factor_id = str(result.get("candidate_id", ""))
                proposal = _object(result.get("proposal"))
                if factor_id:
                    factor_node = node(
                        "factor",
                        factor_id,
                        status=str(result.get("outcome", "persisted")).lower(),
                        href=f"/factors?factor={quote(factor_id, safe='')}",
                        context={**run_context, "factor_id": factor_id},
                        details={"proposal_id": proposal.get("proposal_id")},
                    )
                    visible = proposal.get("visible_experiment_ids")
                    if isinstance(visible, Sequence) and not isinstance(visible, (str, bytes)):
                        for experiment_id in _unique(visible):
                            experiment_node = node(
                                "experiment",
                                experiment_id,
                                href=f"/experiments?experiment={quote(experiment_id, safe='')}",
                                context={**run_context, "experiment_id": experiment_id},
                            )
                            edge(experiment_node, factor_node, "visible_prior_experiment")
            elif tool == "propose_factor_set" and result.get("outcome") == "FACTOR_SET_PROPOSED":
                factor_set = _object(result.get("factor_set"))
                factor_set_id = str(factor_set.get("factor_set_id", ""))
                hypothesis_id = str(factor_set.get("hypothesis_id", ""))
                if factor_set_id:
                    set_node = node("factor_set", factor_set_id, context=run_context, details=factor_set)
                    if hypothesis_id:
                        hypothesis_node = node("hypothesis", hypothesis_id, context=run_context)
                        edge(hypothesis_node, set_node, "proposes_factor_set")
                    for factor_id in _unique(factor_set.get("factor_ids", ())):
                        factor_node = node(
                            "factor",
                            factor_id,
                            href=f"/factors?factor={quote(factor_id, safe='')}",
                            context={**run_context, "factor_id": factor_id},
                        )
                        edge(factor_node, set_node, "member_of")
            elif tool == "propose_allocator" and result.get("outcome") == "ALLOCATOR_PROPOSED":
                allocator = _object(result.get("allocator_proposal"))
                allocator_id = str(allocator.get("allocator_proposal_id", ""))
                if allocator_id:
                    node("allocator", allocator_id, label=str(allocator.get("allocator", allocator_id)), context=run_context, details=allocator)
            elif tool in _EXPERIMENT_TOOLS:
                experiment_id = str(result.get("experiment_id", ""))
                if not experiment_id:
                    unresolved.append(
                        {
                            "run_id": record["run_id"],
                            "call_id": record["call_id"],
                            "relation": "experiment_identity",
                            "reason": "persisted_experiment_id_unavailable",
                        }
                    )
                    continue
                experiment_node = node(
                    "experiment",
                    experiment_id,
                    status=_status(str(record["status"]), result),
                    href=f"/experiments?experiment={quote(experiment_id, safe='')}",
                    context={**run_context, "experiment_id": experiment_id},
                    details={"outcome": result.get("outcome")},
                )
                evaluation_node = node(
                    "evaluation",
                    experiment_id,
                    label=f"Evaluation · {experiment_id}",
                    status=_status(str(record["status"]), result),
                    href=f"/experiments?experiment={quote(experiment_id, safe='')}",
                    context={**run_context, "experiment_id": experiment_id},
                    details={"metrics_source": "persisted_research_result"},
                )
                edge(experiment_node, evaluation_node, "evaluated_as")
                factor_set_id = str(result.get("factor_set_id", "") or args.get("factor_set_id", ""))
                if factor_set_id:
                    edge(node("factor_set", factor_set_id, context=run_context), experiment_node, "evaluated_by")
                allocator_id = str(result.get("allocator_proposal_id", "") or args.get("allocator_proposal_id", ""))
                if allocator_id:
                    edge(node("allocator", allocator_id, context=run_context), evaluation_node, "allocator_evaluated")
            elif tool in {"retire_hypothesis", "finalize_candidate"}:
                decision_node = node(
                    "agent_decision",
                    record["call_id"],
                    label=str(result.get("decision") or result.get("reason") or tool),
                    status=str(result.get("outcome", record["status"])).lower(),
                    href=f"/agent?run={quote(record['run_id'], safe='')}",
                    context=run_context,
                    details=result,
                )
                experiment_ids = result.get("experiment_ids", args.get("experiment_ids", ()))
                if isinstance(experiment_ids, Sequence) and not isinstance(experiment_ids, (str, bytes)):
                    for experiment_id in _unique(experiment_ids):
                        evaluation_node = node(
                            "evaluation",
                            experiment_id,
                            href=f"/experiments?experiment={quote(experiment_id, safe='')}",
                            context={**run_context, "experiment_id": experiment_id},
                        )
                        edge(evaluation_node, decision_node, "supports_decision")
                if result.get("outcome") in _TERMINAL_OUTCOMES:
                    terminal_node = node(
                        "terminal",
                        record["call_id"],
                        label=str(result.get("outcome")),
                        status="terminal",
                        href=f"/agent?run={quote(record['run_id'], safe='')}",
                        context=run_context,
                        details={"candidate": result.get("factor_set") is not None},
                    )
                    edge(decision_node, terminal_node, "finalizes")
                    allocator = _object(result.get("allocator"))
                    allocator_id = str(allocator.get("allocator_proposal_id", ""))
                    if allocator_id:
                        edge(decision_node, node("allocator", allocator_id, context=run_context, details=allocator), "selects_allocator")

        cycle_items = cast(list[dict[str, Any]], self.cycles()["items"])
        for cycle in cycle_items:
            cycle_id = str(cycle["cycle_id"])
            if cycle.get("accepted") is not True:
                unresolved.append(
                    {
                        "cycle_id": cycle_id,
                        "relation": "accepted_cycle_lineage",
                        "reason": "cycle_not_explicitly_accepted",
                    }
                )
                continue
            cycle_node = node(
                "research_cycle",
                cycle_id,
                label=str(cycle.get("protocol_version") or cycle_id),
                status="accepted",
                details={"protocol_id": cycle.get("protocol_id")},
            )
            economic = _object(cycle.get("economic_evidence"))
            evaluation_node = node(
                "evaluation",
                cycle_id,
                label="Economic evidence completeness",
                status="incomplete" if economic.get("deterministic_evidence_complete") is False else "complete",
                details=economic,
            )
            terminal = str(cycle.get("terminal", ""))
            if terminal:
                terminal_node = node(
                    "terminal",
                    cycle_id,
                    label=terminal,
                    status="accepted_terminal",
                    details={
                        "agent_value": cycle.get("agent_value"),
                        "candidate_id": cycle.get("candidate_id"),
                        "agent_reliability": cycle.get("agent_reliability"),
                    },
                )
                edge(cycle_node, evaluation_node, "attests_economic_evidence")
                edge(evaluation_node, terminal_node, "supports_terminal")
            unresolved.append(
                {
                    "cycle_id": cycle_id,
                    "relation": "campaign_run_experiment_lineage",
                    "reason": "accepted_attestation_does_not_embed_run_local_experiment_identities",
                }
            )

        return {
            "schema_version": "finagent.workspace.research-graph.v1",
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "unresolved": unresolved,
            "read_only": True,
            "canonical_identity_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }

    def status(self) -> dict[str, object]:
        cycles = self.cycles()
        cycle_items = cast(list[dict[str, Any]], cycles["items"])
        return {
            "schema_version": "finagent.workspace.research-workspace-status.v1",
            "agent_audit_configured": self.agent_configured,
            "accepted_cycle_count": sum(item.get("accepted") is True for item in cycle_items),
            "read_only": True,
            "browser_recomputation": False,
            "hidden_reasoning": "not_persisted_not_projected",
        }
