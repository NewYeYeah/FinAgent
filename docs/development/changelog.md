# Changelog

This file summarizes meaningful development milestones. Commit and pull-request history remains the detailed audit trail.

## 2026-08-27 — Local A-share data track

- added DuckDB-backed local A-share Parquet data layer;
- normalized daily and minute unit semantics;
- separated raw execution prices from adjustment-aware research returns;
- certified the observed 241-row 1-minute convention;
- added candidate security-master semantics and explicit survivorship limitations;
- added data certification CLI and Windows CI.

## 2026-08-27 — Agent × Factor Quant research core

- added development-only factor diagnostics and cumulative Agent feedback;
- added IC/RankIC, IC decay, quantile portfolio, turnover and redundancy diagnostics;
- added deterministic multi-factor ensemble selection;
- validated ensemble as a real AlphaModel against the full single-factor denominator.

## 2026-08-26 — Research governance hardening

- added immutable research program/family lifecycle;
- filtered Agent-visible evidence scopes;
- added atomic scoped result writes;
- added preregistered sealed-holdout contracts and one-shot evaluator;
- connected deterministic research promotion to model registry;
- added explicit human-approved `VALIDATED → PAPER` handoff.

## Earlier baseline

- canonical PIT `DataAdapter → ResearchDataset` interfaces;
- deterministic alpha, GARCH/OAS/PCA risk and portfolio optimizers;
- event-driven historical execution and transaction costs;
- bounded Agent tooling, LLM provider adapters and generated-feature sandbox;
- paper/shadow broker, reconciliation, approval and kill-switch primitives;
- provider-neutral real-market ingestion and deterministic replay/cross-provider evidence.

## Documentation policy

Stage-specific PHASE/DEVLOG/release notes were removed from the active `docs/` tree in favor of this condensed changelog, the current roadmap and architecture decision summary. Historical documents remain recoverable through Git history.
