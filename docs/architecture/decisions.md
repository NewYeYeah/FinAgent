# Active architecture decisions

Only decisions that remain active are kept here. Superseded rationale is available in Git history and release records.

## D1 — Bounded numerical research contract
`ResearchDataset` / `ResearchSplit` remain the canonical bounded compute representation. Large historical storage uses a separate out-of-core Data Plane.

## D2 — Separate information and execution clocks
`event_time` and `available_at` are distinct; future labels never become features and execution may use only information available at the configured `asof`.

## D3 — Immutable evidence identity
Changing dataset/source identity, candidate family, code artifact, universe, validation protocol or execution assumptions creates different evidence.

## D4 — Fixed search denominator
Every searched candidate remains in the effective denominator. Agent generation receives no multiplicity exemption.

## D5 — Bounded Agent authority
Agent code/hypotheses are proposals. Deterministic application/core services own validation, portfolio, execution and lifecycle authority.

## D6 — Independent evaluation remains independent
Development feedback is separate from outer/holdout/reserve or operational evidence. Evaluation data is not recycled into the same adaptive search program.

## D7 — Model validation is model-level
Multi-factor selections are frozen and validated through actual `AlphaModel`/risk/portfolio/execution paths, not by post-hoc weighted return narratives.

## D8 — Human-governed operational handoff
Research/Alpha acceptance does not self-authorize PAPER or live capital. Irreversible/external authority requires separately governed milestones.

## D9 — Provider capability is not adapter capability
External API capability, account entitlement and FinAgent implementation status are recorded separately and fail closed on gaps.

## D10 — No silent provider fallback
Cross-provider differences are reconciliation evidence. One provider does not silently overwrite another provider's authority.

## D11 — Source authority precedes large-scale U.S. ingestion
A U.S. minute source must have exact revision/provenance, schema, timestamp, adjustment/corporate-action and usage-rights decisions before becoming authoritative research data.

## D12 — Trading calendars are evidence
DST, holidays, half-days and sessions are materialized/versioned schedules. Static session clock strings are not sufficient for authoritative U.S. minute research.

## D13 — Typed labels
Intraday label identity includes metric, horizon, horizon unit, session-crossing policy and price basis.

## D14 — First U.S. research clock
The initial line uses 1-minute source/execution data and a canonical 15-minute signal clock, with 5/30-minute robustness checks. It is not an HFT project.

## D15 — Initial strategy is intraday-flat
The first execution-aware study closes before the session end, isolating overnight CFD financing/swap/accounting until intraday Alpha survives costs.

## D16 — Engineering universe and research universe are different
A present-day MT5 CFD intersection is valid for integration engineering but does not by itself support survivorship-unbiased market-wide Alpha claims.

## D17 — Agent value is empirical
Manual, programmatic and Agent candidate-generation arms are compared under fixed data, budgets, gates and costs. If Agent adds no measurable value, its role is reduced rather than expanded by default.

## D18 — Alpha gates downstream deployment
Broker execution/live product work beyond contract/replay infrastructure is gated by robust historical Alpha evidence; `NO_ROBUST_FACTOR_FAMILY` does not justify building a strategy deployment stack.

## D19 — Historical and broker execution remain separate
Synchronous deterministic `ExecutionVenue` remains historical. MT5 uses asynchronous command/event/query ports and broker/deal identities.

## D20 — Windows is authoritative for official MT5 integration
Core/research/replay remain cross-platform; the official `MetaTrader5` Python integration is treated as a Windows-native adapter and real broker acceptance runs locally against a demo terminal/account.

## D21 — Workbench remains source-neutral
React consumes evidence/state projections and does not contain provider-, MT5-, QMT- or broker-specific financial logic.

## D22 — Live Workbench is downstream
Realtime UI is built after event contracts, replay, state projection, read-only broker data, demo order lifecycle, reconciliation and recovery semantics are accepted.

## D23 — Documentation uses single authority
`docs/status.toml` owns current stage; `docs/development/current-plan.md` is the only active plan. Historical implementation detail belongs to Git/PR history and release snapshots.
