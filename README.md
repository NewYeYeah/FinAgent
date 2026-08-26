# FinAgent

**FinAgent 1.2.0** connects bounded Agent-generated quantitative hypotheses to immutable real-market historical data, nested statistical selection, deterministic alpha/risk/portfolio construction, and next-open historical execution. It remains a typed framework for agent-assisted quantitative research, deterministic portfolio construction, supervised paper/shadow trading, and end-to-end evidence lineage.

> **Release scope:** FinAgent 1.2.0 is a **research + portfolio + historical-market Agent study + paper/shadow** release. It does not include live broker credentials and does not claim live-capital readiness.

Version 1.2.0 builds on the 1.0.1 expert-review hardening, the 1.1.0 real-market ETF study path, and the 1.1.1 capability-driven multi-provider data layer. The development and validation reference path is now US-first; A-share provider interfaces remain available while market-specific individual-equity semantics are deliberately deferred.

## Agent → Real Market Research (1.2)

The canonical 1.2 path is:

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
AST validation + restricted sandbox
        ↓
PIT materialization
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
next-open historical execution + costs
        ↓
append-only AgentMarketResearchResult evidence
```

The LLM generates bounded feature code only. Deterministic infrastructure owns data chronology, research budgets, candidate selection, alpha calibration, risk, weights and execution.

The reference US ETF configuration is:

```text
configs/markets/us_etf_agent_research.toml
```

After materializing and validating an Alpaca or compatible normalized US ETF dataset, install the optional dependencies, set `OPENAI_API_KEY`, replace the placeholder `llm_model` with a model available to the API account, and run:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,us-market,llm-openai]'
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

The CLI verifies the `bars.csv` SHA-256 digest against the immutable manifest before any LLM call. Candidate generation is bounded before evaluation. Within each outer fold only inner-validation evidence may determine the selected candidate; Holm correction is applied across the frozen candidate family. `require_statistical_acceptance=true` can fail closed when no candidate passes this inner gate.

This fold-local Holm check is an admission/selection diagnostic, not a replacement for promotion-grade DSR, PBO, Reality Check and sealed-holdout governance. See [`docs/AGENT_MARKET_RESEARCH_1_2.md`](docs/AGENT_MARKET_RESEARCH_1_2.md).

## Capability-driven market data (1.1.1)

FinAgent does not infer research suitability from a provider name. The data layer exposes machine-readable `ProviderCapabilities`, `ResearchDataRequirement`, explicit `ProviderSymbolMap` mappings and `ProviderDiffReport` cross-source evidence.

Current provider roles are intentionally conservative:

```text
US market
  Alpaca   -> primary historical / realtime-paper capable provider
  AKShare  -> free development and cross-provider validation

CN market
  HiThink  -> official A-share daily/snapshot primary candidate
  AKShare  -> free development and cross-provider validation
  Tushare  -> optional 15,000-point low-frequency/reference/fundamental source
```

The Tushare capability declaration does **not** claim separately paid realtime, minute or US-market entitlements. HiThink is not certified for survivorship-bias-free broad individual-equity research while delisted-history coverage is incomplete. No provider fallback is silent: changing the actual source changes the evidence manifest and research identity.

Use the existing provider CLI to materialize/validate data and compare already-normalized sources:

```bash
./scripts/finagent.sh python scripts/pull_market_data.py configs/markets/us_etf_smoke.toml
./scripts/finagent.sh python scripts/validate_market_data.py data/market/us_etf_alpaca
./scripts/finagent.sh python scripts/compare_market_providers.py \
  data/market/us_etf_alpaca/bars.csv \
  data/market/us_etf_akshare_smoke/bars.csv \
  --left-provider alpaca \
  --right-provider akshare \
  --output reports/provider_diff_us_etf.json
```

## Real-market ETF study (1.1 baseline)

The 1.1 historical-market path records raw provider responses, normalized PIT bars, quality evidence, content hashes and a stable data version before running nested purged walk-forward evaluation with next-open execution and cost sensitivity.

```bash
# US primary study
./scripts/finagent.sh python -m pip install -e '.[dev,us-market]'
./scripts/finagent.sh python scripts/pull_market_data.py configs/markets/us_etf_smoke.toml
./scripts/finagent.sh python scripts/run_market_backtest.py configs/markets/us_etf_smoke.toml

# Free CN/US development coverage
./scripts/finagent.sh python -m pip install -e '.[dev,cn-free]'
```

The legacy Tushare A-share smoke path remains available for users who already have suitable access, but Tushare is no longer a strategic default market-data dependency. See [`docs/REAL_MARKET_BACKTEST_M1.md`](docs/REAL_MARKET_BACKTEST_M1.md) and [`docs/DATA_PROVIDER_ARCHITECTURE_1_1_1.md`](docs/DATA_PROVIDER_ARCHITECTURE_1_1_1.md).

## Why FinAgent exists

Many “trading Agent” demos optimize the visible Agent loop while leaving the difficult financial-engineering questions implicit: point-in-time data, repeated hypothesis testing, portfolio constraints, state recovery, duplicate orders, reconciliation, approval boundaries, and the distinction between a model proposing an action and financial state actually changing.

FinAgent treats those questions as first-class contracts.

```text
LLM / Agent
  hypothesis, bounded feature code, research plans,
  explanations, memory queries, supervision requests
                |
                v
Deterministic control plane
  PIT validation, experiment/program governance,
  policy checks, memory/lineage, human approval
                |
                v
Deterministic financial-state layer
  alpha, risk, constraints, portfolio weights,
  RiskGate, paper execution, reconciliation, kill switch
                |
                v
Operational evidence layer
  sessions, drills, incidents, acceptance reports
```

The central rule is:

```text
Agent proposes.
Deterministic code validates and calculates.
Human approval authorizes critical operational mutation.
Financial state is never owned by the LLM runtime.
```

---

## Quantitative research and statistical governance

FinAgent includes:

- point-in-time `ResearchDataset` / `ResearchSplit` contracts;
- explicit information and execution clocks;
- `(time, asset)` eligibility masks and PIT universe providers;
- purged/embargoed and nested walk-forward validation;
- immutable experiment specifications and fingerprints;
- `ExperimentFamily` lifecycle and fixed family denominator;
- `ResearchProgram` cross-family search and alpha-spending budget;
- Bonferroni, Holm and Benjamini-Hochberg multiple-testing correction;
- Deflated Sharpe Ratio;
- CSCV Probability of Backtest Overfitting;
- White-style Reality Check;
- model-stage governance from candidate through paper/shadow/live lifecycle states.

Failed trials remain part of the research record; they are not silently removed because their results were inconvenient.

### PIT formation contract

For generated-feature research, the formation set at time `t` is:

```text
formation_t = PIT_eligible_t AND finite(feature_t)
```

It is not allowed to depend on the future label:

```text
NOT: PIT_eligible_t AND finite(feature_t) AND finite(forward_return_t)
```

If **all** formed assets at a period have an unrealized forward label, the period is treated as a horizon boundary and omitted from realized-performance evidence. If only part of an already-formed portfolio is missing realized return, evaluation fails by default and requires explicit delisting/corporate-action semantics or PIT ineligibility known before formation.

---

## Governed Agent research

The Agent layer provides typed tasks/run context, a finite `ToolRegistry`, policy-as-code authorization, immutable/durable audit, deterministic research plans and budgets, provider-neutral LLM planning, optional OpenAI Responses integration, telemetry and read-only structured memory tools.

An Agent cannot directly set portfolio weights, change validation thresholds, bypass `RiskGate`, select broker fills, erase failed experiments, or rewrite historical evidence.

`ResearchProgram` adds a higher-level ledger for repeated search across multiple families. Reservations are durable; a failed reserved attempt still consumes search/alpha budget because it was part of the effective hypothesis search.

In 1.2, `LLMMarketFeatureCandidateGenerator` turns one `AgentTask` into a bounded immutable feature family. Duplicate feature IDs/digests fail before research execution.

---

## Generated-feature research and calibrated alpha

FinAgent can ask an LLM to propose bounded feature code, but generated code is not executed as arbitrary application code.

```text
LLMFeatureGenerator
 -> FeatureSpec
 -> AST validation
 -> restricted subprocess execution
 -> immutable GeneratedFeatureArtifact
 -> PIT materialization + eligibility
 -> IC / ICIR / turnover / net-return evidence
```

Each feature value is materialized using an `asof` historical window. `run_batch()` may process multiple independent PIT windows in one restricted subprocess to reduce startup overhead, but generated code does not receive a complete future panel.

`GeneratedFeatureAlphaModel` provides the 1.2 bridge into deterministic portfolios. It evaluates only trailing PIT windows and fits a simple pooled linear calibration:

```text
forward_return = intercept + slope * generated_score + residual
```

The residual standard deviation becomes forecast uncertainty. This intentionally simple calibration avoids adding a second opaque ML layer while validating the Agent-to-market integration.

---

## Alpha, risk and portfolio construction

The deterministic portfolio layer includes canonical momentum/reversal primitives, rolling volatility/volatility scaling, winsorization/z-score, deterministic neutralization, cross-sectional calibration and ensembles, OAS covariance, PCA statistical-factor risk, centralized constraints, equal-weight/minimum-variance/risk-parity/mean-variance construction, stress testing and drift-based rebalancing.

The LLM does not calculate or directly write target weights.

### Turnover convention

For target-weight change `Δw`:

```text
gross_traded_weight = sum_i |Δw_i|
one_way_turnover    = 0.5 * gross_traded_weight
```

Linear cost at `c` basis points is:

```text
cost_fraction = gross_traded_weight * c / 10_000
```

---

## Execution capability boundary

The domain model can represent `EQUITY`, `ETF`, `FUTURE`, `FX`, `CRYPTO`, `CASH` and `OTHER` assets. Representation is not execution support.

The generic planner intentionally supports only `EQUITY` and `ETF` spot-like quantity semantics. It fails closed for other asset types because correct execution may require contract multipliers, margin, settlement, FX conversion, funding, lot rules and venue-specific behavior.

The 1.2 Agent real-market reference pipeline is even narrower: fixed-universe, single-currency ETFs. This is deliberate while the end-to-end research chronology is validated.

---

## Low-permission portfolio supervision

`PortfolioHealthMonitor` converts deterministic portfolio evidence into an immutable health snapshot. The Supervisor can inspect health, benchmarks, stress and rebalance decisions and create bounded requests such as `request_operating_policy`, `request_rebalance` and `request_human_review`.

These requests return `mutation_performed=false`. Critical changes require human approval outside the Agent runtime.

---

## Durable paper/shadow operations

The paper operational layer includes trading-session calendars, persistent `PaperBroker` state, `client_order_id` idempotency, partial fills, restart recovery, trading safety, durable kill switch, explicit human approval, reconciliation, baseline split/cash-dividend handling, shadow comparison and execution-cost calibration.

Important invariants:

```text
retry != second trade
process restart != financial-state reset
request != application
reconciliation failure -> safety state
restart does not clear a halted kill switch
```

---

## Structured evidence memory

FinAgent stores structured research memory rather than using free-form chat history as the source of truth.

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

Historical evidence may preserve or reduce a new research budget; it cannot automatically expand that budget.

The 1.2 `SQLiteAgentMarketResearchStore` adds an append-only end-to-end result store for generated candidate identities, provider/data version, inner selection evidence, selected outer evidence and aggregate portfolio outcomes.

---

## Operational journal and paper acceptance

The operational evidence layer includes `SQLiteOperationalEvidenceStore`, approval expiry/revocation, sessions, drills, incidents, operational metric snapshots and deterministic paper-acceptance reports.

A passing acceptance report means the selected paper/shadow observation period passed the configured deterministic policy. It is **not** a live-capital certification.

---

## Installation

Requirements: Python 3.11+, NumPy and SciPy.

```bash
git clone https://github.com/NewYeYeah/FinAgent.git
cd FinAgent
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Optional surfaces:

```bash
# OpenAI Agent generation
python -m pip install -e ".[llm-openai]"

# US Alpaca data
python -m pip install -e ".[us-market]"

# AKShare free CN/US development data
python -m pip install -e ".[cn-free]"

# Optional Tushare reference/fundamental surface
python -m pip install -e ".[a-share]"
```

Keep credentials outside the repository. The core package and test suite do not require LLM or market-provider credentials.

---

## Environment-isolated command entrypoint

On Ubuntu systems that also use ROS 2, use the single wrapper:

```bash
./scripts/finagent.sh --check
./scripts/finagent.sh
```

It validates the interpreter and removes ROS paths from the child environment. It can also execute individual commands:

```bash
./scripts/finagent.sh python -m pytest -q
./scripts/finagent.sh ruff check src tests --select E9,F63,F7,F82
./scripts/finagent.sh python -m build
```

See [`docs/ENVIRONMENT_ISOLATION.md`](docs/ENVIRONMENT_ISOLATION.md).

---

## Tests and release-quality gates

Run the full regression suite:

```bash
./scripts/run_tests.sh -q
```

Focused suites:

```bash
./scripts/run_tests.sh -q tests/test_quant_core_hardening_v101.py
./scripts/run_tests.sh -q tests/test_provider_layer_us_first.py
./scripts/run_tests.sh -q tests/test_market_study_m1.py
./scripts/run_tests.sh -q tests/test_agent_market_research_v120.py
./scripts/run_tests.sh -q tests/test_operations_phase5.py
./scripts/run_tests.sh -q tests/test_operations_release_v1.py
```

GitHub Actions runs the full tests on Python 3.11, 3.12 and 3.13. The quality job runs project-wide critical Ruff checks, hardened release-surface lint, real-market/provider lint, the dedicated 1.2 Agent-market surface lint, targeted mypy, coverage, package build and dependency consistency.

A green CI suite controls software regressions; it does not establish alpha persistence or replace sustained operational evidence.

---

## Research workflow

A typical governed cycle is:

```text
1. create/revise hypothesis or AgentTask
2. query structured memory for duplicates/failures
3. freeze ResearchProgram budget
4. materialize and validate immutable provider data
5. generate a bounded feature family
6. validate generated feature source
7. materialize features point-in-time
8. run nested inner selection and multiplicity controls
9. evaluate only the fold-selected feature as the portfolio alpha source
10. calibrate alpha and risk
11. construct constrained portfolio
12. execute on the later historical clock with costs
13. retain Agent/market study evidence
14. apply promotion-grade statistical governance before stronger claims
15. if appropriate, continue through portfolio supervision and paper/shadow observation
```

Memory does not grant additional experiment budget because previous results looked good.

---

## Persistence layout

FinAgent intentionally separates state classes:

```text
SQLiteResearchRegistry
  experiments, runs, results, models

SQLiteResearchProgramStore
  cross-family research budgets and sealed holdout access

SQLiteAgentAuditStore / SQLiteAgentPlanStore / SQLiteLLMCallStore
  Agent policy, plans and provider telemetry

SQLiteGeneratedFeatureStore
  generated feature source lineage

SQLiteGeneratedFeatureResearchStore
  feature IC/return evidence

SQLiteAgentMarketResearchStore
  end-to-end Agent + market study evidence

SQLitePortfolioSupervisionStore
  portfolio-health evidence

SQLitePaperBrokerStore
  paper orders, fills, account snapshots, kill switch, applications

SQLiteResearchMemoryStore
  hypothesis revisions, lineage and failures

SQLiteOperationalEvidenceStore
  approval validity, sessions, drills, incidents, acceptance reports
```

A memory table is not the broker ledger, and a broker ledger is not the experiment registry.

---

## Safety and governance invariants

1. **Point-in-time research:** generated and hand-written features must not receive future observations.
2. **PIT universe membership:** future-return realization cannot define formation eligibility.
3. **Fixed research denominator:** failed/poor trials remain part of family evidence.
4. **Cross-family search budget:** repeated families are charged to a durable `ResearchProgram` ledger.
5. **Fold-local selection:** outer-fold evidence cannot choose the candidate being evaluated in that outer fold.
6. **Finite Agent authority:** tools and policy determine capability; prompts are not authorization boundaries.
7. **Deterministic financial calculations:** calibration/risk/constraints/weights remain outside the LLM.
8. **Canonical turnover:** gross trading and one-way turnover are distinct quantities.
9. **Request/apply separation:** Supervisor requests do not mutate financial state.
10. **Human approval binding:** operational application is tied to immutable evidence and approval identity.
11. **Idempotent paper orders:** duplicate retries do not create a second trade.
12. **Durable safety state:** process restart does not clear the paper account or halted kill switch.
13. **Reconciliation before trust:** critical mismatch becomes safety evidence and trips the kill switch.
14. **Provider capability before research:** a source that lacks required market/PIT/delisting semantics fails closed.
15. **Execution capability is explicit:** the generic planner does not pretend derivatives/FX/crypto use equity semantics.
16. **Evidence instead of selective memory:** failures, drills and incidents remain queryable.

---

## Repository layout

```text
src/finagent/
  domain/        typed financial/research contracts
  data/          PIT adapters, provider contracts and dataset construction
  models/alpha/  deterministic and generated-feature alpha models
  models/risk/   covariance and risk models
  portfolio/     constraints, constructors, stress/rebalance
  research/      registries, validation, programs and Agent-market evidence
  agents/        Agent contracts, planning, tools, LLM adapters, supervision
  sandbox/       restricted generated-feature execution
  operations/    paper broker, approvals, reconciliation, safety, evidence
  memory/        structured hypothesis/evidence lineage
  services/      deterministic portfolio/order services

tests/           regression suite
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

The next engineering priority after 1.2 should be **real-data observation and reproducibility**: run the US ETF Agent study on immutable Alpaca data, cross-check market evidence with AKShare where appropriate, inspect selected hypotheses and failure modes, then harden observed defects before expanding the search space or market scope.

---

## Documentation

Key documents:

- `docs/AGENT_MARKET_RESEARCH_1_2.md` — US-first Agent → real-market runbook and statistical boundary;
- `docs/DATA_PROVIDER_ARCHITECTURE_1_1_1.md` — provider roles/capabilities and US-first data plan;
- `docs/REAL_MARKET_BACKTEST_M1.md` — fixed-universe ETF historical study runbook;
- `docs/QUANT_CORE_HARDENING_1_0_1.md` — expert-review findings and quantitative-core fixes;
- `docs/RELEASE_1_0.md` — 1.0/1.0.1 scope and release criteria;
- `docs/DEVLOG.md` — chronological development history;
- `docs/RUNBOOK_PAPER_TRADING.md` — paper operational runbook;
- ADR files under `docs/` — architectural decisions and invariants.

## License / disclaimer

FinAgent is quantitative research and software infrastructure. It is not investment advice, does not guarantee profitability, and a passing historical or paper/shadow result is not a certification that a strategy or system is safe for live capital.
