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

Current stage: `docs/status.toml`.
