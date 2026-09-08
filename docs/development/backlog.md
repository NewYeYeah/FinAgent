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

The [accepted evidence record](../../configs/research/r4_matched_v3_accepted/README.md) is the canonical recording boundary for the independently reviewed `EVIDENCE_ACCEPTED` milestone. On 2026-09-07, a separately authorized real non-research `deepseek-v4-pro` probe passed the exact R4 typed action. ProviderAdmission verified; an ACCEPTED `r4-matched-v3` freeze was generated on executable main `edf7c1942b3acf97926390e45bd46c8ac9aacbee`, verified twice with the exact freeze ID, and passed 34/34 invariants. The real 2025 development source/evaluator admission was reused. No campaign was executed.

- ProviderAdmission: `r4-provider-admission-b78a63f33352d5a01bf2a4ca`; SHA256 `a785e02fcb52f546c1e4cf8a7a08a33e90644323d2cba8722937b99f599e6098`.
- ResearchAdmission: `r4-research-admission-61df92c1caacb80e369f538f`.
- CampaignFreeze: `r4-campaign-freeze-1d12fade12cb269d2b4da416`; full local SHA256 `c7ae0d5151f818b3dc190c223cf1663a5d547c1b4ef0c5771553dc50741e41c3`.
- Protocol: `r4-matched-protocol-191d511a8addb59081d261e8` / `r4-matched-v3`.
- Successful probe request SHA256: `88cfa12ac119059ae8b2295d92714160e61c40fa6c7b07c4af5faecc418f2a4c`; contract `r4-provider-probe-contract-fe25be88367262b64ee310ec`.

The full freeze remains immutable local authority because it embeds local input-binding paths; the repository contains only its sanitized attestation and exact ID/hash. That attestation cannot replace the execution freeze. Resolving admission does not establish Agent value, an AdaptiveStrategy, Alpha, PAPER, Live or R5 eligibility. The 2026-09-06 insufficient-receipt failure and earlier 2026-09-07 transport-success/strict-action failure remain historical facts. The historical [v2 blocked freeze](../../configs/research/r4_matched_v2_blocked/campaign_freeze.json) remains non-executable; no failure was erased or reinterpreted.

### B-006 — Accepted campaign freeze; matched comparison pending

**Affects:** R4  
**State:** OPEN

Controller/Console and all five deterministic allocators are implemented. The Primary campaign protocol proves the three-factor/minimum-size-two search space before applying its host gate: four admissible factor sets, five allocators and 20 reachable strategies. The deterministic Primary schedule exactly covers all four factor sets and is therefore the exhaustive deterministic oracle for this frozen search space. Primary Agent value is `research_efficiency_under_exhaustive_oracle`: three required Agent runs are assessed from host/ResearchLedger-derived portfolio-evaluation accounting, at least two must select an oracle-noninferior strategy while saving at least one of the four deterministic evaluations, and median saving across all three required runs must be at least one. Performance superiority over this exhausted finite space is not identifiable and is not the current support condition. Candidate viability/ranking remains independent and unchanged. Discovery remains exploratory, has no separately identified incremental-value claim, and cannot affect the Primary oracle/value/candidate.

The guarded real campaign execution operator is now implemented as a thin CLI over the existing `verify_campaign()` and `run_campaign()` application authority. A real `run` requires explicit research admission, provider admission, provider config, campaign directory and exact human-reviewed freeze ID; it exposes no protocol-version, research-rule, retry, force, reset or browser execution authority. Blocked and fixture freezes are not accepted as real execution authority, and an already committed campaign result replays without provider/evaluator calls. The accepted v3 freeze binds the already merged operator. Later executable changes invalidate that freeze and require a separate drift review.

The v1/v2 blocked artifacts, including v2 freeze `r4-campaign-freeze-51cdf9a05864e90ffe5310bd`, retain their historical superseded semantics and remain non-executable. B-005's provider admission blocker has been removed: an independently reviewed accepted `r4-matched-v3` freeze now exists, with `campaign_executed = false`. The guarded runner remains unexecuted. The real matched comparison is pending as a separately governed offline execution after a new explicit plan/authorization, never automatically on evidence PR merge. No Agent-value result, accepted AdaptiveStrategy or R4 terminal exists. Exposure timing, multi-year inputs, CopilotKit and query migration remain deferred.

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
