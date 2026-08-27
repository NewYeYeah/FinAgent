# Changelog

This file summarizes meaningful development milestones. Commit and pull-request history remains the detailed audit trail.


## 2026-08-27 — A2.5 research correctness and stability

- added split-independent liquidity warm-up to remove artificial zero-eligible split starts;
- separated workflow completion from the factor research verdict;
- changed validation comparisons to development-frozen direction and signed deltas;
- added rolling/yearly RankIC stability, HAC inference, deterministic block bootstrap and family-wise Holm/BH adjustments;
- kept the A-share ensemble ineligible for promotion until execution semantics are certified.

## 2026-08-27 — Agent generation robustness and observability

- hardened DeepSeek/OpenAI-compatible calls with termination telemetry and bounded provider retries;
- aligned the generated-feature prompt with the actual restricted Python sandbox ABI;
- added bounded JSON/AST/sandbox candidate self-repair and bounded replacement;
- added scoped SQLite checkpoints so accepted logical candidate slots survive process restart without another LLM call;
- preserved hidden-reasoning privacy while recording reasoning-token counts, latency and finish status;
- added vendor-neutral JSONL/OTLP Agent traces and a lightweight Phoenix visualization path without coupling FinAgent to an Agent framework.

## 2026-08-27 — A2 bounded A-share factor research

- added a fixed pre-development candidate-universe selector for bounded 100–200 stock studies;
- added a PIT research-universe policy for listing age, ST state, price and rolling liquidity;
- added panel-native generated-feature materialization to avoid per-asset/session DuckDB queries;
- added deterministic baseline and multi-round Agent Factor Quant discovery modes;
- froze ensemble weights and factor directions on development evidence only;
- added independent factor-level validation, untouched reserve records and exact replay;
- kept A-share execution, promotion, holdout, PAPER and realtime outside the A2 acceptance claim.

## 2026-08-27 — A-share suspension/session semantics

- verified five zero-open/high/low daily anomalies as real suspension/no-trade placeholders rather than corrupted market prices;
- classified the strict vendor pattern `open=high=low=0, close=pre_close>0, vol=amount=0` as non-tradable while keeping all other invalid OHLC fail-closed;
- excluded suspension placeholders from `PriceBar` construction without modifying the frozen vendor source;
- changed A-share forward-return labels to a common panel-session clock so one-session labels cannot silently stretch across suspensions;
- kept legacy vendor identifiers quarantined rather than mapping them to modern securities.

## 2026-08-27 — A-share dataset freeze and supplemental reference layer

- added content-addressed/metadata frozen manifests for local A-share vendor data;
- added independently versioned supplemental delisting/ST/suspension files and source registry;
- kept supplemental status data separate from immutable vendor Parquet;
- added a historical-only local A-share system smoke through the canonical `ResearchDataset` interface;
- documented Yahoo Finance as a secondary/reference option rather than replacing Alpaca SIP.

## 2026-08-27 — Documentation consolidation

- replaced phase/version document sprawl with `guides/`, `testing/`, `architecture/` and `development/`;
- condensed active decisions, roadmap, changelog and risk register;
- rewrote README for the current A-share historical-research-first baseline.

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
