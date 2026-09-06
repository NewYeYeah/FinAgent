---
name: finagent-project
summary: Load the canonical FinAgent project context before planning, implementing, reviewing, or documenting work.
---

# FinAgent project skill

This skill intentionally contains **no independent project-status facts**.

## Required context load

1. Read [`../../AGENTS.md`](../../AGENTS.md).
2. Read `docs/status.toml`.
3. Read `docs/development/current-plan.md`.
4. Read the `stage_plan` named by status.
5. Read `docs/development/backlog.md`.
6. Inspect the relevant source and tests before asserting implementation state.

Use `docs/development/history.md` only when predecessor behavior or old negative research results matter. Use Git/PR history for exact implementation detail.

## Core rule

Never answer a FinAgent planning/implementation question from this Skill alone. The status, stage plan and executable code are the current authority.

When changing documentation, preserve the ownership model in `AGENTS.md` and run `python scripts/check_docs.py`.
