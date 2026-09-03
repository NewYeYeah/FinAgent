# FinAgent documentation

FinAgent documentation follows a **single-authority** model. The same project fact must not be maintained independently in README, a roadmap, a versioned current plan, and a changelog.

New readers should begin with the [project onboarding guide](guides/project-onboarding.md). Agents and automation tools should additionally load the repository [`finagent-project` skill](../skills/finagent-project/SKILL.md).

## Authoritative documents

| Question | Authority |
| --- | --- |
| How should a new person/Agent learn and inspect the project? | [`guides/project-onboarding.md`](guides/project-onboarding.md) / [`finagent-project` skill](../skills/finagent-project/SKILL.md) |
| What stage is active now? | [`status.toml`](status.toml) |
| What are the next stages, dependencies, scope and exit gates? | [`development/current-plan.md`](development/current-plan.md) |
| What is the system architecture now? | [`architecture/overview.md`](architecture/overview.md) |
| Which design decisions are still active? | [`architecture/decisions.md`](architecture/decisions.md) |
| What meaningful milestones have been completed? | [`development/changelog.md`](development/changelog.md) |
| What unresolved risks remain? | [`development/risks.md`](development/risks.md) |
| How are tests and acceptance gates structured? | [`testing/strategy.md`](testing/strategy.md) |
| How do I use the system? | [`guides/`](guides/) |
| How should I prepare for a U.S. active-session evidence run, and which realtime work can be done offline? | [`guides/realtime-development-validation.md`](guides/realtime-development-validation.md) |
| Which source should realtime/algorithm development use, and how are delayed feeds handled? | [`guides/realtime-source-development-model.md`](guides/realtime-source-development-model.md) |
| What exactly did a frozen release prove? | [`releases/`](releases/) |
| What exactly changed in one implementation? | Git commit / pull-request history |

## Lifecycle rules

1. `docs/status.toml` is the only current-stage authority.
2. There is exactly one active plan at the stable path `docs/development/current-plan.md`.
3. Planning revisions update that file in place; Git preserves previous revisions.
4. Stage implementation does **not** create `changelog-<stage>.md`, `roadmap-vX.md` or `current-development-plan-vX.md` files.
5. A completed stage normally updates only `status.toml` and the aggregate changelog.
6. A changed architecture invariant updates `architecture/overview.md` or `architecture/decisions.md`.
7. A changed user workflow updates a guide.
8. A product release creates or finalizes one release snapshot.
9. Detailed implementation history belongs to Git and PRs, not duplicated stage documents.
10. The onboarding skill/guide explain how to consume these authorities; they do not create another project-status authority.

`python scripts/check_docs.py` enforces the active-tree rules in CI.