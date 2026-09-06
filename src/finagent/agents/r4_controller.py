"""R4 capability selection/dispatch; the R3 runtime owns every provider/budget step."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from finagent.agents.r3_contracts import ContractError, identity, proposal_action
from finagent.agents.r3_ledger import ResearchLedger, Reservation
from finagent.agents.r3_runtime import PreparedResearchAction
from finagent.agents.r4_contracts import AUTHORITY, decode_r4_action, r3_proposal, r4_manifest
from finagent.agents.research_audit import resource_snapshot
from finagent.research.adaptive_factor_admission import (
    FactorEvidenceMode,
    evidence_semantics,
    factor_definition_digest,
    proposal_id,
)
from finagent.research.factor_library import _TRANSITIONS, FactorStatus
from finagent.research.market_state import utc_text
from finagent.research.r4_feedback import compare_feedback

if TYPE_CHECKING:
    from finagent.application.research_controller_host import R4ResearchHost


def completed_results(ledger: ResearchLedger) -> list[dict[str, Any]]:
    return [r["result"] for r in ledger.journal() if r["result"] is not None]


def proposal_context(ledger: ResearchLedger, reservation: Reservation) -> dict[str, Any]:
    row = next(r for r in ledger.journal() if r["request_id"] == reservation.request_id)
    context = json.loads(row["context_json"])
    visible: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for k, v in value.items():
                if k == "experiment_id" and isinstance(v, str):
                    visible.add(v)
                else:
                    walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(context)
    visible_history_id = identity(
        {"agent_run_id": ledger.run_id, "visible_context": context}, "r4-proposal-context"
    )
    return {
        "proposal_context_id": visible_history_id,
        "visible_history_id": visible_history_id,
        "visible_experiment_ids": sorted(visible),
        "history_cutoff": context["state"]["history_cutoff"],
    }


class R4ResearchCapabilities:
    def __init__(self, host: R4ResearchHost, objective: str) -> None:
        self.host, self.objective = host, objective

    @property
    def binding(self) -> dict[str, object]:
        from finagent.application.research_controller import controller_implementation

        return {
            "capability_set": "r4-development-v1",
            "host_id": identity(self.host.manifest, "r4-host"),
            "objective": self.objective,
            "implementation": controller_implementation(),
            **AUTHORITY,
        }

    def manifest(self) -> dict[str, object]:
        return r4_manifest()

    def decode(self, raw: str) -> dict[str, Any]:
        return decode_r4_action(raw)

    def context(self, ledger: ResearchLedger) -> dict[str, Any]:
        rows = [r for r in ledger.journal() if r["result"] is not None]
        state: dict[str, Any] = {
            "objective": self.objective,
            "factor_set": None,
            "allocator": None,
            "market_state": None,
            "latest_experiment": None,
            "explicit_decision": None,
            "candidate": None,
            "history_cutoff": rows[-1]["request_id"] if rows else None,
            "resources": resource_snapshot(ledger),
            **AUTHORITY,
        }
        for row in rows:
            result = row["result"]
            if result["outcome"] == "FACTOR_SET_PROPOSED":
                state["factor_set"] = result["factor_set"]
            elif result["outcome"] == "ALLOCATOR_PROPOSED":
                state["allocator"] = result["allocator_proposal"]
            elif result["outcome"] == "MARKET_STATE_INSPECTED":
                state["market_state"] = result["market_state"]
            elif result["outcome"] == "PORTFOLIO_EVALUATED":
                preferred = result["preferred_allocator"]
                state["latest_experiment"] = {
                    "experiment_id": result["experiment_id"],
                    "preferred_allocator": preferred,
                    "metrics": {
                        k: v
                        for k, v in result["summary"]["arms"][preferred].items()
                        if k != "cost_sensitivity"
                    },
                    "evaluation_mode": result["evaluation_mode"],
                }
            elif result["outcome"] == "EXPLICIT_DECISION_RECORDED":
                state["explicit_decision"] = result["explicit_decision"]
            elif result["outcome"] in {
                "DEVELOPMENT_CANDIDATE_PROPOSED",
                "NO_CANDIDATE_RECOMMENDED",
            }:
                state["candidate"] = result
        return state

    def prepare(
        self, action: dict[str, Any], ledger: ResearchLedger, reservation: Reservation, now: float
    ) -> PreparedResearchAction:
        tool, args = action["tool"], action["arguments"]
        at = datetime.fromtimestamp(now, UTC)
        history, results = ledger.journal(), completed_results(ledger)

        def read(result: dict[str, Any], **options: Any) -> PreparedResearchAction:
            return PreparedResearchAction(lambda: {**result, **AUTHORITY}, **options)

        def reference(kind: str, key: str, value: str) -> dict[str, Any]:
            for result in results:
                obj = result.get(kind)
                if isinstance(obj, dict) and obj.get(key) == value:
                    return obj
            raise ContractError("unknown_run_local_proposal")

        def experiments(ids: list[str]) -> list[dict[str, Any]]:
            selected = []
            for item in ids:
                match = next(
                    (
                        r
                        for r in results
                        if r["outcome"] == "PORTFOLIO_EVALUATED" and r["experiment_id"] == item
                    ),
                    None,
                )
                if match is None:
                    raise ContractError("experiment_not_completed_in_run")
                selected.append(match)
            return selected

        def eligible(ids: list[str]) -> None:
            for factor in ids:
                if self.host.factor(factor)["status"] in {"REJECTED", "RETIRED"}:
                    raise ContractError("terminal_factor_selection_denied")

        if tool == "inspect_market_state":
            return read(
                {"outcome": "MARKET_STATE_INSPECTED", "market_state": self.host.market_summary()}
            )
        if tool == "inspect_factor_library":
            ids = [r["factor_id"] for r in self.host.factors()]
            offset = args["offset"]
            return read(
                {
                    "outcome": "FACTOR_LIBRARY_INSPECTED",
                    "library_id": identity(self.host.factors(), "factor-library-snapshot"),
                    "factors": [self.host.factor_summary(f) for f in ids[offset : offset + 5]],
                    "total": len(ids),
                    "next_offset": offset + 5 if offset + 5 < len(ids) else None,
                }
            )
        if tool == "inspect_factor":
            return read(
                {
                    "outcome": "FACTOR_INSPECTED",
                    "factor": self.host.factor_summary(args["factor_id"], full=True),
                }
            )
        if tool == "inspect_experiment_history":
            committed = [r for r in history if r["result"] is not None]
            offset = args["offset"]
            return read(
                {
                    "outcome": "HISTORY_INSPECTED",
                    "attempt_counts": dict(Counter(r["state"] for r in committed)),
                    "attempts": [
                        {
                            "request_id": r["request_id"],
                            "tool": (r["action"] or {}).get("tool", "runtime_admission"),
                            "outcome": r["state"],
                            "code": r["result"].get("code"),
                            "experiment_id": r["evaluation_key"],
                            "repaired_attempt_id": r["result"].get("repaired_attempt_id"),
                            "tokens": r["charged_tokens"],
                            "cost_microusd": r["charged_cost"],
                            "evaluation_reserved": r["evaluation_reserved"],
                        }
                        for r in committed[offset : offset + 20]
                    ],
                    "total": len(committed),
                    "next_offset": offset + 20 if offset + 20 < len(committed) else None,
                }
            )
        if tool == "read_literature":
            record = next(
                (
                    r
                    for r in self.host.admission.scope.records
                    if r.record_id == args["record_id"] and r.kind == "literature"
                ),
                None,
            )
            if record is None:
                raise ContractError("record_access_denied")
            return read({"outcome": "LITERATURE_READ", "record": record.to_dict()})
        if tool in {"propose_factor", "validate_factor"}:
            proposal = r3_proposal(action).proposal
            assert proposal is not None
            hypothesis = proposal.hypothesis()
            factor_id = hypothesis.candidate_id
            if factor_id in {f["factor_id"] for f in self.host.factors()}:
                return read({"outcome": "DUPLICATE_PROPOSAL", "candidate_id": factor_id})
            repaired = args.get("repairs_request_id")
            if repaired is not None and not any(
                r["request_id"] == repaired and r["state"] == "REJECTED" for r in history
            ):
                raise ContractError("invalid_repair_reference")
            envelope = {
                "factor_id": factor_id,
                "proposed_at": utc_text(at),
                "agent_run_id": ledger.run_id,
                "actor": "agent_controller",
                "research_scope_id": self.host.admission.scope.scope_id,
                **proposal_context(ledger, reservation),
            }
            envelope["factor_definition_digest"] = factor_definition_digest(
                self.host.proposal_definition(proposal, envelope)
            )
            envelope["proposal_id"] = proposal_id(envelope)

            def propose() -> dict[str, object]:
                self.host.register_proposal(proposal, envelope)
                return {
                    "outcome": "VALIDATED",
                    "candidate_id": factor_id,
                    "proposal": envelope,
                    "repaired_attempt_id": repaired,
                    **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
                    **AUTHORITY,
                }

            return PreparedResearchAction(
                propose,
                candidate_id=factor_id,
                proposal_json=proposal_action(proposal.graph, hypothesis),
            )
        if tool == "propose_factor_set":
            ids = sorted(args["factor_ids"])
            eligible(ids)
            value = {
                "factor_ids": ids,
                "hypothesis_id": args["hypothesis_id"],
                "library_id": identity(self.host.factors(), "factor-library-snapshot"),
                "agent_run_id": ledger.run_id,
                "proposed_at": utc_text(at),
                "research_scope_id": self.host.admission.scope.scope_id,
                **AUTHORITY,
            }
            value["factor_set_id"] = identity(value, "r4-factor-set")
            return read({"outcome": "FACTOR_SET_PROPOSED", "factor_set": value})
        if tool == "propose_allocator":
            value = {
                "allocator": args["allocator"],
                "lookback_sessions": 20,
                "minimum_observations": 5,
                "ridge_alpha": 1,
                "agent_run_id": ledger.run_id,
                **AUTHORITY,
            }
            value["allocator_proposal_id"] = identity(value, "r4-allocator-proposal")
            return read({"outcome": "ALLOCATOR_PROPOSED", "allocator_proposal": value})
        if tool in {"evaluate_factor", "evaluate_portfolio"}:
            factor_set = allocator = None
            if tool == "evaluate_factor":
                ids = [args["candidate_id"]]
                if ledger.proposal(ids[0]) is None:
                    raise ContractError("candidate_not_proposed_in_run")
            else:
                factor_set = reference("factor_set", "factor_set_id", args["factor_set_id"])
                allocator = reference(
                    "allocator_proposal", "allocator_proposal_id", args["allocator_proposal_id"]
                )
                if factor_set["hypothesis_id"] != args["hypothesis_id"]:
                    raise ContractError("hypothesis_mismatch")
                ids = factor_set["factor_ids"]
            eligible(ids)
            # Preferred arm and hypothesis labels do not change the calculation:
            # all five comparators always run, so they cannot evade deduplication.
            experiment_id = identity(
                {
                    "kind": tool,
                    "factor_ids": ids,
                    "host_id": identity(self.host.manifest, "r4-host"),
                },
                "r4-experiment",
            )
            previous = next(
                (
                    r
                    for r in history
                    if r["evaluation_key"] == experiment_id and r["evaluation_reserved"]
                ),
                None,
            )
            if previous is not None:
                return read(
                    {
                        "outcome": "DUPLICATE_EXPERIMENT",
                        "experiment_id": experiment_id,
                        "original_request_id": previous["request_id"],
                        "original_outcome": previous["state"],
                    }
                )

            def evaluate() -> dict[str, object]:
                if factor_set is None or allocator is None:
                    return {
                        **self.host.evaluate_factor(ids[0], at, experiment_id),
                        "experiment_id": experiment_id,
                    }
                return {
                    "outcome": "PORTFOLIO_EVALUATED",
                    "experiment_id": experiment_id,
                    "factor_set_id": factor_set["factor_set_id"],
                    "factor_ids": ids,
                    "allocator_proposal_id": allocator["allocator_proposal_id"],
                    "preferred_allocator": allocator["allocator"],
                    "compatibility_id": self.host.compatibility_id,
                    "resource_cost": {"evaluation_slots": 1},
                    **self.host.evaluate_portfolio(ids, at, experiment_id),
                    **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
                    **AUTHORITY,
                }

            return PreparedResearchAction(evaluate, evaluation_key=experiment_id)
        if tool == "compare_experiments":
            return read(compare_feedback(experiments(args["experiment_ids"])))
        if tool == "allocate_budget":
            if (
                cast(int, ledger.snapshot()["evaluation_calls"])
                >= ledger.policy.maximum_evaluations
            ):
                raise ContractError("evaluation_budget_exhausted")
            return read(
                {
                    "outcome": "NEXT_EVALUATION_INTENT",
                    "hypothesis_id": args["hypothesis_id"],
                    "budget_authority": "ResearchLedger; maximum_unchanged",
                }
            )
        if tool == "retire_hypothesis":
            row = self.host.factor(args["factor_id"])
            if FactorStatus(args["status"]) not in _TRANSITIONS[FactorStatus(row["status"])]:
                raise ContractError("invalid_lifecycle_transition")
            experiments(args["experiment_ids"])

            def transition() -> dict[str, object]:
                self.host.transition(
                    args["factor_id"], args["status"], at, args["reason"], args["experiment_ids"]
                )
                return {
                    "outcome": "LIFECYCLE_DECIDED",
                    **args,
                    "agent_run_id": ledger.run_id,
                    **AUTHORITY,
                }

            return PreparedResearchAction(transition)
        if tool == "record_decision":
            return read({"outcome": "EXPLICIT_DECISION_RECORDED", "explicit_decision": args})
        if tool == "finalize_candidate":
            support = experiments(args["experiment_ids"])
            if args["recommendation"] == "candidate":
                factor_set = reference("factor_set", "factor_set_id", args["factor_set_id"])
                allocator = reference(
                    "allocator_proposal", "allocator_proposal_id", args["allocator_proposal_id"]
                )
                eligible(factor_set["factor_ids"])
                # Every completed portfolio request contains all five arms. A later
                # explicit allocator choice may cite that arm without a second run
                # or rewriting the experiment's originally preferred allocator.
                if not support or any(
                    r["factor_ids"] != factor_set["factor_ids"]
                    or r["summary"]["arms"]
                    .get(allocator["allocator"], {})
                    .get("mean_fold_return_5bp")
                    is None
                    for r in support
                ):
                    raise ContractError("invalid_development_candidate_evidence")
                terminal = "DEVELOPMENT_CANDIDATE_PROPOSED"
            else:
                if args["factor_set_id"] is not None or args["allocator_proposal_id"] is not None:
                    raise ContractError("no_candidate_must_not_bind_candidate")
                factor_set = allocator = None
                terminal = "NO_CANDIDATE_RECOMMENDED"
            return read(
                {
                    "outcome": terminal,
                    "decision": args["decision"],
                    "factor_set": factor_set,
                    "allocator": allocator,
                    "experiment_ids": args["experiment_ids"],
                    "agent_run_id": ledger.run_id,
                    "resource_usage_before_finalization": resource_snapshot(ledger),
                    "frozen_host_id": identity(self.host.manifest, "r4-host"),
                    **evidence_semantics(FactorEvidenceMode.ADAPTIVE_RETROSPECTIVE),
                },
                terminal=terminal,
            )
        raise ContractError("unknown_r4_tool")
