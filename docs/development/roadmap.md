# Development Roadmap

This roadmap is intentionally short. Historical phase plans remain in Git history.

## Current baseline

Completed core capabilities:

- PIT numerical data contract and split isolation;
- deterministic alpha/risk/portfolio interfaces;
- nested validation, multiplicity control, DSR/PBO/Reality Check;
- bounded Agent-generated features, repair/checkpoint resilience and structured research memory;
- development-only Factor Quant feedback loop;
- deterministic multi-factor ensemble selection and model-level validation;
- sealed holdout lifecycle, research promotion and human-approved PAPER handoff;
- supervised internal paper/shadow operations;
- provider-configured Alpaca/AKShare/Tushare/HiThink data surfaces;
- local A-share daily and audited 1-minute Parquet adapters;
- frozen local A-share dataset identity, supplemental reference layer and Windows CI;
- A2 bounded daily A-share Factor Quant acceptance with deterministic/Agent discovery and exact replay;
- A2.5 split-independent universe warm-up, signed validation verdicts, rolling/subperiod stability, HAC, block bootstrap and Holm/BH evidence;
- vendor-neutral Agent JSONL/OTLP tracing with Phoenix as an optional detailed span UI;
- read-only Streamlit/Plotly Research UI for reports, factors, ensembles, universes, Agent discovery and lineage.

## Completed priority gate — A2.5 correctness and visualization

The first real 150-stock study exposed three issues that are now closed:

1. rolling universe filters use hidden pre-split warm-up history rather than resetting at split boundaries;
2. workflow completion is separate from research validity and validation comparisons use development-frozen direction with signed deltas;
3. factor stability and dependence-aware inference are persisted and rendered through a read-only dashboard.

The Research UI does not modify prompts, candidates, reports, checkpoints, registries or ResearchProgram state. Phoenix remains a complementary low-level Agent trace viewer rather than an application framework dependency.

## Current priority order

### P1 — A2.6 robust A-share ResearchProgram

- retire the already observed 2022–2024 window as clean independent validation;
- define a new ResearchProgram where 2018–2024 is development/internal rolling or nested validation;
- keep 2025+ untouched until the program, factor family, selector and statistical gates are frozen;
- preregister stability-aware selection and rejection rules before reserve access;
- carry promising historical hypotheses into the new denominator as unconfirmed candidates, not accepted Alpha;
- compare deterministic baselines and Agent candidates under the same denominator and internal validation schedule;
- use the Research UI to diagnose instability, not to tune against untouched evidence.

### P1 — A3 A-share execution semantics

- define T+1 sellability and 100-share buy lots;
- model suspension and board/ST price-limit tradeability;
- implement commission, minimum commission, sell-side stamp duty and applicable transfer fees;
- distinguish target weights, desired orders and executable orders;
- only after these rules are tested, evaluate A-share portfolio-level economic returns.

### P1 — Data/research improvements

- improve historical universe with source-bound supplemental data where credible records exist;
- certify 5/15/30/60-minute timestamp conventions before enabling them;
- add chunked/out-of-core study orchestration if a 100–200 stock panel no longer suffices;
- keep Alpaca SIP as the US reference/regression dataset.

### P1.5 — Visualization continuation

The v1 dashboard is complete. Later work should be driven by real debugging needs:

- index and compare multiple immutable ResearchProgram reports;
- show report-to-report identity changes and candidate lineage;
- add downloadable chart/table evidence bundles;
- add trace-to-factor deep links when a stable Phoenix project/trace URL contract is available;
- keep every interactive research action as an explicit fork of a new ResearchProgram rather than an in-place mutation.

### P2 — Research-to-operation continuation

- connect A-share execution-valid ensembles to promotion/model identity;
- repeated PAPER sessions and operational evidence;
- external broker paper/shadow where useful;
- Provider Contract v2 entitlement/runtime capability snapshots.

### Deferred

A-share live-capital and realtime acceptance are not near-term milestones. Expensive realtime/delisting products are not required before historical research and execution semantics mature.

Advanced ML/RL/multi-agent extensions remain lower priority than factor quality, data correctness and execution realism.

## Development rule

```text
core functional loop
→ P0 numerical/data correctness
→ tests/CI
→ record bounded P1 risks
→ later hardening
```

Do not stop feature development for speculative P2 infrastructure, but do not proceed past errors that invalidate chronology, data identity, adaptive-search denominator, validation isolation or execution clocks.
