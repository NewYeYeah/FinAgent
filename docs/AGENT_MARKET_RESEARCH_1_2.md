# FinAgent 1.2 — Agent → Real Market Research

FinAgent 1.2 connects the bounded LLM feature-generation surface to the real-market historical study stack. The initial production path is deliberately **US ETF first** so the research framework can be exercised on comparatively accessible market data before adding A-share-specific trading and survivorship semantics.

## Scope

The canonical 1.2 pipeline is:

```text
immutable normalized market data
        ↓
ResearchDataRequirement / ProviderCapabilities
        ↓
ResearchProgram budget reservation
        ↓
AgentTask
        ↓
bounded LLM-generated feature family
        ↓
AST validation + restricted sandbox
        ↓
PIT feature materialization
        ↓
nested purged walk-forward
        ↓
inner-fold candidate scoring
        ↓
Holm family correction
        ↓
fold-local candidate selection
        ↓
GeneratedFeatureAlphaModel calibration
        ↓
GARCH risk
        ↓
constrained mean-variance portfolio
        ↓
RiskGate
        ↓
next-open historical execution + costs
        ↓
append-only AgentMarketResearchResult evidence
```

The LLM never receives portfolio-writing, broker, validation-threshold, risk-limit, or financial-state authority.

## Statistical boundary

Candidate generation is bounded before the family is evaluated. `ResearchProgram` charges the family count, experiment count and alpha spend durably. Poor/failed candidates therefore remain part of the effective search denominator.

Within each outer fold, candidate selection uses **inner-validation evidence only**. A one-sided mean-return diagnostic p-value is calculated from inner net-return observations and Holm correction is applied across the frozen candidate family. The outer result used for the final portfolio report belongs to the candidate selected from inner evidence.

The Holm gate is an **admission/selection diagnostic**, not a replacement for the existing promotion-grade statistical stack. Overlapping inner windows mean its simple t-test should not be interpreted as an independent-sample proof. Formal model promotion can still require the existing family-level DSR, PBO, Reality Check and sealed-holdout governance.

`require_statistical_acceptance = true` makes the historical portfolio path fail closed for an outer fold when no candidate survives the inner Holm gate. With the default `false`, the runner may produce a diagnostic portfolio for the best inner candidate, but `statistically_accepted=false` remains explicit evidence and must not be reported as a validated alpha claim.

## Generated-feature alpha calibration

`GeneratedFeatureAlphaModel` converts one immutable `GeneratedFeatureArtifact` into a deterministic `AlphaForecast`.

For training observations it evaluates the generated feature only on trailing PIT windows and fits:

```text
forward_return = intercept + slope * generated_score + residual
```

A small optional ridge term regularizes the slope. The fitted residual standard deviation becomes the forecast uncertainty. Prediction again passes only the trailing PIT window to the restricted feature sandbox; generated code never receives the future panel.

This calibration layer is intentionally simple. It establishes a clean contract between Agent-discovered factor scores and the deterministic portfolio engine without introducing a second opaque ML model during the first real-market integration milestone.

## US-first reference study

The reference configuration is:

```text
configs/markets/us_etf_agent_research.toml
```

It is intended for a fixed ETF universe such as SPY / QQQ / IWM / DIA. Alpaca remains the primary US historical provider; an AKShare-normalized dataset may be substituted for free development/cross-provider testing if its manifest passes the same immutable-data checks.

The CLI never downloads data silently. First materialize and validate a market dataset using the existing provider pipeline, then run Agent research against the immutable `bars.csv` + `manifest.json` pair.

Install the US and OpenAI optional dependencies:

```bash
./scripts/finagent.sh python -m pip install -e '.[dev,us-market,llm-openai]'
```

Prepare Alpaca historical data using the existing US market config, then edit `llm_model` in `configs/markets/us_etf_agent_research.toml` to a model available to the API account and provide `OPENAI_API_KEY`.

Run:

```bash
./scripts/finagent.sh python scripts/run_agent_market_research.py \
  configs/markets/us_etf_agent_research.toml
```

The runner verifies that the normalized CSV SHA-256 digest still matches the manifest before any LLM call or research evaluation.

## Persistent evidence

The default state directory contains separate stores:

```text
generated_features.sqlite
research_programs.sqlite
agent_market_research.sqlite
```

The first stores immutable generated source artifacts; the second owns cross-family search/alpha budget; the third stores the final end-to-end Agent/market study result. Re-registering the exact same study is idempotent, while conflicting reuse of the same study identity fails.

The JSON result records:

```text
study/task/program/family identity
provider and data_version
canonical universe
all generated candidate identities/hypotheses
per-outer-fold selected candidate
inner scores and raw/adjusted p-values
whether the selected candidate passed the Holm gate
selected signal outer metrics
selected portfolio outer metrics
aggregate OOS portfolio metrics
```

Non-selected candidate outer-fold evidence is not exposed in `AgentMarketResearchResult` and is never used to select the winner.

## What 1.2 does not certify

FinAgent 1.2 does **not** establish that an LLM-discovered factor is economically persistent merely because a historical study finishes. It also does not add live broker authority, dynamic individual-equity universes, survivorship-bias-free A-share coverage, derivatives/FX/crypto execution, or high-frequency/Level-2 semantics.

A-share adapters remain available from the 1.1.1 multi-provider layer, but broad A-share individual-equity Agent research should wait for explicit delisting, suspension, T+1, lot-size, price-limit, asymmetric-fee and corporate-action semantics.

## Focused verification

```bash
./scripts/run_tests.sh -q tests/test_agent_market_research_v120.py
```

The full release gate also runs the complete Python 3.11/3.12/3.13 suite, critical Ruff checks, the dedicated 1.2 research surface lint, targeted mypy, coverage, package build and dependency consistency.
