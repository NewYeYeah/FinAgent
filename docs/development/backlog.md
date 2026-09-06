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
**State:** OPEN

The R3 v2 runtime has bounded typed dispatch and budget accounting, but offline/runtime correctness is not a general sandbox or source-authentication mechanism. Before large real-model R4 campaigns, bind an admitted provider transport and development evaluator/source lineage. Reuse the existing runtime; do not create a third runtime generation.

### B-006 — Deterministic factor allocators and adaptive comparison remain open

**Affects:** R4  
**State:** OPEN

The first R4 slice implements train-only GMM MarketState and a FactorLibrary with conditional development metrics. The four-state R2 regime remains an executable benchmark. Next implement the declared non-Agent allocators and an adaptive portfolio comparison with fold-local fitting/selection before claiming adaptive value. The current single-window diagnostics do not establish that GMM adds information or that an allocator is viable.

### B-007 — PAPER is not end-to-end accepted

**Affects:** PAPER-TRADING  
**State:** OPEN

Realtime/PAPER/reconciliation/safety modules exist but have not been accepted as one target-broker demo/PAPER state machine under the future confirmed strategy. Do not equate module-level tests or one demo order with PAPER readiness.

## P1

### B-101 — Workbench human usability is not validated for the new product goal

**Affects:** R4 thin console, WORKBENCH-2  
**State:** OPEN

A-share Historical v1 browser automation passed, but the current Agent page remains audit-oriented and no fresh human usability baseline has been recorded for Agent-adaptive research. Before major redesign, run the existing Workbench with real historical artifacts and record concrete friction. Workbench 2.0 must include human task-based acceptance, not only Playwright.

### B-102 — Custom Workbench query client duplicates mature server-state tooling

**Affects:** WORKBENCH-2  
**State:** OPEN

`workspace/src/workbench/query.tsx` implements cache/stale/in-flight/invalidation behavior. Migrate touched Workbench 2.0 surfaces to TanStack Query instead of expanding the custom client. Do not create a standalone migration project unless actual integration demands it.

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
