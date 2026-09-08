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

## D22 — Matched campaign design predates every research result

Provider admission binds an exact profile/model/endpoint, effective generation config, verified integer usage and a public tariff identity; credentials never enter evidence. A non-research probe is not Agent feedback. The provider-admission probe must exercise the same public typed R4 action contract that the real capability runtime exposes: its context carries `capability_set = r4_manifest()`, a frozen exact `PROBE_ACTION`, no market/factor/PnL/objective/campaign evidence, and `research_history = false`. `provider_binding()` cryptographically binds that probe contract through `probe_contract_digest`; changing the R4 manifest, exact probe action or probe-context semantics changes future provider-admission identity. The probe still requires the exact target action: a valid but different action is `probe_contract_mismatch`, not acceptance.

Strict-action diagnostics are themselves an authority boundary. `ContractError` carries fixed safe codes; provider admission may persist only an explicit allowlisted code (or a closed generic contract code) as `strict_action_error_code`. Raw provider/model output, raw exception text, hidden reasoning, credentials and prompts are never copied into failure evidence. A complete verified transport receipt may be retained when strict action decoding fails, because transport/model/usage evidence and typed-action admission are separate facts. Transport success does not create `ProviderAdmission`; exact action conformance still must pass.

Freeze provider/source/folds/seed definitions/tools/budgets/calculation code/dependencies and host terminal rules before any campaign output. Missing admission produces a blocked artifact, never an accepted freeze. Any subsequent semantic change creates a new version and ID; old artifacts remain intact. Protocol-version authority is code-owned in the protocol/application boundary, not the CLI or browser. The corrected current generation is `r4-matched-v3`, with `r4-matched-v3-blocked-provider` for a newly recorded provider-blocked design; historical v1/v2 labels and their old semantics remain immutable and cannot be reused for a new corrected artifact. Test-only v3 variants may be generated only through fixture paths. Primary research slots are matched independently of LLM overhead, and deterministic execution has no artificial token charges. Fixed-pool Agent selection and exploratory discovery remain distinguishable. Agent finalization is a recommendation; deterministic host gates separately assess Agent value and candidate viability. No runtime Agent role or Alpha/PAPER/live authority follows automatically.

The real campaign execution operator is deliberately separate from freeze creation. `scripts/r4_campaign.py run` requires the exact accepted freeze ID and explicit research/provider/config bindings, delegates verification to `verify_campaign()` and execution/replay to `run_campaign()`, and exposes no protocol-version, budget, factor, cost, fallback, retry, force, reset or browser authority. A blocked or fixture freeze cannot authorize the real operator. `campaign_implementation()` binds the operator itself, so executable changes after an accepted freeze invalidate that freeze rather than being tolerated. The intended human-governed sequence is admission → freeze → verify → independent review of the exact freeze ID → STOP → separately authorized campaign run; freeze, review or evidence PR merge must not automatically execute research.

Accepted evidence publication preserves the original execution identity. When a full freeze embeds local ResearchAdmission/input-binding filesystem paths, it remains immutable local authority and is not redistributed. GitHub stores byte-preserved repository-safe provider/probe evidence and a sanitized attestation of the exact full-freeze ID/SHA256, protocol/admission identities, frozen executable baseline and authority flags. The attestation uses a distinct schema, is not a replacement freeze and grants no separate execution authority. Never edit or regenerate the original freeze just to remove paths for publication. The [accepted v3 record](../../configs/research/r4_matched_v3_accepted/README.md) follows this rule; historical failures remain intact.

For the frozen three-factor Primary space, the FactorSet contract admits exactly four sets and every portfolio evaluation runs all five allocators. The deterministic schedule covers those four sets exactly, so it is an exhaustive oracle over all 20 Primary factor-set/allocator strategies. Protocol construction must derive and prove this coverage; if a future deterministic schedule does not cover the full Agent-admissible space, it may not claim exhaustive-oracle semantics. Because performance superiority over an exhaustive oracle is structurally unidentifiable here, Primary Agent value is research efficiency under oracle noninferiority: the host compares stable factor-set/allocator strategy keys using the frozen economic ordering and measures portfolio-evaluation savings from ResearchLedger/campaign accounting. Agent-reported or presentation-layer resource counts have no gate authority. Candidate viability and ranking remain an independent host gate, and exploratory discovery cannot affect the Primary oracle/value/candidate.
