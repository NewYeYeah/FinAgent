# Development Roadmap

This roadmap is intentionally short. Historical phase plans are preserved in Git history rather than duplicated as active documents.

## Current baseline

Completed core capabilities:

- PIT numerical data contract and split isolation;
- deterministic alpha/risk/portfolio interfaces;
- nested validation, multiplicity control, DSR/PBO/Reality Check;
- bounded Agent-generated features and structured research memory;
- development-only Factor Quant feedback loop;
- deterministic multi-factor ensemble selection and formal model-level validation;
- sealed holdout lifecycle, research promotion and human-approved PAPER handoff;
- supervised internal paper/shadow operations;
- Alpaca/AKShare/Tushare/HiThink provider configuration surfaces;
- local A-share daily and audited 1-minute Parquet adapters;
- native Windows CI.

## Current priority order

### P0 — Historical research usability

1. Freeze the current local A-share dataset identity.
2. Maintain incomplete status data as independent supplemental files.
3. Add a canonical local A-share system test through `ResearchDataset` and Factor Quant interfaces.
4. Run bounded daily A-share cross-sectional research on real local data.
5. Keep Alpaca SIP as the US reference/regression dataset.

### P1 — A-share research semantics

- improve historical universe using supplemental delisting/listing data where credible sources exist;
- add historical ST/suspension/price-limit datasets when affordable/reliable;
- define A-share T+1, lot size, asymmetric fee and price-limit execution rules;
- certify 5/15/30/60-minute timestamp conventions before enabling research use;
- introduce chunked/out-of-core panel materialization for larger universes.

### P2 — Research-to-operation continuation

- ensemble identity/promotion integration where still incomplete;
- repeated PAPER sessions and operational evidence;
- external broker paper/shadow where useful;
- Provider Contract v2 entitlement/runtime capability snapshots.

### Deferred

A-share live-capital or realtime acceptance is not a near-term milestone. Expensive realtime/delisting products are not required before the historical research and execution model are mature.

Advanced ML/RL/multi-agent extensions remain lower priority than data correctness, factor research quality and execution realism.

## Development rule

Priority remains:

```text
core functional loop
→ P0 numerical/data correctness
→ tests/CI
→ record bounded P1 risks
→ later hardening
```

Do not stop feature development for speculative P2 infrastructure, but do not proceed past errors that invalidate research chronology, data identity, search denominator or execution clocks.
