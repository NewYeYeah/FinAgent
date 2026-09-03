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

### 5.1 MT5 feed-regime protocol

For MT5 work, classify every run before interpreting it:

```text
Lane A — FX continuous/near-continuous fixture
    EURUSD / GBPUSD / USDJPY
    authority: transport / clock / current bid-ask engineering smoke only

Lane B — MetaQuotes-Demo delayed U.S. equity reference
    authority: simulation EngineeringUniverse / delayed-reference evidence only

Lane C — future target-broker current U.S. equity/CFD feed
    authority: separately admitted broker-specific PAPER/live-current evidence
```

Rules:

- a roughly 15-minute delay is a bound feed/server/subscription observation, not an intrinsic `MetaTrader5` Python API delay and not a universal stock/CFD property;
- use FX freely for transport, reconnect, broker-clock normalization, timestamp parsing, current bid/ask plumbing, read-only inventory serialization and error handling;
- do not use FX to prove U.S. Market Watch visibility, delayed-reference timing, stock session behavior, stock trade/Last semantics, U.S. spread gates, MT5-D0, US-D3, stock/CFD margin/fill behavior, PAPER or live readiness;
- the continuous FX preflight must remain outside the U.S. certification denominator;
- delayed U.S. quotes may support only the authority carried by the simulation policy/report and never current executable spread, current liquidity, target-broker account, order or live-capital authority;
- future broker/server/account evidence is a new admission chain; never auto-promote Lane A or Lane B identities into Lane C;
- governed US-I0 symbol visibility remains an operator boundary: do not add `symbol_select()` to force Market Watch state;
- preserve frozen S2 and MT5-D0 thresholds; do not weaken quote age, delayed anchor, minimum universe count, 50-bps delayed diagnostic spread, seed retention, overlap or offset thresholds to obtain a pass;
- where MT5 exposes them, prefer preserving `subscription_delay`, `chart_mode`, `trade_exemode`, `ticks_bookdepth` and related symbol/server identity fields in capability evidence; absence of these fields must not be filled by inference.

When reviewing a generic quote test, ask whether it is truly transport-invariant or whether it accidentally assumes FX microstructure. A test that requires universal `last > 0`, universal volume semantics, or a 24x5 session model is not a valid generic MT5 test.

## 6. Stage implementation protocol

When asked to implement the current or next stage:

1. verify the active stage in `docs/status.toml`;
2. read that stage's Exit Gate in `current-plan.md`;
3. inspect predecessor evidence/tests so the new stage does not weaken an accepted boundary;
4. define the smallest coherent increment whose tests prove a real part of the Exit Gate;
5. keep new modules strict-typed where practical and preserve provider/domain separation;
6. add tests at the lowest useful layer plus the stage acceptance layer;
7. run focused tests before broad regressions;
8. update documentation according to the matrix below, not by creating a new stage document;
9. advance `docs/status.toml` only when the entire Exit Gate is actually satisfied.

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

Current stage: `docs/status.toml`.
