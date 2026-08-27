# Agent Research Workflow

The Agent proposes bounded hypotheses and feature code. Deterministic code owns data access, validation, Factor Quant evidence, portfolio logic and state transitions.

## 1. Configure and smoke-test the LLM

Public routing lives in `configs/llm.toml`; credentials remain in the external secret store described in `getting-started.md`.

```bash
python -c "from finagent.agents.providers import load_llm_profile; print(load_llm_profile('configs/llm.toml'))"
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

The DeepSeek V4-Pro profile keeps thinking enabled with high reasoning effort. A2 currently allows a large completion ceiling because real high-thinking feature-generation calls can use substantially more than a short JSON answer. The configured ceiling is not a target; provider-reported usage is the actual token consumption.

## 2. Generated-feature contract and repair

Generated code follows:

```text
provider response
→ strict JSON schema
→ FeatureSpec
→ AST guardrail
→ restricted subprocess smoke
→ immutable GeneratedFeatureArtifact
```

The runtime ABI is intentionally small:

```text
inputs: dict[str, list[float | None]]
output: list[float | None]  # same length
```

Inputs are plain Python lists, not NumPy arrays. Element-wise arithmetic must use comprehensions/loops/`zip`/`enumerate`. Arbitrary object attributes and methods such as `.append()`, `.get()`, `.mean()` and `.tolist()` are forbidden; only the validator-approved `math.*` members are available.

A generated candidate is not accepted merely because the LLM call succeeded. FinAgent separates three failure classes:

```text
provider transient
→ bounded provider retry

JSON / AST / sandbox conformance failure
→ bounded repair of the same logical candidate

repair budget exhausted
→ bounded replacement for the same candidate slot
```

Repair feedback contains engineering conformance errors only. It never contains independent validation, reserve, holdout, promotion, PAPER or live evidence.

Successful logical candidate slots are checkpointed in the A2 `state_dir`. Restarting the same scoped research task reuses the exact validated artifact instead of regenerating it and mutating the search denominator.

## 3. A-share Factor Quant A2

The canonical entry point is:

```text
scripts/run_local_ashare_factor_research.py
configs/research/local_ashare_factor_research.example.toml
```

The example freezes a candidate universe before development, uses 2018–2021 for adaptive development, 2022–2024 for independent factor-level validation and leaves 2025 onward untouched.

Deterministic baseline:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode deterministic `
  --verify-content
```

Agent mode:

```powershell
python scripts/run_local_ashare_factor_research.py `
  configs\research\local_ashare_factor_research.local.toml `
  --mode agent `
  --llm-profile deepseek_official_v4_pro `
  --verify-content `
  --report reports\local_ashare_factor_research_a2_agent.json
```

The Factor Quant loop is cumulative. Each later round can see development-only IC/RankIC/ICIR, explicit horizon decay, quantile behavior, turnover, coverage, redundancy and the current deterministic ensemble selection. Every accepted adaptive candidate remains in the final search denominator.

## 4. Agent observability and visualization

FinAgent tracing is vendor-neutral. The code emits local JSONL traces and can export the same hierarchy over OTLP/OpenTelemetry with OpenInference-compatible span-kind semantics. Phoenix is the recommended first UI because it can receive OTLP traces without changing FinAgent's research architecture.

### 4.1 Local JSONL trace

No extra dependency is required:

```powershell
$env:FINAGENT_AGENT_TRACE = "1"
$env:FINAGENT_AGENT_TRACE_BACKEND = "jsonl"
$env:FINAGENT_AGENT_TRACE_JSONL = ".finagent\a2-agent-trace.jsonl"
```

Then run the normal Agent command. The trace records the hierarchy and engineering metadata for:

```text
Factor Quant discovery
├─ round
│  ├─ candidate generation
│  │  └─ LLM call
│  ├─ static validation
│  ├─ sandbox smoke
│  ├─ repair / replacement / checkpoint events
│  ├─ Factor Quant evaluator
│  └─ factor selection
└─ development feedback identity
```

### 4.2 Phoenix UI

Keep the Phoenix server isolated from the FinAgent research environment. This is especially important when FinAgent uses Python 3.11: current Phoenix 20.x server code contains `dataclass` defaults based on `MappingProxyType`, while Python 3.11 treats those defaults as unhashable/mutable and can fail during `phoenix serve` import. Python 3.12 added hashing support for `MappingProxyType`.

Install only the OTLP exporter support in the FinAgent environment:

```powershell
conda activate finagent
python -m pip install -e ".[observability]"
```

Run Phoenix in a dedicated Python 3.12+ environment:

```powershell
conda create -n phoenix312 python=3.12 -y
conda activate phoenix312
python -m pip install --upgrade pip
python -m pip install arize-phoenix
phoenix serve
```

Do not need to install the full `arize-phoenix` server package into `finagent`. The two environments communicate over HTTP OTLP.

In a second terminal, return to FinAgent and enable export:

```powershell
conda activate finagent
$env:FINAGENT_AGENT_TRACE = "1"
$env:FINAGENT_AGENT_TRACE_BACKEND = "both"
$env:FINAGENT_AGENT_TRACE_OTLP_ENDPOINT = "http://localhost:6006/v1/traces"
$env:FINAGENT_AGENT_TRACE_PROJECT = "finagent-a2"
```

Open the Phoenix UI at `http://localhost:6006` and run A2 Agent research normally. The UI should show nested Agent/LLM/guardrail/tool/evaluator spans, token counts, latency, repair errors and Factor Quant round identities.

If `phoenix serve` fails before the server starts, first record the environment identity:

```powershell
python --version
python -m pip show arize-phoenix
```

Do not patch `site-packages/phoenix` in place. Prefer a separate supported interpreter or a deliberately pinned Phoenix server environment so the observability service cannot destabilize FinAgent dependencies.

By default FinAgent does **not** export prompt or response bodies. For local debugging only, opt in explicitly:

```powershell
$env:FINAGENT_AGENT_TRACE_CAPTURE_CONTENT = "1"
```

This can expose research prompts, generated JSON/Python and development Factor Quant feedback, so do not enable it for traces that will be shared externally. Hidden model reasoning / `reasoning_content` is never stored or exported; only reasoning-token count and a presence flag may be recorded.

## 5. Why Phoenix rather than an Agent framework rewrite

FinAgent does not adopt LangChain/LangGraph merely to gain a UI. Its research lifecycle, candidate denominator, sealed evidence and deterministic numerical interfaces already define the application architecture. Replatforming those semantics onto another Agent framework would add coupling without improving research correctness.

The selected boundary is therefore:

```text
FinAgent domain/research runtime
        ↓
OpenTelemetry / OpenInference-style trace semantics
        ↓
Phoenix today
        ↓
other OTLP-compatible observability backend later if needed
```

Langfuse remains a viable later backend when centralized prompt management, multi-user evaluation or a heavier hosted/self-hosted observability stack is justified.

## 6. US reference Agent study

After materializing validated Alpaca SIP data:

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --report reports/us_etf_agent_market_research.json
```

Before feature generation the runner verifies provider, market, symbols, normalized bars digest and manifest identity.

## 7. Replay and evidence boundary

A2 exact replay uses the immutable generated-feature store and frozen report and must not call the LLM again.

Agent-visible feedback may contain development diagnostics. It must never contain:

```text
independent validation evidence
untouched reserve evidence
sealed holdout evidence
promotion decisions
PAPER/live outcomes used for adaptive research
```

Human approval remains required for operational stage transitions. A2 is factor-level historical research; A-share T+1, lots, price limits and asymmetric trading costs remain an A3 execution concern.
