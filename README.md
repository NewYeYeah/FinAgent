# FinAgent

**FinAgent 1.2.1** is an auditable Agent-assisted quantitative research framework that keeps LLM proposal authority separate from deterministic data chronology, statistical governance, portfolio construction, execution simulation and operational state.

> **Release scope:** research + deterministic portfolio construction + real-market historical Agent studies + supervised paper/shadow operations. FinAgent does **not** include live broker credentials and does not claim live-capital readiness.

The current development path is deliberately **US-first**. A-share provider interfaces are implemented, but broad individual-stock research is deferred until point-in-time universe, delisting, suspension, T+1, lot-size, price-limit, asymmetric-fee and richer corporate-action semantics are explicit.

## What is new in 1.2.1

FinAgent 1.2.0 connected bounded Agent-generated features to real historical market data. Version 1.2.1 hardens that path around reproducibility and provider sensitivity:

```text
first Agent study
      ↓
immutable generated feature family
      ├──────── exact same data ────────> deterministic replay
      │                                  exact payload required
      │
      └──────── second provider ────────> frozen-family cross-provider study
                                         structural identity + calendar evidence
                                         financial differences reported explicitly
```

The new validation layer provides:

- exact replay without another LLM call;
- frozen candidate-family reconstruction from `SQLiteGeneratedFeatureStore`;
- provider/market/symbol contract checks before research begins;
- `AgentMarketValidationPolicy` and `AgentMarketValidationReport`;
- cross-provider `ProviderDiffReport` calendar evidence;
- append-only `SQLiteAgentMarketValidationStore`;
- optional, explicitly pre-registered metric tolerances instead of hidden default financial thresholds.

See [`docs/AGENT_MARKET_VALIDATION_1_2_1.md`](docs/AGENT_MARKET_VALIDATION_1_2_1.md).

---

## Canonical Agent → real-market pipeline

```text
immutable normalized market data
        ↓
ProviderCapabilities / ResearchDataRequirement
        ↓
ResearchProgram search + alpha budget
        ↓
AgentTask
        ↓
bounded LLM-generated feature family
        ↓
AST validation + restricted subprocess sandbox
        ↓
PIT feature materialization
        ↓
nested purged walk-forward
        ↓
inner-fold scoring + Holm family correction
        ↓
fold-local selected feature
        ↓
GeneratedFeatureAlphaModel
        ↓
GARCH risk + constrained mean-variance portfolio
        ↓
RiskGate
        ↓
next-open historical execution + transaction costs
        ↓
append-only AgentMarketResearchResult
        ↓
exact replay / frozen-family cross-provider validation
```

The LLM can propose hypotheses and bounded feature code. It cannot set portfolio weights, validation thresholds, risk limits, fills, broker state or operational approval.

### Statistical boundary

Within each outer fold, candidate selection uses **inner-validation evidence only**. Holm correction is applied across the frozen candidate family. Non-selected candidate outer evidence is not used to choose the winner.

The fold-local one-sided return diagnostic and Holm gate are **selection diagnostics**, not a replacement for promotion-grade Deflated Sharpe Ratio, PBO, Reality Check and sealed-holdout governance. `require_statistical_acceptance=true` can fail closed when no candidate survives the inner gate.

### Generated-feature alpha calibration

The selected immutable feature is converted to expected return by a deterministic calibration:

```text
forward_return = intercept + slope * generated_score + residual
```

Only trailing PIT windows are supplied to generated feature code. Forecast uncertainty is derived from fitted residual dispersion. This intentionally simple layer keeps the first Agent-to-market integration interpretable.

---

## US-first reference workflow

The reference universe is fixed to:

```text
SPY / QQQ / IWM / DIA
```

### 1. Materialize the primary Alpaca dataset

```bash
python -m pip install -e '.[dev,us-market,llm-openai]'
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_alpaca.toml
./scripts/finagent.sh python scripts/validate_market_data.py \
  data/market/us_etf_alpaca
```

### 2. Run the first Agent study

Set `OPENAI_API_KEY`, then replace the placeholder `llm_model` in `configs/markets/us_etf_agent_research.toml` with a model available to the API account.

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

Before any LLM call the CLI checks:

```text
bars.csv SHA-256 == manifest.normalized_sha256
configured provider == manifest.provider
configured market == manifest.request.market
expected_symbols == manifest.request.symbols
expected_symbols == canonical normalized-bar symbols
```

This prevents a research configuration from silently evaluating a different universe.

### 3. Exact deterministic replay

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_replay.json \
  --assert-replay
```

The exact generated feature digests are loaded from durable feature storage. No LLM request is made. Re-reserving the identical `(task, program, family, candidate family)` plan is idempotent and does not double-spend the program's search/alpha budget.

Replay requires the same provider, `data_version`, research identity, candidate family, universe, fold boundaries, selection decisions, statistical-acceptance decisions and canonical result payload.

### 4. Materialize free AKShare validation data

```bash
python -m pip install -e '.[dev,cn-free]'
./scripts/finagent.sh python scripts/pull_market_data.py \
  configs/markets/us_etf_agent_data_akshare.toml
```

AKShare is a free/best-effort secondary source. Provider-specific symbols such as `105.SPY` remain outside canonical `AssetId` identity.

### 5. Run the same frozen family on AKShare

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml \
  --bars data/market/us_etf_akshare/bars.csv \
  --manifest data/market/us_etf_akshare/manifest.json \
  --provider akshare \
  --frozen-family-report reports/us_etf_agent_market_research.json \
  --report reports/us_etf_agent_market_research_akshare.json
```

### 6. Validate cross-provider evidence

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

Cross-provider mode requires an exact normalized calendar match and the same frozen research identity. Financial differences are reported rather than silently reconciled. If a protocol needs acceptance thresholds, register them explicitly, for example:

```bash
--min-selection-agreement 0.75 \
--min-acceptance-agreement 0.75 \
--metric-abs-limit sharpe=0.25
```

FinAgent deliberately does not invent a default rule such as “Sharpe must be within 0.2”.

---

## Capability-driven market data

Provider suitability is expressed through `ProviderCapabilities` and `ResearchDataRequirement`, not inferred from a provider name.

Current conservative roles:

```text
US market
  Alpaca   -> primary historical / realtime-paper capable provider
  AKShare  -> free development and cross-provider validation

CN market
  HiThink  -> official A-share daily/snapshot primary candidate
  AKShare  -> free development and cross-provider validation
  Tushare  -> optional 15,000-point low-frequency/reference/fundamental source
```

Tushare's declaration intentionally excludes separately paid realtime, minute and US-market entitlements. HiThink is not certified for survivorship-bias-free broad A-share individual-equity studies while delisted-history coverage is incomplete.

Normalized provider evidence is materialized as:

```text
raw provider records
       ↓
normalized bars.csv
       ↓
quality_report.json
       ↓
SHA-256 manifest + stable data_version
```

Provider fallback is never silent. A different provider produces a different evidence identity.

General provider commands:

```bash
./scripts/finagent.sh python scripts/pull_market_data.py <market-config.toml>
./scripts/finagent.sh python scripts/validate_market_data.py <materialized-directory>
./scripts/finagent.sh python scripts/compare_market_providers.py \
  <left-bars.csv> <right-bars.csv> \
  --left-provider <name> --right-provider <name> \
  --output reports/provider_diff.json
```

---

## Quantitative research governance

FinAgent includes:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- explicit information and execution clocks;
- `(time, asset)` eligibility masks and PIT universe providers;
- purged/embargoed and nested walk-forward validation;
- immutable experiment specifications and fingerprints;
- fixed `ExperimentFamily` denominator;
- durable `ResearchProgram` cross-family family/experiment/alpha-spending budgets;
- Bonferroni, Holm and Benjamini-Hochberg correction;
- Deflated Sharpe Ratio;
- CSCV Probability of Backtest Overfitting;
- White-style Reality Check;
- candidate → paper/shadow/live model-stage governance;
- sealed-holdout one-time access contracts.

Failed and poor trials remain part of the effective search record.

### PIT formation contract

At formation time `t`:

```text
formation_t = PIT_eligible_t AND finite(feature_t)
```

Future label availability may not define the portfolio universe:

```text
NOT: PIT_eligible_t AND finite(feature_t) AND finite(forward_return_t)
```

If all formed assets at a period have not yet realized the forward label, the period is a horizon boundary and is omitted from realized evidence. If only some already-formed assets lose the label, evaluation fails by default until delisting/corporate-action semantics or prior PIT ineligibility explains the case.

---

## Governed Agent and generated code

Agent capability is finite and policy-driven. The Agent layer provides typed tasks, tool registries, policy-as-code authorization, durable audit, deterministic plans and budgets, provider-neutral LLM adapters and read-only structured memory access.

Generated feature code follows:

```text
LLMFeatureGenerator
 -> FeatureSpec
 -> AST validation
 -> restricted subprocess
 -> immutable GeneratedFeatureArtifact
 -> PIT materialization
 -> nested research evidence
```

Forbidden syntax/calls and source/AST limits are enforced before execution. Batch sandbox execution may amortize subprocess startup across independent PIT windows, but generated code is not given a future panel.

---

## Deterministic alpha, risk and portfolio construction

The deterministic layer includes:

- momentum and short-term reversal primitives;
- rolling volatility and volatility scaling;
- winsorization, cross-sectional z-score and deterministic neutralization;
- generated-feature calibration and alpha ensembles;
- GARCH volatility;
- OAS covariance and PCA statistical-factor risk;
- centralized portfolio constraints;
- equal-weight, minimum-variance, risk-parity and mean-variance construction;
- stress testing and drift-based rebalance logic;
- `RiskGate` before execution.

The LLM does not calculate or write final target weights.

### Turnover convention

For target-weight change `Δw`:

```text
gross_traded_weight = sum_i |Δw_i|
one_way_turnover    = 0.5 * gross_traded_weight
cost_fraction       = gross_traded_weight * bps / 10_000
```

---

## Execution capability boundary

The domain model can represent equities, ETFs, futures, FX, crypto, cash and other assets. Representation is not execution support.

The generic quantity planner supports only equity/ETF spot-like semantics. It fails closed for other asset classes because derivatives, FX and crypto require explicit multiplier, margin, settlement, funding and venue contracts.

The 1.2.x Agent reference path is narrower still: fixed-universe, single-currency ETFs.

---

## Supervised paper/shadow operations

The operational layer includes:

- trading-session calendars;
- durable `PaperBroker` orders, fills and account snapshots;
- `client_order_id` idempotency;
- partial fills and restart recovery;
- deterministic safety limits;
- durable kill switch;
- explicit request/application separation;
- human approval binding, expiry and revocation;
- reconciliation;
- split/cash-dividend baseline handling;
- shadow comparison and execution-cost calibration;
- operational sessions, drills, incidents and paper acceptance reports.

Core invariants:

```text
retry != second trade
process restart != financial-state reset
request != application
reconciliation failure -> safety state
restart does not clear a halted kill switch
```

A passing paper acceptance report means a configured observation window met its deterministic policy. It is not a live-capital certification.

---

## Structured evidence memory

Structured memory, not chat history, is the source of truth:

```text
hypothesis
 -> generated feature
 -> experiment / Agent market study
 -> result
 -> model
 -> portfolio-health snapshot
 -> paper order/fill
 -> reconciliation/shadow outcome
```

The project stores research hypotheses, revisions, similarity evidence, failures and lineage in SQLite-backed typed stores. Historical evidence may preserve or reduce a new search budget; it cannot automatically expand it.

For the Agent market path:

```text
SQLiteGeneratedFeatureStore
  immutable generated source artifacts

SQLiteResearchProgramStore
  cross-family search/alpha budget

SQLiteAgentMarketResearchStore
  end-to-end Agent + market study evidence

SQLiteAgentMarketValidationStore
  exact-replay and cross-provider validation evidence
```

These stores are separate from the paper broker ledger and operational evidence store.

---

## Installation

Requirements: Python 3.11+, NumPy and SciPy.

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Optional surfaces:

```bash
# OpenAI feature generation
python -m pip install -e '.[llm-openai]'

# Alpaca US market data
python -m pip install -e '.[us-market]'

# AKShare free CN/US development data
python -m pip install -e '.[cn-free]'

# Optional Tushare 15k-point reference/fundamental surface
python -m pip install -e '.[a-share]'
```

Keep credentials outside the repository. The core package and CI suite require no LLM or market-provider credentials.

### Environment isolation

For Ubuntu machines that also contain ROS 2 environments, use:

```bash
./scripts/finagent.sh --check
./scripts/finagent.sh python -m pytest -q
```

The wrapper validates the interpreter and strips ROS paths from the child process. See [`docs/ENVIRONMENT_ISOLATION.md`](docs/ENVIRONMENT_ISOLATION.md).

---

## Tests and release-quality gates

Run all tests:

```bash
./scripts/run_tests.sh -q
```

Focused suites:

```bash
./scripts/run_tests.sh -q tests/test_quant_core_hardening_v101.py
./scripts/run_tests.sh -q tests/test_provider_layer_us_first.py
./scripts/run_tests.sh -q tests/test_market_study_m1.py
./scripts/run_tests.sh -q tests/test_agent_market_research_v120.py
./scripts/run_tests.sh -q tests/test_agent_market_validation_v121.py
./scripts/run_tests.sh -q tests/test_operations_phase5.py
./scripts/run_tests.sh -q tests/test_operations_release_v1.py
```

GitHub Actions runs the full suite on Python 3.11, 3.12 and 3.13. The quality job runs project-wide critical Ruff checks, release-surface lint, real-market/provider lint, Agent-market/validation lint, targeted mypy, coverage, package build and dependency consistency.

A green software test suite controls implementation regressions. It does not establish alpha persistence.

---

## Safety and governance invariants

1. **Point-in-time research:** generated and hand-written features do not receive future observations.
2. **PIT universe membership:** future-return realization cannot define formation eligibility.
3. **Fixed research denominator:** failed/poor trials remain part of family evidence.
4. **Cross-family budget:** repeated families consume a durable program search/alpha budget.
5. **Fold-local selection:** outer-fold evidence cannot select its own candidate.
6. **Frozen replay identity:** exact replay does not regenerate features or silently change data/provider/universe.
7. **Cross-provider evidence:** secondary data differences are measured, not automatically reconciled.
8. **Finite Agent authority:** prompts are not authorization boundaries.
9. **Deterministic financial calculations:** calibration, risk, constraints and weights remain outside the LLM.
10. **Canonical turnover:** gross trading and one-way turnover are distinct quantities.
11. **Request/apply separation:** Supervisor requests do not mutate financial state.
12. **Human approval binding:** critical operational application is tied to immutable evidence.
13. **Idempotent orders:** retries do not create a second paper trade.
14. **Durable safety:** restart does not clear broker state or a halted kill switch.
15. **Reconciliation before trust:** critical mismatches become safety evidence.
16. **Provider capability before research:** unsupported market/PIT/delisting semantics fail closed.
17. **Execution capability is explicit:** non-equity assets do not inherit equity execution semantics.
18. **Evidence over selective memory:** failures, incidents and validation disagreements remain queryable.

---

## Repository layout

```text
src/finagent/
  domain/        typed financial/research contracts
  data/          PIT adapters, provider contracts and materialization
  models/alpha/  deterministic and generated-feature alpha
  models/risk/   covariance and risk models
  portfolio/     constraints, constructors, stress/rebalance
  research/      validation, registries, programs, Agent market evidence
  agents/        tools, policy, planning, LLM adapters, supervision
  sandbox/       restricted generated-feature execution
  operations/    paper broker, approvals, reconciliation, safety, evidence
  memory/        structured hypothesis/evidence lineage
  services/      deterministic portfolio/order services
scripts/         provider, research, validation and operational CLIs
configs/         reproducible market/research configurations
tests/           regression suites
docs/            ADRs, runbooks, roadmap and release notes
```

---

## Deliberate non-goals / deferred work

```text
live broker adapters and credentials
broad survivorship-bias-free A-share individual-equity Agent research
A-share T+1 / lot / price-limit / asymmetric-fee production semantics
futures/FX/crypto execution planners
multi-currency cash/FX accounting
full security-master/corporate-action accounting
institutional nonlinear market-impact calibration
high-frequency / Level-2 research
unrestricted autonomous code generation
multi-Agent trading authority
vector database as structured evidence source of truth
```

The immediate engineering priority after 1.2.1 is **measurement on real US data**: establish an immutable Alpaca reference dataset, run bounded Agent studies, replay them exactly, rerun the frozen family on AKShare, retain disagreements, and use observed defects to decide the next hardening work. A-share functionality should then be expanded as a separate market-semantics track rather than blocking core framework validation.

---

## Key documentation

- [`docs/AGENT_MARKET_VALIDATION_1_2_1.md`](docs/AGENT_MARKET_VALIDATION_1_2_1.md) — exact replay and frozen-family cross-provider validation;
- [`docs/AGENT_MARKET_RESEARCH_1_2.md`](docs/AGENT_MARKET_RESEARCH_1_2.md) — Agent → real-market research and statistical boundary;
- [`docs/DATA_PROVIDER_ARCHITECTURE_1_1_1.md`](docs/DATA_PROVIDER_ARCHITECTURE_1_1_1.md) — multi-provider roles and capability contracts;
- [`docs/REAL_MARKET_BACKTEST_M1.md`](docs/REAL_MARKET_BACKTEST_M1.md) — baseline fixed-universe historical market study;
- [`docs/QUANT_CORE_HARDENING_1_0_1.md`](docs/QUANT_CORE_HARDENING_1_0_1.md) — expert-review quantitative-core hardening;
- [`docs/RELEASE_1_0.md`](docs/RELEASE_1_0.md) — stable 1.0 scope;
- [`docs/RUNBOOK_PAPER_TRADING.md`](docs/RUNBOOK_PAPER_TRADING.md) — paper operations;
- [`docs/ROADMAP_REBASELINE.md`](docs/ROADMAP_REBASELINE.md) — post-1.0 conditional priorities.

## License / disclaimer

FinAgent is quantitative research and software infrastructure. It is not investment advice, does not guarantee profitability, and a passing historical, validation, paper or shadow result is not certification that a strategy is safe or profitable with live capital.
