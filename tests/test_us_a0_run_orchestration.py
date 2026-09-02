from __future__ import annotations

from finagent.research.us_agent_value_assembly import parse_us_a0_run_evidence_bundle
from finagent.research.us_agent_value_orchestration import (
    USAgentValuePilotOrchestrationCheckpoint,
    USAgentValuePilotOrchestrationState,
)
from finagent.research.us_agent_value_run_orchestration import (
    advance_us_a0_pilot_run_progress,
    build_run_evidence_complete_checkpoint,
    parse_us_a0_pilot_run_progress,
    parse_us_a0_pilot_run_promotion_intent,
    promotion_intent_from_parsed_evidence,
)
from tests.test_us_a0_assembly import _artifacts, _plan, _predecessor, _runs


def _parsed_runs():
    plan = _plan()
    predecessor = _predecessor()
    runs = _runs(plan)
    parsed = tuple(
        parse_us_a0_run_evidence_bundle(
            execution_plan=plan,
            predecessor=predecessor,
            generation_document=generation,
            run_evaluation_document=evaluation,
            evaluation_link_document=link,
            run_manifest_document=manifest,
        )
        for generation, evaluation, link, manifest in (
            _artifacts(plan, predecessor, run) for run in runs
        )
    )
    agent = runs[2]
    checkpoint = USAgentValuePilotOrchestrationCheckpoint(
        launch_bundle_id="launch-test",
        runtime_policy_id="runtime-test",
        execution_plan_id=plan.plan_id,
        agent_run_spec_id=agent.spec.run_spec_id,
        state=USAgentValuePilotOrchestrationState.AGENT_GENERATED,
        checkpoint_ordinal=1,
        previous_checkpoint_id="prepared-checkpoint-test",
        agent_generation_run_id=agent.run_id,
    )
    return plan, predecessor, parsed, checkpoint


def test_run_progress_commits_exact_execution_plan_prefix_and_final_checkpoint() -> None:
    plan, predecessor, parsed, checkpoint = _parsed_runs()
    progress = None
    for item in parsed:
        progress = advance_us_a0_pilot_run_progress(
            previous=progress,
            execution_plan=plan,
            agent_checkpoint=checkpoint,
            predecessor=predecessor,
            parsed_run=item,
        )
        assert parse_us_a0_pilot_run_progress(progress.to_dict()) == progress

    assert progress is not None
    assert progress.progress_ordinal == 3
    assert tuple(item.run_spec_id for item in progress.completed_runs) == tuple(
        spec.run_spec_id for spec in plan.run_specs
    )
    completed = build_run_evidence_complete_checkpoint(
        agent_checkpoint=checkpoint,
        execution_plan=plan,
        progress=progress,
    )
    assert completed.state is USAgentValuePilotOrchestrationState.RUN_EVIDENCE_COMPLETE
    assert completed.previous_checkpoint_id == checkpoint.checkpoint_id
    assert completed.run_evidence_manifest_ids == tuple(
        item.run_evidence_manifest_id for item in parsed
    )


def test_run_progress_rejects_out_of_order_commit() -> None:
    plan, predecessor, parsed, checkpoint = _parsed_runs()
    try:
        advance_us_a0_pilot_run_progress(
            previous=None,
            execution_plan=plan,
            agent_checkpoint=checkpoint,
            predecessor=predecessor,
            parsed_run=parsed[2],
        )
    except ValueError as exc:
        assert "exact ExecutionPlan run order" in str(exc)
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("out-of-order AGENT commit must fail")


def test_run_progress_cannot_replace_committed_manifest() -> None:
    plan, predecessor, parsed, checkpoint = _parsed_runs()
    first = advance_us_a0_pilot_run_progress(
        previous=None,
        execution_plan=plan,
        agent_checkpoint=checkpoint,
        predecessor=predecessor,
        parsed_run=parsed[0],
    )
    forged_document = first.to_dict()
    forged_document["completed_runs"][0]["run_evidence_manifest_id"] = "different-manifest"
    try:
        parse_us_a0_pilot_run_progress(forged_document)
    except ValueError:
        pass
    else:  # pragma: no cover - fail-closed assertion
        raise AssertionError("tampered committed manifest must fail content identity")


def test_promotion_intent_round_trips_validated_run_evidence() -> None:
    plan, _, parsed, _ = _parsed_runs()
    intent = promotion_intent_from_parsed_evidence(parsed[0], execution_plan=plan)
    assert parse_us_a0_pilot_run_promotion_intent(intent.to_dict()) == intent
    assert intent.execution_plan_id == plan.plan_id
    assert intent.generation_run_id == parsed[0].run_id
    assert intent.run_evidence_manifest_id == parsed[0].run_evidence_manifest_id
