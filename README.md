# FinAgent

FinAgent is an auditable Agent-assisted quantitative research framework. LLMs propose hypotheses and bounded feature code; deterministic components own data chronology, factor evaluation, portfolio construction, statistical validation, execution simulation and operational state.

## Current scope

The current development baseline supports:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- Agent-generated features with AST validation and restricted execution;
- factor diagnostics including IC, RankIC, IC decay, quantile portfolios and turnover;
- deterministic multi-factor ensemble construction;
- nested walk-forward validation, multiplicity control, DSR, PBO and Reality Check;
- supervised paper/shadow operations;
- US market ingestion through Alpaca and best-effort AKShare validation;
- local A-share Parquet research through DuckDB-backed adapters.

The current market priority is **A-share historical research first**, with **Alpaca SIP as the US reference/regression path**. A-share live-capital or realtime acceptance is intentionally deferred until historical research, execution semantics and data supplementation are mature.

## Quick start

Python 3.11+ is required.

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest -q
```

Optional dependencies:

```bash
python -m pip install -e ".[llm]"          # DeepSeek / SiliconFlow / OpenAI transport
python -m pip install -e ".[us-market]"    # Alpaca
python -m pip install -e ".[cn-free]"      # AKShare
python -m pip install -e ".[a-share]"      # Tushare
python -m pip install -e ".[local-parquet]"# local A-share Parquet / DuckDB
```

For Windows and Ubuntu setup, credential configuration and provider-specific commands, see the guides below.

## Documentation

- [Getting started](docs/guides/getting-started.md)
- [Market data and local A-share datasets](docs/guides/data-sources.md)
- [Agent research workflow](docs/guides/agent-research.md)
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
Factor Quant diagnostics
        ↓
Formal experiment family
        ↓
Multi-factor AlphaModel
        ↓
RiskModel → Portfolio Optimizer → RiskGate
        ↓
Holdout / promotion governance
        ↓
Human-approved paper/shadow operations
```

The Agent never owns positions, fills, risk limits, validation thresholds or broker state.

## Research invariants

1. Features use only information available at `asof`.
2. Forward labels never define formation eligibility.
3. Failed and weak trials remain in the search denominator.
4. Frozen families are replayed without silent mutation.
5. Provider changes create new evidence identities; fallback is never silent.
6. Research prices and executable prices remain separate when corporate-action adjustment is required.
7. A software test pass is not evidence of persistent alpha or live-capital readiness.

## Data note

The local A-share database is treated as immutable vendor raw data. FinAgent normalizes units and time semantics but does not automatically trust undocumented vendor factors or claim survivorship-free coverage when delisting/list-status history is incomplete. Supplemental historical reference data is maintained separately from the raw vendor dataset.

## License and data rights

FinAgent code and third-party market data have separate licensing/usage constraints. Users are responsible for complying with each provider's terms and entitlements. Do not commit API keys or paid/raw datasets to the repository.
