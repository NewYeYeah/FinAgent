# Agent Research Workflow

This guide covers the currently supported Agent-assisted research path. The Agent proposes hypotheses and bounded feature code; deterministic code owns evaluation, portfolio construction and state changes.

## 1. Configure an LLM profile

Public routing is stored in `configs/llm.toml`. Credentials remain in the external secret store described in `getting-started.md`.

Check the selected profile without exposing a key:

```bash
python -c "from finagent.agents.providers import load_llm_profile; print(load_llm_profile('configs/llm.toml'))"
```

Run provider connectivity first:

```bash
python scripts/smoke_llm_provider.py configs/llm.toml --profile deepseek_official_v4_pro
```

## 2. US reference Agent study

Materialize validated Alpaca SIP data first. Then run:

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --report reports/us_etf_agent_market_research.json
```

Windows PowerShell:

```powershell
python scripts/run_agent_market_research.py `
  configs\markets\us_etf_agent_research.toml `
  --report reports\us_etf_agent_market_research.json
```

Before feature generation the runner verifies provider, market, symbols, bars digest and manifest identity.

## 3. Generated-feature boundary

Generated code follows:

```text
LLM response
→ FeatureSpec
→ AST validation
→ restricted subprocess
→ immutable GeneratedFeatureArtifact
→ PIT materialization
```

Generated code cannot perform file/network I/O, mutate portfolio state or call arbitrary Python APIs.

## 4. Factor discovery and ensemble research

The research layer supports cumulative development-only feedback and Factor Quant diagnostics, including:

- Pearson IC / RankIC;
- ICIR and explicit-horizon IC decay;
- quantile portfolios and long-short spread;
- turnover and coverage;
- factor-value correlation;
- deterministic redundancy-aware ensemble selection.

Formal validation keeps development feedback separate from outer/holdout evidence. An ensemble is evaluated as its own `AlphaModel`, not as a post-hoc weighted sum of single-factor returns.

## 5. Replay

Exact replay must reuse the frozen candidate family and must not call the LLM again:

```bash
python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_replay.json \
  --assert-replay
```

Replay failure is a research-governance failure, not a warning.

## 6. A-share Agent research

The local A-share Parquet adapter is now available to the common `ResearchDataset` contract. A-share Agent research should initially use bounded daily universes and historical-only validation. Do not start from full-market 1-minute panels or realtime trading.

Recommended first study:

```text
200–500 liquid equities
2018–2025 daily data
PIT-safe price/volume/market-value features
1d and 5d forward-return labels
Factor Quant → ensemble → formal validation
```

Seller-provided undocumented factor columns are not automatically approved. Prefer features that FinAgent recomputes from observed market fields until their PIT semantics are independently verified.

## 7. Evidence boundary

Agent-visible feedback may contain development diagnostics. It must not contain:

```text
outer-test results
sealed holdout evidence
promotion decisions
paper/live outcomes used for adaptive research
```

Human approval remains required for operational stage transitions.
