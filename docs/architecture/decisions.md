# Architecture Decisions

This document replaces the previous phase-by-phase ADR files with a concise list of decisions that remain active. Historical rationale remains available in Git history.

## D1 — Canonical numerical data contract

All research uses typed `ResearchDataset` / `ResearchSplit` panels with explicit universe, features, labels, split windows and data identity. Data adapters own provider/vendor normalization.

## D2 — Separate information and execution clocks

`event_time` and `available_at` are distinct. Historical execution may use only the configured executable price field at or before execution `asof`. Forward labels never become input features.

## D3 — Immutable experiment identity

Experiment identity includes dataset, code/factor artifacts, universe, parameters and seed. Existing experiment/family identity is idempotent but not mutable.

## D4 — Fixed search denominator and program budget

Every searched candidate, including weak and failed trials, remains in the effective family/program record. Agent automation does not grant a free multiplicity exemption.

## D5 — Agent proposal authority is bounded

Agent tools are finite and policy-controlled. LLM output cannot directly modify portfolio or broker state. Generated feature code must pass AST restrictions and sandbox execution.

## D6 — Development feedback is not outer/holdout evidence

Agent adaptive feedback is development-only. Outer validation, sealed holdout and operational outcomes are not fed back into the same adaptive search program.

## D7 — Model-level validation

Selected generated factors are calibrated through standard `AlphaModel` interfaces. Multi-factor ensembles are validated as real models through the same risk/portfolio/execution pipeline, not as post-hoc weighted return series.

## D8 — One-shot sealed holdout

Holdout specification and acceptance policy are registered before access. Post-access failure consumes the holdout; accepted/rejected evidence is terminal for that research program unless a new program is explicitly created.

## D9 — Human-approved operational handoff

Research promotion to `VALIDATED` is deterministic. Transition to operational PAPER and rebalance application require immutable requests plus explicit human approval.

## D10 — Structured evidence memory

SQLite-backed typed evidence is authoritative. Agent-visible memory is filtered by scope; sealed holdout evidence is not Agent-readable.

## D11 — Provider capability is explicit

A provider name is not a capability guarantee. Market/frequency/asset support and entitlements must be checked explicitly. Provider fallback is never silent.

## D12 — Local A-share vendor data is raw input, not truth by assertion

The local Parquet dataset is treated as immutable vendor raw data. FinAgent normalizes observed units and timestamp semantics but does not automatically certify seller claims such as complete delisting history or “no future data”.

Current A-share contract:

- `ts_code` is authoritative identity;
- daily volume is normalized from lots to shares;
- daily amount is normalized from thousand CNY to CNY;
- continuous 1-minute bars use bar-end timestamps and exclude the 09:30 opening-auction observation by default;
- executable/market OHLC remains raw;
- return features/labels use `raw close × adj_factor`;
- vendor basic data provides a candidate listing-date universe, not survivorship certification.

## D13 — Supplemental A-share status data is independent

Delisting, historical ST, suspension and similar externally collected status data must be stored and versioned separately from vendor raw Parquet. Missing supplemental coverage must remain visible in metadata/limitations.

## D14 — A-share historical research before realtime operations

Near-term A-share development focuses on local historical daily research and data quality. Realtime A-share feed acceptance and live brokerage are deferred until execution semantics and historical supplementary data are sufficiently mature.

## D15 — Platform support

Ubuntu remains the canonical shell/isolation environment; native Windows is a supported test environment. CI validates Windows Python 3.11 in addition to the Ubuntu Python matrix. POSIX-only shell-wrapper tests are skipped on Windows by design.
