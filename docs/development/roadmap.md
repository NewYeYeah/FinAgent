# Development Roadmap

This roadmap is intentionally short. Historical phase plans remain in Git history.

## Current baseline

Completed core capabilities:

- PIT numerical data contract and split isolation;
- deterministic alpha/risk/portfolio interfaces;
- nested validation, multiplicity control, DSR/PBO/Reality Check;
- bounded Agent-generated features and structured research memory;
- development-only Factor Quant feedback loop;
- deterministic multi-factor ensemble selection and model-level validation;
- sealed holdout lifecycle, research promotion and human-approved PAPER handoff;
- supervised internal paper/shadow operations;
- provider-configured Alpaca/AKShare/Tushare/HiThink data surfaces;
- local A-share daily and audited 1-minute Parquet adapters;
- frozen local A-share dataset identity, supplemental reference layer and Windows CI;
- A2 bounded daily A-share Factor Quant acceptance with deterministic/Agent discovery and exact replay.

## Current priority order

### P0 — A2.5 research correctness and stability

1. Use pre-split warm-up data for rolling universe filters; split starts must not create artificial zero-eligible sessions.
2. Keep system completion separate from the research verdict and report validation comparisons with development-frozen direction.
3. Report rolling/yearly RankIC stability, sign consistency, quantile monotonicity, coverage and turnover stability.
4. Use HAC and deterministic block-bootstrap inference, with Holm and BH adjustments over the complete candidate family.
5. Keep the 2025+ reserve untouched and do not promote A-share factors before A3 execution semantics.

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
