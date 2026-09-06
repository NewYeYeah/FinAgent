"""Finite opt-in workflow repair pilot, without model/strategy selection or outer access."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from finagent.agents.providers.config import load_llm_profile
from finagent.agents.r3_contracts import DevelopmentScope, ResearchRuntimePolicy, decode_action
from finagent.agents.r3_provider import TARIFF, StrictDeepSeekProvider
from finagent.agents.r3_runtime import ResearchCapabilityRuntime
from finagent.research.us_r3_completion import (
    AdmittedEvaluator,
    baseline_action,
    completion_code,
    seal,
)
from finagent.research.us_r3_economic_campaign import _sealed, digest, file_digest


def workflow_code() -> str:
    return digest({"core": completion_code(), "pilot": file_digest(Path(__file__))})


def freeze_workflow(previous_root: Path, config: Path, output: Path) -> dict[str, Any]:
    old = _sealed(previous_root / "protocol.json", "evidence_id", "us-r3-completion-protocol-")
    summary = _sealed(previous_root / "summary.json", "evidence_id", "us-r3-completion-")
    if summary["protocol_id"] != old["evidence_id"]:
        raise ValueError("predecessor chain mismatch")
    profile = load_llm_profile(config)
    if (profile.provider, profile.model, profile.base_url.rstrip("/")) != (
        "deepseek",
        "deepseek-v4-pro",
        "https://api.deepseek.com",
    ):
        raise ValueError("unadmitted provider routing")
    policy = ResearchRuntimePolicy(
        maximum_slots=1,
        maximum_attempts=6,
        maximum_attempts_per_slot=6,
        maximum_evaluations=1,
        maximum_tokens=98304,
        maximum_cost_microusd=150000,
        call_timeout_seconds=45.0,
    )
    return seal(
        output,
        {
            "schema_version": "finagent.us-r3-workflow-pilot.v1",
            "frozen_at_utc": datetime.now(UTC).isoformat(),
            "implementation_id": workflow_code(),
            "predecessor": {
                "root": str(previous_root.resolve()),
                "protocol_id": old["evidence_id"],
                "evidence_id": summary["evidence_id"],
            },
            "economic_protocol": old["economic_protocol"],
            "development_sessions": old["splits"]["development"],
            "config": {"path": str(config.resolve()), "sha256": file_digest(config)},
            "provider_tariff": TARIFF,
            "runtime_policy": asdict(policy),
            "runs": 3,
            "candidate_slots": 3,
            "maximum_evaluations": 3,
            "maximum_external_cost_microusd": 450000,
            "workflow": "validate_evaluate_identical_submit_v1",
            "acceptance": "all three runs must VALIDATE, EVALUATE_DEVELOPMENT, and SUBMIT the identical proposal within their original six attempts; no replacement runs",
            "research_scope": "tool adherence and causal capability integration only; at most three additional development proposals retained, no profitability selection, no outer/final reads, no superiority test",
            "stopping": "complete or exhaust each fixed run; never extend budget based on success or return",
            "alpha_authority": False,
            "broker_authority": False,
        },
        "us-r3-workflow-protocol-",
    )


def run_workflow(
    protocol_path: Path, root: Path, *, provider_factory: Any = None, progress: Any = None
) -> dict[str, Any]:
    protocol = _sealed(protocol_path, "evidence_id", "us-r3-workflow-protocol-")
    if protocol["implementation_id"] != workflow_code():
        raise ValueError("workflow implementation changed")
    for name in ("config", "economic_protocol"):
        item = protocol[name]
        if file_digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("workflow input binding changed")
    economic = _sealed(
        Path(protocol["economic_protocol"]["path"]), "protocol_id", "us-r3-economic-protocol-"
    )
    for item in economic["inputs"].values():
        if file_digest(Path(item["path"])) != item["sha256"]:
            raise ValueError("workflow admitted source changed")
    from finagent.research.us_r3_usability import write_immutable_json

    write_immutable_json(root / "protocol.json", protocol)
    if (root / "summary.json").exists():
        saved = _sealed(root / "summary.json", "evidence_id", "us-r3-workflow-pilot-")
        records = [
            _sealed(root / f"run-{i}.json", "evidence_id", "us-r3-workflow-run-") for i in range(3)
        ]
        if saved["protocol_id"] != protocol["evidence_id"] or saved["run_ids"] != [
            r["evidence_id"] for r in records
        ]:
            raise ValueError("workflow report chain mismatch")
        return {
            **saved,
            "resumed": True,
            "provider_calls_this_invocation": 0,
            "evaluator_calls_this_invocation": 0,
        }
    policy = ResearchRuntimePolicy(**protocol["runtime_policy"])
    evaluator = AdmittedEvaluator(
        economic, protocol["development_sessions"], root / "development", "workflow-development"
    )
    scope = DevelopmentScope(
        "workflow-development", (), evaluator.source_id, evaluator.evaluator_id
    )
    records = []
    calls = 0
    for index in range(3):
        path = root / f"run-{index}.json"
        if path.exists():
            record = _sealed(path, "evidence_id", "us-r3-workflow-run-")
            if record["protocol_id"] != protocol["evidence_id"]:
                raise ValueError("workflow run binding changed")
            records.append(record)
            continue
        example = json.loads(baseline_action("manual", index, index))
        example["tool"] = "validate_factor"
        instruction = (
            "Execute a strictly ordered research workflow. Return exactly ONE JSON action, never an explanation. "
            "The user context workflow.required_tool is mandatory. If workflow.required_action exists, return that EXACT JSON object unchanged. "
            "Otherwise propose one simple dimensionless factor with at most eight nodes, POSITIVE direction and at most twelve bars lookback; "
            "return validate_factor with full nodes/output_node_id/hypothesis arguments. No extra fields or empty operator parameters. "
            "Do not claim profitability. Rejected attempts consume budget. After validation, evaluate the candidate, then submit its unchanged proposal even if returns are negative. "
            "Wire-format validation example: " + json.dumps(example, separators=(",", ":"))
        )
        provider = (
            provider_factory(index, instruction)
            if provider_factory
            else StrictDeepSeekProvider(Path(protocol["config"]["path"]), instruction)
        )
        runtime = ResearchCapabilityRuntime(
            root / f"run-{index}.sqlite",
            run_id=f"workflow-{index}",
            scope=scope,
            provider=provider,
            provider_id="deepseek-official" if provider_factory is None else "synthetic",
            model_id="deepseek-v4-pro" if provider_factory is None else "synthetic",
            policy=policy,
            evaluator=evaluator,
            require_evaluated_submission=True,
        )
        before = cast(int, runtime.ledger.snapshot()["attempt_count"])
        for attempt in range(policy.maximum_attempts):
            reply = runtime.step(f"attempt-{attempt}", 0)
            if reply["outcome"] in ("PENDING_RECONCILIATION", "RUN_BUSY"):
                # Another worker or an uncertain interrupted call owns this run.
                # Never seal a failed terminal while its outcome is still pending.
                raise RuntimeError("pending workflow requires worker reconciliation")
            if progress:
                progress(
                    "workflow_step", {"run": index, "attempt": attempt, "outcome": reply["outcome"]}
                )
            if reply["outcome"] == "SUBMITTED":
                break
        ledger = runtime.ledger.snapshot()
        calls += cast(int, ledger["attempt_count"]) - before
        outcomes = runtime.ledger.slot_results(0)
        successful = [
            r
            for r in outcomes
            if r["outcome"] in ("VALIDATED", "DEVELOPMENT_EVALUATED", "SUBMITTED")
        ]
        passed = [r["outcome"] for r in successful] == [
            "VALIDATED",
            "DEVELOPMENT_EVALUATED",
            "SUBMITTED",
        ]
        evaluation = None
        if passed:
            raw = runtime.ledger.proposal(successful[0]["candidate_id"])
            proposal = decode_action(raw or "").proposal
            if proposal is None:
                raise ValueError("submitted workflow proposal missing")
            evaluation = evaluator.calculate(proposal.graph)
        record = seal(
            path,
            {
                "protocol_id": protocol["evidence_id"],
                "run": index,
                "provider_calls_are_real": provider_factory is None,
                "passed": passed,
                "outcomes": outcomes,
                "ledger": ledger,
                "evaluation": evaluation,
                "alpha_authority": False,
                "broker_authority": False,
            },
            "us-r3-workflow-run-",
        )
        records.append(record)
    passed = all(r["passed"] for r in records)
    return seal(
        root / "summary.json",
        {
            "protocol_id": protocol["evidence_id"],
            "run_ids": [r["evidence_id"] for r in records],
            "passed": passed,
            "successful_runs": sum(r["passed"] for r in records),
            "run_denominator": 3,
            "real_model_workflow_accepted": passed and provider_factory is None,
            "attempts": sum(r["ledger"]["attempt_count"] for r in records),
            "charged_cost_upper_microusd": sum(
                r["ledger"]["charged_cost_microusd"] for r in records
            ),
            "development_evaluation_calls": sum(r["ledger"]["evaluation_calls"] for r in records),
            "provider_calls_this_invocation": calls,
            "evaluator_calls_this_invocation": evaluator.calls,
            "scope": protocol["research_scope"],
            "autonomous_agent_value_demonstrated": False,
            "terminal": "GUIDED_WORKFLOW_ACCEPTED" if passed else "WORKFLOW_PILOT_FAILED_STOPPED",
            "alpha_authority": False,
            "broker_authority": False,
        },
        "us-r3-workflow-pilot-",
    )
