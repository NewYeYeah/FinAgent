# ADR-013 — Phase 3C LLM Planning Boundary

Status: **Accepted**

## Context

Phase 3A established the finite Agent tool surface and deterministic policy/audit boundary. Phase 3B proved that an autonomous research workflow can execute through those tools without an LLM. Phase 3C introduces a real provider abstraction and optional OpenAI Responses API adapter.

The primary architectural question is where model nondeterminism is allowed to enter.

## Decision 1 — LLMs propose plans, deterministic code executes actions

Phase 3C does **not** give an LLM an unrestricted iterative tool loop.

```text
Natural-language research task
    -> LLMResearchPlanner
    -> strict structured ResearchPlan proposal
    -> deterministic plan validation
    -> ScriptedResearchAgent
    -> ToolRegistry / PolicyEngine
    -> Research Control Plane
```

The LLM may choose an approved template and bounded experiment variants. It does not receive portfolio, execution, risk-gate, registry, SQL or Python-code mutation capabilities.

## Decision 2 — statistical and risk policy remain outside the model schema

The structured planner schema does not expose alpha, multiple-testing method, DSR/PBO thresholds, bootstrap configuration, tool/experiment budgets, model promotion stages, portfolio weights, fill prices or execution settings. Those values remain deterministic.

Any extra top-level planner field is rejected.

## Decision 3 — template catalog is the only experiment construction surface

`LLMResearchPlanner` receives only the approved `ExperimentTemplateRegistry` catalog. Each returned variant must reference one registered template and provide exactly the declared parameter set. Unknown or missing parameters are rejected before any Agent run is registered.

Arbitrary source-code generation remains deferred to Phase 3D.

## Decision 4 — selection metrics are allowlisted

The LLM may choose only metrics present in `allowed_primary_metrics` and `allowed_tie_break_metrics`. The initial defaults are `validation_sharpe` and `turnover`.

This prevents a model from selecting an outer-test or otherwise prohibited metric merely by naming it in a plan.

## Decision 5 — provider API is framework-independent

Core contracts are:

```text
LLMRequest
LLMResponse
LLMUsage
LLMProvider
LLMProviderError
```

`StaticLLMProvider` supports deterministic CI/offline testing. `OpenAIResponsesProvider` is optional and lazy-loads the provider SDK through the `llm-openai` extra.

## Decision 6 — provider structured output is still validated locally

Provider-level JSON-schema enforcement is only the first line of defense. `LLMResearchPlanner.parse_plan` repeats deterministic checks for exact fields, registered templates, approved metrics, variant count, exact parameter names, duplicate parameters and safe identifiers.

A syntactically valid provider response can therefore still be rejected by FinAgent.

## Decision 7 — LLM telemetry is durable but hidden reasoning is not stored

`SQLiteLLMCallStore` persists request/task ids, provider/model, prompt hash, provider status, response id, token counts, cached input tokens, latency, planning validity and validation errors.

API keys and hidden model reasoning are never stored.

Provider telemetry is separate from `SQLiteAgentAuditStore`: the former records model-call behavior, while the latter remains the source of truth for governed tool actions.

## Decision 8 — Phase 3C evaluates Agent engineering quality

`AgentEvaluationMetrics` reports research completion, tool-call count/success, denied/failed calls, token use and model latency. PnL remains a quantitative research outcome rather than an Agent-quality score.

## Consequences

Positive:

- real LLM planning can be added without weakening the Phase 3A/3B action boundary;
- provider implementations are replaceable;
- malformed or policy-changing plans fail before research mutation;
- token/latency/reproducibility metrics become measurable;
- removing all LLM providers leaves the deterministic Quant/Research system operational.

Trade-offs:

- Phase 3C is less flexible than free-form tool-calling agents;
- the planner cannot invent code or new experiment templates;
- natural-language planning is constrained by a fixed schema and metric allowlists;
- sandbox code generation remains a later milestone.

These limitations are intentional and should only be relaxed with a new ADR.
