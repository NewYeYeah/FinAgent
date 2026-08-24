# FinAgent

FinAgent is a typed, auditable quantitative-research and portfolio infrastructure in which language models may plan approved research without entering the numerical trading hot path.

Current status: **Phase 3C — Provider-Agnostic LLM Research Planning**.

The project rule is:

```text
LLM:
  proposes bounded research plans.

Deterministic Agent runtime:
  executes only finite registered tools.

Deterministic quantitative code:
  owns PIT data, models, statistical validation, portfolio weights,
  hard risk approval, execution semantics and model lifecycle.
```

## Architecture

```text
Natural-language research task
          |
          v
  LLMResearchPlanner
          |
   strict ResearchPlan
          |
          v
 ScriptedResearchAgent
          |
 ToolRegistry + Policy
          |
 Audit / Replay / Budget
          |
 Research Control Plane
          |
ExperimentFamily / Runner / Validation / Registry
          |
          v
      Quant Engine
          |
Data -> Alpha -> Risk -> Portfolio -> RiskGate -> Timed Execution
```

The LLM is intentionally outside the numerical trading hot path.

## Quant and research foundations

The frozen numerical path remains:

```text
DataAdapter
 -> ResearchDataset / ResearchSplit
 -> FeatureWindow
 -> AlphaModel / RiskModel
 -> AlphaForecast / RiskForecast
 -> PortfolioOptimizer
 -> PortfolioTarget
 -> RiskGate
 -> OrderIntent
 -> TimedExecutionVenue
 -> Fill / PortfolioState
```

Implemented reference components include PIT-safe data adapters, random-walk/AR/ARMA alpha models, GARCH/EWMA covariance risk models, mean-variance optimization, deterministic risk gates, timed execution and event-driven backtesting.

Research governance includes purged/embargoed and nested walk-forward validation, `ExperimentFamily` lifecycle control, multiple-testing correction, Deflated Sharpe Ratio, CSCV PBO, a White-style Reality Check and governed model stages:

```text
CANDIDATE -> VALIDATED -> PAPER -> SHADOW -> LIVE -> RETIRED
```

## Phase 3A — governed Agent surface

Phase 3A established the finite Agent action vocabulary, ToolRegistry, deterministic policy, immutable AgentRunContext and SQLite audit trail. The Agent cannot set portfolio weights, bypass risk, choose fills, delete failed trials, remove frozen family members, directly promote models or execute broker orders.

## Phase 3B — deterministic scripted Agent

Phase 3B added `ResearchBudget`, `ResearchPlan`, `ExperimentTemplateRegistry`, `ScriptedResearchAgent`, `AgentRunCoordinator`, `SQLiteAgentPlanStore` and `AgentReplayEngine`.

The scripted workflow is:

```text
inspect families
 -> create family
 -> register approved variants
 -> run variants
 -> compare approved metrics
 -> seal deterministic winner
 -> freeze family
 -> validate full family
 -> optional non-mutating promotion request
```

Plans are SHA-256 fingerprinted and poor results cannot silently expand their research budget.

## Phase 3C — LLM planning boundary

Phase 3C adds provider-neutral LLM contracts:

```text
LLMRequest
LLMResponse
LLMUsage
LLMProvider
SQLiteLLMCallStore
LLMResearchPlanner
LLMResearchAgent
AgentEvaluationMetrics
```

The LLM only proposes an approved-template `ResearchPlan`. FinAgent then revalidates the plan locally and delegates execution to the deterministic Phase 3B runtime.

The structured planner cannot supply validation thresholds, multiple-testing settings, research budgets, promotion stages, portfolio weights, risk overrides, fill prices, broker actions or Python code. Selection metrics and experiment templates are allowlisted.

### Provider support

The default install has no provider SDK dependency. Deterministic tests use `StaticLLMProvider`.

An optional OpenAI Responses API adapter is available through:

```bash
python -m pip install -e ".[llm-openai]"
```

Example construction:

```python
from finagent.agents import LLMPlanningPolicy, LLMResearchPlanner, OpenAIResponsesProvider

provider = OpenAIResponsesProvider()
planner = LLMResearchPlanner(
    provider=provider,
    templates=template_registry,
    policy=LLMPlanningPolicy(model="YOUR_SUPPORTED_MODEL"),
)
```

The provider adapter uses strict JSON-schema structured output and does not expose SDK types outside the adapter.

## Audit and evaluation

Three durable stores have distinct responsibilities:

```text
SQLiteResearchRegistry  -> experiments/models/results
SQLiteAgentAuditStore   -> governed tool actions and decisions
SQLiteLLMCallStore      -> provider/model/prompt-hash/token/latency telemetry
```

Agent quality is evaluated by orchestration correctness, invalid-plan/tool rates, policy denials, completion, reproducibility, token use and latency. PnL remains a quantitative research outcome, not an Agent-quality score.

## Repository layout

```text
src/finagent/
├── agents/
│   ├── audit.py
│   ├── coordinator.py
│   ├── domain.py
│   ├── llm_planner.py
│   ├── llm_research.py
│   ├── metrics.py
│   ├── planning.py
│   ├── policy.py
│   ├── providers/
│   ├── replay.py
│   ├── runtime.py
│   ├── scripted.py
│   ├── templates/
│   └── tools/
├── analysis/
├── backtest/
├── data/
├── domain/
├── models/
├── portfolio/
├── research/
├── services/
└── ports.py
```

## Development

Python 3.11+ is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
pytest -q
```

GitHub Actions runs the complete suite on Python 3.11, 3.12 and 3.13. External provider calls are never required by CI.

## Next milestone

The next milestone is **Phase 3D — sandboxed feature/factor code generation**.

```text
LLM hypothesis
 -> generated feature artifact
 -> static validation
 -> isolated sandbox
 -> approved ExperimentTemplate/ArtifactRef
 -> existing research governance
```

Phase 3D should not add broker access, direct portfolio-weight authority or risk-gate bypasses.

## Design documents

- [`docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md`](docs/ADR-007_PHASE1_NUMERICAL_DATA_CONTRACT.md)
- [`docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md`](docs/ADR-008_PHASE2_VALIDATION_AND_EXECUTION_CLOCK.md)
- [`docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md`](docs/ADR-009_PHASE2_MODEL_GOVERNANCE.md)
- [`docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md`](docs/ADR-010_PHASE25_RESEARCH_MULTIPLICITY.md)
- [`docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md`](docs/ADR-011_PHASE3A_AGENT_CONTROL_SURFACE.md)
- [`docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md`](docs/ADR-012_PHASE3B_SCRIPTED_AGENT.md)
- [`docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md`](docs/ADR-013_PHASE3C_LLM_PLANNING_BOUNDARY.md)
- [`docs/PHASE3A.md`](docs/PHASE3A.md)
- [`docs/PHASE3B.md`](docs/PHASE3B.md)
- [`docs/PHASE3C.md`](docs/PHASE3C.md)
- [`docs/DEVLOG.md`](docs/DEVLOG.md)
