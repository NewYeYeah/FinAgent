# Research Visualization

FinAgent uses two complementary visualization layers:

```text
immutable A2/A2.5 report JSON ─┐
generated_features.sqlite ─────┼─→ Streamlit Research UI
Agent JSONL trace ──────────────┘

Agent OTLP trace ─────────────────→ Phoenix
```

The Streamlit application explains factor research evidence. Phoenix explains low-level Agent, LLM, repair, sandbox and evaluator spans. Neither layer owns research state.

## 1. Safety and governance boundary

The Research UI is read-only. It may read:

- an A-share factor acceptance JSON report;
- `generated_features.sqlite` through SQLite read-only mode;
- an Agent observability JSONL file;
- a Phoenix URL for navigation.

It cannot:

- call an LLM;
- repair or replace a candidate;
- rerun Factor Quant;
- modify prompts, checkpoints, reports or registries;
- consume an untouched reserve;
- promote a model or start PAPER/live execution.

Seeing validation evidence and then changing a hypothesis requires a new ResearchProgram. The UI must not be used to relabel an already observed validation window as clean validation.

## 2. Install

Install the dashboard in the FinAgent environment:

```bash
python -m pip install -e ".[visualization]"
```

This installs Streamlit and Plotly. Phoenix remains a separate optional service. On Windows, run Phoenix in the dedicated Python 3.12+ environment documented in [Agent research](agent-research.md); FinAgent can remain on Python 3.11 and export traces through OTLP.

## 3. Launch

### Windows PowerShell

```powershell
python scripts/run_research_ui.py `
  --report reports\local_ashare_factor_research_a2p5.json `
  --feature-store .finagent\local-ashare-factor-a2p5\generated_features.sqlite `
  --trace .finagent\a2-agent-trace.jsonl `
  --phoenix-url http://localhost:6006
```

### Ubuntu

```bash
python scripts/run_research_ui.py \
  --report reports/local_ashare_factor_research_a2p5.json \
  --feature-store .finagent/local-ashare-factor-a2p5/generated_features.sqlite \
  --trace .finagent/a2-agent-trace.jsonl \
  --phoenix-url http://localhost:6006
```

The default browser address is:

```text
http://localhost:8501
```

Useful launcher options:

```text
--port 8501
--address localhost
--headless
--print-command
```

A report can also be uploaded through the sidebar. Generated code and Agent trace inputs are optional; the numerical report views work without them.

## 4. Pages

### Overview

Shows:

- system workflow status separately from research outcome;
- mode, candidate denominator, candidate-universe size and reserve status;
- development-versus-validation RankICIR scatter;
- one table covering RankICIR, long-short Sharpe, coverage, HAC, Holm/BH and stability metrics.

A successful workflow can coexist with a failed research outcome. The dashboard preserves this distinction.

### Agent Discovery

Shows:

- cumulative discovery rounds;
- new and selected candidate identities by round;
- hypotheses, inputs, lookback and accepted source code;
- Agent JSONL trace hierarchy, status, duration, errors and events;
- prompt/completion/reasoning token counts, latency, provider attempts and finish reason;
- a direct link to the configured Phoenix project.

Hidden model reasoning is not available because FinAgent does not persist `reasoning_content`. Only explicit captured prompt/response content and reasoning-token metadata may appear in traces.

### Factor Lab

For each candidate:

- development and validation RankIC/RankICIR;
- rolling RankIC;
- yearly/subperiod RankIC and ICIR;
- quantile mean forward returns;
- HAC and circular block-bootstrap evidence;
- Holm-adjusted p-value and Benjamini-Hochberg q-value;
- sign, horizon, turnover and coverage stability;
- accepted generated source and AST validation metadata when the SQLite store is supplied.

### Ensemble

Shows:

- frozen development weights and directions;
- signed ensemble-versus-best-single validation comparison;
- validation ensemble stability;
- development and validation factor-value correlation heatmaps.

Absolute metric magnitude is not presented as economic improvement. Signed comparison remains the primary interpretation.

### Universe

Shows:

- fixed candidate-universe identity and selection date;
- split warm-up counts;
- first-session, average, minimum and maximum eligible assets;
- PIT policy rejection diagnostics.

This page is intended to expose split-boundary and universe-policy anomalies quickly.

### Lineage

Shows:

- dataset, candidate-universe, universe-policy, Factor Quant, stability, ensemble and discovery identities;
- reserve and promotion invariants;
- the immutable raw report.

Exact replay remains a CLI operation. The UI deliberately has no rerun button.

## 5. Phoenix integration

Start Phoenix in its separate environment:

```powershell
conda activate phoenix312
phoenix serve
```

Run FinAgent with OTLP and JSONL enabled:

```powershell
conda activate finagent
$env:FINAGENT_AGENT_TRACE = "1"
$env:FINAGENT_AGENT_TRACE_BACKEND = "both"
$env:FINAGENT_AGENT_TRACE_JSONL = ".finagent\a2-agent-trace.jsonl"
$env:FINAGENT_AGENT_TRACE_OTLP_ENDPOINT = "http://localhost:6006/v1/traces"
$env:FINAGENT_AGENT_TRACE_PROJECT = "finagent-a2"
```

Phoenix is the detailed span viewer; the Streamlit page supplies research-domain context and numerical interpretation. FinAgent is not coupled to Phoenix or to a third-party Agent framework.

## 6. Acceptance test

Run:

```bash
python -m pip install -e ".[dev,visualization]"
python -m pytest -q tests/test_research_visualization.py
```

Manual acceptance requires:

1. the report denominator matches development, validation and stability denominators;
2. a denominator mismatch blocks rendering rather than silently dropping a candidate;
3. `generated_features.sqlite` is opened in read-only mode;
4. the dashboard does not create or modify research databases, reports or checkpoints;
5. development and validation charts retain signed values;
6. reserve status and `promotion_eligible=false` are visible;
7. malformed/orphan JSONL records are reported as warnings;
8. Phoenix remains optional and the dashboard works with report JSON alone.

## 7. Troubleshooting

### Streamlit is missing

```text
RuntimeError: Streamlit is not installed
```

Install:

```bash
python -m pip install -e ".[visualization]"
```

### Report is rejected

The UI validates the candidate denominator before rendering. Regenerate the report with the current A2.5 runner if development, validation, stability or ensemble identities differ. Do not edit report JSON manually to bypass the check.

### Generated code is unavailable

Confirm the `state_dir` used by the research run and pass:

```text
<state_dir>/generated_features.sqlite
```

The numerical report remains usable without this file.

### Trace is unavailable

JSONL tracing must have been enabled before the Agent run. Phoenix traces cannot be reconstructed into the local JSONL file after the fact.

### Phoenix is unavailable

The Research UI does not require Phoenix. Continue with report, feature-store and JSONL views, then diagnose Phoenix independently.
