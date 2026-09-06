## Summary

Describe the coherent capability/change and why it belongs in the active stage.

## Development stage

Stage: `<!-- e.g. R3-CLOSE / R4-AGENT-ADAPTIVE / R5-INDEPENDENT-CONFIRMATION / WORKBENCH-2 / PAPER-TRADING / none -->`

Read current authority from `docs/status.toml` and detailed scope from the stage file named by `stage_plan`. Do not infer stage state from README, old PRs or historical release docs.

## Reuse / scope

- existing FinAgent implementation reused:
- mature open-source component reused/evaluated:
- new abstraction/code that was actually necessary:
- explicit non-goals:

Prefer a reviewable vertical slice; PR count is not an acceptance target.

## Documentation impact

- [ ] none
- [ ] `docs/status.toml` current-stage/authority/capability fact
- [ ] `docs/development/current-plan.md` end-to-end route/dependency change
- [ ] current `docs/development/stages/*.md` scope/deliverable/exit-gate change
- [ ] `docs/development/backlog.md` unresolved/deferred item change
- [ ] `docs/development/history.md` durable completed milestone/negative result
- [ ] architecture/active-decision change
- [ ] user/operator workflow change
- [ ] frozen release interpretation change

Do not create versioned current plans, roadmaps, per-PR stage guides or stage changelogs.

## Validation

List the focused unit/component/vertical acceptance evidence for the boundary changed by this PR. Add broader regression only where that shared boundary can be invalidated.

## Authority / safety

State whether the PR changes Agent research agency, financial/statistical authority, broker/PAPER state, safety/reconciliation, or live-capital authority. If none, say so explicitly.
