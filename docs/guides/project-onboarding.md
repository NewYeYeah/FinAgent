# Project onboarding

This guide is the shortest reliable route for a person or Agent encountering FinAgent for the first time. The executable Agent-oriented protocol is [`../../skills/finagent-project/SKILL.md`](../../skills/finagent-project/SKILL.md).

## 1. Read current truth before history

Read these in order:

1. [`../status.toml`](../status.toml) — current stage and next stage;
2. [`../development/current-plan.md`](../development/current-plan.md) — stage scope, dependency and Exit Gate;
3. [`../architecture/overview.md`](../architecture/overview.md) — system structure and authority boundaries;
4. [`../architecture/decisions.md`](../architecture/decisions.md) — active design decisions;
5. [`../testing/strategy.md`](../testing/strategy.md) — what tests/acceptance actually prove;
6. the guide relevant to your task;
7. source code and tests;
8. aggregate changelog, commits and PRs for historical rationale.

Do not begin with an old versioned roadmap from Git history and assume it still describes the project.

## 2. Mental model

FinAgent separates adaptive research from deterministic financial state:

```text
source evidence / Data Plane
        ↓
bounded ResearchDataset
        ↓
Agent/manual/programmatic candidate research
        ↓
Alpha / Risk / Portfolio / historical execution
        ↓
immutable evidence + acceptance gates
        ↓
Workbench projections

future:
realtime events → replay/state → broker gateway → reconciliation/safety
```

The Agent may propose bounded research artifacts. It does not own final portfolio, broker or live-capital authority.

## 3. Five distinctions that prevent most misunderstandings

- `event_time` is not `available_at`;
- historical research instrument is not broker CFD identity;
- provider capability is not implemented adapter capability;
- platform acceptance is not Alpha acceptance;
- PAPER/demo acceptance is not live-capital acceptance.

A `NO_ROBUST_FACTOR_FAMILY` terminal is valid evidence, not an error that should be hidden by fabricating a strategy.

## 4. How to inspect a subsystem

For any subsystem:

```text
current stage/plan
→ architecture decision
→ domain contract
→ adapter/application implementation
→ unit/contract test
→ acceptance/release evidence
```

If docs and code disagree, report the disagreement. Use `docs/status.toml` for project-stage truth and code/tests for concrete implementation truth.

## 5. How to change documentation

Use one owner per fact:

| Fact changed | Update |
| --- | --- |
| current stage | `docs/status.toml` |
| future stage scope/order/Gate | `development/current-plan.md` |
| stable architecture | `architecture/overview.md` / `decisions.md` |
| completed milestone | aggregate `development/changelog.md` |
| active risk | `development/risks.md` |
| test structure | `testing/strategy.md` |
| user procedure | `guides/*.md` |
| frozen release meaning | `releases/*.md` |

Never add a new versioned current plan, roadmap or per-stage changelog to the active tree. Detailed implementation history belongs to Git/PRs.

Run:

```bash
python scripts/check_docs.py
```

before submitting documentation changes.

## 6. Where to go next

- data/source work: [`data.md`](data.md)
- research/Agent work: [`research.md`](research.md)
- Workbench: [`workbench.md`](workbench.md)
- operations/PAPER/realtime: [`operations.md`](operations.md)
- Historical v1.0 interpretation: [`../releases/ashare-historical-v1.md`](../releases/ashare-historical-v1.md)
