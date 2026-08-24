# FinAgent Development Log — Phase 3A

Date: 2026-08-24

## Goal

Freeze and implement a governed Agent-facing control surface before introducing an LLM runtime. The Agent must be able to inspect and orchestrate approved research actions while remaining unable to mutate portfolio weights, execution semantics, statistical thresholds or model stages directly.

## Implemented

Added a framework-independent `finagent.agents` package with:

```text
AgentAction
AgentTask
AgentRunContext
ToolCallRequest
ToolCallResult
PolicyDecision
AgentDecision
AgentAuditEvent
AgentRuntime Protocol
```

Added a finite `ToolRegistry`, exact `ToolSpec` argument validation, deterministic `DefaultResearchAgentPolicy`, `SQLiteAgentAuditStore`, `SQLiteResearchQueryService`, `ExperimentEvaluatorRegistry`, and fourteen approved research tools.

The Phase 3A tool surface is limited to research inspection, experiment-family creation/registration/execution/freeze/validation and non-mutating model-promotion requests. Portfolio/execution/risk bypass operations are not registered.

## Statistical governance

The Agent-facing family-validation tool accepts only `family_id` and `selected_experiment_id`. Returns, p-values and thresholds are obtained from trusted deterministic providers/configuration, preserving Phase 2.5 multiplicity, DSR, PBO and reality-check controls.

## Model governance

`request_model_promotion` validates a requested model-stage transition but does not call `promote_model`. Requests for SHADOW/LIVE require human approval. Illegal stage skipping fails before a human-review payload is materialized.

## Audit

Agent audit state is stored separately from research truth in:

```text
agent_runs
agent_tool_calls
agent_policy_decisions
agent_audit_events
```

Denied and failed actions are first-class audit records. Request sequences are replayable.

## Security refinement after first CI

The first Phase 3A implementation passed the complete 83-test matrix on Python 3.11, 3.12 and 3.13. Review then identified a privilege-boundary issue: a caller could reuse a registered `run_id` while constructing a different `AgentRunContext` with a larger tool budget or altered allowlist.

The fix persists the original context and adds `AgentAuditStore.get_run_context`. `ToolRegistry.invoke` now requires the supplied context to exactly equal the immutable registered context before recording or executing a tool request. A regression test verifies that a forged context is rejected without consuming or creating a tool call.

## Documentation and version

Added:

```text
docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md
docs/PHASE3A.md
docs/PHASE3B_PLAN.md
docs/DEVLOG_PHASE3A.md
```

Package prerelease version advances to `0.3.0a1`.

## Acceptance process

The freeze commit must pass the repository's complete GitHub Actions matrix under Python 3.11, 3.12 and 3.13 before `main` is advanced.

## Next step

Phase 3B introduces a deterministic `ScriptedResearchAgent`, run coordinator, typed research plan, experiment-template registry and replay engine. It will use the exact same Phase 3A ToolRegistry/policy/audit contracts later used by an LLM runtime in Phase 3C.
