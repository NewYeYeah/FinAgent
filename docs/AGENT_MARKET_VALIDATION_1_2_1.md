# FinAgent 1.2.1 — US-first Agent Market Validation

FinAgent 1.2.1 hardens the 1.2 Agent → real-market path around **reproducibility and frozen-family cross-provider validation**. It does not add another model family or expand LLM authority.

## Why this patch exists

FinAgent 1.2.0 established an end-to-end Agent market study, but two distinct questions still needed explicit contracts:

1. can the same immutable data + same generated feature family reproduce the exact result without another LLM call;
2. can the same frozen family be evaluated on a second normalized provider dataset without silently changing the research question or consuming another search budget.

The 1.2.1 validation surface answers those questions while keeping provider disagreement as evidence rather than automatically reconciling it.

## Canonical US dataset pair

The reference universe is now fixed explicitly to:

```text
SPY / QQQ / IWM / DIA
```

Primary Alpaca materialization:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,us-market,llm-openai]'
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml
```

Free secondary AKShare materialization:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,cn-free]'
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml
```

Both configs use the same canonical symbols, date range and venue identities. Provider-specific AKShare symbols remain isolated in `ProviderSymbolMap`.

## First Agent study

Configure an OpenAI model available to the API account in:

```text
configs/markets/us_etf_agent_research.toml
```

Then run:

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

Before any LLM call, the runner now verifies all of the following:

```text
bars.csv digest == manifest.normalized_sha256
configured provider == manifest.provider
configured market == manifest.request.market
expected_symbols == manifest.request.symbols
expected_symbols == canonical symbols observed in bars.csv
```

This closes the possibility of a configuration that says SPY/QQQ/IWM/DIA while silently evaluating a different four-ETF dataset.

## Exact deterministic replay

The generated feature artifacts are already immutable in `generated_features.sqlite`. Reuse them rather than calling the LLM again:

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_replay.json \
  --assert-replay
```

`--frozen-family-report` loads the exact candidate digests, checks their immutable metadata and approved input fields, and skips feature generation entirely. Re-reserving the exact same program/family/task/candidate plan is idempotent in `SQLiteResearchProgramStore`, so replay does not double-spend family count, experiment count or alpha budget.

`--assert-replay` applies the strict replay policy:

```text
same task/program/family
same candidate family
same canonical universe
same outer-fold boundaries
same provider
a same data_version
100% selected-feature agreement
100% statistical-acceptance agreement
exact canonical AgentMarketResearchResult payload
```

Any difference fails closed.

## Frozen-family cross-provider validation

Run the exact Alpaca-generated feature family against the independently materialized AKShare dataset:

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --bars data/market/us_etf_akshare/bars.csv \
  --manifest data/market/us_etf_akshare/manifest.json \
  --provider akshare \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_research_akshare.json
```

The second study is allowed to have a different provider, `data_version`, selected feature and financial outcome. What is not allowed to change is the frozen research identity: task/program/family, candidate family, canonical universe and outer-fold chronology.

Validate the pair:

```bash
./scripts/finagent.sh python scripts/validate_agent_market_research.py \
  reports/us_etf_agent_market_research.json \
  reports/us_etf_agent_market_research_akshare.json \
  --mode cross_provider \
  --left-bars data/market/us_etf_alpaca/bars.csv \
  --right-bars data/market/us_etf_akshare/bars.csv \
  --output reports/us_etf_agent_cross_provider_validation.json \
  --store .finagent/agent-market-us/agent_market_validation.sqlite
```

Cross-provider validation requires an exact normalized calendar match through `ProviderDiffReport`. It reports selected-feature agreement, statistical-acceptance agreement and aggregate metric differences.

## No hidden financial acceptance thresholds

FinAgent does **not** define arbitrary default thresholds such as “Sharpe must differ by less than 0.2”. Cross-provider financial differences are evidence by default. If a research protocol pre-registers a tolerance, it can be supplied explicitly:

```bash
--min-selection-agreement 0.75 \
--min-acceptance-agreement 0.75 \
--metric-abs-limit sharpe=0.25 \
--metric-abs-limit max_drawdown=0.05
```

These thresholds become part of the deterministic validation identity and stored report.

## Evidence model

`AgentMarketValidationReport` records:

```text
validation mode and identity
left/right study/provider/data_version
structural identity checks
provider calendar agreement
common outer folds
selected-feature agreement
statistical-acceptance agreement
aggregate metric absolute differences
explicit policy violations
pass/fail
```

`SQLiteAgentMarketValidationStore` is append-only and idempotent for the same validation identity.

## Boundary

1.2.1 validates reproducibility and provider sensitivity; it does not prove that an LLM-discovered alpha is persistent or economically causal. Promotion-grade DSR/PBO/Reality Check/sealed-holdout governance remains separate. AKShare remains a best-effort secondary provider, not a production feed. A-share broad individual-equity research remains deferred until PIT universe, delisting, suspension, T+1, lot, price-limit, asymmetric-fee and richer corporate-action semantics are explicit.

## Focused verification

```bash
./scripts/run_tests.sh -q \
  tests/test_agent_market_research_v120.py \
  tests/test_agent_market_validation_v121.py
```

The release gate also runs the complete Python 3.11/3.12/3.13 test suite, Ruff, targeted mypy, coverage, package build and dependency consistency.
