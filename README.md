# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs propose hypotheses and bounded feature code; deterministic components own data chronology, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

## Current scope

The current development baseline supports:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- Agent-generated features with AST validation, restricted execution, repair and checkpointing;
- factor diagnostics including IC, RankIC, IC decay, quantile portfolios and turnover;
- rolling/subperiod stability, HAC, block bootstrap and candidate-family multiplicity control;
- A2.6 immutable A-share ResearchPrograms with expanding walk-forward, preregistered robust gates, explicit no-alpha outcomes and exact replay;
- A3 exact-session A-share execution semantics including T+1, board quantity rules, suspension/price limits and asymmetric fees;
- A4 execution-aware internal portfolio validation with frozen-factor Alpha, historical risk, optimizer targets, gross/net ledgers and byte-identical replay;
- nested validation, DSR, PBO and Reality Check on the existing general research path;
- supervised paper/shadow operations and sealed-holdout/promotion primitives;
- US market ingestion through Alpaca SIP and best-effort AKShare validation;
- local A-share Parquet research through DuckDB-backed adapters;
- read-only Streamlit/Plotly research visualization plus Phoenix/JSONL Agent traces.

The current market priority is **A-share historical research first**, with **Alpaca SIP as the US reference/regression path**. A-share live-capital or realtime acceptance is intentionally deferred until the frozen research, execution-aware internal validation, one-shot reserve and repeated PAPER gates are complete.

## Quick start

Python 3.11+ is required.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional dependencies:

```bash
python -m pip install -e ".[llm]"           # DeepSeek / SiliconFlow / OpenAI transport
python -m pip install -e ".[us-market]"     # Alpaca
python -m pip install -e ".[cn-free]"       # AKShare
python -m pip install -e ".[a-share]"       # Tushare
python -m pip install -e ".[local-parquet]" # local A-share Parquet / DuckDB
python -m pip install -e ".[observability]" # OTLP Agent trace exporter
python -m pip install -e ".[visualization]" # Streamlit / Plotly Research UI
```

For Windows and Ubuntu setup, credential configuration and provider-specific commands, see the guides below.

## A-share research-to-execution flow

```text
Frozen local Parquet
        ↓
A2.6 robust ResearchProgram
        ↓
Frozen factor family / explicit no-alpha result
        ↓
A3 target-to-executable-order semantics
        ↓
A4 internal gross/net portfolio validation
        ↓
Unified acceptance and protocol freeze
        ↓
Future one-shot reserve evaluation
```

Run A4 only from an immutable A2.6 report:

```powershell
python scripts\run_ashare_portfolio_validation.py `
  configs\execution\ashare_portfolio_validation_a4.local.toml `
  --verify-content
```

A completed A4 report remains `promotion_eligible=false` and leaves the 2025+ reserve untouched.

## Research UI

After producing an A2/A2.5 report:

```bash
python scripts/run_research_ui.py \
  --report reports/local_ashare_factor_research_a2p5.json \
  --feature-store .finagent/local-ashare-factor-a2p5/generated_features.sqlite \
  --trace .finagent/a2-agent-trace.jsonl
```

Open `http://localhost:8501`. The application visualizes development-versus-validation drift, rolling/yearly RankIC, quantiles, HAC/bootstrap and multiplicity evidence, ensemble composition, universe eligibility, Agent discovery rounds and JSONL traces. It is read-only and cannot rerun, mutate, promote or consume reserve evidence.

A4 NAV/order/cost visualization is a planned read-only extension. Until then, use the immutable A4 JSON report and JSONL execution ledger.

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Market data and local A-share datasets](docs/guides/data-sources.md)
- [Agent research workflow](docs/guides/agent-research.md)
- [A-share execution semantics](docs/guides/ashare-execution.md)
- [A-share execution-aware portfolio validation](docs/guides/ashare-portfolio-validation.md)
- [Research visualization](docs/guides/research-visualization.md)
- [Paper/shadow operations](docs/guides/paper-trading.md)
- [Testing and system acceptance](docs/testing/testing.md)
- [Architecture overview](docs/architecture/overview.md)
- [Architecture decisions](docs/architecture/decisions.md)
- [Roadmap](docs/development/roadmap.md)
- [Changelog](docs/development/changelog.md)
- [Risk register](docs/development/risks.md)

## Core boundary

```text
Provider / local data
        ↓
DataAdapter → ResearchDataset
        ↓
Agent hypothesis / generated feature
        ↓
Factor Quant / robust ResearchProgram
        ↓
Frozen multi-factor AlphaModel
        ↓
RiskModel → Portfolio Optimizer
        ↓
Market-specific target-to-executable-order rules
        ↓
Internal portfolio validation / reserve governance
        ↓
Human-approved paper/shadow operations
```

The Agent never owns positions, fills, risk limits, validation thresholds or broker state. The visualization layer never owns prompts, candidate generation, numerical evidence or lifecycle transitions.

## Research invariants

1. Features use only information available at `asof`.
2. Forward labels never define formation eligibility.
3. Failed and weak trials remain in the search denominator.
4. Frozen families are replayed without silent mutation.
5. Provider changes create new evidence identities; fallback is never silent.
6. Research prices and executable prices remain separate when corporate-action adjustment is required.
7. A software test pass is not evidence of persistent alpha or live-capital readiness.
8. Viewing validation evidence cannot turn the same window into clean validation for a modified ResearchProgram.
9. A4 cannot consume reserve, alter A2.6 weights/directions or bypass A3 execution rules.
10. Portfolio and execution evidence must reproduce through exact report and ledger identities.

## Data note

The local A-share database is treated as immutable vendor raw data. FinAgent normalizes units and time semantics but does not automatically trust undocumented vendor factors or claim survivorship-free coverage when delisting/list-status history is incomplete. Supplemental historical reference data is maintained separately from the raw vendor dataset.

## License and data rights

FinAgent code and third-party market data have separate licensing/usage constraints. Users are responsible for complying with each provider's terms and entitlements. Do not commit API keys or paid/raw datasets to the repository.
