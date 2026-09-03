---
name: finagent-project
summary: Learn, inspect, implement, review, and document FinAgent without confusing historical plans, current authority, research evidence, or broker authority.
---

# FinAgent Project Learning & Documentation Skill

Use this skill when first entering the FinAgent repository, reviewing an unfamiliar subsystem, planning or implementing a stage, or changing project documentation.

## 1. Mission

Build an accurate model of **what FinAgent is now**, **what has actually been accepted**, **what is merely planned**, and **which artifact owns each claim** before proposing code or documentation changes.

FinAgent deliberately separates:

```text
platform/system acceptance
research/Alpha acceptance
portfolio/economic acceptance
PAPER/demo acceptance
live-capital acceptance
```

Never collapse these into one status.

## 2. Source-of-truth hierarchy

Read in this order unless the task has a narrower explicit source:

1. `docs/status.toml` — only authority for current stage, stage status, next stage and release-state pointer.
2. `docs/development/current-plan.md` — current scope, dependencies, non-goals and Exit Gates.
3. `docs/architecture/overview.md` — current system decomposition and authority boundaries.
4. `docs/architecture/decisions.md` — active design decisions only.
5. `docs/testing/strategy.md` — accepted test layers and what each gate proves.
6. relevant `docs/guides/*.md` — current user/operator workflow.
7. relevant `docs/releases/*.md` — what a frozen historical release proved.
8. source code + tests — implementation truth for concrete behavior.
9. `docs/development/changelog.md`, Git commits and PRs — implementation history and rationale.

Historical Git/PR content may explain how the project arrived here, but must not override active status/plan/architecture documents.

## 3. Ten-minute onboarding protocol

Before reviewing or changing code:

### Step A — establish repository identity

Record the branch/commit being inspected. Do not discuss “current main” from an old SHA.

### Step B — establish project state

Read `docs/status.toml` and state:

```text
planning_revision
current_stage
current_stage_status
next_stage
relevant release status
```

### Step C — read only the current planning authority

Open `docs/development/current-plan.md`. Locate the active stage and its predecessor/successor. Extract:

```text
Goal
Required work
Non-goals
Dependencies
Exit Gate
```

Do not read old versioned plans first; they are historical material in Git.

### Step D — build the architecture map

Read `architecture/overview.md` and relevant decisions. Identify which layer owns the task:

```text
domain
Data Plane / adapter
research
Agent
portfolio / historical execution
application/runtime
realtime/broker
Evidence/Workbench
```

### Step E — inspect implementation and tests together

For every material behavior claim, inspect both the implementation and its acceptance/regression tests. A Markdown claim without code/test evidence is not sufficient to declare implementation complete.

### Step F — classify evidence authority

When reading Workbench/research output, explicitly distinguish:

```text
authoritative
persisted deterministic derived
derived presentation
diagnostic
unavailable_not_inferred
```

### Step G — report uncertainty

If source code, tests and current docs disagree, do not silently reconcile them. Report the inconsistency and treat executable code/test behavior as implementation truth while `docs/status.toml` remains stage truth.

## 4. Task routing

| Task/question | Read first |
| --- | --- |
| What should be developed next? | `status.toml` → `current-plan.md` |
| Why is a stage ordered this way? | `current-plan.md` → `architecture/decisions.md` |
| How does FinAgent work? | `architecture/overview.md` |
| What may the Agent do? | `architecture/decisions.md` + Agent source/tests |
| How should I run/use something? | relevant `guides/` document |
| How may FX be used during MT5/U.S. development? | `architecture/decisions.md` D24 → `guides/mt5-continuous-smoke-and-deferred-us-i0.md` |
| Which realtime tasks actually require the U.S. session, and how should an active-session run be prepared? | `guides/realtime-development-validation.md` → relevant stage guide/source |
| Which source should algorithms/realtime development use, and how must delayed feeds be handled? | `guides/realtime-source-development-model.md` → RT/MT5 source + algorithm-runner tests |
| What does a test failure mean? | `testing/strategy.md` + failing test + runtime source |
| What did Historical v1.0 prove? | `releases/ashare-historical-v1.md` |
| Why was code changed historically? | aggregate changelog → Git/PR |
| Is a capability really implemented? | source + tests; provider capability declarations alone are insufficient |

## 5. Code-reading rules specific to FinAgent

1. **PIT chronology is non-negotiable.** Preserve the distinction between `event_time` and `available_at`; forward labels are never input features.
2. **Identity is part of correctness.** Dataset, program, factor, portfolio, evidence, broker and release identities must not be reconstructed ad hoc.
3. **No silent provider fallback.** Provider capability, FinAgent adapter capability and broker capability are different facts.
4. **Research data and broker instruments are not interchangeable.** A listed U.S. equity and an MT5 CFD with a similar ticker are different instrument authorities.
5. **Historical execution is not broker execution.** Do not force asynchronous broker lifecycle into the synchronous historical `ExecutionVenue` abstraction.
6. **The browser is presentation, not financial authority.** Missing evidence remains unavailable; React must not invent authoritative financial/statistical facts.
7. **Agent automation receives no multiplicity exemption.** Failed, repaired and weak candidates remain in the effective search denominator where the research protocol requires it.
8. **No hidden reasoning persistence.** Store explicit hypotheses, artifacts, events and usage metadata, not model chain-of-thought.
9. **No-alpha is a valid research terminal.** Never fabricate strategy/portfolio evidence to make a release appear populated.
10. **MT5 feed regimes are not interchangeable.** A passing FX fixture proves only the asset/feed-invariant engineering behavior it actually exercised. It cannot satisfy U.S. universe, delayed-reference, reconciliation, US-D3, PAPER or live-broker evidence.
11. **Realtime development is replay-first, broker-last.** Do not wait for a live interface to implement/test provider-neutral contracts, ReplayGateway, deterministic projections, restart behavior or evidence validators; reserve real-session/broker interaction for the smallest acceptance surface that actually requires it.
12. **Source substitution is by canonical contract, not by market identity.** Algorithms must consume canonical events/state through a provider-neutral source/subscription boundary. Use local U.S. database replay for market/algorithm semantics, FX live for connected transport/runtime semantics, and target U.S. CFD only for final broker/source freeze.
13. **Delayed feeds are a supported degraded mode, not “bad current data.”** Preserve measured/declared delay through `event_time`/`received_at` and health/freshness state. If delay exceeds a strategy decision budget, fail closed or downgrade the strategy; never relabel delayed observations as current.

### 5.1 MT5 feed-regime protocol

For MT5 work, classify every run before interpreting it:

```text
Lane A — FX continuous/near-continuous fixture
    EURUSD / GBPUSD / USDJPY
    authority: transport / clock / current bid-ask engineering smoke only

Lane B — MetaQuotes-Demo delayed U.S. equity reference
    authority: simulation EngineeringUniverse / delayed-reference evidence only

Lane C — future target-broker U.S. equity/CFD feed
    authority: separately admitted broker-specific source/PAPER evidence
    timing class: CURRENT, DELAYED or UNKNOWN must be measured/frozen; never assumed
```

Development source roles are orthogonal to those authority lanes:

```text
DEV-REPLAY — certified/local U.S. historical DB -> paced canonical BarEvent stream
DEV-LIVE   — FX live -> real MT5 transport/runtime stream
DEGRADED   — delayed U.S./future delayed broker source -> structural delay/freshness tests
FINAL      — target U.S. CFD -> broker/server/account/source/execution freeze
```

Rules:

- a roughly 15-minute delay is a bound feed/server/subscription observation, not an intrinsic `MetaTrader5` Python API delay and not a universal stock/CFD property;
- use FX freely for transport, reconnect, broker-clock normalization, timestamp parsing, current bid/ask plumbing, read-only inventory serialization and error handling;
- do not use FX to prove U.S. Market Watch visibility, delayed-reference timing, stock session behavior, stock trade/Last semantics, U.S. spread gates, MT5-D0, US-D3, stock/CFD margin/fill behavior, PAPER or live readiness;
- the continuous FX preflight must remain outside the U.S. certification denominator;
- delayed U.S. quotes may support only the authority carried by the simulation policy/report and never current executable spread, current liquidity, target-broker account, order or live-capital authority;
- future broker/server/account evidence is a new admission chain; never auto-promote Lane A or Lane B identities into Lane C;
- do not discard Lane B because development can proceed with FX/replay: keep it as the canonical structural delayed-feed/degraded-mode case; a future delayed-only broker should reuse the same semantics, not a special workaround;
- a target broker may be admitted as interface-compatible while still classified delayed-only; current-market strategy authority remains false when the measured delay exceeds its freshness/decision budget;
- never manufacture QuoteEvent bid/ask/tick history from OHLCV-only database rows; database replay emits only source-supported event types;
- governed US-I0 symbol visibility remains an operator boundary: do not add `symbol_select()` to force Market Watch state;
- preserve frozen S2 and MT5-D0 thresholds; do not weaken quote age, delayed anchor, minimum universe count, 50-bps delayed diagnostic spread, seed retention, overlap or offset thresholds to obtain a pass;
- where MT5 exposes them, prefer preserving `subscription_delay`, `chart_mode`, `trade_exemode`, `ticks_bookdepth` and related symbol/server identity fields in capability evidence; absence of these fields must not be filled by inference.

When reviewing a generic quote test, ask whether it is truly transport-invariant or whether it accidentally assumes FX microstructure. A test that requires universal `last > 0`, universal volume semantics, or a 24x5 session model is not a valid generic MT5 test.

### 5.2 Realtime dependency and active-session efficiency protocol

Before scheduling or interpreting realtime work, classify it by dependency:

```text
D0 — offline/deterministic
     source/tests/replay/content-ID/certification work; no broker required

D1 — connected engineering
     MT5 connection required; active U.S. ticks not required
     Lane A may substitute only for explicitly feed-invariant plumbing

D2 — U.S. active-session evidence capture
     U.S. source/session behavior is part of the evidence identity
     FX cannot substitute

D3 — broker mutation/execution acceptance
     demo/PAPER or live broker interaction is part of the final authority
```

Operational rules:

1. **Spend the U.S. session only on D2 evidence.** Finish imports, type/static checks, focused regressions, policy freezing, output-path preparation and generic MT5 debugging before the exchange session.
2. **Run Lane A before Lane B.** Use EURUSD/GBPUSD/USDJPY to fail early on terminal, transport, server, broker-clock, timestamp and quote-health problems; a Lane A pass does not prove U.S. evidence.
3. **Prepare governed U.S. Market Watch state before the session.** Manually expose the intended candidate set and verify required seeds; never add `symbol_select()` to automate the governed boundary.
4. **Respect delayed-source session timing.** For the observed roughly 900-second Lane B delay, do not interpret a wall-clock XNYS open as an immediately valid regular-session delayed anchor. Begin governed capture after `XNYS open + expected source delay + buffer`, using the accepted XNYS calendar rather than a hard-coded local clock.
5. **Treat the raw v2 report as the scarce D2 capture.** Preserve current/live failure semantics such as `stale_quote`; do not widen the live freshness Gate. Derive the simulation delayed-reference report from the immutable raw artifact.
6. **After a passing delayed assessment, collect inventory and finalize S2 promptly.** S2 inventory has a freshness bound; retain the 25/20/30 count policy, 50-bps delayed diagnostic spread and all required seeds.
7. **Move MT5-D0 out of the live tick window.** The current U.S.-specific reconciliation uses accepted U.S. mappings plus MT5 historical M1 `copy_rates_range()` over a bound historical window. It still cannot use FX as a substitute, but it does not require currently progressing U.S. ticks.
8. **Run S3 certification and independent review offline.** They are deterministic over captured S2/reconciliation/source/D1/D2 artifacts and should not consume the active-session window.
9. **Historical research remains independent of realtime after US-D3.** US-B0, US-A0, US-R1 and US-X0/X1 consume certified historical/research evidence, not a continuously available live U.S. interface.
10. **RT-R0/R1/R2 are replay-first and do not require broker acceptance.** Freeze typed events, implement ReplayGateway failure scenarios, build idempotent projections and prove restart reconstruction without waiting for MT5-M1.
11. **Broker-facing final acceptance begins at MT5-M1.** MT5-M1 requires real market-gateway/source evidence for final acceptance; MT5-E1/O1 require demo/PAPER broker lifecycle evidence; replay remains useful preparation but cannot create broker authority.
12. **RT-R3 consumes canonical projections, not direct MT5 truth.** Most UI work can run against replay; final accepted live presentation follows accepted M1/E1/O1 state/reconciliation semantics.
13. **MT5-L0 remains separate human governance.** No Lane A/B, replay, historical, simulation or PAPER evidence auto-promotes to live-capital authority.

Evidence reuse rules after a live capture:

- documentation or presentation-only changes that do not alter authoritative content IDs do not require recapturing the market;
- deterministic wrappers/orchestrators may reuse exact captured inputs if they only verify existing identities;
- changing delayed-reference computation invalidates the delayed report and descendants, while raw provenance may remain reusable only when its own sampling/clock semantics are unchanged;
- changing candidate identity, raw quote sampling/timestamp normalization, broker/server/feed lane or governed Market Watch set requires a new D2 capture;
- changing S2 policy/computation invalidates S2 and descendants; do not keep an old S2 acceptance under new semantics;
- when the affected upstream boundary is uncertain, fail closed and rerun the smallest evidence capture whose semantics actually changed.

The practical conclusion is deliberately two-part:

```text
normal FinAgent development is not strictly dependent on a realtime U.S. interface
stage/broker authority still requires the specific real-session or broker evidence named by its Gate
```

Use `docs/guides/realtime-development-validation.md` as the operator checklist for pre-session preparation, active-session capture and post-capture offline certification.

### 5.3 Algorithm streaming-source protocol

Normal algorithm/runtime development should use one subscription contract with interchangeable sources:

```text
DatabaseReplaySource  -> canonical BarEvent / source-supported events
MT5 FX live source    -> canonical QuoteEvent / BarEvent / ConnectionEvent
MT5 delayed source    -> same canonical events + explicit delay/freshness state
MT5 target CFD source -> same canonical events + broker/source freeze identity
```

Rules:

1. The algorithm must not import/use DuckDB or MetaTrader5 provider objects directly.
2. Preserve market chronology: historical replay changes delivery pacing, not `event_time`.
3. Provide 1x, accelerated, as-fast-as-possible and step replay modes; deterministic mode must reproduce event/state identities.
4. Maintain a feed timing profile with measured/declared delay, latency/jitter/freshness metadata and source identity.
5. Test delayed delivery separately from stale/frozen data. A progressing 900-second delayed feed is structurally different from a disconnected or non-progressing feed.
6. Compare effective source delay with the strategy’s decision/freshness budget before allowing signal/execution use.
7. Use FX to validate live transport/runtime only; use U.S. historical replay for U.S. algorithm/cross-sectional behavior; use target U.S. CFD for final broker/source semantics.
8. Keep final source capability honest: `CURRENT`, `DELAYED`, `REPLAY` or `UNKNOWN` are distinct states.
9. Provider/source switching must happen outside algorithm logic. The same `AlgorithmRunner`/feature/state path should process replay and live sources.
10. Final CFD freeze should be a differential acceptance: compare canonical contract/state behavior between replay/FX-hardened implementation and the target broker, then freeze only broker/source-specific differences.

See `docs/guides/realtime-source-development-model.md` for the development model and next implementation increment.

## 6. Stage implementation protocol

When asked to implement the current or next stage:

1. verify the active stage in `docs/status.toml`;
2. read that stage's Exit Gate in `current-plan.md`;
3. inspect predecessor evidence/tests so the new stage does not weaken an accepted boundary;
4. define the smallest coherent increment whose tests prove a real part of the Exit Gate;
5. keep new modules strict-typed where practical and preserve provider/domain separation;
6. add tests at the lowest useful layer plus the stage acceptance layer;
7. run focused tests before broad regressions;
8. for realtime/broker tasks, classify D0/D1/D2/D3 and move all possible validation out of scarce D2/D3 windows;
9. update documentation according to the matrix below, not by creating a new stage document;
10. advance `docs/status.toml` only when the entire Exit Gate is actually satisfied.

A partial implementation may be merged without changing the current stage to complete.

### Local Windows execution convention

The current operator workstation uses **Conda** for Python environment management and **PowerShell** for shell execution.

When writing commands intended for the operator's local Windows machine:

```powershell
conda activate finagent
cd D:\PythonWorkspace\FinAgent
python ...
npm ...
```

Rules:

- assume the `finagent` Conda environment is activated unless the task explicitly establishes another environment;
- use PowerShell syntax and backticks `` ` `` for multiline commands;
- use Windows paths when the user supplies Windows paths;
- invoke `python`, `pytest`, `npm`, or repository scripts directly inside the active Conda environment;
- do **not** rewrite normal local instructions as `uv run ...` or require the user to replace Conda with uv;
- `uv.lock` and the pinned uv resolver remain the ENG-0 **CI/reproducibility resolution authority**, not the workstation environment manager;
- when a local dependency is missing, state the Conda-environment installation/update needed rather than silently switching environment systems.

CI examples may continue to use uv exactly as defined by repository workflows.

## 7. Documentation development protocol

### 7.1 Decide which authority owns the change

| Change | Document to update |
| --- | --- |
| Current stage/status/next stage | `docs/status.toml` only |
| Stage scope/order/dependency/Exit Gate | `docs/development/current-plan.md` |
| Stable system decomposition | `docs/architecture/overview.md` |
| Active architectural invariant/decision | `docs/architecture/decisions.md` |
| Meaningful completed milestone | `docs/development/changelog.md` |
| Active unresolved risk | `docs/development/risks.md` |
| Test philosophy/gate structure | `docs/testing/strategy.md` |
| User/operator procedure | relevant `docs/guides/*.md` |
| Frozen product interpretation/reproduction | `docs/releases/*.md` |
| Detailed implementation diff | Git commit / PR, not a new docs file |

### 7.2 Forbidden active-document patterns

Do not create:

```text
docs/development/current-development-plan-v*.md
docs/development/roadmap*.md
docs/development/changelog-<stage>.md
```

Do not create `docs/archive/` merely to retain obsolete planning files. Git history is the archive.

### 7.3 No duplicate current status

README, guides, architecture documents and changelog may link to `docs/status.toml`, but must not maintain an independent “current milestone” value.

### 7.4 Stage completion update

A normal stage completion should be small:

```text
docs/status.toml
+ docs/development/changelog.md
+ release/guide/architecture docs only when their own authority changed
```

Do not rewrite the plan merely to say completed if scope/order/Gate did not change.

## 8. Documentation review checklist

Before approving a documentation change, verify:

- [ ] the fact is stored in the correct authority document;
- [ ] no second current-stage source was introduced;
- [ ] planned behavior is not written as implemented behavior;
- [ ] implementation claims are backed by source/tests or release evidence;
- [ ] platform acceptance is not described as Alpha/PAPER/live acceptance;
- [ ] historical A-share limitations remain explicit where relevant;
- [ ] provider/API capability is not confused with FinAgent adapter capability;
- [ ] FX engineering smoke is not described or consumed as U.S. research/MT5-D0/US-D3/PAPER/live evidence;
- [ ] delayed U.S. simulation evidence is not described as current executable-spread or target-broker authority;
- [ ] delayed-feed compatibility is not removed merely because FX/database replay are the normal development sources;
- [ ] database replay does not invent bid/ask/tick/order-book data absent from the historical source;
- [ ] algorithms are provider-neutral and do not branch on DuckDB/MT5 source implementations;
- [ ] realtime work is not described as globally blocked on live data when D0/D1 replay/engineering validation is sufficient;
- [ ] replay evidence is not described as broker/PAPER/live readiness;
- [ ] local Windows commands follow the Conda + PowerShell convention;
- [ ] relative links resolve;
- [ ] `python scripts/check_docs.py` passes.

## 9. Review/output format for an Agent

For a non-trivial project review, report in this order:

```text
Observed repository SHA
Current stage/status
Relevant authority documents
Implementation evidence inspected
Findings
Contradictions/uncertainties
Recommended change
Tests / Exit Gate affected
Documentation authority affected
```

This prevents conclusions from being based on a planning document alone.

## 10. Entry points

Human-readable onboarding: `docs/guides/project-onboarding.md`.

Documentation index: `docs/README.md`.

MT5 feed-regime guide: `docs/guides/mt5-continuous-smoke-and-deferred-us-i0.md`.

Realtime development / active-session workflow: `docs/guides/realtime-development-validation.md`.

Realtime source / database replay / delayed-feed model: `docs/guides/realtime-source-development-model.md`.

Current stage: `docs/status.toml`.
