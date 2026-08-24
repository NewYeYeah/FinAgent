# Phase 3C — Provider-Agnostic LLM Research Planning

## Objective

Phase 3C introduces model-driven research planning without putting a language model into the numerical trading hot path or giving it direct mutation privileges.

```text
AgentTask
  -> LLMResearchPlanner
  -> provider structured output
  -> local ResearchPlan validation
  -> LLMResearchAgent facade
  -> ScriptedResearchAgent
  -> ToolRegistry / PolicyEngine
  -> Research Control Plane
```

Phase 3B remains the deterministic execution engine. Phase 3C changes how a bounded `ResearchPlan` is proposed.

## Implemented components

### Provider layer

```text
LLMUsage
LLMRequest
LLMResponse
LLMProvider
LLMProviderError
StaticLLMProvider
OpenAIResponsesProvider
```

The OpenAI adapter uses the Responses API with strict JSON-schema output and `store=False`. The SDK is a lazy optional dependency.

Install only when needed:

```bash
python -m pip install -e ".[llm-openai]"
```

The default package and CI remain independent of provider SDKs.

### LLM planning policy

`LLMPlanningPolicy` deterministically owns the model id, planner version, variant/tool/failure ceilings, allowed primary and tie-break metrics, alpha, multiple-testing correction and output-token ceiling.

The model does not receive fields for statistical thresholds, promotion stages, portfolio weights or execution configuration.

### Structured planner

`LLMResearchPlanner` builds an approved-template catalog and requests a strict structured plan. Provider output is locally revalidated and converted into the existing Phase 3B `ResearchPlan`.

The model may propose family id, research question, approved template id, approved selection metrics, bounded variants, hypotheses and template-declared parameter values. It may not propose arbitrary code or undeclared parameters.

### LLMResearchAgent facade

`LLMResearchAgent` performs:

```text
plan(task)
 -> validated ResearchPlan
 -> ScriptedResearchAgent(plan)
 -> AgentRunCoordinator
 -> governed deterministic execution
```

The LLM never gets a direct handle to `SQLiteResearchRegistry`, `ExperimentRunner`, `RiskGate`, portfolio services or execution adapters.

### Provider telemetry

`SQLiteLLMCallStore` records provider/model identity, prompt hash, response id, token usage, cached-input tokens, latency, planning validity and validation errors. No API keys or hidden reasoning are stored.

### Evaluation

`AgentEvaluationMetrics` derives completion, tool-call count/success, denied/failed calls, token use, cached input and LLM latency from the provider response and Phase 3B replay trace.

## Security invariants

1. the LLM cannot call unregistered tools;
2. the LLM cannot alter the immutable Agent run budget;
3. the LLM cannot modify multiple-testing/DSR/PBO thresholds;
4. the LLM cannot choose an unapproved selection metric;
5. the LLM cannot create undeclared template parameters;
6. the LLM cannot set portfolio weights or fill prices;
7. the LLM cannot directly promote models;
8. the LLM cannot generate/execute arbitrary Python;
9. all executed research actions still pass through ToolRegistry and policy-as-code.

## OpenAI adapter

The optional adapter uses the current Responses API shape with `client.responses.create(...)`, strict `text.format.type=json_schema`, `store=False`, and provider-neutral extraction of `output_text`, response/model identity and usage telemetry.

Provider-specific SDK objects do not escape the adapter.

## Tests

Phase 3C adds coverage for policy-bounded structured plan generation, prompt-hash/provider telemetry, rejection of planner-supplied validation thresholds, rejection of unapproved tie-break metrics, exact template-parameter enforcement, end-to-end LLM planning followed by deterministic Phase 3B execution, Agent evaluation metrics and the OpenAI adapter request shape using an injected fake client.

CI does not call an external model and does not require an API key.

## Deferred

Phase 3C still does not implement free-form hypothesis/code generation, sandbox execution, adaptive multi-turn tool planning, semantic/vector memory, multi-Agent debate, LangGraph, broker access or Agent portfolio-weight authority.

Phase 3D should focus on sandboxed feature/factor code generation rather than weakening the existing action boundary.
