# Active backlog, limitations and technical debt

This is the only active unresolved-work register. Items are removed or marked resolved when the underlying limitation is actually closed. Historical resolved items belong in [`history.md`](history.md) or Git history.

## Priority definitions

- **P0** — blocks the current/next research claim or a downstream authority transition.
- **P1** — material product/engineering debt that should be resolved in the named stage but does not block the current stage immediately.
- **P2** — intentionally deferred hardening or optional capability.

## P0

### B-002 — No independent confirmation evidence for post-R2 adaptive research

**Affects:** R4, R5  
**State:** OPEN

R2/R3 exposed substantial historical data to iterative research. A new adaptive strategy cannot use the same exposed periods as independent confirmation merely by renaming splits or using another provider copy. R5 needs prospective or otherwise demonstrably sealed evidence and a frozen evaluation protocol.

### B-003 — PIT/security-master limitation

**Affects:** R4, R5 claims  
**State:** OPEN

The 25-name U.S. EngineeringUniverse is current-symbol/survivorship conditioned. No authoritative point-in-time listing/delisting/security-master source is integrated. Limit claims to the admitted universe or add PIT lifecycle evidence before making market-wide statements.

### B-004 — CFD/equity cost and instrument mismatch

**Affects:** R4 economics, R5, PAPER  
**State:** OPEN

Historical listed-equity OHLCV and broker CFDs differ in contract/margin/session/volume/spread/financing semantics. R4 may use frozen broker-neutral cost scenarios; R5/PAPER must bind realistic broker-compatible assumptions and mapping evidence. A ticker match is not sufficient.

### B-005 — Trusted real-provider/evaluator admission for R4 Agent research

**Affects:** R4  
**State:** RESOLVED

The [accepted evidence record](../../configs/research/r4_matched_v3_accepted/README.md) is the canonical recording boundary for the independently reviewed `EVIDENCE_ACCEPTED` milestone. On 2026-09-07, a separately authorized real non-research `deepseek-v4-pro` probe passed the exact R4 typed action. ProviderAdmission verified; an ACCEPTED `r4-matched-v3` freeze was generated on executable main `edf7c1942b3acf97926390e45bd46c8ac9aacbee`, verified twice with the exact freeze ID, and passed 34/34 invariants. The real 2025 development source/evaluator admission was reused.

- ProviderAdmission: `r4-provider-admission-b78a63f33352d5a01bf2a4ca`; SHA256 `a785e02fcb52f546c1e4cf8a7a08a33e90644323d2cba8722937b99f599e6098`.
- ResearchAdmission: `r4-research-admission-61df92c1caacb80e369f538f`.
- CampaignFreeze: `r4-campaign-freeze-1d12fade12cb269d2b4da416`; full local SHA256 `c7ae0d5151f818b3dc190c223cf1663a5d547c1b4ef0c5771553dc50741e41c3`.
- Protocol: `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3`.
- Successful probe request SHA256: `88cfa12ac119059ae8b2295d92714160e61c40fa6c7b07c4af5faecc418f2a4c`; contract `r4-provider-probe-contract-fe25be88367262b64ee310ec`.

The full freeze remains immutable local authority because it embeds local input-binding paths; the repository contains only its sanitized attestation and exact ID/hash. Resolving admission did not establish Agent value, an AdaptiveStrategy, Alpha, PAPER, Live or R5 eligibility. The 2026-09-06 insufficient-receipt failure and earlier 2026-09-07 transport-success/strict-action failure remain historical facts.

### B-006 — Accepted R4 matched campaign comparison

**Affects:** R4  
**State:** RESOLVED

The previously authorized real `r4-matched-v3` campaign was executed exactly once and independently reviewed as `R4_RESULT_ACCEPTED`. The repository-safe [result record](../../configs/research/r4_matched_v3_result/README.md) references CampaignResult `r4-campaign-result-d32ec253d62eb4f9349896b0`, SHA256 `5f9cb2b687f5b5750255c4d91e6db273fdf2577a8ce71f33365cddf19789c8ac`, without reconstructing the immutable local result.

All seven required runs completed, with no automatic retry, rerun or provider fallback. Artifact integrity was 44/44 PASS. The deterministic host returned AgentValue `INCONCLUSIVE`, `deterministic_oracle = null` and terminal `NO_ADAPTIVE_CANDIDATE` with `candidate_id = null`.

The no-candidate terminal is completeness-driven, not a negative-return claim. The deterministic search structurally covered 20/20 factor-set/allocator strategies, but 0/20 had complete three-fold economic evidence: every deterministic strategy had `evaluable_folds = 0/3` and unavailable-session counts ranged from 39 to 64. Therefore no complete deterministic economic oracle existed, and median portfolio-evaluation saving of 3 is not positive Agent-value evidence. This accepted outcome is not `SYSTEM_FAILURE`.

B-006 closure records the matched campaign result only. It does not establish Alpha, accept PAPER, authorize Live, create an AdaptiveStrategy or make R5 eligible. A future research attempt must use a new versioned R4 cycle rather than rerun this accepted campaign because of its result.

### B-007 — PAPER is not end-to-end accepted

**Affects:** PAPER-TRADING  
**State:** OPEN

Realtime/PAPER/reconciliation/safety modules exist but have not been accepted as one target-broker demo/PAPER state machine under the future confirmed strategy. Do not equate module-level tests or one demo order with PAPER readiness.

## P1

### B-101 — Workbench human usability is not validated for the new product goal

**Affects:** R4 thin console, WORKBENCH-2  
**State:** OPEN

The pre-WORKBENCH-2 Agent baseline was audit-oriented. The first WORKBENCH-2 slice reorganized that surface around a research objective/session, Project → Thread → Run navigation, persisted Agent action/result/decision cards, research context, accepted negative terminal state and evidence/config identities. The second slice adds first-class persisted Experiments/comparison and a canonical Research Graph with unresolved-lineage handling. These are implementation milestones only: no fresh task-based human usability baseline has been recorded, so B-101 remains open until the stage's real-artifact human acceptance work is completed.

### B-102 — Custom Workbench query client duplicates mature server-state tooling

**Affects:** WORKBENCH-2  
**State:** OPEN

`workspace/src/workbench/query.tsx` still implements cache/stale/in-flight/invalidation behavior for untouched surfaces. The Agent Workspace first slice migrated its touched Agent/Research reads, and the Experiments/Research Graph slice also uses `@tanstack/react-query` for list/detail/comparison/graph/cycle server-state plus SSE-driven graph invalidation. No new custom-query consumer is added. Other Workbench consumers remain on the existing wrapper, so B-102 is only partially progressed and remains OPEN; continue migration only when those surfaces are touched for product work.

### B-103 — Legacy Streamlit Research UI

**Affects:** repository maintenance  
**State:** DEFERRED/FREEZE

`apps/research_ui.py` is legacy. Do not add features. Keep only while required by compatibility/release tests; remove when no retained acceptance path depends on it.

### B-104 — Historical A-share frozen tests and old planning references

**Affects:** CI compatibility  
**State:** OPEN/CONTAINED

Some historical release-reproduction tests/configs reference planning material removed from the active tree. They are release-history tests, not active U.S. research gates. Keep them in dedicated historical workflows or update their ownership without recreating obsolete active docs.

### B-105 — Timezone-explicit regression portability

**Affects:** U.S. minute compatibility tests  
**State:** OPEN

Some older U.S. D2 assertions depended on local timestamp rendering. Normalize test expectations to explicit UTC/aware semantics when those tests are touched; do not reinterpret accepted data evidence.

### B-106 — Historical source rights remain limited

**Affects:** distribution/public hosting  
**State:** OPEN/LIMITED

The admitted U.S. minute dataset does not declare a complete redistribution license chain. Local non-redistributed research is the accepted scope. Do not redistribute or claim stronger public provenance without a separate rights review.

### B-107 — Transaction-cost model uncertainty

**Affects:** R4, R5  
**State:** OPEN

The R3 primary 5 bps model is a research scenario, not a measured universal execution cost. Preserve cost sensitivity and bind stronger broker-compatible cost evidence before R5/PAPER economic claims.

### B-108 — R4 economic-support completeness / unavailable sessions

**Affects:** future versioned R4 research  
**State:** OPEN

The accepted `r4-matched-v3` campaign structurally covered 20 deterministic strategies, but none had complete three-fold economic evidence. Every deterministic strategy had `evaluable_folds = 0/3`, with unavailable-session counts from 39 to 64; all 30 Primary candidate rows were incomplete under the frozen Candidate completeness rule. This prevented construction of a deterministic economic oracle and made Agent-value assessment `INCONCLUSIVE`.

The root cause is not established by the accepted evidence. Diagnose the unavailable-session/economic-support mechanism before a future versioned R4 cycle relies on comparable economic evidence. Do not pre-classify it as a source or evaluator bug without evidence.

### B-109 — R4 Agent discovery/tool-use reliability

**Affects:** future versioned R4 research  
**State:** OPEN

The accepted campaign retained 62 rejected Agent action attempts. Discovery-03 consumed 48 provider calls and ended `SLOT_ATTEMPTS_EXHAUSTED`; 44 actions were rejected in that run, including 43 `candidate_not_proposed_in_run` rejections. ProviderAdmission remained valid: the limitation is observed autonomous tool-use reliability under the admitted contract, not provider admission.

This does not invalidate the accepted R4 terminal and does not block WORKBENCH-2. Address it before claiming stronger autonomous discovery capability in a future R4 cycle; do not weaken the tool contract merely to improve rejection statistics.

## P2 / intentionally deferred

### B-201 — Tick/LOB microstructure research

**Affects:** none in active roadmap  
**State:** INTENTIONALLY_DEFERRED

Historical Tick/LOB data is not currently available with sufficient authority. Do not build queue/OFI/order-book research around synthetic proxies. Revisit only after an authoritative source is obtained.

### B-202 — Online learning / concept-drift framework

**Affects:** future PAPER optimization  
**State:** DEFERRED

Do not integrate River or another online-learning framework during R4 solely because it is available. First prove that the frozen/adaptive batch policy needs true online parameter updates under PAPER observations.

### B-203 — FINOS Perspective / high-volume live tables

**Affects:** future PAPER UI  
**State:** DEFERRED

Use current TanStack Table until real order/event volumes show a performance need.

### B-204 — Alternative data / news / text factors

**Affects:** future research  
**State:** DEFERRED

The current research program intentionally focuses on minute OHLCV plus Agent-driven adaptive allocation. Text/news/macro inputs can become a separate research program after R4/R5 rather than widening the first adaptive experiment.

### B-205 — Live-capital HA/SLO/incident automation

**Affects:** LIVE-CAPITAL  
**State:** DEFERRED

High availability, network partition procedures, SLOs, credential hardening and jurisdiction/account-specific controls belong to live-capital acceptance, not exploratory research.
