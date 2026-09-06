# Active architecture and product decisions

Only decisions that still constrain future work belong here. Superseded rationale is available in Git/PR history.

## D1 — One current status and one current plan

`docs/status.toml` owns current stage/authority. `docs/development/current-plan.md` owns the end-to-end active roadmap. Detailed stage work lives in `docs/development/stages/`; history/backlog are separate. Do not create parallel roadmaps/versioned plans.

## D2 — Agent has research agency, not truth authority

Agent may choose development research direction, factor sets, allocators and experiment budget within typed policy. Deterministic code owns calculations, frozen statistical gates, final evidence, portfolio/account truth, reconciliation and safety.

## D3 — Adaptive search and independent confirmation are separate programs

R4 is allowed to adapt to development feedback and must retain every relevant trial. R5 freezes the complete adaptive algorithm and evaluates genuinely independent/prospective evidence. R5 outcomes cannot be fed back into the same frozen spec and remain independent.

## D4 — Causal chronology is non-negotiable

Market observations, model fitting, normalizers, market-state inference, labels and execution obey explicit clocks/session semantics. Future information never enters a live/development feature through preprocessing or smoothing.

## D5 — Factor discovery and factor allocation are separate layers

FinAgent does not require one globally permanent factor. R4 uses a FactorLibrary plus MarketState/allocator layer. Market-timing/exposure control is evaluated at strategy/allocation level rather than forced through a cross-sectional RankIC-only gate.

## D6 — Bounded FactorGraph remains the Agent factor language

Reuse the existing typed FactorGraph/shared-DAG engine. Do not grant unrestricted model-generated Python/SQL/shell execution for ordinary factor research. Extend the DSL only when a concrete admitted mechanism cannot be expressed otherwise.

## D7 — Trial accounting survives failure

Failed, invalid, repaired and duplicate Agent/programmatic attempts remain part of the development research record where they consumed search budget. Agent generation receives no multiplicity/accounting exemption.

## D8 — Evidence intensity follows stage purpose

Exploration needs causal reproducibility and complete trial accounting; independent confirmation needs sealed/preregistered evidence; operations need broker-state/recovery/safety evidence. Do not reproduce production-grade content-addressing for every exploratory intermediate unless it protects a real correctness boundary.

## D9 — Reuse before new infrastructure

Evaluate existing FinAgent implementation first, then mature open source, then a thin adapter. Write a bespoke subsystem only when project-specific authority/semantics cannot be delegated. A framework migration requires demonstrated value.

## D10 — No Tick/LOB research without authoritative data

The active roadmap is minute-OHLCV based. Do not synthesize order-flow/queue/LOB evidence from bars. Microstructure research is deferred until an authoritative finer-grained dataset exists.

## D11 — Historical and broker instruments remain separate identities

Listed equity history and an MT5 CFD may share ticker text while differing in contract size, margin, spread, financing, sessions and volume semantics. Mapping/reconciliation is explicit.

## D12 — Existing realtime substrate is reused

`src/finagent/realtime` already provides canonical event/replay/source/projection infrastructure. PAPER work integrates and validates it rather than creating another RT-R0/R1/R2 architecture.

## D13 — Realtime UI is developed with PAPER state

No standalone mock Live terminal. Market/Strategy/Portfolio/Execution/System Health panels are added as vertical slices that consume canonical PAPER projections. React never calls the broker SDK directly.

## D14 — Existing Workbench analytical stack is retained

Use ECharts for analytical/statistical charts, React Flow for research/evidence graphs and TanStack Table for structured data. Workbench 2.0 migrates touched server-state code toward TanStack Query instead of expanding the custom query client.

AG-UI is the preferred first protocol candidate for Agent↔Workbench event/tool/state streaming. CopilotKit is optional and only adopted if it embeds without replacing FinAgent's Agent runtime/authority model.

TradingView Lightweight Charts is reserved for financial price/order/fill interaction when real PAPER state exists.

## D15 — Browser is presentation/control intent, not financial calculation authority

The browser may select/filter and perform clearly labeled presentation aggregation. It does not reconstruct missing Alpha, statistical inference, broker/account truth or safety state.

## D16 — Research value includes negative results

`NO_ROBUST_FACTOR_FAMILY`, `NO_ADAPTIVE_CANDIDATE`, `REJECTED` and `INSUFFICIENT_INDEPENDENT_EVIDENCE` are valid terminals. Thresholds and data boundaries are not weakened to manufacture progression.

## D17 — PR boundaries follow coherent capability

Prefer vertical slices. Avoid long chains of infrastructure-only PRs and unrelated mega-PRs. PR count is not a project KPI; reviewability, rollback boundaries and functional quality decide the split.

## D18 — Workbench 2.0 is research-first

The existing Agent page is primarily an audit projection. The next product generation makes Agent objective→tool→experiment→decision interaction first-class while keeping evidence links available as the underlying audit trail.

## D19 — Live capital is separately human governed

No research/PAPER/Agent state self-promotes into live authority. Live acceptance binds a specific strategy, broker/server/account, capital/risk envelope, safety/recovery procedure and operator responsibility.

## D20 — Market time and adaptive research time are distinct

`PREDECLARED_STATIC` preserves historical factor-definition admission. `ADAPTIVE_RETROSPECTIVE` permits a factor proposed now to be frozen and tested on already-exposed historical development folds. Never falsify `FactorRegistration.created_at`. Immutable proposal/definition/visible-history identities bind what existed before that factor's own evaluation request and result. All historical signals, model fits and performance releases still obey market availability. R5 requires the complete frozen strategy to predate its independent/prospective evidence; an R4 development candidate alone is not R5 eligible.

## D21 — Controller execution, calculation, budget and audit remain separate

R4 extends the existing R3 capability runtime, not its provider/accounting loop. Host adapters own deterministic calculations, ResearchLedger owns resource admission and trial denominator, and AgentAuditStore owns explicit product-visible action history. Required audit failures or ledger/audit disagreement stop further actions. The browser submits objectives through the existing local Control Plane and reads audit projections. The first Controller admits only the five frozen allocator configurations and runs all mandatory comparators.
